"""按运行平台选择集成实现，向上层暴露统一接口。

暴露：
- is_non_text_cursor() -> bool   按下鼠标时光标是否"明显不在选文本"
- is_foreground_terminal() -> bool 前台窗口是否为终端（终端里抢剪贴板易出问题）
- COPY_MODIFIER                   模拟复制时按下的修饰键（Win=Ctrl, mac=Cmd）

只 import 当前平台对应的模块——platform_win 依赖 ctypes.windll，platform_mac 依赖
AppKit，跨平台 import 会在模块加载期失败，所以必须按 sys.platform 分支。
"""
from __future__ import annotations

import sys

if sys.platform == "darwin":
    from platform_mac import (
        COPY_MODIFIER,
        is_foreground_terminal,
        is_non_text_cursor,
    )
elif sys.platform == "win32":
    from platform_win import (
        COPY_MODIFIER,
        is_foreground_terminal,
        is_non_text_cursor,
    )
else:
    # Linux 等其它平台的保底实现：不做光标/终端判断，复制用 Ctrl。
    from pynput.keyboard import Key

    COPY_MODIFIER = Key.ctrl

    def is_non_text_cursor() -> bool:
        return False

    def is_foreground_terminal() -> bool:
        return False


__all__ = ["COPY_MODIFIER", "is_foreground_terminal", "is_non_text_cursor"]
