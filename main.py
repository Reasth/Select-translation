from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback

from PyQt6.QtCore import QLockFile, QObject, QPoint, QTimer, pyqtSlot
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication

from config import CONFIG_DIR, Config
from floating_icon import FloatingIcon
from langs import lang_to_code
from llm_client import LLMClient
from platform_backend import foreground_app, is_autostart, set_autostart
from selection_monitor import (
    SelectionGrabber,
    SelectionMonitor,
    is_foreground_terminal,
)
from terminal_context import clean_terminal_text, lookup_glossary
from settings_dialog import SettingsDialog
from telemetry import Telemetry, ensure_install_id, new_session_id
from translation_popup import TranslateWorker, TranslationPopup
from tray import TrayController


LOG_PATH = CONFIG_DIR / "app.log"

# Eager 翻译最小长度。低于此长度认为是误选/单字光标停留,不预发请求,避免烧 token。
EAGER_MIN_CHARS = 6
EAGER_GRAB_TIMEOUT_MS = 350
INFLIGHT_GRAB_WAIT_MS = 450
CLICK_GRAB_TIMEOUT_MS = 1200


def _install_logging() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_PATH),
        filemode="a",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )

    def _excepthook(exc_type, exc, tb):
        logging.error("Unhandled exception:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))

    sys.excepthook = _excepthook


class App(QObject):
    """主控对象。**必须**是 QObject —— eager TranslateWorker 的 token_received 信号
    要连到这个类的方法上,PyQt6 才会用 QueuedConnection 把 token 跳回主线程。
    1.3 早期版本曾把信号连到普通 lambda,PyQt 默认 DirectConnection,槽跑在 worker
    线程里碰 self.popup(QWidget),Qt 跨线程 assert,在 Qt6Core.dll 0x1cf68 闪退
    (异常码 0xc0000409,即 STACK_BUFFER_OVERRUN/fast-fail)。
    """

    def __init__(self):
        super().__init__()
        self.cfg = Config.load()
        # 匿名 install_id 在首次启动生成并落库;session_id 每次启动随机不持久。
        install_id = ensure_install_id(self.cfg)
        session_id = new_session_id()
        self.telemetry = Telemetry(install_id, session_id)

        self.client = LLMClient(self.cfg)
        # 让 hosted 翻译请求的 X-Install-Id / X-Session-Id 和事件用同一对 ID,
        # 这样代理端 metric 行能与客户端事件在 events 表里 JOIN。
        self.client.install_id = install_id
        self.client.session_id = session_id

        self.icon = FloatingIcon()
        self.popup = TranslationPopup(self.client)
        self.monitor = SelectionMonitor()
        self.tray = TrayController(enabled=self.cfg.enabled, autostart=is_autostart())
        self._suppress_next_close: bool = False
        self._cached_selection_text: str = ""
        # 点击蓝点后才抓取选中文本。划词结束只显示圆点,不再提前发 Ctrl+C,
        # 避免用户只是划词查看/复制时被本应用改动剪贴板。
        self._grabber: SelectionGrabber | None = None
        # 点击路径上的 grabber:popup 已经先显示 loading,再后台发复制快捷键。
        self._click_grabber: SelectionGrabber | None = None
        self._click_anchor: QPoint | None = None
        # 划词那一刻前台是否终端。按产品假设「终端 = Claude Code 会话」,该标志决定
        # 点击后走终端专用 prompt/词典/弹窗宽度。在选区结束时采样,点击时直接用——
        # 点击时圆点/popup 可能已抢前台,再探测会失真。
        self._selection_terminal_fg: bool = False

        # ---- Eager 翻译状态 ----
        # 保留状态清理逻辑以兼容旧流程,但当前策略是不在点击蓝点前复制/预翻译。
        self._eager_text: str = ""           # 当前预翻译的原文（也用于过滤陈旧 worker 的信号）
        self._eager_buffer: str = ""         # 累计收到的可见 token
        self._eager_done: bool = False       # 预翻译是否完成
        self._eager_started_at: float = 0.0  # 本轮 eager 的起点（time.monotonic）
        self._eager_worker: TranslateWorker | None = None
        self._popup_consuming_text: str = ""  # 当前 popup 正在显示的 eager 对应的原文

        self.monitor.selection_finished.connect(self._on_selection_finished)
        self.monitor.mouse_pressed.connect(self._on_mouse_pressed)
        self.icon.clicked.connect(self._on_icon_clicked)
        self.icon.auto_hidden.connect(self._on_icon_auto_hidden)
        self.popup.closed.connect(self._on_popup_closed)
        self.popup.suggestion_copied.connect(
            lambda: self.telemetry.fire("claude_suggestion_copied")
        )
        self.tray.toggle_enabled.connect(self._on_toggle_enabled)
        self.tray.toggle_autostart.connect(self._on_toggle_autostart)
        self.tray.open_settings.connect(self._on_open_settings)
        self.tray.quit_app.connect(QApplication.instance().quit)

        # app 退出时发一次 app_quit;先 connect 这里,后面 main() 再发 app_start。
        QApplication.instance().aboutToQuit.connect(
            lambda: self.telemetry.fire("app_quit")
        )

        self.telemetry.fire(
            "app_start",
            {
                "engine": self.cfg.engine,
                "target_lang": self.cfg.target_lang,
                "autostart": self.cfg.autostart,
                "enabled": self.cfg.enabled,
            },
        )

        if self.cfg.enabled:
            self.monitor.start()

        if not self.cfg.api_key:
            self.tray.notify(
                "Select 已启动",
                "首次使用请右键托盘图标 → 设置，填写 API Key。",
            )

    def _on_toggle_enabled(self, on: bool):
        self.cfg.enabled = on
        self.cfg.save()
        self.telemetry.fire("tray_enabled_changed", {"enabled": on})
        if on:
            self.monitor.start()
        else:
            self.monitor.stop()
            self.icon.hide()
            self._cached_selection_text = ""
            self._cancel_eager(reason="disabled")

    def _on_toggle_autostart(self, on: bool):
        if set_autostart(on):
            self.cfg.autostart = on
            self.cfg.save()
            self.telemetry.fire("tray_autostart_changed", {"on": on})
        else:
            self.tray.set_autostart_checked(is_autostart())
            self.tray.notify("开机自启", "设置开机自启失败，请检查系统权限。")
            self.telemetry.fire("tray_autostart_changed", {"on": False, "failed": True})

    def _on_open_settings(self):
        self.telemetry.fire("settings_opened")
        prev_engine = self.cfg.engine
        prev_lang = self.cfg.target_lang
        prev_model = self.cfg.model
        dlg = SettingsDialog(self.cfg)
        if dlg.exec():
            dlg.apply_to(self.cfg)
            self.client.cfg = self.cfg
            self.telemetry.fire("settings_saved", {
                "engine_changed": prev_engine != self.cfg.engine,
                "lang_changed": prev_lang != self.cfg.target_lang,
                "model_changed": prev_model != self.cfg.model,
                "engine": self.cfg.engine,
                "target_lang": self.cfg.target_lang,
            })
            if prev_engine != self.cfg.engine or prev_lang != self.cfg.target_lang:
                # 引擎/语言变了,丢掉旧的预翻译——它可能是错引擎或错方向出的。
                self._cancel_eager(reason="settings_changed")
        else:
            self.telemetry.fire("settings_cancelled")

    def _on_mouse_pressed(self):
        QTimer.singleShot(0, self._maybe_hide_icon)

    def _maybe_hide_icon(self):
        if self._suppress_next_close:
            self._suppress_next_close = False
            return
        if self.popup.isVisible():
            if not self.popup.contains_global_point(QCursor.pos()):
                self.popup.hide()
            return
        if self.icon.isVisible():
            if self.icon.contains_global_point(QCursor.pos()):
                return
            self.icon.hide()
            self._cached_selection_text = ""
            self._cancel_eager(reason="icon_abandoned")  # 点外面 = 用户放弃

    def _on_selection_finished(self, press_x: int, press_y: int, release_x: int, release_y: int):
        if not self.cfg.enabled:
            return
        if self.popup.isVisible():
            # 正在展示/流式追加翻译时,新的鼠标拖选可能只是用户在别处操作。
            # 不要让它取消当前 eager worker,否则弹窗会停在已经收到的几个 token。
            logging.info("selection ignored while popup visible")
            self.telemetry.fire("selection_ignored", {"reason": "popup_visible"})
            return
        release_pos = QCursor.pos()
        self._cached_selection_text = ""
        # 主线程立刻 show:Qt 事件循环不再被剪贴板轮询卡 300ms,圆点画面没有黑窗。
        self.icon.show_near_cursor(release_pos.x(), release_pos.y(), lifetime_ms=self.cfg.show_icon_ms)
        drag_px = max(abs(release_x - press_x), abs(release_y - press_y))
        terminal_fg = is_foreground_terminal()
        self._selection_terminal_fg = terminal_fg
        app_name, win_title = foreground_app()
        # 窗口标题留 200 字以内,够分类/分析,够远离「整页 URL 截屏」级别隐私。
        self.telemetry.fire("icon_shown", {
            "drag_px": drag_px,
            "terminal_fg": terminal_fg,
            "app_name": app_name,
            "window_title": win_title[:200],
        })
        # Do not copy here. The selected text is grabbed only after the user clicks
        # the blue dot, so a plain selection never changes the clipboard.

    def _kick_grab(self) -> None:
        # 旧 grabber 还在跑就丢引用,让它自然结束(captured 信号被 sender() != self._grabber 过滤掉)。
        # 不强杀:杀一个还在 isRunning 的 QThread = 0xc0000409。
        # use_shift 用划词时采样的 _selection_terminal_fg(见 __init__ 注释),不再重探前台窗口。
        use_shift = sys.platform == "win32" and self._selection_terminal_fg
        g = SelectionGrabber(use_shift=use_shift, timeout_ms=EAGER_GRAB_TIMEOUT_MS, restore=True)
        g.captured.connect(self._on_grab_captured)
        self._grabber = g
        g.start()

    @pyqtSlot(str)
    def _on_grab_captured(self, text: str) -> None:
        # sender() 过滤陈旧 grabber:用户连选两次时旧的尾巴信号到达也会被丢掉。
        if self.sender() is not self._grabber:
            return
        self._grabber = None
        if not text:
            return
        if self.popup.isVisible() and self._popup_consuming_text:
            logging.info("grab ignored while popup is consuming eager")
            self.telemetry.fire("selection_ignored", {"reason": "popup_consuming_eager"})
            return
        self._cached_selection_text = text
        logging.info("cached selected text len=%s", len(text))
        self.telemetry.fire("selection_cached", {"len": len(text)})
        self._start_eager(text)

    # ---- Eager 翻译实现 ----

    def _start_eager(self, text: str) -> None:
        """选中文本一就绪就发请求。失败/取消都吃掉,等用户点击时若仍未就绪则正常回退。"""
        if len(text) < EAGER_MIN_CHARS or len(text) > self.cfg.max_chars:
            return
        if self.popup.isVisible() and self._popup_consuming_text:
            logging.info("new eager ignored while popup is consuming current eager")
            self.telemetry.fire("eager_ignored", {"reason": "popup_consuming_eager"})
            return
        if self._eager_worker is not None and self._eager_text == text:
            return  # 同一段文本已经在跑
        self._cancel_eager(reason="new_selection")
        self._eager_text = text
        self._eager_buffer = ""
        self._eager_done = False
        self._eager_started_at = time.monotonic()
        worker = TranslateWorker(self.client, text, source="eager")
        # **绑定方法**(不是 lambda):PyQt6 检测到接收方是 QObject(App)→ 自动
        # QueuedConnection → 槽在主线程跑。陈旧 worker 的信号用 self.sender() 过滤。
        worker.token_received.connect(self._eager_token_slot)
        worker.finished_translation.connect(self._eager_finished_slot)
        self._eager_worker = worker
        worker.start()
        logging.info("eager started len=%s", len(text))
        self.telemetry.fire("eager_started", {"len": len(text)})

    def _cancel_eager(self, *, reason: str = "other") -> None:
        was_running = False
        if self._eager_worker is not None:
            try:
                was_running = self._eager_worker.isRunning()
                if was_running:
                    # 只打中断标记。run() 在下一个 token 间隙退出,worker.finished 已
                    # 自接 deleteLater 会负责析构。这里再调 deleteLater + 线程未退
                    # = Qt fast-fail 0xc0000409 P9=7,正是上一版崩溃的真正成因。
                    self._eager_worker.requestInterruption()
            except RuntimeError:
                pass
            self._eager_worker = None
        if was_running:
            self.telemetry.fire("eager_cancelled", {
                "reason": reason,
                "buffered_chars": len(self._eager_buffer),
            })
        self._eager_text = ""
        self._eager_buffer = ""
        self._eager_done = False

    @pyqtSlot(str)
    def _eager_token_slot(self, token: str) -> None:
        # 主线程 guard:若哪天 PyQt 默认连接策略变了,宁可丢 token 也不让 Qt 跨线程崩。
        if threading.current_thread() is not threading.main_thread():
            logging.error("eager token slot fired off main thread (tid=%s); dropping",
                          threading.get_ident())
            return
        # sender() 是 PyQt6 提供的"触发当前槽的发送方 QObject":陈旧 worker(已被 _cancel_eager
        # deleteLater 的)若有尾巴信号还在事件队列里,sender() ≠ 当前 self._eager_worker,直接丢。
        if self.sender() is not self._eager_worker:
            return
        if not self._eager_buffer:
            logging.info("eager first token received chars=%s", len(token))
        self._eager_buffer += token
        if self._popup_consuming_text == self._eager_text and self.popup.isVisible():
            self.popup.append_eager_token(token)

    @pyqtSlot()
    def _eager_finished_slot(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            logging.error("eager finished slot fired off main thread (tid=%s); dropping",
                          threading.get_ident())
            return
        if self.sender() is not self._eager_worker:
            return
        self._eager_done = True
        if self._popup_consuming_text == self._eager_text and self.popup.isVisible():
            self.popup.mark_eager_done()
        dt_ms = int((time.monotonic() - self._eager_started_at) * 1000)
        logging.info(
            "eager completed chars=%s duration_ms=%s adopted=%s",
            len(self._eager_buffer),
            dt_ms,
            self._popup_consuming_text == self._eager_text,
        )
        self.telemetry.fire("eager_completed", {
            "chars": len(self._eager_buffer),
            "duration_ms": dt_ms,
            "adopted": self._popup_consuming_text == self._eager_text,
        })

    def _on_popup_closed(self) -> None:
        self.telemetry.fire("popup_closed", {
            "buffered_chars": len(self._eager_buffer),
            "eager_done": self._eager_done,
            "consumed_eager": bool(self._popup_consuming_text),
        })
        self._popup_consuming_text = ""
        self._cancel_eager(reason="popup_closed")

    def _on_icon_auto_hidden(self) -> None:
        self.telemetry.fire("icon_auto_hidden", {"had_eager": self._eager_worker is not None})
        self._cancel_eager(reason="icon_timeout")

    def _on_icon_clicked(self):
        self._suppress_next_close = True
        bubble_anchor = self.icon.dot_center_global()
        # Copying is only allowed after this click. Drop any legacy eager state so
        # the click always drives the actual selection grab.
        self._cached_selection_text = ""
        self._grabber = None
        text = self._cached_selection_text
        from_cache = bool(text)
        from_inflight = False
        if not text and self._grabber is not None:
            # eager grab 还在跑(非终端场景用户点得很快):同步 wait 取它的 .text,
            # 比再发一次 Ctrl+C 撞剪贴板靠谱。wait 返回时线程已死,deleteLater 尚未轮到。
            try:
                if self._grabber.isRunning():
                    self._grabber.wait(INFLIGHT_GRAB_WAIT_MS)
                text = self._grabber.text or ""
                from_inflight = bool(text)
            except RuntimeError:
                text = ""
        if text:
            self._dispatch_translation(
                text, bubble_anchor,
                from_cache=from_cache, from_inflight=from_inflight,
            )
            return
        # 终端场景到这里:eager 没起,cache 没值。直接 popup loading + reveal,
        # 让用户先看到「正在翻译」的视觉反馈,再后台发 Ctrl+Shift+C。
        # 选区被宿主清掉的瞬间被 popup 的弹出动画遮蔽——感知层面"没丢"。
        self._popup_consuming_text = ""
        self.popup.show_loading_state()
        self.popup.reveal_at(anchor=bubble_anchor)
        self._click_anchor = bubble_anchor
        # 50ms 后再 kick grab:让 popup 的 show() 在 Windows 这边完成 paint。
        # 否则后台线程可能跑得太快,在 popup 还没真正可见时就发出 Ctrl+Shift+C,
        # 用户依然能瞥到「选区先没,popup 后到」的 50ms 缝隙。
        QTimer.singleShot(50, self._start_click_grabber)
        logging.info("icon clicked, deferred grab scheduled")
        self.telemetry.fire("icon_clicked", {
            "text_len": 0,
            "from_cache": False,
            "from_inflight": False,
            "deferred": True,
        })

    def _dispatch_translation(
        self,
        text: str,
        bubble_anchor: QPoint,
        *,
        from_cache: bool,
        from_inflight: bool,
    ) -> None:
        logging.info(
            "icon clicked, selected text len=%s cached=%s inflight=%s",
            len(text), from_cache, from_inflight,
        )
        self.telemetry.fire("icon_clicked", {
            "text_len": len(text),
            "from_cache": from_cache,
            "from_inflight": from_inflight,
            "deferred": False,
        })
        if len(text) < self.cfg.min_chars or len(text) > self.cfg.max_chars:
            self.popup.show_message("未获取到选中文本，请重新划词后再点圆点。")
            self.popup.reveal_at(anchor=bubble_anchor)
            self.telemetry.fire("translation_failed", {"reason": "no_text", "len": len(text)})
            return
        self._cached_selection_text = ""
        adopted_eager = False
        if text == self._eager_text and self._eager_done and self._eager_buffer:
            # 只复用已经完成的 eager。未完成的 eager 接管后容易被后续鼠标/选区事件打断,
            # 造成弹窗停在首 token(常见为「这是」)。
            self._popup_consuming_text = text
            self.popup.present_eager(self._eager_buffer)
            self.popup.mark_eager_done()
            adopted_eager = True
            logging.info("icon click adopted completed eager (buffered %s chars)", len(self._eager_buffer))
            self.telemetry.fire("eager_adopted", {
                "buffered_chars": len(self._eager_buffer),
                "eager_done": self._eager_done,
                "text_len": len(text),
            })
        else:
            if text == self._eager_text and self._eager_worker is not None:
                logging.info(
                    "icon click ignored unfinished eager; starting fresh click translation "
                    "(buffered %s chars, done=%s)",
                    len(self._eager_buffer),
                    self._eager_done,
                )
                self._cancel_eager(reason="click_fresh_translation")
            # 没有完整 eager 可复用,走正式点击翻译请求。可靠性优先于预翻译省下的几百毫秒。
            self._popup_consuming_text = ""
            self.popup.start_translation(text)
            self.telemetry.fire("translation_started", {
                "text_len": len(text),
                "eager_existed": self._eager_text != "",
                "eager_text_mismatch": self._eager_text != "" and self._eager_text != text,
                "fresh_click": True,
            })
        self.popup.reveal_at(anchor=bubble_anchor)
        self.telemetry.fire("popup_shown", {
            "engine": self.cfg.engine,
            "adopted_eager": adopted_eager,
        })

    def _start_click_grabber(self) -> None:
        # use_shift 用划词时采样的 _selection_terminal_fg:此刻 popup 已抢前台,再探测会失真。
        use_shift = sys.platform == "win32" and self._selection_terminal_fg
        # restore=False:click 时让选区文本留在剪贴板里(与用户主动 Ctrl+C 的语义一致)。
        g = SelectionGrabber(use_shift=use_shift, timeout_ms=CLICK_GRAB_TIMEOUT_MS, restore=False)
        g.captured.connect(self._on_click_grab_captured)
        self._click_grabber = g
        g.start()

    @pyqtSlot(str)
    def _on_click_grab_captured(self, text: str) -> None:
        # sender() 过滤陈旧 click_grabber(用户在 popup 出来后又点了别的)。
        if self.sender() is not self._click_grabber:
            return
        self._click_grabber = None
        anchor = self._click_anchor or QCursor.pos()
        self._click_anchor = None
        if not text or len(text) < self.cfg.min_chars or len(text) > self.cfg.max_chars:
            self.popup.show_message("未获取到选中文本，请重新划词后再点圆点。")
            self.telemetry.fire("translation_failed", {
                "reason": "no_text", "len": len(text), "deferred": True,
            })
            return
        terminal = self._selection_terminal_fg
        if terminal:
            # 终端选区常带 Claude Code 的边框字符/状态标记/硬换行,清掉再进 LLM——
            # 噪音字符也是要花钱的 input token。
            text = clean_terminal_text(text)
            # 高频术语先查本地词典:命中 = 零请求、零 token、零延迟。
            # 词典是中文口径,只在目标语言为中文时启用。
            if lang_to_code(self.cfg.target_lang, default="en").startswith("zh"):
                gloss = lookup_glossary(text)
                if gloss:
                    self.popup.show_message(gloss)
                    logging.info("glossary hit, len=%s", len(text))
                    self.telemetry.fire("glossary_hit", {"term": text[:40]})
                    return
        # popup 已经是 loading 形态,直接 start_translation 接过去(cancel_translation 是 no-op,
        # 不会闪掉 loading 视觉)。
        self._popup_consuming_text = ""
        self.popup.start_translation(text, terminal=terminal)
        logging.info("deferred grab captured, len=%s terminal=%s", len(text), terminal)
        self.telemetry.fire("translation_started", {
            "text_len": len(text),
            "eager_existed": False,
            "eager_text_mismatch": False,
            "deferred": True,
            "terminal": terminal,
        })


def main():
    if os.environ.get("TRANSLATE_POPUP_SMOKE_TEST") == "1":
        return
    _install_logging()
    logging.info("translate-popup starting, log=%s", LOG_PATH)
    lock = QLockFile(str(CONFIG_DIR / "app.lock"))
    lock.setStaleLockTime(10_000)
    if not lock.tryLock(100):
        logging.info("another translate-popup instance is already running; exiting")
        sys.exit(0)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    holder = App()
    logging.info("event loop entering")
    code = app.exec()
    logging.info("event loop exited with code=%s", code)
    sys.exit(code)


if __name__ == "__main__":
    main()
