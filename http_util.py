"""标准库 urllib 实现的极简 HTTP 客户端。

用它替代 httpx，去掉 httpx + certifi + anyio + h11 + idna 这一串传递依赖，
显著减小打包体积，并复用系统证书库（对 PyInstaller 冻结包更友好）。

只覆盖本项目需要的三种用法：
- get()           免费翻译引擎的 GET 请求
- post_json()     连接测试等一次性 JSON 请求
- stream_post_lines()  大模型流式响应（按行 yield）
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterator, Mapping, Optional

# 一些免费翻译端点对默认 Python UA 不友好，统一带上浏览器风格 UA。
_DEFAULT_UA = "Mozilla/5.0 (compatible; TranslatePopup/1.0)"


@dataclass
class HttpResponse:
    status: int
    text: str
    ok: bool
    error: str = ""


class HttpStreamError(Exception):
    """流式请求阶段失败，携带一条可直接展示给用户的中文消息。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def short_error(status_code: int, body: str) -> str:
    """把接口返回的错误体压成一行简短可读的提示。"""
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


def _build_request(
    url: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    data: Optional[bytes] = None,
    method: Optional[str] = None,
) -> urllib.request.Request:
    merged = {"User-Agent": _DEFAULT_UA}
    if headers:
        merged.update(headers)
    return urllib.request.Request(url, data=data, headers=merged, method=method)


def _execute(req: urllib.request.Request, timeout: float) -> HttpResponse:
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        return HttpResponse(status=e.code, text=body, ok=False, error=short_error(e.code, body))
    except urllib.error.URLError as e:
        return HttpResponse(status=0, text="", ok=False, error=f"网络连接失败：{e.reason}")
    except Exception as e:  # noqa: BLE001 - 兜底任何 socket/ssl 异常
        return HttpResponse(status=0, text="", ok=False, error=f"网络连接失败：{e}")
    with resp:
        text = resp.read().decode("utf-8", "ignore")
    return HttpResponse(status=getattr(resp, "status", 200), text=text, ok=True)


def get(url: str, *, headers: Optional[Mapping[str, str]] = None, timeout: float = 15.0) -> HttpResponse:
    return _execute(_build_request(url, headers=headers, method="GET"), timeout)


def post_json(
    url: str,
    payload: dict,
    *,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = 30.0,
) -> HttpResponse:
    data = json.dumps(payload).encode("utf-8")
    merged = {"Content-Type": "application/json"}
    if headers:
        merged.update(headers)
    return _execute(_build_request(url, headers=merged, data=data, method="POST"), timeout)


def stream_post_lines(
    url: str,
    payload: dict,
    *,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = 60.0,
) -> Iterator[str]:
    """发起流式 POST，按行 yield 解码后的文本。

    非 2xx 或网络异常时抛 HttpStreamError（消息已是面向用户的中文）。
    """
    data = json.dumps(payload).encode("utf-8")
    merged = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if headers:
        merged.update(headers)
    req = _build_request(url, headers=merged, data=data, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        raise HttpStreamError(short_error(e.code, body))
    except urllib.error.URLError as e:
        raise HttpStreamError(f"网络错误：{e.reason}")
    except Exception as e:  # noqa: BLE001
        raise HttpStreamError(f"网络错误：{e}")
    with resp:
        for raw in resp:
            yield raw.decode("utf-8", "ignore")
