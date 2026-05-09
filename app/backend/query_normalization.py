from __future__ import annotations

import re

VENUE_ALIASES: dict[str, str] = {
    "usenix": "USENIX_SECURITY",
    "usenix security": "USENIX_SECURITY",
    "usenix安全": "USENIX_SECURITY",
    "ndss": "NDSS",
    "ieee sp": "IEEE_SP",
    "ieee s&p": "IEEE_SP",
    "oakland": "IEEE_SP",
    "sp": "IEEE_SP",
    "s&p": "IEEE_SP",
    "ccs": "ACM_CCS",
    "acm ccs": "ACM_CCS",
}

ZH_STOP_PHRASES = [
    "帮我找",
    "给我找",
    "帮我查",
    "查一下",
    "搜一下",
    "检索一下",
    "帮我比较",
    "帮我总结",
    "请帮我",
    "我想找",
    "有哪些关于",
    "有哪些",
    "关于",
    "相关的",
    "相关",
    "方面的",
    "方向的",
    "里面",
    "论文",
    "文章",
    "工作",
    "研究",
    "请问",
    "一下",
    "什么",
    "哪些",
    "给我",
    "帮我",
    "比较",
    "对比",
    "总结",
    "归纳",
    "综述",
    "为什么",
    "如何",
    "哪个",
    "更适合",
]

EN_STOP_PHRASES = [
    "papers about",
    "paper about",
    "find papers about",
    "find papers on",
    "search papers about",
    "search for",
    "please",
    "papers",
    "paper",
    "about",
    "on",
    "related to",
    "compare",
    "comparison",
    "summarize",
    "summary",
    "why",
    "how",
    "which",
]

TOP_K_PATTERNS = [
    re.compile(r"top\s*(\d{1,2})", re.IGNORECASE),
    re.compile(r"前\s*(\d{1,2})\s*篇"),
    re.compile(r"(\d{1,2})\s*篇"),
]

YEAR_RANGE_PATTERN = re.compile(r"(20\d{2})\s*[-~到]\s*(20\d{2})")
YEAR_PATTERN = re.compile(r"(?<!\d)(20\d{2})(?!\d)")

ZH_FILLER_PREFIXES = [
    "请问",
    "我想",
    "我想找",
    "帮我",
    "给我",
    "看看",
    "找",
    "查",
    "搜",
]

CHINESE_SUFFIX_NOISE_PATTERNS = [
    re.compile(r"(中的|里的)+$"),
    re.compile(r"(方面|方向|领域)的$"),
    re.compile(r"的论文$"),
    re.compile(r"的文章$"),
    re.compile(r"的工作$"),
    re.compile(r"的研究$"),
    re.compile(r"相关论文$"),
    re.compile(r"相关工作$"),
    re.compile(r"相关研究$"),
    re.compile(r"相关内容$"),
    re.compile(r"有哪些$"),
    re.compile(r"的$"),
]

CHINESE_WRAPPER_PATTERNS = [
    (re.compile(r"^关于(.+)$"), 1),
    (re.compile(r"^对于(.+)$"), 1),
    (re.compile(r"^有关(.+)$"), 1),
]


def remove_english_stop_phrases(text: str) -> str:
    value = text
    for phrase in sorted(EN_STOP_PHRASES, key=len, reverse=True):
        value = re.sub(rf"\b{re.escape(phrase)}\b", " ", value, flags=re.IGNORECASE)
    return value


def remove_chinese_stop_phrases(text: str) -> str:
    value = text
    for phrase in sorted(ZH_STOP_PHRASES, key=len, reverse=True):
        value = value.replace(phrase, " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def strip_filler_prefixes(text: str) -> str:
    value = text.strip()
    changed = True
    while changed and value:
        changed = False
        for prefix in sorted(ZH_FILLER_PREFIXES, key=len, reverse=True):
            if value.startswith(prefix):
                value = value[len(prefix):].strip()
                changed = True
    return value


def strip_chinese_wrapper_phrases(text: str) -> str:
    value = text.strip()
    changed = True
    while changed and value:
        changed = False
        for pattern, group_index in CHINESE_WRAPPER_PATTERNS:
            matched = pattern.match(value)
            if matched:
                value = matched.group(group_index).strip()
                changed = True
        for pattern in CHINESE_SUFFIX_NOISE_PATTERNS:
            next_value = pattern.sub("", value).strip()
            if next_value != value and next_value:
                value = next_value
                changed = True
    return value


def normalize_topic_text(text: str) -> str:
    value = text
    value = YEAR_RANGE_PATTERN.sub(" ", value)
    value = YEAR_PATTERN.sub(" ", value)
    for pattern in TOP_K_PATTERNS:
        value = pattern.sub(" ", value)

    for alias in sorted(VENUE_ALIASES.keys(), key=len, reverse=True):
        value = re.sub(rf"\b{re.escape(alias)}\b", " ", value, flags=re.IGNORECASE)

    value = remove_english_stop_phrases(value)
    value = remove_chinese_stop_phrases(value)
    value = re.sub(r"[，。,．.?!？!：:;；()（）\[\]{}\-_/]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" -_")
    value = strip_filler_prefixes(value)
    value = strip_chinese_wrapper_phrases(value)
    value = re.sub(r"\s+", " ", value).strip(" -_")
    return value.strip()
