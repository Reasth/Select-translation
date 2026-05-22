from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


CONFIG_DIR = Path.home() / ".translate-popup"
CONFIG_PATH = CONFIG_DIR / "config.json"


def normalize_base_url(value: str) -> str:
    """Return an OpenAI-compatible API base URL from user input."""
    url = (value or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    url = url.rstrip("/")
    suffix = "/chat/completions"
    if url.lower().endswith(suffix):
        url = url[: -len(suffix)].rstrip("/")
    return url


@dataclass
class Config:
    # MiniMax 原生端点；MiniMax-M2.1 是当前 token plan 下最快的 chat 模型（实测 ~3s 完成）
    base_url: str = "https://api.minimaxi.com/v1"
    api_key: str = ""
    model: str = "MiniMax-M2.1"
    target_lang: str = "中文"
    source_lang: str = "auto"
    enabled: bool = True
    show_icon_ms: int = 2000  # 乔布斯式：看清→识别→决策→移动到圆点 ≈ 2s
    min_chars: int = 1
    max_chars: int = 3000
    system_prompt: str = (
        "You are a professional translator. Translate the user's text into {target_lang}. "
        "If the text is already in {target_lang}, translate it into English instead. "
        "Output ONLY the translation, with no explanations, no quotes, no labels, no thinking."
    )

    @classmethod
    def load(cls) -> "Config":
        if not CONFIG_PATH.exists():
            cfg = cls()
            cfg.save()
            return cfg
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        cfg = cls()
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        cfg.base_url = normalize_base_url(cfg.base_url)
        return cfg

    def save(self) -> None:
        self.base_url = normalize_base_url(self.base_url)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
