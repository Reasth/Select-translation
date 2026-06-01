from __future__ import annotations

import logging
import sys
import traceback

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import QApplication

from config import CONFIG_DIR, Config
from floating_icon import FloatingIcon
from llm_client import LLMClient
from platform_backend import is_autostart, set_autostart
from selection_monitor import SelectionMonitor, grab_selected_text, is_foreground_terminal
from settings_dialog import SettingsDialog
from translation_popup import TranslateWorker, TranslationPopup
from tray import TrayController


LOG_PATH = CONFIG_DIR / "app.log"

# Eager 翻译最小长度。低于此长度认为是误选/单字光标停留,不预发请求,避免烧 token。
EAGER_MIN_CHARS = 6


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


class App:
    def __init__(self):
        self.cfg = Config.load()
        self.client = LLMClient(self.cfg)

        self.icon = FloatingIcon()
        self.popup = TranslationPopup(self.client)
        self.monitor = SelectionMonitor()
        self.tray = TrayController(enabled=self.cfg.enabled, autostart=is_autostart())
        self._suppress_next_close: bool = False
        self._cached_selection_text: str = ""

        # ---- Eager 翻译状态 ----
        # 选中文本一就绪就预发请求,用户移鼠标→点圆点的几百毫秒里 API 已经在跑。
        self._eager_text: str = ""           # 当前预翻译的原文（也用于过滤陈旧 worker 的信号）
        self._eager_buffer: str = ""         # 累计收到的可见 token
        self._eager_done: bool = False       # 预翻译是否完成
        self._eager_worker: TranslateWorker | None = None
        self._popup_consuming_text: str = ""  # 当前 popup 正在显示的 eager 对应的原文

        self.monitor.selection_finished.connect(self._on_selection_finished)
        self.monitor.mouse_pressed.connect(self._on_mouse_pressed)
        self.icon.clicked.connect(self._on_icon_clicked)
        self.icon.auto_hidden.connect(self._cancel_eager)  # 圆点超时未点 = 用户放弃 → 取消预翻译
        self.popup.closed.connect(self._on_popup_closed)
        self.tray.toggle_enabled.connect(self._on_toggle_enabled)
        self.tray.toggle_autostart.connect(self._on_toggle_autostart)
        self.tray.open_settings.connect(self._on_open_settings)
        self.tray.quit_app.connect(QApplication.instance().quit)

        if self.cfg.enabled:
            self.monitor.start()

        if not self.cfg.api_key:
            self.tray.notify(
                "翻译助手已启动",
                "首次使用请右键托盘图标 → 设置，填写 API Key。",
            )

    def _on_toggle_enabled(self, on: bool):
        self.cfg.enabled = on
        self.cfg.save()
        if on:
            self.monitor.start()
        else:
            self.monitor.stop()
            self.icon.hide()
            self._cached_selection_text = ""
            self._cancel_eager()

    def _on_toggle_autostart(self, on: bool):
        if set_autostart(on):
            self.cfg.autostart = on
            self.cfg.save()
        else:
            self.tray.set_autostart_checked(is_autostart())
            self.tray.notify("开机自启", "设置开机自启失败，请检查系统权限。")

    def _on_open_settings(self):
        dlg = SettingsDialog(self.cfg)
        if dlg.exec():
            dlg.apply_to(self.cfg)
            self.client.cfg = self.cfg

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
            self._cancel_eager()  # 点外面 = 用户放弃 → 取消预翻译

    def _on_selection_finished(self, press_x: int, press_y: int, release_x: int, release_y: int):
        if not self.cfg.enabled:
            return
        right_x = max(press_x, release_x)
        top_y = min(press_y, release_y)
        ratio = QGuiApplication.primaryScreen().devicePixelRatio() or 1.0
        lx = int(right_x / ratio)
        ly = int(top_y / ratio)
        self._cached_selection_text = ""
        self.icon.show_near_cursor(lx, ly, lifetime_ms=self.cfg.show_icon_ms)
        if is_foreground_terminal():
            logging.info("skip eager selection cache for terminal foreground window")
        else:
            QTimer.singleShot(80, self._cache_selected_text)

    def _cache_selected_text(self):
        text = grab_selected_text(timeout_ms=300, restore_clipboard=True)
        if text:
            self._cached_selection_text = text
            logging.info("cached selected text len=%s", len(text))
            self._start_eager(text)

    # ---- Eager 翻译实现 ----

    def _start_eager(self, text: str) -> None:
        """选中文本一就绪就发请求。失败/取消都吃掉,等用户点击时若仍未就绪则正常回退。"""
        if len(text) < EAGER_MIN_CHARS or len(text) > self.cfg.max_chars:
            return
        if self._eager_worker is not None and self._eager_text == text:
            return  # 同一段文本已经在跑
        self._cancel_eager()
        self._eager_text = text
        self._eager_buffer = ""
        self._eager_done = False
        worker = TranslateWorker(self.client, text)
        owner_text = text  # 闭包捕获,过滤陈旧 worker 的信号
        worker.token_received.connect(lambda tok: self._on_eager_token(owner_text, tok))
        worker.finished_translation.connect(lambda: self._on_eager_finished(owner_text))
        self._eager_worker = worker
        worker.start()
        logging.info("eager started len=%s", len(text))

    def _cancel_eager(self) -> None:
        if self._eager_worker is not None:
            try:
                if self._eager_worker.isRunning():
                    self._eager_worker.requestInterruption()
                    self._eager_worker.quit()
            except RuntimeError:
                pass
            self._eager_worker.deleteLater()
            self._eager_worker = None
        self._eager_text = ""
        self._eager_buffer = ""
        self._eager_done = False

    def _on_eager_token(self, owner_text: str, token: str) -> None:
        if owner_text != self._eager_text:
            return  # 陈旧 worker 的尾巴信号,丢弃
        self._eager_buffer += token
        if self._popup_consuming_text == owner_text and self.popup.isVisible():
            self.popup.append_eager_token(token)

    def _on_eager_finished(self, owner_text: str) -> None:
        if owner_text != self._eager_text:
            return
        self._eager_done = True
        if self._popup_consuming_text == owner_text and self.popup.isVisible():
            self.popup.mark_eager_done()

    def _on_popup_closed(self) -> None:
        self._popup_consuming_text = ""
        self._cancel_eager()

    def _on_icon_clicked(self):
        self._suppress_next_close = True
        bubble_anchor = self.icon.dot_center_global()
        text = self._cached_selection_text or grab_selected_text()
        logging.info("icon clicked, selected text len=%s cached=%s", len(text), bool(self._cached_selection_text))
        if len(text) < self.cfg.min_chars or len(text) > self.cfg.max_chars:
            self.popup.show_message("未获取到选中文本，请重新划词后再点圆点。")
            self.popup.reveal_at(anchor=bubble_anchor)
            return
        self._cached_selection_text = ""
        if text == self._eager_text and self._eager_worker is not None:
            # Eager 命中:接管已经在跑/已经完成的预翻译,buffer 立即显示,后续 token 继续追加
            self._popup_consuming_text = text
            self.popup.present_eager(self._eager_buffer)
            if self._eager_done:
                self.popup.mark_eager_done()
            logging.info("icon click adopted eager (buffered %s chars, done=%s)", len(self._eager_buffer), self._eager_done)
        else:
            # 没命中(文本变了/小于阈值/无 eager),走原路新发请求
            self._popup_consuming_text = ""
            self.popup.start_translation(text)
        self.popup.reveal_at(anchor=bubble_anchor)


def main():
    _install_logging()
    logging.info("translate-popup starting, log=%s", LOG_PATH)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    holder = App()
    logging.info("event loop entering")
    code = app.exec()
    logging.info("event loop exited with code=%s", code)
    sys.exit(code)


if __name__ == "__main__":
    main()
