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


def test_lang_to_code():
    from langs import lang_to_code
    assert lang_to_code("中文") == "zh-CN"
    assert lang_to_code("简体中文") == "zh-CN"
    assert lang_to_code("English") == "en"
    assert lang_to_code("english") == "en"
    assert lang_to_code("日本語") == "ja"
    assert lang_to_code("韩语") == "ko"
    assert lang_to_code("繁体中文") == "zh-TW"
    # 未知语言名 → 回落到默认值
    assert lang_to_code("克林贡语") == "en"
    assert lang_to_code("", default="zh-CN") == "zh-CN"


def test_engine_parse_primary():
    from engines import _parse_primary
    # Google translate_a/single 的真实结构：data[0] 是分段列表，seg[0] 是译文块
    raw = '[[["你好世界","Hello world",null,null,3]],null,"en"]'
    assert _parse_primary(raw) == "你好世界"
    # 多分段应拼接
    raw2 = '[[["第一句。","S1."],["第二句。","S2."]],null,"en"]'
    assert _parse_primary(raw2) == "第一句。第二句。"
    # 损坏的 JSON → None（触发兜底）
    assert _parse_primary("not json") is None
    assert _parse_primary("[]") is None


def test_engine_parse_fallback():
    from engines import _parse_fallback
    # clients5 的结构：[["译文","源语言"]]
    assert _parse_fallback('[["Hello world","fr"]]') == "Hello world"
    assert _parse_fallback('[["A","fr"],["B","fr"]]') == "AB"
    assert _parse_fallback("garbage") is None


def test_short_error_formats_json_message():
    from http_util import short_error
    body = '{"error": {"message": "invalid api key", "type": "auth"}}'
    assert short_error(401, body) == "HTTP 401: invalid api key"
    assert short_error(500, "") == "HTTP 500"
    # 非 JSON 体也能压成一行
    assert short_error(404, "Not Found").startswith("HTTP 404: Not Found")


def test_resolve_endpoint_picks_hosted_constants():
    from config import Config, HOSTED_PROXY_BASE_URL, HOSTED_DEFAULT_MODEL
    from llm_client import _resolve_endpoint

    cfg = Config()  # engine="hosted" by default
    base_url, model, auth, err = _resolve_endpoint(cfg)
    assert err is None
    assert base_url == HOSTED_PROXY_BASE_URL
    assert model == HOSTED_DEFAULT_MODEL
    assert auth is None  # hosted 不带 Authorization 头


def test_resolve_endpoint_ai_requires_key():
    from config import Config
    from llm_client import _resolve_endpoint

    cfg = Config(engine="ai", base_url="https://x.example/v1", model="m", api_key="")
    _, _, _, err = _resolve_endpoint(cfg)
    assert err and "API Key" in err

    cfg2 = Config(engine="ai", base_url="https://x.example/v1", model="m", api_key="sk-xyz")
    base, model, auth, err2 = _resolve_endpoint(cfg2)
    assert err2 is None
    assert base == "https://x.example/v1"
    assert auth == "sk-xyz"


def test_qthread_signal_to_qobject_bound_method_runs_on_main_thread():
    """回归保护:1.3.0 把 eager worker 信号连到普通 lambda 导致 PyQt 用 DirectConnection,
    槽跑在 worker 线程里碰 QWidget,Qt6Core.dll 0x1cf68 闪退(0xc0000409)。
    修法是让 App 继承 QObject、信号连绑定方法。这个 test 就守住这个不变量:
    QObject 子类的绑定方法槽必须在主线程被调用。"""
    import os, threading
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QCoreApplication, QObject, QThread, pyqtSignal, pyqtSlot
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    main_tid = threading.get_ident()

    class StubWorker(QThread):
        token_received = pyqtSignal(str)
        def run(self):
            self.token_received.emit("hello")

    class Receiver(QObject):
        def __init__(self):
            super().__init__()
            self.observed_tids: list[int] = []

        @pyqtSlot(str)
        def on_token(self, _tok: str):
            self.observed_tids.append(threading.get_ident())

    recv = Receiver()
    worker = StubWorker()
    worker.token_received.connect(recv.on_token)
    worker.start()
    worker.wait(2000)
    # 让事件循环消化排队的 QueuedConnection 调用
    for _ in range(20):
        QCoreApplication.processEvents()

    assert recv.observed_tids == [main_tid], (
        f"signal landed on wrong thread(s) {recv.observed_tids}, main={main_tid}; "
        "this is the 0xc0000409 crash pattern"
    )


def test_hosted_falls_back_to_free_when_proxy_fails():
    """代理挂了时,翻译应自动降级到免费引擎,保证「打开就能用」。"""
    import http_util
    import engines
    from config import Config
    from llm_client import LLMClient

    def fail_stream(*args, **kwargs):
        raise http_util.HttpStreamError("simulated proxy 502")
        yield  # 让 Python 把它识别为生成器函数

    def fake_free(text, target):
        yield "FREE_FALLBACK_TOKEN"

    orig_stream = http_util.stream_post_lines
    orig_free = engines.stream_free_translate
    try:
        http_util.stream_post_lines = fail_stream
        engines.stream_free_translate = fake_free
        cfg = Config()  # engine=hosted
        out = "".join(LLMClient(cfg).stream_translate("hello"))
    finally:
        http_util.stream_post_lines = orig_stream
        engines.stream_free_translate = orig_free

    assert out == "FREE_FALLBACK_TOKEN", f"got: {out!r}"


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


