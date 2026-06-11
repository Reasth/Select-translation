from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Iterator, Optional

import engines
import http_util
from config import (
    CLIENT_VERSION,
    HOSTED_DEFAULT_MODEL,
    HOSTED_PROXY_BASE_URL,
    TERMINAL_SYSTEM_PROMPT,
    _DEFAULT_SYSTEM_PROMPT,
    Config,
    normalize_base_url,
)
from langs import resolve_target_lang  # re-export: 旧代码与测试从 llm_client 引用

__all__ = [
    "ConnectionCheckResult",
    "LLMClient",
    "check_connection",
    "resolve_target_lang",
]


_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


@dataclass
class ConnectionCheckResult:
    ok: bool
    message: str


def _build_chat_payload(
    cfg: Config,
    text: str,
    *,
    model: str,
    stream: bool,
    max_tokens: Optional[int] = None,
    extra: Optional[dict] = None,
    terminal: bool = False,
) -> dict:
    # 终端场景不做「中文原文→反向翻英文」:用户选中 Claude 的中文输出时要的是
    # 中文解释这段话在说什么,而不是英文翻译。
    actual_target = cfg.target_lang if terminal else resolve_target_lang(text, cfg.target_lang)
    # 终端变体只在用户没自定义过 prompt 时启用——自定义过的是 power user,尊重其设置。
    system_prompt = cfg.system_prompt
    if terminal and cfg.system_prompt.strip() == _DEFAULT_SYSTEM_PROMPT.strip():
        system_prompt = TERMINAL_SYSTEM_PROMPT
    payload: dict = {
        "model": model,
        "stream": stream,
        "messages": [
            {"role": "system", "content": system_prompt.format(target_lang=actual_target)},
            {"role": "user", "content": text},
        ],
        "temperature": 0.2,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if extra:
        payload.update(extra)
    return payload


def _resolve_endpoint(cfg: Config) -> tuple[str, str, Optional[str], Optional[str]]:
    """返回 (base_url, model, auth_token, precheck_error)。
    precheck_error 非空时说明用户缺关键配置，应直接把它当作 [..] 提示展示。
    auth_token 为 None 时不发 Authorization 头（hosted 不需要）。
    """
    if cfg.engine == "hosted":
        return HOSTED_PROXY_BASE_URL, HOSTED_DEFAULT_MODEL, None, None

    base_url = normalize_base_url(cfg.base_url)
    model = cfg.model.strip()
    api_key = cfg.api_key.strip()
    if not base_url:
        return "", "", None, "请先填写 Base URL。"
    if not model:
        return "", "", None, "请先填写模型名称。"
    if not api_key:
        return "", "", None, "请先填写 API Key。"
    return base_url, model, api_key, None


def check_connection(cfg: Config, sample_text: str = "Hello") -> ConnectionCheckResult:
    """验证当前翻译设置是否可用。"""
    if cfg.engine == "free":
        ok, message = engines.check_free_engine(sample_text)
        return ConnectionCheckResult(ok, message)

    base_url, model, auth_token, err = _resolve_endpoint(cfg)
    if err:
        return ConnectionCheckResult(False, err)

    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
    # hosted 走 M3 必须明确关掉 thinking，否则会浪费 1-3s 推理时间
    extra = {"thinking": {"type": "disabled"}} if cfg.engine == "hosted" else None
    payload = _build_chat_payload(cfg, sample_text, model=model, stream=False, max_tokens=64, extra=extra)
    res = http_util.post_json(
        base_url + "/chat/completions",
        payload,
        headers=headers,
        timeout=30.0,
    )
    if not res.ok:
        return ConnectionCheckResult(False, res.error or f"HTTP {res.status}")

    try:
        data = json.loads(res.text)
        choices = data.get("choices") or []
        content = ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
    except Exception:
        content = ""
    if not content:
        return ConnectionCheckResult(False, "接口已返回 200，但没有翻译内容。请检查模型名称。")
    if cfg.engine == "hosted":
        return ConnectionCheckResult(True, "托管代理可用，MiniMax 已就绪。")
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
        # App 在 Telemetry 就绪后塞进来,让 hosted 请求带上 X-Install-Id / X-Session-Id,
        # 这样代理端 metric 行能和客户端事件用同一 install_id 关联。
        self.install_id: str = ""
        self.session_id: str = ""

    def _stream_openai_compat(
        self,
        text: str,
        *,
        base_url: str,
        model: str,
        auth_token: Optional[str],
        extra_payload: Optional[dict] = None,
        extra_headers: Optional[dict] = None,
        terminal: bool = False,
    ) -> Iterator[str]:
        """通用 OpenAI 兼容流式调用。网络/HTTP 错误向上抛 HttpStreamError。"""
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
        if extra_headers:
            headers.update(extra_headers)
        payload = _build_chat_payload(
            self.cfg, text, model=model, stream=True, extra=extra_payload, terminal=terminal
        )
        for raw in http_util.stream_post_lines(
            base_url + "/chat/completions",
            payload,
            headers=headers,
            timeout=60.0,
        ):
            line = raw.strip()
            if not line:
                continue
            if line.startswith("data: "):
                line = line[6:]
            if line == "[DONE]":
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

    def _ai_stream(self, text: str, *, terminal: bool = False) -> Iterator[str]:
        """AI 档：缺配置或网络错误以 [..] 形式回显，便于排查自家 Key。"""
        base_url, model, auth_token, err = _resolve_endpoint(self.cfg)
        if err:
            yield f"[{err}]"
            return
        try:
            yield from self._stream_openai_compat(
                text, base_url=base_url, model=model, auth_token=auth_token, terminal=terminal
            )
        except http_util.HttpStreamError as e:
            yield f"[{e.message}]"

    def _hosted_stream(self, text: str, *, source: str = "click", terminal: bool = False) -> Iterator[str]:
        """托管档：用作者代付的代理；失败时静默降级到免费引擎，保证「打开就能翻译」。
        thinking=disabled 在 M3 上是真禁推理（实测 0 think token，TTFT 直接降到 ~3s）。
        source 决定 X-Source header（eager|click），用于代理端日志区分预翻译命中率。"""
        headers = {
            "X-Client": f"translate-popup/{CLIENT_VERSION}",
            "X-Source": source,
        }
        if self.install_id:
            headers["X-Install-Id"] = self.install_id
        if self.session_id:
            headers["X-Session-Id"] = self.session_id
        try:
            yield from self._stream_openai_compat(
                text,
                base_url=HOSTED_PROXY_BASE_URL,
                model=HOSTED_DEFAULT_MODEL,
                auth_token=None,
                extra_payload={"thinking": {"type": "disabled"}},
                extra_headers=headers,
                terminal=terminal,
            )
        except http_util.HttpStreamError as e:
            logging.warning("hosted engine failed (%s), falling back to free", e.message)
            yield from engines.stream_free_translate(text, self.cfg.target_lang)

    def stream_translate(self, text: str, *, source: str = "click", terminal: bool = False) -> Iterator[str]:
        # terminal=True 表示文本选自终端(按产品假设即 Claude Code 会话),走终端
        # 专用 prompt:报错给修复建议、命令给风险标识。free 引擎是纯翻译,无视该标志。
        engine = self.cfg.engine
        if engine == "free":
            yield from engines.stream_free_translate(text, self.cfg.target_lang)
            return
        if engine == "hosted":
            raw = self._hosted_stream(text, source=source, terminal=terminal)
        else:
            raw = self._ai_stream(text, terminal=terminal)
        yield from _strip_leading_whitespace(_filter_think(raw))
