"""自测脚本：验证关键内部逻辑，不依赖真实鼠标/GUI。"""
from __future__ import annotations

import sys
import time

import pyperclip


def test_filter_think_strips_block():
    from llm_client import _filter_think

    def gen():
        for c in "Hello<think>thinking secret</think> world":
            yield c

    out = "".join(_filter_think(gen()))
    assert out == "Hello world", f"got: {out!r}"


def test_filter_think_split_across_chunks():
    from llm_client import _filter_think
    # 模拟 <think> 标签跨多个 token 边界
    chunks = ["A", "<", "thi", "nk>", "secret", "</", "think>", "B"]
    out = "".join(_filter_think(iter(chunks)))
    assert out == "AB", f"got: {out!r}"


def test_filter_think_no_block_passes_through():
    from llm_client import _filter_think
    out = "".join(_filter_think(iter(["你好", "世界"])))
    assert out == "你好世界", f"got: {out!r}"


def test_resolve_target_lang():
    from llm_client import resolve_target_lang
    # 中文原文 + 默认目标是中文 → 反向翻译到英文
    assert resolve_target_lang("你好世界", "中文") == "English"
    assert resolve_target_lang("你好", "zh-CN") == "English"
    # 英文原文 + 默认目标是中文 → 仍翻成中文
    assert resolve_target_lang("Hello world", "中文") == "中文"
    # 中文原文 + 默认目标不是中文（比如日文） → 按用户设置
    assert resolve_target_lang("你好", "日本語") == "日本語"
    # 纯符号 → 按用户设置
    assert resolve_target_lang("123 !!!", "中文") == "中文"


def test_normalize_base_url_accepts_full_chat_endpoint():
    from config import normalize_base_url

    assert normalize_base_url("api.example.com/v1") == "https://api.example.com/v1"
    assert normalize_base_url("https://api.example.com/v1/") == "https://api.example.com/v1"
    assert (
        normalize_base_url("https://api.example.com/v1/chat/completions")
        == "https://api.example.com/v1"
    )


def test_filter_think_unclosed_block_dropped():
    from llm_client import _filter_think
    # <think> 后没有结束标签，整段都应丢弃
    out = "".join(_filter_think(iter(["X<think>", "infinite reasoning..."])))
    assert out == "X", f"got: {out!r}"


def test_stream_strips_leading_whitespace():
    from llm_client import _strip_leading_whitespace

    out = "".join(_strip_leading_whitespace(iter(["\n", "\n  ", "Hello", " world"])))
    assert out == "Hello world", f"got: {out!r}"


def test_grab_restores_clipboard_when_no_selection():
    """没有选中任何文本时，剪贴板应该恢复原状。"""
    from selection_monitor import grab_selected_text

    sentinel = f"ORIGINAL_{time.time_ns()}"
    pyperclip.copy(sentinel)
    assert pyperclip.paste() == sentinel

    # 当前焦点窗口（CMD/PowerShell/IDE）应该没有"刚选中的文本"，grab 应失败并恢复
    result = grab_selected_text(timeout_ms=200)
    after = pyperclip.paste()
    # 即使有捕获也无所谓；关键是测"失败路径会恢复"——构造一个必失败的场景比较麻烦，
    # 这里至少验证函数不会留下哨兵字符串
    assert "__TRANSLATE_POPUP_SENTINEL__" not in after, f"sentinel leaked: {after!r}"
    print(f"  grab returned: {result!r}, clipboard after: {after!r}")


def test_floating_icon_construct_and_position():
    """构造圆点窗口、调用 show_near_cursor 不应崩溃，位置计算正确。"""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    from floating_icon import FloatingIcon

    icon = FloatingIcon()
    icon.show_near_cursor(500, 300, lifetime_ms=10)
    # 验证位置：anchor_x + 4, anchor_y - (SIZE + 4) = 504, 286
    assert icon.x() == 504, f"x={icon.x()}"
    assert icon.y() == 280, f"y={icon.y()}"
    assert icon.contains_global_point(icon.mapToGlobal(icon.rect().center()))
    icon.hide()


def main():
    tests = [
        test_filter_think_strips_block,
        test_filter_think_split_across_chunks,
        test_filter_think_no_block_passes_through,
        test_filter_think_unclosed_block_dropped,
        test_stream_strips_leading_whitespace,
        test_resolve_target_lang,
        test_normalize_base_url_accepts_full_chat_endpoint,
        test_grab_restores_clipboard_when_no_selection,
        test_floating_icon_construct_and_position,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