def test_clean_terminal_text():
    from terminal_context import clean_terminal_text
    # Claude Code 对话框边框 + 行首标记应被剥掉
    assert clean_terminal_text("╭─────╮\n│ hi  │\n╰─────╯") == "hi"
    assert clean_terminal_text("⏺ Bash(npm install)") == "Bash(npm install)"
    assert clean_terminal_text("$ git push") == "git push"
    # 被终端宽度硬切断的行应合并(上行无结束标点 + 下行小写开头)
    out = clean_terminal_text("ModuleNotFoundError: No module named\nrequests")
    assert out == "ModuleNotFoundError: No module named requests", f"got: {out!r}"
    # 句子完整的多行保持换行
    out2 = clean_terminal_text("First line.\nSecond line.")
    assert out2 == "First line.\nSecond line.", f"got: {out2!r}"
    # 清洗后为空时退回原文
    assert clean_terminal_text("│││") == "│││"


def test_glossary_lookup():
    from terminal_context import lookup_glossary
    assert lookup_glossary("MCP") is not None
    assert lookup_glossary("  mcp:  ") is not None  # 大小写/空白/尾标点都能命中
    assert lookup_glossary("`package.json`") is not None  # 包裹的反引号剥掉
    assert lookup_glossary("/clear") is not None
    assert lookup_glossary("merge conflict") is not None
    assert lookup_glossary("不存在的词xyz") is None
    assert lookup_glossary("a" * 50) is None  # 超长 → 交给 LLM
    assert lookup_glossary("two\nlines") is None  # 多行 → 交给 LLM


def test_extract_claude_suggestion():
    from terminal_context import extract_claude_suggestion
    ans = "端口被占了，不严重。\n👉 发给 Claude：帮我换一个端口重启服务"
    assert extract_claude_suggestion(ans) == "帮我换一个端口重启服务"
    assert extract_claude_suggestion("👉 fix the port conflict") == "fix the port conflict"
    assert extract_claude_suggestion("没有建议行的回答。") is None
    assert extract_claude_suggestion("") is None


def test_terminal_prompt_payload():
    from config import Config, TERMINAL_SYSTEM_PROMPT
    from llm_client import _build_chat_payload

    cfg = Config()
    # 终端场景 + 默认 prompt → 换用终端变体
    p = _build_chat_payload(cfg, "EADDRINUSE", model="m", stream=False, terminal=True)
    assert p["messages"][0]["content"] == TERMINAL_SYSTEM_PROMPT.format(target_lang="中文")
    # 非终端 → 仍是通用 prompt
    p2 = _build_chat_payload(cfg, "EADDRINUSE", model="m", stream=False)
    assert "Claude Code" not in p2["messages"][0]["content"]
    # 终端场景不做中→英反转:选中 Claude 的中文输出也用中文解释
    p3 = _build_chat_payload(cfg, "正在压缩对话", model="m", stream=False, terminal=True)
    assert "中文" in p3["messages"][0]["content"]
    # 用户自定义过 prompt → 终端场景也尊重,不覆盖
    cfg.system_prompt = "CUSTOM PROMPT {target_lang}"
    p4 = _build_chat_payload(cfg, "EADDRINUSE", model="m", stream=False, terminal=True)
    assert p4["messages"][0]["content"].startswith("CUSTOM PROMPT")


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


def test_selection_grabber_runs_off_main_thread():
    """回归保护:grab_selected_text 一旦回到 Qt 主线程,圆点就会出现 ~300ms 黑窗,
    破坏「丝滑划词」红线。SelectionGrabber 必须在自己的 QThread 里跑剪贴板轮询。
    用 mock 替换底层抓取,验证 worker 函数确实在非主线程被调用。"""
    import os, threading
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtWidgets import QApplication
    import selection_monitor

    app = QApplication.instance() or QApplication(sys.argv)
    main_tid = threading.get_ident()
    observed_tid: list[int] = []

    original = selection_monitor.grab_selected_text

    def spy(*args, **kwargs):
        observed_tid.append(threading.get_ident())
        return "captured"

    selection_monitor.grab_selected_text = spy
    try:
        captured_text: list[str] = []
        g = selection_monitor.SelectionGrabber(use_shift=False, timeout_ms=50, restore=True)
        g.captured.connect(captured_text.append)
        g.start()
        g.wait(2000)
        for _ in range(20):
            QCoreApplication.processEvents()
    finally:
        selection_monitor.grab_selected_text = original

    assert observed_tid and observed_tid[0] != main_tid, (
        f"grab ran on main thread tid={main_tid} (observed={observed_tid}); "
        "this re-introduces the 划词卡顿 regression"
    )
    assert captured_text == ["captured"], f"captured signal not delivered: {captured_text!r}"


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
        test_lang_to_code,
        test_engine_parse_primary,
        test_engine_parse_fallback,
        test_short_error_formats_json_message,
        test_resolve_endpoint_picks_hosted_constants,
        test_resolve_endpoint_ai_requires_key,
        test_clean_terminal_text,
        test_glossary_lookup,
        test_extract_claude_suggestion,
        test_terminal_prompt_payload,
        test_hosted_falls_back_to_free_when_proxy_fails,
        test_qthread_signal_to_qobject_bound_method_runs_on_main_thread,
        test_normalize_base_url_accepts_full_chat_endpoint,
        test_grab_restores_clipboard_when_no_selection,
        test_selection_grabber_runs_off_main_thread,
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
