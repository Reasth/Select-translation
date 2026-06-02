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


# 客户端版本号，随发版变。通过 X-Client header 上报给代理日志，用于按版本聚合指标。
CLIENT_VERSION = "1.3.0"

# 托管代理是定值，不放进 Config（避免被本地配置改写指向别处）。
HOSTED_PROXY_BASE_URL = "https://translate-omega-livid.vercel.app/api/v1"
# M3 是 MiniMax 唯一真正尊重 thinking=disabled 的旗舰模型（实测 0 think token）。
# M2.x 系列「-highspeed」对 thinking=disabled 半听不听，仍会浪费 400+ 字思考 tokens。
HOSTED_DEFAULT_MODEL = "MiniMax-M3"

# 旧版「纯翻译」系统提示词,1.3 之前的默认值。检测到老用户配置里是这个就自动升到新 prompt。
_LEGACY_SYSTEM_PROMPT = (
    "You are a professional translator. Translate the user's text into {target_lang}. "
    "If the text is already in {target_lang}, translate it into English instead. "
    "Output ONLY the translation, with no explanations, no quotes, no labels, no thinking."
)

# 1.3 起的默认提示词:智能上下文释义。
# 核心使用场景已从「翻译外文」扩到「在命令行/IDE 里看到不懂的英文缩写/CLI flag/库名/术语
# 需要在上下文中解释」。技术词优先释义,自然语言走传统翻译。
_DEFAULT_SYSTEM_PROMPT = (
    "The user selected text and wants to understand it in context. "
    "If it's a technical term, acronym, CLI flag, library/tool name, code symbol or "
    "proper noun: explain what it means in this context, in {target_lang}. "
    "Expand acronyms. "
    "If it's natural-language prose in a foreign language: translate it into {target_lang}. "
    "If the text is already in {target_lang}, give a brief paraphrase in English instead. "
    "Be concise: 1-3 sentences max. Output ONLY the answer — no prefix, no quotes, "
    "no labels, no thinking."
)


@dataclass
class Config:
    # 默认走 hosted：作者代付的 MiniMax 大模型托管代理，打开即用、无需任何 Key。
    # "free" = 公共免费翻译（Google，非 AI），断网/代理挂时也作为兜底；
    # "ai"   = 用户自带 OpenAI 兼容服务（自费、自填 Key）。
    engine: str = "hosted"  # "hosted" | "free" | "ai"
    # 以下字段仅在 engine == "ai" 时生效；预填 MiniMax 国内端点作为常用起点。
    base_url: str = "https://api.minimaxi.com/v1"
    api_key: str = ""
    model: str = "MiniMax-M2.7-highspeed"
    target_lang: str = "中文"
    source_lang: str = "auto"
    enabled: bool = True
    autostart: bool = False
    install_id: str = ""  # 首次启动自动生成的匿名持久 UUID,用于埋点关联同一安装的事件
    show_icon_ms: int = 2000  # 乔布斯式：看清→识别→决策→移动到圆点 ≈ 2s
    min_chars: int = 1
    max_chars: int = 3000
    system_prompt: str = _DEFAULT_SYSTEM_PROMPT

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
        # 1.3 升级:老配置里的「纯翻译」prompt 自动替成「智能上下文释义」。
        # 用户自定义过的 prompt 保留不动。
        if cfg.system_prompt.strip() == _LEGACY_SYSTEM_PROMPT.strip():
            cfg.system_prompt = _DEFAULT_SYSTEM_PROMPT
            cfg.save()
        return cfg

    def save(self) -> None:
        self.base_url = normalize_base_url(self.base_url)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
