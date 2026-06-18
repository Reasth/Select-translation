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
CLIENT_VERSION = "1.4.1"

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

# 1.3 默认提示词:智能上下文释义。保留用于自动迁移老用户配置。
_CONTEXT_SYSTEM_PROMPT_V1 = (
    "The user selected text and wants to understand it in context. "
    "If it's a technical term, acronym, CLI flag, library/tool name, code symbol or "
    "proper noun: explain what it means in this context, in {target_lang}. "
    "Expand acronyms. "
    "If it's natural-language prose in a foreign language: translate it into {target_lang}. "
    "If the text is already in {target_lang}, give a brief paraphrase in English instead. "
    "Be concise: 1-3 sentences max. Output ONLY the answer — no prefix, no quotes, "
    "no labels, no thinking."
)

# 1.4.2 默认提示词:继续支持术语释义,但强制单一目标语言输出。
# 之前的 prompt 偶尔会让英文原文得到英文+中文或纯英文解释。
_DEFAULT_SYSTEM_PROMPT = (
    "The user selected text and wants to understand it in context. "
    "Always answer in {target_lang}. Do not answer in English unless {target_lang} is English. "
    "If it's natural-language prose that is not already in {target_lang}: translate it into {target_lang}. "
    "If it's already in {target_lang}: briefly paraphrase it in {target_lang}. "
    "If it's a technical term, acronym, CLI flag, library/tool name, code symbol or "
    "proper noun: explain what it means in this context, in {target_lang}; keep the "
    "original spelling only when necessary. Expand acronyms. "
    "Output a single-language answer; do not include the original text or a bilingual translation. "
    "Be concise: 1-3 sentences max. Output ONLY the answer — no prefix, no quotes, "
    "no labels, no thinking."
)

# 1.4 终端(Claude Code)场景变体:产品假设「终端划词 = Claude Code 会话里的零编程
# 经验用户」。回答从「解释」升级为「消除焦虑 + 给下一步动作」:报错给严重度和可直接
# 发给 Claude 的修复请求(👉 行,UI 据此显示一键复制按钮),命令给风险标识。
# token 预算约束:本 prompt 控制在 ~160 token;输出默认仍 1-3 句,只有报错/命令
# 才放宽到 5 句,90% 的查询成本与通用 prompt 持平。
TERMINAL_SYSTEM_PROMPT = (
    "The selected text comes from a terminal running Claude Code (Anthropic's AI "
    "coding agent). The user is a non-programmer. Answer in {target_lang} using plain "
    "everyday words; never explain jargon with more jargon. "
    "If it's an error message: say what broke and how serious it is, then on a new "
    "line write exactly '👉 ' followed by one short instruction the user can paste "
    "to Claude to get it fixed. "
    "If it's a shell command: start with ✅ (read-only/safe), ⚠️ (modifies files or "
    "state) or 🛑 (destructive/hard to undo), then say what it does. "
    "If it's Claude Code UI text or a technical term: explain what it means for the "
    "user here. Otherwise translate or paraphrase it briefly. "
    "Default 1-3 sentences; up to 5 for errors or commands. Output ONLY the answer — "
    "no prefix, no labels, no thinking."
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
        # 老默认 prompt 自动升级；用户自定义过的 prompt 保留不动。
        default_prompt_aliases = {
            _LEGACY_SYSTEM_PROMPT.strip(),
            _CONTEXT_SYSTEM_PROMPT_V1.strip(),
        }
        if cfg.system_prompt.strip() in default_prompt_aliases:
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
