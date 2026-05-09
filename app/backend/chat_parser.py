from __future__ import annotations

import json
import re
import subprocess
import threading
from typing import Any

import requests

from backend.chat_models import (
    ChatFilters,
    ExpectedResultShape,
    NeighborDriftRisk,
    QueryScope,
    StructuredQuery,
    TargetGranularity,
)
from backend.config import settings
from backend.llm_usage import log_llm_usage
from backend.pg_json_store import run_sql
from backend.query_normalization import (
    TOP_K_PATTERNS,
    VENUE_ALIASES,
    YEAR_PATTERN,
    YEAR_RANGE_PATTERN,
    ZH_FILLER_PREFIXES,
    normalize_topic_text,
    strip_filler_prefixes,
)
from backend.topic_profile_config import match_runtime_profile
from backend.topic_taxonomy import expand_topics, infer_query_type_from_topics, score_topic_entries

INTENT_KEYWORDS = {
    "compare": ["compare", "比较", "区别", "不同", "versus", "vs", "对比"],
    "summarize": ["summarize", "总结", "概述", "趋势", "归纳", "综述一下"],
    "qa": ["why", "how", "which", "哪篇", "为什么", "如何", "哪个好", "更适合", "更偏", "是什么"],
}

CHAT_PATTERNS = [
    r"^(你好|您好|嗨|哈喽|hello|hi|hey)[!,.，。！？\s]*$",
    r"^(早上好|中午好|下午好|晚上好)[!,.，。！？\s]*$",
]
META_PATTERNS = [
    r"^(你是谁|你是干什么的|介绍一下你自己|who are you)[!,.，。！？\s]*$",
]
HELP_PATTERNS = [
    r"^(help|帮助|怎么用|如何使用|你能做什么|这个页面怎么用|你可以做什么)[!,.，。！？\s]*$",
]
ASK_CLARIFICATION_PATTERNS = [
    r"^(继续|然后呢|再说说|展开说说|展开讲讲|细说|继续说)[!,.，。！？\s]*$",
]

FULLTEXT_KEYWORDS = [
    "full text",
    "fulltext",
    "全文",
    "evidence",
    "证据",
    "实验",
    "threat model",
    "参数",
    "细节",
    "结果",
]

ZH_KEYWORD_MAP: dict[str, list[str]] = {
    "越狱": ["jailbreak", "prompt injection", "guardrail bypass"],
    "提示注入": ["prompt injection", "indirect prompt injection"],
    "攻击": ["attack", "exploitation"],
    "防御": ["defense", "mitigation"],
    "浏览器": ["browser", "web", "extension"],
    "网页": ["web", "website", "browser"],
    "指纹": ["fingerprinting", "fingerprint", "browser fingerprinting"],
    "水印": ["watermarking", "watermark"],
    "安全聚合": ["secure aggregation"],
    "隐私": ["privacy", "private learning"],
    "大模型": ["llm", "large language model", "foundation model"],
    "语言模型": ["language model", "llm", "large language model"],
    "AI 安全": ["ai security", "secure ai systems", "security of ai"],
    "AI安全": ["ai security", "secure ai systems", "security of ai"],
    "LLM 安全": ["llm security", "llm safety", "model safety", "safe ai systems"],
    "LLM安全": ["llm security", "llm safety", "model safety", "safe ai systems"],
    "模型安全": ["model security", "ml model security", "llm safety", "model safety"],
    "模型安全性": ["llm safety", "model safety", "safety evaluation"],
    "数据投毒": ["data poisoning", "poisoning attacks", "adversarial machine learning"],
    "投毒攻击": ["data poisoning", "poisoning attacks", "adversarial machine learning"],
    "中毒攻击": ["data poisoning", "poisoning attacks", "adversarial machine learning"],
    "后门攻击": ["backdoor", "backdoor attacks", "trojan attack", "adversarial machine learning"],
    "模型窃取": ["model stealing", "model extraction"],
    "成员推断": ["membership inference", "privacy attacks"],
    "供应链": ["supply chain"],
    "恶意软件": ["malware", "ransomware", "trojan"],
    "钓鱼": ["phishing", "credential theft"],
    "侧信道": ["side channel", "side-channel"],
    "联邦学习": ["federated learning", "fl"],
    "机器学习": ["machine learning", "ml", "machine learning security", "adversarial machine learning"],
    "机器学习安全": ["machine learning security", "ml security", "adversarial machine learning", "robust machine learning"],
    "学习安全": ["machine learning security", "ml security"],
    "总结": ["survey", "overview"],
    "综述": ["survey", "overview"],
    "比较": ["compare", "comparison"],
}

