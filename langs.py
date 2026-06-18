"""语言方向判断与语言码映射。

单独成模块，避免 llm_client 与 engines 互相 import 形成环：
- resolve_target_lang：保留旧入口,现在始终尊重用户设置的目标语言
- lang_to_code：把用户填的语言名（中文/English/日本語…）映射成翻译引擎用的语言码
"""
from __future__ import annotations


def resolve_target_lang(text: str, default_target: str) -> str:
    """返回用户设置的目标语言;不再根据原文语言反向切换。"""
    return default_target


# 语言名 → 翻译引擎语言码（Google 风格）。键统一小写；中日韩名本身小写即自身。
_LANG_CODES = {
    "中文": "zh-CN",
    "中文(简体)": "zh-CN",
    "简体中文": "zh-CN",
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh_cn": "zh-CN",
    "chinese": "zh-CN",
    "simplified chinese": "zh-CN",
    "繁体中文": "zh-TW",
    "中文(繁体)": "zh-TW",
    "zh-tw": "zh-TW",
    "traditional chinese": "zh-TW",
    "english": "en",
    "英语": "en",
    "英文": "en",
    "en": "en",
    "日本語": "ja",
    "日语": "ja",
    "japanese": "ja",
    "ja": "ja",
    "한국어": "ko",
    "韩语": "ko",
    "korean": "ko",
    "ko": "ko",
    "français": "fr",
    "法语": "fr",
    "french": "fr",
    "fr": "fr",
    "deutsch": "de",
    "德语": "de",
    "german": "de",
    "de": "de",
    "español": "es",
    "西班牙语": "es",
    "spanish": "es",
    "es": "es",
    "italiano": "it",
    "意大利语": "it",
    "italian": "it",
    "it": "it",
    "português": "pt",
    "葡萄牙语": "pt",
    "portuguese": "pt",
    "pt": "pt",
    "русский": "ru",
    "俄语": "ru",
    "russian": "ru",
    "ru": "ru",
    "العربية": "ar",
    "阿拉伯语": "ar",
    "arabic": "ar",
    "ar": "ar",
    "tiếng việt": "vi",
    "越南语": "vi",
    "vietnamese": "vi",
    "vi": "vi",
    "ไทย": "th",
    "泰语": "th",
    "thai": "th",
    "th": "th",
}


def lang_to_code(name: str, default: str = "en") -> str:
    raw = (name or "").strip()
    if not raw:
        return default
    return _LANG_CODES.get(raw.lower(), _LANG_CODES.get(raw, default))
