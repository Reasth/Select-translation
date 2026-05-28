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
