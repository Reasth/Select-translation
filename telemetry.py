"""客户端埋点 fire-and-forget 发送器。

每个事件后台线程 POST 到 /api/event,失败永远静默——埋点不能拖慢主流程或
吓到用户。事件结构:
    POST .../api/event
    Headers: X-Client, X-Install-Id, X-Session-Id
    Body:    { "event": "<snake_case>", "props": {...} }
代理端用 service-side anon key 写入 Supabase events 表。

安哥(2026-06-01)硬约束:每个交互一条 log + 持久化数据库。本模块只负责
「客户端 → 函数」这一段,持久化在函数端完成。
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from typing import Any
from uuid import uuid4

from config import CLIENT_VERSION, HOSTED_PROXY_BASE_URL


# .../api/v1 → .../api/event。和翻译端点共享 host,但路径不一样。
_EVENT_URL = HOSTED_PROXY_BASE_URL.rsplit("/v1", 1)[0] + "/event"
_TIMEOUT = 5.0


def new_session_id() -> str:
    """每次 app 启动随机一个,放内存,不持久化。"""
    return str(uuid4())


def ensure_install_id(cfg) -> str:
    """读 cfg.install_id,空就生成一个并写回 config.json。匿名,无 PII。"""
    if not cfg.install_id:
        cfg.install_id = str(uuid4())
        cfg.save()
    return cfg.install_id


class Telemetry:
    def __init__(self, install_id: str, session_id: str, *, enabled: bool = True):
        self.install_id = install_id
        self.session_id = session_id
        self.client = f"translate-popup/{CLIENT_VERSION}"
        self.enabled = enabled

    def fire(self, event: str, props: dict[str, Any] | None = None) -> None:
        """异步发一条事件;调用方拿到控制权立即返回。"""
        if not self.enabled:
            return
        threading.Thread(
            target=self._send,
            args=(event, dict(props or {})),
            daemon=True,
        ).start()

    def _send(self, event: str, props: dict[str, Any]) -> None:
        try:
            body = json.dumps({"event": event, "props": props}).encode("utf-8")
        except (TypeError, ValueError):
            return  # props 里有不可序列化的对象,丢
        req = urllib.request.Request(
            _EVENT_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Client": self.client,
                "X-Install-Id": self.install_id,
                "X-Session-Id": self.session_id,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                r.read()
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            # 永远不要让埋点拖垮主流程。日志降级到 DEBUG。
            logging.debug("telemetry fire failed event=%s", event, exc_info=False)
        except Exception:
            logging.debug("telemetry fire crashed event=%s", event, exc_info=False)

    def telemetry_headers(self) -> dict[str, str]:
        """供翻译请求复用的同套 ID 头,让代理端 metric 行也能挂上 install_id/session_id。"""
        return {
            "X-Client": self.client,
            "X-Install-Id": self.install_id,
            "X-Session-Id": self.session_id,
        }
