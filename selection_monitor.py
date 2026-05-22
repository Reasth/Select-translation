from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

import pyperclip
from PyQt6.QtCore import QObject, pyqtSignal
from pynput import mouse
from pynput.keyboard import Controller, Key

_SENTINEL = "\x00__TRANSLATE_POPUP_SENTINEL__\x00"


# --- Win32: 判断当前光标是不是 I-beam（文本选择光标） ---
class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", wintypes.HANDLE),
        ("ptScreenPos", _POINT),
    ]


_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TERMINAL_PROCESS_NAMES = {
    "cmd.exe",
    "conhost.exe",
    "openconsole.exe",
    "powershell.exe",
    "pwsh.exe",
    "windowsterminal.exe",
    "wt.exe",
}

# 黑名单策略：只排除"明显不是在选文本"的系统光标。
# Electron/浏览器/IDE 等会用自定义 I-beam 资源（句柄 ≠ 系统 IDC_IBEAM），白名单
# 判断会把它们误杀。改成黑名单后这些应用的拖选都能正确触发。
_NON_TEXT_CURSOR_IDS = (
    32646,  # IDC_SIZEALL  拖动窗口
    32642,  # IDC_SIZENWSE 调整大小 ↖↘
    32643,  # IDC_SIZENESW 调整大小 ↗↙
    32644,  # IDC_SIZEWE   调整大小 ←→
    32645,  # IDC_SIZENS   调整大小 ↑↓
    32514,  # IDC_WAIT     等待
    32651,  # IDC_APPSTARTING
    32648,  # IDC_NO       禁止
    32650,  # IDC_HELP
)
_NON_TEXT_CURSORS = {
    h for h in (_user32.LoadCursorW(0, cid) for cid in _NON_TEXT_CURSOR_IDS) if h
}


def _is_non_text_cursor() -> bool:
    ci = _CURSORINFO()
    ci.cbSize = ctypes.sizeof(_CURSORINFO)
    if not _user32.GetCursorInfo(ctypes.byref(ci)):
        return False
    return ci.hCursor in _NON_TEXT_CURSORS


def _foreground_process_name() -> str:
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""

    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value.rsplit("\\", 1)[-1].lower()
    finally:
        _kernel32.CloseHandle(handle)


def is_foreground_terminal() -> bool:
    return _foreground_process_name() in _TERMINAL_PROCESS_NAMES


class SelectionMonitor(QObject):
    """监听全局鼠标拖选事件。

    只有按下鼠标时光标处于 I-beam（文本选择光标）状态、且实际拖动了一定距离，才认为
    用户在选文字。拖窗口、拖滚动条、拖文件等场景的光标不是 I-beam，自动被过滤掉。

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
            self._press_non_text = _is_non_text_cursor()
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
        if _is_non_text_cursor():
            return
        moved = abs(x - px) >= self._drag_threshold or abs(y - py) >= self._drag_threshold
        if not moved:
            return
        self.selection_finished.emit(px, py, x, y)


def grab_selected_text(timeout_ms: int = 250, restore_clipboard: bool = False) -> str:
    """模拟 Ctrl+C 获取当前选中文本。

    设计原则：只在用户主动点击翻译图标时调用，避免在选中瞬间打断用户的复制操作。
    成功时让选中文本留在剪贴板里（与用户主动 Ctrl+C 的结果一致）；失败时恢复原内容。
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
    kb.press(Key.ctrl)
    kb.press("c")
    kb.release("c")
    kb.release(Key.ctrl)

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
