"""Windows 平台集成层：光标形状判断、前台进程名、复制修饰键。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from pynput.keyboard import Key

# 模拟"复制"时按下的修饰键。Windows 是 Ctrl+C。
COPY_MODIFIER = Key.ctrl


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


def is_non_text_cursor() -> bool:
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
