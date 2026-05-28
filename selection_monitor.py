from __future__ import annotations

import time

import pyperclip
from PyQt6.QtCore import QObject, pyqtSignal
from pynput import mouse
from pynput.keyboard import Controller

from platform_backend import COPY_MODIFIER, is_foreground_terminal, is_non_text_cursor

__all__ = [
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


def grab_selected_text(timeout_ms: int = 250, restore_clipboard: bool = False) -> str:
    """模拟复制快捷键获取当前选中文本（Windows: Ctrl+C, macOS: Cmd+C）。

    设计原则：只在用户主动点击翻译图标时调用，避免在选中瞬间打断用户的复制操作。
    成功时让选中文本留在剪贴板里（与用户主动复制的结果一致）；失败时恢复原内容。
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
    kb.press(COPY_MODIFIER)
    kb.press("c")
    kb.release("c")
    kb.release(COPY_MODIFIER)

    deadline = time.time() + timeout_ms / 1000.0
    captured = ""
    while time.time() < deadline:
        time.sleep(0.02)
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
