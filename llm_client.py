from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterator

import httpx

from config import Config, normalize_base_url


_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


@dataclass
class ConnectionCheckResult:
    ok: bool
    message: str


def _contains_cjk(text: str) -> bool:
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff":
            return True
    return False


def _is_chinese_target(target: str) -> bool:
    t = target.strip().lower()
    return "中" in target or t in {
        "zh",
        "zh-cn",
        "zh_cn",
        "chinese",
        "simplified chinese",
        "chinese (simplified)",
    }


def resolve_target_lang(text: str, default_target: str) -> str:
    """Reverse direction when Chinese/Japanese source is already targeting Chinese."""
    if _contains_cjk(text) and _is_chinese_target(default_target):
        return "English"
    return default_target


def _short_error(status_code: int, body: str) -> str:
    body = (body or "").strip()
    if not body:
        return f"HTTP {status_code}"
    try:
        payload = json.loads(body)
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict):
            body = err.get("message") or err.get("type") or body
        elif isinstance(err, str):
            body = err
    except json.JSONDecodeError:
        pass
    return f"HTTP {status_code}: {body[:300]}"


def check_connection(cfg: Config, sample_text: str = "Hello") -> ConnectionCheckResult:
    """Make a small non-streaming request to verify the current API settings."""
    api_key = cfg.api_key.strip()
    base_url = normalize_base_url(cfg.base_url)
    model = cfg.model.strip()
    if not api_key:
        return ConnectionCheckResult(False, "请先填写 API Key。")
    if not base_url:
        return ConnectionCheckResult(False, "请先填写 Base URL。")
    if not model:
        return ConnectionCheckResult(False, "请先填写模型名称。")

    actual_target = resolve_target_lang(sample_text, cfg.target_lang)
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": cfg.system_prompt.format(target_lang=actual_target)},
            {"role": "user", "content": sample_text},
        ],
        "temperature": 0.2,
        "max_tokens": 64,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = httpx.post(
            base_url + "/chat/completions",
            json=payload,
            headers=headers,
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        return ConnectionCheckResult(False, f"网络连接失败：{exc}")

    if response.status_code != 200:
        return ConnectionCheckResult(False, _short_error(response.status_code, response.text))

    try:
        data = response.json()
        choices = data.get("choices") or []
        content = ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
    except Exception:
        content = ""
    if not content:
        return ConnectionCheckResult(False, "接口已返回 200，但没有返回翻译内容。请检查模型名称。")
    return ConnectionCheckResult(True, "连接成功，API Key 和模型可用。")


def _filter_think(raw_stream: Iterator[str]) -> Iterator[str]:
    """Filter <think>...</think> blocks from streamed model output."""
    in_think = False
    pending = ""
    for token in raw_stream:
        if not token:
            continue
        pending += token
        out = ""
        while pending:
            if in_think:
                idx = pending.find(_THINK_CLOSE)
                if idx == -1:
                    safe_len = len(pending)
                    for k in range(min(len(pending), len(_THINK_CLOSE) - 1), 0, -1):
                        if pending.endswith(_THINK_CLOSE[:k]):
                            safe_len = len(pending) - k
                            break
                    pending = pending[safe_len:]
                    break
                pending = pending[idx + len(_THINK_CLOSE) :]
                in_think = False
                continue
            idx = pending.find(_THINK_OPEN)
            if idx == -1:
                safe_len = len(pending)
                for k in range(min(len(pending), len(_THINK_OPEN) - 1), 0, -1):
                    if pending.endswith(_THINK_OPEN[:k]):
                        safe_len = len(pending) - k
                        break
                out += pending[:safe_len]
                pending = pending[safe_len:]
                break
            out += pending[:idx]
            pending = pending[idx + len(_THINK_OPEN) :]
            in_think = True
        if out:
            yield out
    if not in_think and pending:
        yield pending


def _strip_leading_whitespace(raw_stream: Iterator[str]) -> Iterator[str]:
    seen_text = False
    for token in raw_stream:
        if not seen_text:
            token = token.lstrip()
            if not token:
                continue
            seen_text = True
        yield token


class LLMClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _raw_stream(self, text: str) -> Iterator[str]:
        cfg = self.cfg
        api_key = cfg.api_key.strip()
        base_url = normalize_base_url(cfg.base_url)
        model = cfg.model.strip()
        if not api_key:
            yield "[未配置 API Key，请在系统托盘菜单 → 设置 中填写]"
            return
        if not base_url:
            yield "[未配置 Base URL，请在系统托盘菜单 → 设置 中填写]"
            return
        if not model:
            yield "[未配置模型名称，请在系统托盘菜单 → 设置 中填写]"
            return

        actual_target = resolve_target_lang(text, cfg.target_lang)
        system_prompt = cfg.system_prompt.format(target_lang=actual_target)
        payload = {
            "model": model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.stream(
                "POST",
                base_url + "/chat/completions",
                json=payload,
                headers=headers,
                timeout=60.0,
            ) as r:
                if r.status_code != 200:
                    body = r.read().decode("utf-8", errors="ignore")
                    yield f"[{_short_error(r.status_code, body)}]"
                    return
                for line in r.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    if line.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    token = delta.get("content")
                    if token:
                        yield token
        except httpx.HTTPError as e:
            yield f"[网络错误] {e}"

    def stream_translate(self, text: str) -> Iterator[str]:
        yield from _strip_leading_whitespace(_filter_think(self._raw_stream(text)))
