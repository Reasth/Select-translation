"""免费翻译引擎：无需 API Key，打开即用。

面向全球用户，使用 Google 的公开免费翻译端点（与众多开源划词翻译工具同源）。
主端点失败时自动切到备用端点，最大化“零配置也能用”的成功率。

不追求逐 token 流式——免费端点是一次性返回整段译文，直接交付反而更快。
"""
from __future__ import annotations

import json
import logging
from typing import Iterator, Optional
from urllib.parse import quote

import http_util
from langs import lang_to_code, resolve_target_lang

_PRIMARY = "https://translate.googleapis.com/translate_a/single"
_FALLBACK = "https://clients5.google.com/translate_a/t"


def _parse_primary(text: str) -> Optional[str]:
    try:
        data = json.loads(text)
        segments = data[0] or []
        out = "".join(seg[0] for seg in segments if seg and seg[0])
        return out or None
    except (json.JSONDecodeError, IndexError, TypeError):
        return None


def _parse_fallback(text: str) -> Optional[str]:
    try:
        data = json.loads(text)
        if isinstance(data, str):
            return data or None
        out = "".join(item[0] for item in data if isinstance(item, list) and item and item[0])
        return out or None
    except (json.JSONDecodeError, IndexError, TypeError):
        return None


def free_translate(text: str, target_lang: str) -> str:
    """返回译文；失败时抛 RuntimeError（消息面向用户）。"""
    target_code = lang_to_code(resolve_target_lang(text, target_lang))
    q = quote(text)

    primary_url = f"{_PRIMARY}?client=gtx&sl=auto&tl={target_code}&dt=t&q={q}"
    res = http_util.get(primary_url, timeout=15.0)
    if res.ok:
        parsed = _parse_primary(res.text)
        if parsed:
            return parsed
    else:
        logging.info("free engine primary failed: %s", res.error)

    fallback_url = f"{_FALLBACK}?client=dict-chrome-ex&sl=auto&tl={target_code}&q={q}"
    res2 = http_util.get(fallback_url, timeout=15.0)
    if res2.ok:
        parsed = _parse_fallback(res2.text)
        if parsed:
            return parsed
    else:
        logging.info("free engine fallback failed: %s", res2.error)

    raise RuntimeError("免费翻译暂时不可用，请检查网络，或在设置里切换到 AI 大模型引擎。")


def stream_free_translate(text: str, target_lang: str) -> Iterator[str]:
    try:
        yield free_translate(text, target_lang)
    except RuntimeError as e:
        yield f"[{e}]"


def check_free_engine(sample_text: str = "Hello") -> tuple[bool, str]:
    try:
        out = free_translate(sample_text, "中文")
    except RuntimeError as e:
        return False, str(e)
    if not out:
        return False, "免费翻译没有返回内容。"
    return True, "免费翻译可用，无需任何配置即可使用。"