QUERY_TYPE_PROMPT_VERSION = "v1"
_query_type_cache_table_ready = False
_query_type_cache_lock = threading.Lock()


def _resolve_gemini_model(model_name: str) -> str:
    normalized = (model_name or "").strip()
    aliases = {
        "gemini-3.1-flash": "gemini-2.5-flash",
        "gemini-3-flash": "gemini-2.5-flash",
        "gemini-flash": "gemini-2.5-flash",
    }
    return aliases.get(normalized, normalized or "gemini-2.5-flash")


def _extract_text_response(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    texts = [part.get("text", "") for part in parts if part.get("text")]
    answer = "\n".join(texts).strip()
    if not answer:
        raise RuntimeError("Gemini returned empty answer")
    return answer


def _parse_json_payload(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    candidates: list[str] = [raw]

    if "```json" in raw:
        start = raw.find("```json") + len("```json")
        end = raw.find("```", start)
        if end != -1:
            candidates.insert(0, raw[start:end].strip())
    elif "```" in raw:
        start = raw.find("```") + len("```")
        end = raw.find("```", start)
        if end != -1:
            candidates.insert(0, raw[start:end].strip())

    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.insert(0, raw[first_brace:last_brace + 1].strip())

    seen: set[str] = set()
    for candidate in candidates:
        item = candidate.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        try:
            parsed = json.loads(item)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, str):
                reparsed = json.loads(parsed)
                if isinstance(reparsed, dict):
                    return reparsed
        except Exception:
            continue

    raise json.JSONDecodeError("Unable to parse JSON object from model output", raw, 0)


def _extract_usage(payload: dict[str, Any]) -> dict[str, int]:
    usage = payload.get("usageMetadata") or {}
    prompt_tokens = int(usage.get("promptTokenCount") or 0)
    completion_tokens = int(usage.get("candidatesTokenCount") or 0)
    total_tokens = int(usage.get("totalTokenCount") or (prompt_tokens + completion_tokens))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _call_gemini_json(prompt: str, model_name: str | None = None, usage_source: str = "chat_parser") -> dict[str, Any]:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    resolved_model = _resolve_gemini_model(model_name or settings.gemini_model)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{resolved_model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "topP": 0.8,
            "responseMimeType": "application/json",
            "maxOutputTokens": 1200,
        },
    }
    command = [
        "curl",
        "-sS",
        "--connect-timeout",
        "3",
        "--max-time",
        "8",
        "-X",
        "POST",
        url,
        "-H",
        f"x-goog-api-key: {settings.gemini_api_key}",
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        json.dumps(payload, ensure_ascii=False),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(message or f"curl exited with {result.returncode}")
    response_payload = json.loads(result.stdout)
    finish_reason = ((response_payload.get("candidates") or [{}])[0] or {}).get("finishReason")
    log_llm_usage(
        source=usage_source,
        model=resolved_model,
        finish_reason=finish_reason,
        token_usage=_extract_usage(response_payload),
    )
    text = _extract_text_response(response_payload)
    return _parse_json_payload(text)


def _build_primary_parser_prompt(query: str, default_top_k: int) -> str:
    return f"""
Return ONLY one JSON object for paper retrieval parsing.
No prose, no markdown.

Required keys:
intent, topic, must_terms, should_terms, negative_terms, filters, top_k, needs_fulltext, query_variants

Allowed values:
- intent: search|qa|compare|summarize|chat|meta|help|ask_clarification
- filters.venues: USENIX_SECURITY|NDSS|IEEE_SP|ACM_CCS
- top_k: 1..20 (default {default_top_k})

Rules:
- retrieval parsing only
- keep core security terms
- do not invent venue/year filters
- greeting / identity / help / ambiguous continuation should use chat/meta/help/ask_clarification instead of search

User query: {query}
""".strip()


def _build_query_type_prompt(query: str) -> str:
    return f"""
Classify the query as generic or specific for security paper retrieval.
Return strict JSON only:
{{"query_type":"generic|specific"}}

Guidelines:
- generic: broad topic intent, high-level domain ask, no concrete attack/mechanism target
- specific: contains concrete mechanism, attack family, method name, or explicit technical target

User query: {query}
""".strip()


def _build_fallback_parser_prompt(query: str, default_top_k: int) -> str:
    return f"""
Output strict compact JSON only.
{{
  "intent":"search|qa|compare|summarize|chat|meta|help|ask_clarification",
  "topic":"string",
  "must_terms":[],
  "should_terms":[],
  "negative_terms":[],
  "filters":{{"venues":[],"years":[],"year_from":null,"year_to":null}},
  "top_k":{default_top_k},
  "needs_fulltext":false,
  "query_variants":[]
}}
User query: {query}
""".strip()


def detect_special_intent(query: str) -> str | None:
    normalized = re.sub(r"\s+", " ", (query or "").strip().lower())
    if not normalized:
        return "ask_clarification"

    for pattern in CHAT_PATTERNS:
        if re.fullmatch(pattern, normalized, flags=re.IGNORECASE):
            return "chat"
    for pattern in META_PATTERNS:
        if re.fullmatch(pattern, normalized, flags=re.IGNORECASE):
            return "meta"
    for pattern in HELP_PATTERNS:
        if re.fullmatch(pattern, normalized, flags=re.IGNORECASE):
            return "help"
    for pattern in ASK_CLARIFICATION_PATTERNS:
        if re.fullmatch(pattern, normalized, flags=re.IGNORECASE):
            return "ask_clarification"
    return None


def detect_intent(query: str) -> str:
    special_intent = detect_special_intent(query)
    if special_intent:
        return special_intent
    lowered = query.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return intent
    return "search"


def detect_needs_fulltext(query: str) -> bool:
    lowered = query.lower()
    return any(keyword in lowered for keyword in FULLTEXT_KEYWORDS)


def extract_top_k(query: str, default: int) -> int:
    for pattern in TOP_K_PATTERNS:
        match = pattern.search(query)
        if match:
            try:
                value = int(match.group(1))
                return max(1, min(value, 20))
            except ValueError:
                continue
    return default


def extract_filters(query: str) -> ChatFilters:
    lowered = query.lower()
    venues = []
    for alias, code in sorted(VENUE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in lowered and code not in venues:
            venues.append(code)

    year_from = None
    year_to = None
    range_match = YEAR_RANGE_PATTERN.search(query)
    if range_match:
        year_from = int(range_match.group(1))
        year_to = int(range_match.group(2))

    years = []
    for match in YEAR_PATTERN.findall(query):
        year = int(match)
        if year not in years:
            years.append(year)

    if year_from is not None and year_to is not None:
        years = [year for year in years if year < year_from or year > year_to]

    return ChatFilters(
        venues=venues,
        years=years,
        year_from=year_from,
        year_to=year_to,
    )


_normalize_topic_text = normalize_topic_text
_strip_filler_prefixes = strip_filler_prefixes


def _derive_topic_terms(topic: str, limit: int = 3) -> list[str]:
    text = _normalize_topic_text(topic or "")
    if not text:
        return []

    terms: list[str] = []

    en_tokens = [token.lower() for token in re.findall(r"[a-z0-9][a-z0-9_+.#/-]*", text, flags=re.IGNORECASE)]
    en_tokens = [token for token in en_tokens if len(token) > 2]
    if len(en_tokens) >= 2:
        terms.append(f"{en_tokens[0]} {en_tokens[1]}")
    terms.extend(en_tokens[:2])

    zh_blocks = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    terms.extend(zh_blocks[:2])

    deduped: list[str] = []
    seen = set()
    for item in terms:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(item.strip())
        if len(deduped) >= limit:
            break
    return deduped


def _escape_sql_literal(value: str) -> str:
    return (value or "").replace("'", "''")


def _ensure_query_type_cache_table() -> None:
    global _query_type_cache_table_ready
    if _query_type_cache_table_ready:
        return
    with _query_type_cache_lock:
        if _query_type_cache_table_ready:
            return
        run_sql(
            """
            CREATE TABLE IF NOT EXISTS query_type_cache (
              query_text_normalized text NOT NULL,
              query_type text NOT NULL,
              model text NOT NULL,
              prompt_version text NOT NULL,
              query_text text NOT NULL,
              created_at timestamptz NOT NULL DEFAULT now(),
              updated_at timestamptz NOT NULL DEFAULT now(),
              PRIMARY KEY (query_text_normalized, model, prompt_version)
            );
            """
        )
        _query_type_cache_table_ready = True


def _load_query_type_cache(query_text_normalized: str, model: str, prompt_version: str) -> str | None:
    _ensure_query_type_cache_table()
    q = _escape_sql_literal(query_text_normalized)
    m = _escape_sql_literal(model)
    p = _escape_sql_literal(prompt_version)
    output = run_sql(
        f"""
        SELECT query_type
        FROM query_type_cache
        WHERE query_text_normalized = '{q}'
          AND model = '{m}'
          AND prompt_version = '{p}'
        LIMIT 1;
        """
    )
    value = (output or "").strip().lower()
    if value in {"generic", "specific"}:
        return value
    return None


def _save_query_type_cache(query_text: str, query_text_normalized: str, query_type: str, model: str, prompt_version: str) -> None:
    _ensure_query_type_cache_table()
    qt = _escape_sql_literal(query_type)
    qn = _escape_sql_literal(query_text_normalized)
    q = _escape_sql_literal(query_text)
    m = _escape_sql_literal(model)
    p = _escape_sql_literal(prompt_version)
    run_sql(
        f"""
        INSERT INTO query_type_cache (
          query_text_normalized, query_type, model, prompt_version, query_text
        ) VALUES (
          '{qn}', '{qt}', '{m}', '{p}', '{q}'
        )
        ON CONFLICT (query_text_normalized, model, prompt_version)
        DO UPDATE SET
          query_type = EXCLUDED.query_type,
          query_text = EXCLUDED.query_text,
          updated_at = now();
        """
    )


def classify_query_type(query: str, topic: str | None = None) -> str:
    normalized_query = _normalize_topic_text(query)
    if not normalized_query:
        return "generic"

    topic_hint = infer_query_type_from_topics(topic or query)
    if topic_hint in {"generic", "specific"}:
        return topic_hint

    model_name = settings.query_type_classifier_model.strip() or settings.gemini_model
    resolved_model = _resolve_gemini_model(model_name)
    cached = _load_query_type_cache(normalized_query, resolved_model, QUERY_TYPE_PROMPT_VERSION)
    if cached:
        return cached

    try:
        payload = _call_gemini_json(_build_query_type_prompt(query), model_name=resolved_model, usage_source="query_classifier")
        llm_value = str(payload.get("query_type") or "").strip().lower()
        if llm_value not in {"generic", "specific"}:
            raise RuntimeError("invalid query_type from llm")
        _save_query_type_cache(query, normalized_query, llm_value, resolved_model, QUERY_TYPE_PROMPT_VERSION)
        return llm_value
    except Exception:
        fallback = "specific"
        inferred_fallback = infer_query_type_from_topics(query)
        if inferred_fallback in {"generic", "specific"}:
            fallback = inferred_fallback
        _save_query_type_cache(query, normalized_query, fallback, resolved_model, QUERY_TYPE_PROMPT_VERSION)
        return fallback


def _infer_query_structure_fields(
    query: str,
    topic: str,
    query_type: str,
    topic_labels: list[str],
    profile,
) -> tuple[str, str, str, str]:
    """Derive query_scope, target_granularity, expected_result_shape, risk_of_neighbor_drift."""
    qlow = (query or "").lower()
    scope: QueryScope = "unknown"
    if re.search(r"NDSS|USENIX|CCS|IEEE\s*SP|SP\s*20|CCS\s*20", query or "", re.IGNORECASE) or re.search(
        r"20\d{2}", query or ""
    ):
        scope = "venue_constrained"
    elif query_type == "generic":
        scope = "broad_topic"
    elif any(w in qlow for w in ("compare", "vs", "versus")) or any(w in (query or "") for w in ("区别", "对比", "比较")):
        scope = "comparison"
    elif "最近" in (query or "") or "近年" in (query or "") or "recent" in qlow or "newest" in qlow:
        scope = "trend"
    elif query_type == "specific":
        scope = "specific_subtopic"

    granularity: TargetGranularity = "unknown"
    if profile:
        granularity = "field" if getattr(profile, "strategy_type", "") == "broad_aggregate" else "subfield"
    elif query_type == "specific":
        granularity = "task"

    shape: ExpectedResultShape = "unknown"
    if query_type == "generic":
        shape = "representative_overview"
    if "经典" in (query or "") or "canonical" in qlow or "代表作" in (query or ""):
        shape = "canonical_papers"
    if profile and getattr(profile, "strategy_type", "") == "broad_aggregate":
        shape = "representative_overview"

    drift: NeighborDriftRisk = "medium"
    if profile and getattr(profile, "strategy_type", "") == "broad_aggregate":
        drift = "high"
    elif query_type == "specific":
        drift = "low"

    return scope, granularity, shape, drift


def _apply_runtime_profile_parser(
    topic: str,
    query: str,
    topic_labels: list[str],
    should_terms: list[str],
    negative_terms: list[str],
) -> tuple[list[str], list[str], object | None]:
    profile = match_runtime_profile(topic_labels, topic)
    if not profile:
        return should_terms, negative_terms, None
    for term in profile.parser.extra_should_terms:
        t = (term or "").strip()
        if t and t not in should_terms:
            should_terms.append(t)
    for term in profile.parser.extra_negative_terms:
        t = (term or "").strip()
        if t and t not in negative_terms:
            negative_terms.append(t)
    return should_terms, negative_terms, profile


def build_query_variants(topic: str, original_query: str, query_type: str = "specific", translation: QueryTranslationResult | None = None) -> list[str]:
    variants: list[str] = []

    normalized_topic = _strip_filler_prefixes(_normalize_topic_text(topic or original_query))
    normalized_original = _strip_filler_prefixes(_normalize_topic_text(original_query))
    if translation and translation.normalized_query:
        variants.append(translation.normalized_query)
    if normalized_topic:
        variants.append(normalized_topic)

    lowered_probe = (normalized_topic or normalized_original).lower()
    prototype_forced_expansions: list[str] = []
    if any(term in lowered_probe for term in [
        "rag code generation", "retrieval-augmented code generation", "retrieval augmented code generation",
        "dependency hijacking", "dependency confusion", "importsnare", "code manual hijacking", "package hallucination",
    ]):
        prototype_forced_expansions.extend([
            "retrieval-augmented code generation",
            "dependency hijacking",
            "dependency confusion",
            "importsnare",
            "code manual hijacking",
        ])
    if any(term in lowered_probe for term in [
        "prompt stealing", "system prompt", "prompt obfuscation", "prompt ip", "prompt leakage",
        "prompt services", "real-world prompt services", "in-the-wild prompts",
    ]):
        prototype_forced_expansions.extend([
            "prompt stealing",
            "system prompt",
            "prompt obfuscation",
            "prompt leakage",
            "real-world prompt services",
        ])
    if any(term in lowered_probe for term in [
        "training data poisoning", "training-time poisoning", "data poisoning", "clean-label", "dirty-label",
        "training provenance", "trajectory spectrum",
    ]):
        prototype_forced_expansions.extend([
            "training data poisoning",
            "training-time poisoning",
            "clean-label",
            "backdoor defense",
            "training provenance",
        ])

    expansions: list[str] = list(prototype_forced_expansions)
    if translation:
        expansions.extend(list(translation.english_aliases))
        expansions.extend(list(translation.canonical_topics))
        expansions.extend(list(translation.prototype_hints))
        expansions.extend(list(translation.chinese_aliases))
    for zh_term, mapped_terms in ZH_KEYWORD_MAP.items():
        if zh_term in normalized_topic:
            expansions.extend(mapped_terms)

    topic_scored = score_topic_entries(normalized_topic or original_query)
    for index, (score, _, entry) in enumerate(topic_scored[:2]):
        expansions.append(entry.canonical)
        expansions.extend(entry.aliases)
        expansions.extend(entry.zh_aliases)
        if score >= 4:
            expansions.extend(entry.subtopics[: (3 if index == 0 else 1)])
            if query_type == "generic" and index == 0:
                expansions.extend(entry.related_terms[:2])
        elif score >= 2:
            expansions.extend(entry.subtopics[:1])

    taxonomy_expansions = expand_topics(normalized_topic or original_query, generic=(query_type == "generic"), limit=10)
    expansions.extend(taxonomy_expansions)

    probe_labels = expand_topics(normalized_topic or original_query, generic=(query_type == "generic"), limit=8)
    _variant_profile = match_runtime_profile(probe_labels, normalized_topic or original_query)
    if query_type == "generic" and _variant_profile and _variant_profile.expansion.variant_expansions_generic:
        expansions.extend(list(_variant_profile.expansion.variant_expansions_generic))

    deduped_expansions: list[str] = []
    seen_expansions: set[str] = set()
    for item in expansions:
        value = (item or "").strip()
        key = value.lower()
        if not key or key == normalized_topic.lower() or key in seen_expansions:
            continue
        seen_expansions.add(key)
        deduped_expansions.append(value)

    if query_type == "generic":
        for item in deduped_expansions[:4]:
            variants.append(item)
    else:
        if deduped_expansions:
            variants.extend(deduped_expansions[:4])

    if normalized_original and normalized_original not in variants:
        variants.append(normalized_original)

    deduped: list[str] = []
    seen = set()
    for item in variants:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(item.strip())
    return deduped


def extract_topic(query: str, translation: QueryTranslationResult | None = None) -> str:
    if translation and translation.normalized_query:
        return translation.normalized_query
    variants = build_query_variants(query, query, translation=translation)
    return variants[0] if variants else query.strip()


def extract_topic_labels(topic: str, query: str, query_type: str, translation: QueryTranslationResult | None = None) -> list[str]:
    labels = []
    if translation and translation.canonical_topics:
        labels.extend([str(x).strip() for x in translation.canonical_topics if str(x).strip()])
    labels.extend(expand_topics(topic or query, generic=(query_type == "generic"), limit=12))
    scored_topics = score_topic_entries(topic or query)
    canonical: list[str] = []
    seen: set[str] = set()
    for item in labels:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            canonical.append(item.strip())

    primary_topics = [entry.canonical for score, _, entry in scored_topics if score >= 4][:2]
    if primary_topics:
        canonical = [item for item in canonical if item in primary_topics or item.lower() not in {e.canonical.lower() for _, _, e in scored_topics[2:]}]

    lowered = (topic or query or "").lower()
    ai_security_trigger = any(term in lowered for term in [
        "data poisoning", "poisoning defense", "training data poisoning",
        "backdoor", "trojan", "backdoor detection", "backdoor defense",
        "model stealing", "model extraction", "membership inference", "privacy leakage", "pii extraction",
        "prompt stealing", "system prompt", "watermark", "watermarking", "ownership verification"
    ]) or any(term in (topic or query) for term in [
        "中毒攻击", "投毒攻击", "数据投毒", "后门攻击", "模型窃取", "成员推断", "模型水印"
    ])
    if ai_security_trigger and "ai security" not in canonical:
        canonical.insert(0, "ai security")
    preferred: list[str] = []
    deferred: list[str] = []

    def _push(label: str) -> None:
        if label in canonical and label not in preferred:
            preferred.append(label)

    if "llm" in lowered or "大模型" in (topic or query) or "语言模型" in (topic or query):
        for item in ["llm safety", "model safety", "llm security", "ai security"]:
            _push(item)
    elif "ai" in lowered or "人工智能" in (topic or query):
        for item in ["ai security", "llm safety", "llm security"]:
            _push(item)
    if "jailbreak" in lowered or "越狱" in (topic or query):
        for item in ["llm safety", "llm security", "ai security"]:
            _push(item)

    if any(term in (topic or query) for term in ["中毒攻击", "投毒攻击", "数据投毒", "data poisoning", "poisoning defense", "training data poisoning"]):
        for item in ["ai security", "data poisoning", "poisoning attacks", "adversarial machine learning"]:
            _push(item)
    if any(term in (topic or query) for term in ["后门攻击", "backdoor", "trojan", "backdoor detection", "backdoor defense"]):
        for item in ["ai security", "backdoor attacks", "backdoor", "adversarial machine learning"]:
            _push(item)
    if any(term in (topic or query) for term in ["模型窃取", "模型提取", "model stealing", "model extraction", "query-based extraction", "model inversion", "prompt stealing", "system prompt"]):
        for item in ["ai security", "model stealing", "model extraction", "adversarial machine learning"]:
            _push(item)
    if any(term in (topic or query) for term in ["rag code generation", "rag codegen", "retrieval-augmented code generation", "retrieval augmented code generation", "dependency hijacking", "dependency confusion", "importsnare", "code manual hijacking", "documentation poisoning"]):
        for item in ["ai security", "code generation security", "retrieval-augmented generation security"]:
            _push(item)
    if any(term in (topic or query) for term in ["prompt stealing", "system prompt", "prompt obfuscation", "prompt leakage", "prompt ip"]):
        for item in ["ai security", "prompt stealing", "model extraction"]:
            _push(item)
    if any(term in (topic or query) for term in ["成员推断", "membership inference", "privacy leakage", "pii extraction"]):
        for item in ["ai security", "membership inference", "privacy attacks", "adversarial machine learning"]:
            _push(item)
    if any(term in (topic or query) for term in ["watermark", "watermarking", "模型水印", "ownership verification", "model attribution", "fingerprinting", "provenance"]):
        for item in ["ai security", "ai model integrity and watermarking"]:
            _push(item)

    _label_profile = match_runtime_profile(labels, topic or query)
    if _label_profile and _label_profile.parser.boost_topic_labels:
        for item in _label_profile.parser.boost_topic_labels:
            _push(item)

    for item in canonical:
        if item not in preferred and item not in deferred:
            deferred.append(item)
    return preferred + deferred


def rules_parse_query(query: str, default_top_k: int = 8, translation: QueryTranslationResult | None = None) -> StructuredQuery:
    filters = extract_filters(query)
    topic = extract_topic(query, translation=translation)
    query_type=classify_query_type(query, topic)
    variant_terms = [term for term in build_query_variants(topic, query, query_type=query_type, translation=translation)[:3] if term and term != topic]
    topic_terms = _derive_topic_terms(topic, limit=3)
    topic_labels = extract_topic_labels(topic, query, query_type, translation=translation)
    should_terms = []
    for term in variant_terms + topic_terms + topic_labels:
        if term and term not in should_terms and term != topic:
            should_terms.append(term)
    must_terms = should_terms[:1] if query_type != "generic" else topic_labels[:2]
    if query_type != "generic" and not must_terms and topic:
        must_terms = [topic]
    if query_type != "generic" and not should_terms and topic:
        should_terms = [topic]
    negative_terms: list[str] = []
    should_terms, negative_terms, matched_profile = _apply_runtime_profile_parser(
        topic, query, topic_labels, should_terms, negative_terms
    )

    lowered = query.lower()
    if "而不是" in query:
        tail = query.split("而不是", 1)[1].strip()
        if tail:
            negative_terms.append(_normalize_topic_text(tail))
    elif "instead of" in lowered:
        tail = re.split(r"instead of", lowered, maxsplit=1)[1].strip()
        if tail:
            negative_terms.append(_normalize_topic_text(tail))
    scope, granularity, shape, drift = _infer_query_structure_fields(
        query, topic, query_type, topic_labels, matched_profile
    )
    prototype_targets = [c.id for c in (matched_profile.prototype_clusters if matched_profile else [])]
    return StructuredQuery(
        intent=detect_intent(query),
        topic=topic,
        query_type=query_type,
        topic_labels=topic_labels,
        filters=filters,
        top_k=extract_top_k(query, default_top_k),
        needs_fulltext=detect_needs_fulltext(query),
        must_terms=must_terms,
        should_terms=should_terms,
        negative_terms=[item for item in negative_terms if item],
        translated_query=(translation.normalized_query if translation else None),
        translation_english_aliases=(list(translation.english_aliases) if translation else []),
        translation_chinese_aliases=(list(translation.chinese_aliases) if translation else []),
        translation_canonical_topics=(list(translation.canonical_topics) if translation else []),
        translation_prototype_hints=(list(translation.prototype_hints) if translation else []),
        translation_language=(translation.query_language if translation else None),
        translation_confidence=(translation.confidence if translation else None),
        query_scope=scope,
        target_granularity=granularity,
        expected_result_shape=shape,
        risk_of_neighbor_drift=drift,
        profile_id=matched_profile.topic_id if matched_profile else None,
        prototype_targets=prototype_targets,
    )


def llm_parse_query_payload(query: str, default_top_k: int = 8) -> dict[str, Any]:
    compact_prompt = _build_fallback_parser_prompt(query, default_top_k)
    return _call_gemini_json(compact_prompt, usage_source="chat_parser")


def _normalize_intent(intent: str, query: str) -> str:
    raw = (intent or "").strip().lower()
    detected = detect_intent(query)
    if raw in {"search", "qa", "compare", "summarize", "chat", "meta", "help", "ask_clarification"}:
        if detected in {"compare", "summarize", "qa", "chat", "meta", "help", "ask_clarification"} and raw == "search":
            return detected
        if detected in {"chat", "meta", "help", "ask_clarification"}:
            return detected
        return raw
    return detected


def _normalize_filters(query: str, filters_payload: dict[str, Any]) -> ChatFilters:
    filters = ChatFilters(
        venues=[item for item in (filters_payload.get("venues") or []) if item in {"USENIX_SECURITY", "NDSS", "IEEE_SP", "ACM_CCS"}],
        years=[int(item) for item in (filters_payload.get("years") or []) if str(item).isdigit()],
        year_from=int(filters_payload["year_from"]) if filters_payload.get("year_from") is not None else None,
        year_to=int(filters_payload["year_to"]) if filters_payload.get("year_to") is not None else None,
    )

    if re.search(r"(20\d{2})\s*之后", query):
        matched = re.search(r"(20\d{2})\s*之后", query)
        if matched:
            filters.year_from = int(matched.group(1))
    if re.search(r"after\s+(20\d{2})", query, flags=re.IGNORECASE):
        matched = re.search(r"after\s+(20\d{2})", query, flags=re.IGNORECASE)
        if matched:
            filters.year_from = int(matched.group(1))

    return filters


def _jaccard_labels(a: list[str], b: list[str]) -> float:
    sa = {x.strip().lower() for x in a if str(x).strip()}
    sb = {x.strip().lower() for x in b if str(x).strip()}
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _merge_topic_labels(rule_first: list[str], llm: list[str], *, max_labels: int = 12) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for seq in (rule_first, llm):
        for item in seq:
            key = str(item).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(str(item).strip())
            if len(out) >= max_labels:
                return out
    return out


def _align_structured_query_with_rules(llm_sq: StructuredQuery, rule_sq: StructuredQuery, raw_query: str) -> StructuredQuery:
    """Reduce direct vs chat gap: when LLM parser drifts from rules+taxy, merge toward rules for retrieval-critical fields."""
    qtype = llm_sq.query_type
    # Broad-topic safety: if rules say generic, do not let LLM force specific (hurts embedding + expansion).
    if rule_sq.query_type == "generic" and llm_sq.query_type == "specific":
        qtype = "generic"

    labels = llm_sq.topic_labels
    jac = _jaccard_labels(rule_sq.topic_labels, llm_sq.topic_labels)
    if jac < 0.35 or (rule_sq.profile_id and rule_sq.profile_id != llm_sq.profile_id):
        labels = _merge_topic_labels(rule_sq.topic_labels, llm_sq.topic_labels)

    must = list(llm_sq.must_terms)
    if qtype == "generic":
        for t in rule_sq.must_terms:
            if t and t not in must:
                must.append(t)
    should = list(llm_sq.should_terms)
    for t in rule_sq.should_terms:
        if t and t not in should:
            should.append(t)

    neg = list(dict.fromkeys([*rule_sq.negative_terms, *llm_sq.negative_terms]))[:24]

    topic = (llm_sq.topic or "").strip() or rule_sq.topic
    matched_profile = match_runtime_profile(labels, topic)
    should, neg, _ = _apply_runtime_profile_parser(topic, raw_query, labels, should, neg)
    scope, granularity, shape, drift = _infer_query_structure_fields(
        llm_sq.topic or topic, topic, qtype, labels, matched_profile
    )
    prototype_targets = [c.id for c in (matched_profile.prototype_clusters if matched_profile else [])]

    return llm_sq.model_copy(
        update={
            "query_type": qtype,
            "topic_labels": labels,
            "must_terms": must,
            "should_terms": should,
            "negative_terms": neg,
            "profile_id": matched_profile.topic_id if matched_profile else profile_id,
            "prototype_targets": prototype_targets,
            "query_scope": scope,
            "target_granularity": granularity,
            "expected_result_shape": shape,
            "risk_of_neighbor_drift": drift,
            "topic": topic,
        }
    )


def llm_parse_query(query: str, default_top_k: int = 8) -> StructuredQuery:
    payload = llm_parse_query_payload(query, default_top_k=default_top_k)
    filters_payload = payload.get("filters") or {}
    filters = _normalize_filters(query, filters_payload)
    topic = str(payload.get("topic") or "").strip() or extract_topic(query)
    query_type = classify_query_type(query, topic)
    topic_labels = extract_topic_labels(topic, query, query_type)
    must_terms = [str(item).strip() for item in (payload.get("must_terms") or []) if str(item).strip()]
    should_terms = [str(item).strip() for item in (payload.get("should_terms") or []) if str(item).strip()]
    if query_type == "generic":
        for item in topic_labels[:2]:
            if item not in must_terms:
                must_terms.append(item)
    for item in topic_labels:
        if item not in should_terms and item != topic:
            should_terms.append(item)
    should_terms, negative_terms, matched_profile = _apply_runtime_profile_parser(
        topic,
        query,
        topic_labels,
        should_terms,
        [str(item).strip() for item in (payload.get("negative_terms") or []) if str(item).strip()],
    )
    scope, granularity, shape, drift = _infer_query_structure_fields(
        query, topic, query_type, topic_labels, matched_profile
    )
    prototype_targets = [c.id for c in (matched_profile.prototype_clusters if matched_profile else [])]
    llm_sq = StructuredQuery(
        intent=_normalize_intent(str(payload.get("intent") or ""), query),
        topic=topic,
        query_type=query_type,
        topic_labels=topic_labels,
        filters=filters,
        top_k=max(1, min(int(payload.get("top_k") or default_top_k), 20)),
        needs_fulltext=bool(payload.get("needs_fulltext")) or detect_needs_fulltext(query),
        must_terms=must_terms,
        should_terms=should_terms,
        negative_terms=negative_terms,
        query_scope=scope,
        target_granularity=granularity,
        expected_result_shape=shape,
        risk_of_neighbor_drift=drift,
        profile_id=matched_profile.topic_id if matched_profile else None,
        prototype_targets=prototype_targets,
    )
    try:
        rule_sq = rules_parse_query(query, default_top_k=default_top_k)
        return _align_structured_query_with_rules(llm_sq, rule_sq, query)
    except Exception:
        return llm_sq


def parse_query(query: str, default_top_k: int = 8) -> StructuredQuery:
    try:
        return llm_parse_query(query, default_top_k=default_top_k)
    except Exception:
        return rules_parse_query(query, default_top_k=default_top_k)
