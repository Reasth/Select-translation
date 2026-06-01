"""macOS 平台集成层：前台应用判断、复制修饰键。

与 Windows 的差异：
- macOS 没有"全局取当前光标形状"的可靠公共 API（GetCursorInfo 的等价物）。
  因此 is_non_text_cursor() 恒为 False，是否在选文本完全交给"拖动距离启发式 +
  点击圆点时实际 Cmd+C 取词成功与否"来判断。误触发的最坏结果只是弹出一句
  "未获取到选中文本"，可接受。
- 复制快捷键是 Cmd+C 而非 Ctrl+C。

依赖 pyobjc 的 AppKit（pyobjc-framework-Cocoa）。
"""
from __future__ import annotations

import os
import plistlib
import sys

from AppKit import NSWorkspace
from pynput.keyboard import Key

# 模拟"复制"时按下的修饰键。macOS 是 Cmd+C。
COPY_MODIFIER = Key.cmd

_TERMINAL_BUNDLE_IDS = {
    "com.apple.Terminal",
    "com.googlecode.iterm2",
    "io.alacritty",
    "net.kovidgoyal.kitty",
    "co.zeit.hyper",
    "dev.warp.Warp-Stable",
    "org.tabby",
}


def is_non_text_cursor() -> bool:
    # macOS 无可靠的全局光标形状 API，见模块文档。
    return False


def _foreground_bundle_id() -> str:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return ""
    return app.bundleIdentifier() or ""


def is_foreground_terminal() -> bool:
    return _foreground_bundle_id() in _TERMINAL_BUNDLE_IDS


# ---- 开机自启：写 ~/Library/LaunchAgents 下的 LaunchAgent plist ----
_AGENT_LABEL = "com.translatepopup.agent"
_AGENT_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{_AGENT_LABEL}.plist")


def _program_arguments() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, os.path.abspath(sys.argv[0])]


def set_autostart(enabled: bool) -> bool:
    try:
        if enabled:
            os.makedirs(os.path.dirname(_AGENT_PATH), exist_ok=True)
            with open(_AGENT_PATH, "wb") as f:
                plistlib.dump(
                    {
                        "Label": _AGENT_LABEL,
                        "ProgramArguments": _program_arguments(),
                        "RunAtLoad": True,
                    },
                    f,
                )
        elif os.path.exists(_AGENT_PATH):
            os.remove(_AGENT_PATH)
        return True
    except OSError:
        return False


def is_autostart() -> bool:
    return os.path.exists(_AGENT_PATH)
