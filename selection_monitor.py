from __future__ import annotations

import sys
import time

import pyperclip
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from pynput import mouse
from pynput.keyboard import Controller, Key

from platform_backend import COPY_MODIFIER, is_foreground_terminal, is_non_text_cursor

__all__ = [
    "SelectionGrabber",
    "SelectionMonitor",
    "grab_selected_text",
    "is_foreground_terminal",
]

_SENTINEL = "\x00__TRANSLATE_POPUP_SENTINEL__\x00"


class SelectionMonitor(QObject):
    """监听全局鼠标拖选事件。

    只有按下鼠标时光标处于可选文本状态（Windows 上排除拖窗/调整大小等系统光标；
    macOS 无此判断）、且实际拖动了一定距离，才认为用户在选文字。

    信号不携带坐标——上层应在 Qt 主线程通过 QCursor.pos() 取逻辑坐标，避免高 DPI 缩放下
    pynput 给出的物理像素与 Qt 逻辑坐标错位。
    """

    selection_finished = pyqtSignal(int, int, int, int)
    mouse_pressed = pyqtSignal()  # 用户按下左键（用于让残留的圆点立即退场）

    def __init__(self, drag_threshold: int = 5):
        super().__init__()
        self._press_pos: tuple[int, int] | None = None
        self._press_non_text: bool = False
        self._drag_threshold = drag_threshold
        self._listener: mouse.Listener | None = None

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = mouse.Listener(on_click=self._on_click)
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _on_click(self, x: int, y: int, button, pressed: bool) -> None:
        if button != mouse.Button.left:
            return
        if pressed:
            self._press_pos = (x, y)
            self._press_non_text = is_non_text_cursor()
            self.mouse_pressed.emit()
            return
        if self._press_pos is None:
            return
        px, py = self._press_pos
        self._press_pos = None
        non_text = self._press_non_text
        self._press_non_text = False
        if non_text:
            return
        if is_non_text_cursor():
            return
        moved = abs(x - px) >= self._drag_threshold or abs(y - py) >= self._drag_threshold
        if not moved:
            return
        self.selection_finished.emit(px, py, x, y)


def grab_selected_text(
    timeout_ms: int = 250,
    restore_clipboard: bool = False,
    *,
    use_shift: bool | None = None,
) -> str:
    """模拟复制快捷键获取当前选中文本（Windows: Ctrl+C, macOS: Cmd+C）。

    设计原则：只在用户主动点击翻译图标时调用，避免在选中瞬间打断用户的复制操作。
    成功时让选中文本留在剪贴板里（与用户主动复制的结果一致）；失败时恢复原内容。

    use_shift 显式传入时跳过 is_foreground_terminal 探测——主线程已先取好的值传进来,
    后台 grabber 就不必再次 GetForegroundWindow（也更确定地反映「释放鼠标」那一刻的前台窗口）。
    """
    try:
        original = pyperclip.paste()
    except Exception:
        original = ""

    try:
        pyperclip.copy(_SENTINEL)
    except Exception:
        pass

    kb = Controller()
    # Windows 终端里裸 Ctrl+C 等于 SIGINT,会杀掉前台进程(CC/git/npm 跑一半就被打断)。
    # 现代终端约定 Ctrl+Shift+C 才是复制。macOS Cmd+C 在终端里就是复制,不冲突。
    if use_shift is None:
        use_shift = sys.platform == "win32" and is_foreground_terminal()
    if use_shift:
        kb.press(Key.ctrl)
        kb.press(Key.shift)
        kb.press("c")
        kb.release("c")
        kb.release(Key.shift)
        kb.release(Key.ctrl)
    else:
        kb.press(COPY_MODIFIER)
        kb.press("c")
        kb.release("c")
        kb.release(COPY_MODIFIER)

    # 5ms 轮询(老版本 20ms):剪贴板典型 20-60ms 到位,5ms 间隔能在 1-2 个 tick 内就返回,
    # 实际 grab 总耗时从 ~300ms 上限压到 ~30-80ms,圆点出现的"卡顿感"消失。
    deadline = time.time() + timeout_ms / 1000.0
    captured = ""
    while time.time() < deadline:
        time.sleep(0.005)
        try:
            current = pyperclip.paste()
        except Exception:
            current = ""
        if current and current != _SENTINEL:
            captured = current
            break

    if restore_clipboard or not captured:
        try:
            pyperclip.copy(original)
        except Exception:
            pass

    return captured.strip()


class SelectionGrabber(QThread):
    """后台抓取选中文本。主线程不再被剪贴板轮询阻塞——圆点立刻可见、可点。

    用法:连 captured(str) 槽,start();线程 run() 结束后通过 finished->deleteLater 自毁。
    captured emit 之后,主线程仍可同步读 self.text(线程已死/尚未 deleteLater 都安全)。
    """

    captured = pyqtSignal(str)

    def __init__(
        self,
        *,
        use_shift: bool,
        timeout_ms: int = 300,
        restore: bool = True,
    ) -> None:
        super().__init__()
        self._use_shift = use_shift
        self._timeout_ms = timeout_ms
        self._restore = restore
        self.text: str = ""
        # QThread 生命周期:run 返回后让 Qt 在事件循环里 deleteLater,
        # 严禁外面手动 delete 一个还在 isRunning 的 QThread(0xc0000409 fast-fail)。
        self.finished.connect(self.deleteLater)

    def run(self) -> None:
        try:
            self.text = grab_selected_text(
                timeout_ms=self._timeout_ms,
                restore_clipboard=self._restore,
                use_shift=self._use_shift,
            )
        except Exception:
            self.text = ""
        self.captured.emit(self.text)
