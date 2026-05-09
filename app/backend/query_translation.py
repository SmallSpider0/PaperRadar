from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from pydantic import BaseModel, Field

from backend.config import settings
from backend.pg_json_store import execute_sql, fetch_all, fetch_one
from backend.query_normalization import normalize_topic_text

TRANSLATION_PROMPT_VERSION = "v1"
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_CACHE_TABLE_READY = False

DEFAULT_CACHE_TTL_DAYS = 30
SHORT_QUERY_TTL_DAYS = 7
LONG_QUERY_TTL_DAYS = 14
PROMOTE_TTL_HIT_COUNT = 3
PIN_HIT_COUNT = 10
PROMOTE_TTL_DAYS = 90
PIN_TTL_DAYS = 365
LONG_QUERY_LENGTH_THRESHOLD = 48
NOISY_REPEAT_RE = re.compile(r"(.)\\1{3,}")


class QueryTranslationResult(BaseModel):
    source_query: str
    normalized_query: str
    english_aliases: list[str] = Field(default_factory=list)
    chinese_aliases: list[str] = Field(default_factory=list)
    canonical_topics: list[str] = Field(default_factory=list)
    prototype_hints: list[str] = Field(default_factory=list)
    query_language: str = "unknown"
    confidence: float = 0.0
    from_cache: bool = False
    model: str | None = None
    prompt_version: str = TRANSLATION_PROMPT_VERSION


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_gemini_model(model_name: str) -> str:
    normalized = (model_name or "").strip()
    aliases = {
        "gemini-3.1-flash": "gemini-2.5-flash",
        "gemini-3-flash": "gemini-2.5-flash",
        "gemini-flash": "gemini-2.5-flash",
    }
    return aliases.get(normalized, normalized or "gemini-2.5-flash")


def _contains_cjk(text: str) -> bool:
    return bool(CJK_RE.search(text or ""))


def detect_query_language(query: str) -> str:
    text = (query or "").strip()
    has_cjk = _contains_cjk(text)
    has_ascii_word = bool(re.search(r"[A-Za-z]", text))
    if has_cjk and has_ascii_word:
        return "mixed"
    if has_cjk:
        return "zh"
    if has_ascii_word:
        return "en"
    return "unknown"


def should_translate_query(query: str) -> bool:
    return detect_query_language(query) in {"zh", "mixed"}


def _normalize_cache_key(query: str) -> str:
    return re.sub(r"\s+", " ", (query or "").strip())


def _normalize_query_alias(query: str) -> str:
    raw = _normalize_cache_key(query)
    if not raw:
        return ""
    normalized = normalize_topic_text(raw)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    for prefix in ("请 ", "请", "帮我 ", "给我 ", "我想 "):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    if normalized:
        return normalized
    return raw.lower()


def _cache_hash(query: str, model: str, prompt_version: str) -> str:
    payload = f"raw\n{_normalize_cache_key(query)}\n{model}\n{prompt_version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _alias_hash(normalized_query: str, model: str, prompt_version: str) -> str:
    payload = f"alias\n{_normalize_query_alias(normalized_query)}\n{model}\n{prompt_version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _detect_query_kind(query: str) -> str:
    text = _normalize_cache_key(query)
    if not text:
        return "empty"
    if len(text) >= LONG_QUERY_LENGTH_THRESHOLD:
        return "long"
    weird_punct_count = len(re.findall(r"[^\w\s\u4e00-\u9fff-]", text))
    ascii_count = len(re.findall(r"[A-Za-z]", text))
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    digit_count = len(re.findall(r"\d", text))
    if NOISY_REPEAT_RE.search(text):
        return "suspicious"
    if weird_punct_count >= max(3, len(text) // 4):
        return "suspicious"
    if ascii_count and cjk_count and (ascii_count + cjk_count + digit_count) <= max(6, len(text) // 2):
        return "suspicious"
    alias = _normalize_query_alias(text)
    if alias and alias != text.lower() and abs(len(alias) - len(text)) >= max(4, len(text) // 3):
        return "suspicious"
    return "normal"


def _initial_ttl_days(query: str, *, query_kind: str | None = None) -> int:
    kind = query_kind or _detect_query_kind(query)
    if kind == "suspicious":
        return SHORT_QUERY_TTL_DAYS
    if kind == "long":
        return LONG_QUERY_TTL_DAYS
    return DEFAULT_CACHE_TTL_DAYS


def _compute_expiry(*, now: datetime, hit_count: int, is_pinned: bool, query_kind: str) -> datetime | None:
    if is_pinned:
        return now + timedelta(days=PIN_TTL_DAYS)
    if hit_count >= PROMOTE_TTL_HIT_COUNT:
        return now + timedelta(days=PROMOTE_TTL_DAYS)
    return now + timedelta(days=_initial_ttl_days("", query_kind=query_kind))


def _ensure_tables() -> None:
    global _CACHE_TABLE_READY
    if _CACHE_TABLE_READY:
        return
    execute_sql(
        """
        CREATE TABLE IF NOT EXISTS query_translation_cache (
          query_hash TEXT PRIMARY KEY,
          query_text TEXT NOT NULL,
          normalized_query TEXT NOT NULL,
          normalized_key TEXT,
          cache_scope TEXT NOT NULL DEFAULT 'raw',
          canonical_query_hash TEXT,
          english_aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
          chinese_aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
          canonical_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
          prototype_hints JSONB NOT NULL DEFAULT '[]'::jsonb,
          query_language TEXT NOT NULL DEFAULT 'unknown',
          confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
          model TEXT NOT NULL,
          prompt_version TEXT NOT NULL,
          first_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          last_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          hit_count INTEGER NOT NULL DEFAULT 1,
          expires_at TIMESTAMPTZ,
          is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
          query_kind TEXT NOT NULL DEFAULT 'normal',
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS first_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS last_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS hit_count INTEGER NOT NULL DEFAULT 1;
        ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
        ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS query_kind TEXT NOT NULL DEFAULT 'normal';
        ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS normalized_key TEXT;
        ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS cache_scope TEXT NOT NULL DEFAULT 'raw';
        ALTER TABLE query_translation_cache ADD COLUMN IF NOT EXISTS canonical_query_hash TEXT;
        CREATE INDEX IF NOT EXISTS idx_query_translation_cache_expires_at
          ON query_translation_cache(expires_at)
          WHERE is_pinned = FALSE;
        CREATE INDEX IF NOT EXISTS idx_query_translation_cache_normalized_key
          ON query_translation_cache(normalized_key, model, prompt_version);
        CREATE INDEX IF NOT EXISTS idx_query_translation_cache_canonical_query_hash
          ON query_translation_cache(canonical_query_hash);

        CREATE TABLE IF NOT EXISTS query_translation_rules (
          id BIGSERIAL PRIMARY KEY,
          pattern TEXT NOT NULL UNIQUE,
          match_mode TEXT NOT NULL DEFAULT 'contains',
          normalized_query TEXT NOT NULL,
          english_aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
          canonical_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
          prototype_hints JSONB NOT NULL DEFAULT '[]'::jsonb,
          confidence DOUBLE PRECISION NOT NULL DEFAULT 0.55,
          enabled BOOLEAN NOT NULL DEFAULT TRUE,
          priority INTEGER NOT NULL DEFAULT 100,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    seed_rows = [
        ("成员推断", "contains", "membership inference", ["membership inference", "privacy attacks"], ["ai security", "membership inference", "adversarial machine learning"], ["membership inference", "privacy leakage"], 10),
        ("membership inference", "contains", "membership inference", ["membership inference", "privacy attacks"], ["ai security", "membership inference", "adversarial machine learning"], ["membership inference", "privacy leakage"], 11),
        ("模型窃取", "contains", "model extraction", ["model extraction", "model stealing", "model extraction attack", "model inversion"], ["ai security", "model extraction", "adversarial machine learning"], ["model extraction", "model stealing", "query-based extraction", "model inversion"], 20),
        ("模型提取", "contains", "model extraction", ["model extraction", "model stealing", "model extraction attack", "model inversion"], ["ai security", "model extraction", "adversarial machine learning"], ["model extraction", "model stealing", "query-based extraction", "model inversion"], 21),
        ("model extraction", "contains", "model extraction", ["model extraction", "model stealing", "model extraction attack", "model inversion"], ["ai security", "model extraction", "adversarial machine learning"], ["model extraction", "model stealing", "query-based extraction", "model inversion"], 22),
        ("model stealing", "contains", "model extraction", ["model extraction", "model stealing", "model extraction attack", "query-based extraction"], ["ai security", "model extraction", "adversarial machine learning"], ["model extraction", "model stealing", "query-based extraction", "knockoff nets"], 23),
        ("提示注入", "contains", "prompt injection", ["prompt injection", "indirect prompt injection"], ["ai security", "prompt injection"], ["prompt injection", "indirect prompt injection"], 30),
        ("提示词注入", "contains", "prompt injection", ["prompt injection", "indirect prompt injection"], ["ai security", "prompt injection"], ["prompt injection", "indirect prompt injection"], 31),
        ("prompt injection", "contains", "prompt injection", ["prompt injection", "indirect prompt injection"], ["ai security", "prompt injection"], ["prompt injection", "indirect prompt injection"], 32),
        ("提示词窃取", "contains", "prompt stealing", ["prompt stealing", "prompt leakage", "system prompt"], ["ai security", "prompt stealing", "model extraction"], ["prompt stealing", "prompt leakage", "system prompt"], 40),
        ("系统提示泄露", "contains", "prompt stealing", ["prompt stealing", "prompt leakage", "system prompt"], ["ai security", "prompt stealing", "model extraction"], ["prompt stealing", "prompt leakage", "system prompt"], 41),
        ("prompt leakage", "contains", "prompt stealing", ["prompt stealing", "prompt leakage", "system prompt"], ["ai security", "prompt stealing", "model extraction"], ["prompt stealing", "prompt leakage", "system prompt"], 42),
        ("后门攻击", "contains", "backdoor attack", ["backdoor attack", "trojan attack"], ["ai security", "backdoor attacks", "adversarial machine learning"], ["backdoor", "trojan"], 50),
        ("backdoor", "contains", "backdoor attack", ["backdoor attack", "trojan attack"], ["ai security", "backdoor attacks", "adversarial machine learning"], ["backdoor", "trojan"], 51),
        ("训练数据投毒", "contains", "training data poisoning", ["training data poisoning", "data poisoning"], ["ai security", "data poisoning", "adversarial machine learning"], ["training data poisoning", "data poisoning"], 60),
        ("数据投毒", "contains", "training data poisoning", ["training data poisoning", "data poisoning"], ["ai security", "data poisoning", "adversarial machine learning"], ["training data poisoning", "data poisoning"], 61),
        ("中毒攻击", "contains", "training data poisoning", ["training data poisoning", "data poisoning"], ["ai security", "data poisoning", "adversarial machine learning"], ["training data poisoning", "data poisoning"], 62),
        ("网页安全", "contains", "web security", ["web security", "browser security"], ["web security"], ["web security", "browser security"], 70),
        ("浏览器安全", "contains", "web security", ["web security", "browser security"], ["web security"], ["web security", "browser security"], 71),
        ("web 安全", "contains", "web security", ["web security", "browser security"], ["web security"], ["web security", "browser security"], 72),
        ("web安全", "contains", "web security", ["web security", "browser security"], ["web security"], ["web security", "browser security"], 73),
        ("RAG代码生成安全", "contains", "retrieval-augmented code generation security", ["retrieval-augmented code generation", "code generation security", "dependency hijacking", "documentation poisoning"], ["ai security", "code generation security", "retrieval-augmented generation security"], ["retrieval-augmented code generation", "code manual hijacking", "dependency hijacking", "documentation poisoning", "importsnare"], 80),
        ("代码生成安全", "contains", "retrieval-augmented code generation security", ["retrieval-augmented code generation", "code generation security", "rag code generation"], ["ai security", "code generation security", "retrieval-augmented generation security"], ["retrieval-augmented code generation", "code manual hijacking", "dependency hijacking", "documentation poisoning"], 81),
        ("模型水印", "contains", "model watermarking", ["model watermarking", "ownership verification", "model attribution", "fingerprinting"], ["ai security", "ai model integrity and watermarking"], ["model watermarking", "ownership verification", "model attribution", "fingerprinting"], 90),
        ("watermark", "contains", "model watermarking", ["model watermarking", "ownership verification", "model attribution", "fingerprinting"], ["ai security", "ai model integrity and watermarking"], ["model watermarking", "ownership verification", "model attribution", "fingerprinting"], 91),
    ]
    for pattern, match_mode, normalized_query, english_aliases, canonical_topics, prototype_hints, priority in seed_rows:
        execute_sql(
            """
            INSERT INTO query_translation_rules (
              pattern, match_mode, normalized_query, english_aliases, canonical_topics, prototype_hints,
              confidence, enabled, priority, created_at, updated_at
            ) VALUES (
              %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
              %s, TRUE, %s, NOW(), NOW()
            )
            ON CONFLICT (pattern)
            DO UPDATE SET
              match_mode = EXCLUDED.match_mode,
              normalized_query = EXCLUDED.normalized_query,
              english_aliases = EXCLUDED.english_aliases,
              canonical_topics = EXCLUDED.canonical_topics,
              prototype_hints = EXCLUDED.prototype_hints,
              confidence = EXCLUDED.confidence,
              enabled = TRUE,
              priority = EXCLUDED.priority,
              updated_at = NOW()
            """,
            [
                pattern,
                match_mode,
                normalized_query,
                json.dumps(english_aliases, ensure_ascii=False),
                json.dumps(canonical_topics, ensure_ascii=False),
                json.dumps(prototype_hints, ensure_ascii=False),
                0.55,
                priority,
            ],
        )
    _CACHE_TABLE_READY = True


def _row_to_result(row: dict, *, source_query: str, from_cache: bool, model: str) -> QueryTranslationResult:
    return QueryTranslationResult(
        source_query=source_query,
        normalized_query=str(row.get("normalized_query") or "").strip() or source_query,
        english_aliases=list(row.get("english_aliases") or []),
        chinese_aliases=list(row.get("chinese_aliases") or []) or ([source_query] if _contains_cjk(source_query) else []),
        canonical_topics=list(row.get("canonical_topics") or []),
        prototype_hints=list(row.get("prototype_hints") or []),
        query_language=str(row.get("query_language") or detect_query_language(source_query)),
        confidence=float(row.get("confidence") or 0.0),
        from_cache=from_cache,
        model=model,
        prompt_version=str(row.get("prompt_version") or TRANSLATION_PROMPT_VERSION),
    )


def _touch_cache_row(row: dict, *, query_hash: str) -> None:
    next_hit_count = int(row.get("hit_count") or 0) + 1
    next_is_pinned = bool(row.get("is_pinned")) or next_hit_count >= PIN_HIT_COUNT
    query_kind = str(row.get("query_kind") or "normal")
    next_expires_at = _compute_expiry(now=_utcnow(), hit_count=next_hit_count, is_pinned=next_is_pinned, query_kind=query_kind)
    execute_sql(
        """
        UPDATE query_translation_cache
        SET hit_count = %s,
            last_hit_at = NOW(),
            is_pinned = %s,
            expires_at = %s,
            updated_at = NOW()
        WHERE query_hash = %s
        """,
        [
            next_hit_count,
            next_is_pinned,
            next_expires_at.isoformat() if next_expires_at else None,
            query_hash,
        ],
    )


def _is_row_expired(row: dict) -> bool:
    expires_at_raw = row.get("expires_at")
    if not expires_at_raw or bool(row.get("is_pinned")):
        return False
    expires_at = datetime.fromisoformat(str(expires_at_raw).replace("Z", "+00:00"))
    return expires_at < _utcnow()


def _load_cache(query: str, model: str, prompt_version: str) -> QueryTranslationResult | None:
    _ensure_tables()
    raw_hash = _cache_hash(query, model, prompt_version)
    row = fetch_one(
        """
        SELECT query_hash, query_text, normalized_query, english_aliases, chinese_aliases,
               canonical_topics, prototype_hints, query_language, confidence,
               model, prompt_version, hit_count, is_pinned, query_kind, expires_at
        FROM query_translation_cache
        WHERE query_hash = %s
        """,
        [raw_hash],
    )
    if row and not _is_row_expired(row):
        _touch_cache_row(row, query_hash=raw_hash)
        return _row_to_result(row, source_query=str(row.get("query_text") or query), from_cache=True, model=str(row.get("model") or model))

    alias_key = _normalize_query_alias(query)
    if not alias_key:
        return None
    alias_hash = _alias_hash(alias_key, model, prompt_version)
    alias_row = fetch_one(
        """
        SELECT query_hash, query_text, normalized_query, english_aliases, chinese_aliases,
               canonical_topics, prototype_hints, query_language, confidence,
               model, prompt_version, hit_count, is_pinned, query_kind, expires_at,
               canonical_query_hash
        FROM query_translation_cache
        WHERE query_hash = %s
          AND cache_scope = 'alias'
        """,
        [alias_hash],
    )
    if not alias_row or _is_row_expired(alias_row):
        return None

    canonical_hash = str(alias_row.get("canonical_query_hash") or "").strip()
    canonical_row = None
    if canonical_hash:
        canonical_row = fetch_one(
            """
            SELECT query_hash, query_text, normalized_query, english_aliases, chinese_aliases,
                   canonical_topics, prototype_hints, query_language, confidence,
                   model, prompt_version, hit_count, is_pinned, query_kind, expires_at
            FROM query_translation_cache
            WHERE query_hash = %s
            """,
            [canonical_hash],
        )
    resolved_row = canonical_row if canonical_row and not _is_row_expired(canonical_row) else alias_row
    resolved_hash = str(resolved_row.get("query_hash") or alias_hash)
    _touch_cache_row(resolved_row, query_hash=resolved_hash)
    if resolved_hash != alias_hash:
        _touch_cache_row(alias_row, query_hash=alias_hash)
    return _row_to_result(resolved_row, source_query=query, from_cache=True, model=str(resolved_row.get("model") or model))


def _save_cache(result: QueryTranslationResult, *, cache_model: str | None = None) -> None:
    _ensure_tables()
    query_kind = _detect_query_kind(result.source_query)
    now = _utcnow()
    effective_model = cache_model or result.model or ""
    raw_hash = _cache_hash(result.source_query, effective_model, result.prompt_version)
    normalized_key = _normalize_query_alias(result.source_query)
    expires_at = _compute_expiry(now=now, hit_count=1, is_pinned=False, query_kind=query_kind)
    execute_sql(
        """
        INSERT INTO query_translation_cache (
          query_hash, query_text, normalized_query, normalized_key, cache_scope, canonical_query_hash,
          english_aliases, chinese_aliases, canonical_topics, prototype_hints,
          query_language, confidence, model, prompt_version,
          first_hit_at, last_hit_at, hit_count, expires_at, is_pinned, query_kind,
          created_at, updated_at
        ) VALUES (
          %s, %s, %s, %s, 'raw', NULL,
          %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
          %s, %s, %s, %s,
          NOW(), NOW(), 1, %s, FALSE, %s,
          NOW(), NOW()
        )
        ON CONFLICT (query_hash)
        DO UPDATE SET
          query_text = EXCLUDED.query_text,
          normalized_query = EXCLUDED.normalized_query,
          normalized_key = EXCLUDED.normalized_key,
          english_aliases = EXCLUDED.english_aliases,
          chinese_aliases = EXCLUDED.chinese_aliases,
          canonical_topics = EXCLUDED.canonical_topics,
          prototype_hints = EXCLUDED.prototype_hints,
          query_language = EXCLUDED.query_language,
          confidence = EXCLUDED.confidence,
          model = EXCLUDED.model,
          prompt_version = EXCLUDED.prompt_version,
          query_kind = EXCLUDED.query_kind,
          expires_at = COALESCE(query_translation_cache.expires_at, EXCLUDED.expires_at),
          updated_at = NOW()
        """,
        [
            raw_hash,
            result.source_query,
            result.normalized_query,
            normalized_key,
            json.dumps(result.english_aliases, ensure_ascii=False),
            json.dumps(result.chinese_aliases, ensure_ascii=False),
            json.dumps(result.canonical_topics, ensure_ascii=False),
            json.dumps(result.prototype_hints, ensure_ascii=False),
            result.query_language,
            float(result.confidence),
            effective_model,
            result.prompt_version,
            expires_at.isoformat() if expires_at else None,
            query_kind,
        ],
    )
    alias_key = _normalize_query_alias(result.source_query)
    if alias_key and alias_key != _normalize_cache_key(result.source_query).lower():
        alias_kind = _detect_query_kind(result.source_query)
        alias_expires_at = _compute_expiry(now=now, hit_count=1, is_pinned=False, query_kind=alias_kind)
        execute_sql(
            """
            INSERT INTO query_translation_cache (
              query_hash, query_text, normalized_query, normalized_key, cache_scope, canonical_query_hash,
              english_aliases, chinese_aliases, canonical_topics, prototype_hints,
              query_language, confidence, model, prompt_version,
              first_hit_at, last_hit_at, hit_count, expires_at, is_pinned, query_kind,
              created_at, updated_at
            ) VALUES (
              %s, %s, %s, %s, 'alias', %s,
              %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
              %s, %s, %s, %s,
              NOW(), NOW(), 1, %s, FALSE, %s,
              NOW(), NOW()
            )
            ON CONFLICT (query_hash)
            DO UPDATE SET
              query_text = EXCLUDED.query_text,
              normalized_query = EXCLUDED.normalized_query,
              normalized_key = EXCLUDED.normalized_key,
              canonical_query_hash = EXCLUDED.canonical_query_hash,
              english_aliases = EXCLUDED.english_aliases,
              chinese_aliases = EXCLUDED.chinese_aliases,
              canonical_topics = EXCLUDED.canonical_topics,
              prototype_hints = EXCLUDED.prototype_hints,
              query_language = EXCLUDED.query_language,
              confidence = EXCLUDED.confidence,
              model = EXCLUDED.model,
              prompt_version = EXCLUDED.prompt_version,
              query_kind = EXCLUDED.query_kind,
              expires_at = COALESCE(query_translation_cache.expires_at, EXCLUDED.expires_at),
              updated_at = NOW()
            """,
            [
                _alias_hash(alias_key, effective_model, result.prompt_version),
                result.source_query,
                result.normalized_query,
                alias_key,
                raw_hash,
                json.dumps(result.english_aliases, ensure_ascii=False),
                json.dumps(result.chinese_aliases, ensure_ascii=False),
                json.dumps(result.canonical_topics, ensure_ascii=False),
                json.dumps(result.prototype_hints, ensure_ascii=False),
                result.query_language,
                float(result.confidence),
                effective_model,
                result.prompt_version,
                alias_expires_at.isoformat() if alias_expires_at else None,
                alias_kind,
            ],
        )


def _load_rule_match(query: str) -> QueryTranslationResult | None:
    _ensure_tables()
    lowered = (query or "").strip().lower()
    rows = fetch_all(
        """
        SELECT pattern, match_mode, normalized_query, english_aliases, canonical_topics, prototype_hints,
               confidence, priority
        FROM query_translation_rules
        WHERE enabled = TRUE
        ORDER BY priority ASC, id ASC
        """
    )
    for row in rows:
        pattern = str(row.get("pattern") or "").strip().lower()
        mode = str(row.get("match_mode") or "contains").strip().lower()
        matched = lowered == pattern if mode == "exact" else pattern in lowered
        if not pattern or not matched:
            continue
        return QueryTranslationResult(
            source_query=(query or "").strip(),
            normalized_query=str(row.get("normalized_query") or query).strip(),
            english_aliases=list(row.get("english_aliases") or []),
            chinese_aliases=[(query or "").strip()] if _contains_cjk(query) else [],
            canonical_topics=list(row.get("canonical_topics") or []),
            prototype_hints=list(row.get("prototype_hints") or []),
            query_language=detect_query_language(query),
            confidence=float(row.get("confidence") or 0.55),
            from_cache=False,
            model="fallback-rules-db",
            prompt_version=TRANSLATION_PROMPT_VERSION,
        )
    return None


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
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
    return json.loads(raw)


def _call_gemini_json(prompt: str, model_name: str | None = None) -> tuple[dict[str, Any], str]:
    if not settings.gemini_api_key:
        raise RuntimeError("Gemini API key is not configured")
    resolved_model = _resolve_gemini_model(model_name or settings.gemini_model)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{resolved_model}:generateContent"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.post(
                url,
                headers={"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.1,
                    },
                },
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
            return _parse_json_payload(_extract_text_response(payload)), resolved_model
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"translation request failed: {last_error!r}")


def _build_translation_prompt(query: str) -> str:
    return f"""
You normalize search queries for academic security paper retrieval.
Return ONLY one JSON object with these fields:
normalized_query, english_aliases, chinese_aliases, canonical_topics, prototype_hints, query_language, confidence

Rules:
- Keep the user's retrieval intent unchanged.
- normalized_query must be concise English retrieval wording, not a sentence.
- english_aliases should contain 0-6 short English retrieval aliases.
- chinese_aliases should retain key Chinese forms from the query when useful.
- canonical_topics should prefer stable taxonomy-like topic names.
- prototype_hints should contain terms useful for retrieval prototype matching.
- confidence is 0..1.
- No explanation text.

Examples:
User query: 成员推断
{{
  "normalized_query": "membership inference",
  "english_aliases": ["membership inference", "privacy attacks"],
  "chinese_aliases": ["成员推断"],
  "canonical_topics": ["ai security", "membership inference", "adversarial machine learning"],
  "prototype_hints": ["membership inference", "privacy leakage"],
  "query_language": "zh",
  "confidence": 0.97
}}

User query: 提示注入
{{
  "normalized_query": "prompt injection",
  "english_aliases": ["prompt injection", "indirect prompt injection"],
  "chinese_aliases": ["提示注入"],
  "canonical_topics": ["ai security", "prompt injection"],
  "prototype_hints": ["prompt injection", "indirect prompt injection"],
  "query_language": "zh",
  "confidence": 0.98
}}

User query: {query}
""".strip()


def cleanup_expired_query_translation_cache(*, limit: int | None = None) -> int:
    _ensure_tables()
    sql = """
        SELECT query_hash
        FROM query_translation_cache
        WHERE is_pinned = FALSE
          AND expires_at IS NOT NULL
          AND expires_at < NOW()
        ORDER BY expires_at ASC NULLS FIRST
    """
    params: list[Any] = []
    if limit is not None and limit > 0:
        sql += " LIMIT %s"
        params.append(int(limit))
    rows = fetch_all(sql, params)
    if not rows:
        return 0
    deleted = 0
    for row in rows:
        query_hash = str(row.get("query_hash") or "").strip()
        if not query_hash:
            continue
        execute_sql("DELETE FROM query_translation_cache WHERE query_hash = %s", [query_hash])
        deleted += 1
    return deleted


def normalize_query_for_retrieval(query: str, *, force: bool = False) -> QueryTranslationResult | None:
    raw_query = (query or "").strip()
    if not raw_query:
        return None
    if not force and not should_translate_query(raw_query):
        return None

    model_name = _resolve_gemini_model(settings.gemini_model)
    cached = _load_cache(raw_query, model_name, TRANSLATION_PROMPT_VERSION)
    if cached is not None:
        return cached

    local_rule = _load_rule_match(raw_query)
    if local_rule is not None:
        _save_cache(local_rule, cache_model=model_name)
        return local_rule

    try:
        payload, resolved_model = _call_gemini_json(_build_translation_prompt(raw_query), model_name=model_name)
        normalized_query = str(payload.get("normalized_query") or "").strip() or raw_query
        result = QueryTranslationResult(
            source_query=raw_query,
            normalized_query=normalized_query,
            english_aliases=[str(x).strip() for x in (payload.get("english_aliases") or []) if str(x).strip()],
            chinese_aliases=[str(x).strip() for x in (payload.get("chinese_aliases") or []) if str(x).strip()],
            canonical_topics=[str(x).strip() for x in (payload.get("canonical_topics") or []) if str(x).strip()],
            prototype_hints=[str(x).strip() for x in (payload.get("prototype_hints") or []) if str(x).strip()],
            query_language=str(payload.get("query_language") or detect_query_language(raw_query)),
            confidence=max(0.0, min(1.0, float(payload.get("confidence") or 0.0))),
            from_cache=False,
            model=resolved_model,
            prompt_version=TRANSLATION_PROMPT_VERSION,
        )
    except Exception:
        result = QueryTranslationResult(
            source_query=raw_query,
            normalized_query=raw_query,
            english_aliases=[],
            chinese_aliases=[raw_query] if _contains_cjk(raw_query) else [],
            canonical_topics=[],
            prototype_hints=[],
            query_language=detect_query_language(raw_query),
            confidence=0.2,
            from_cache=False,
            model="fallback-empty",
            prompt_version=TRANSLATION_PROMPT_VERSION,
        )
    _save_cache(result, cache_model=model_name)
    return result
