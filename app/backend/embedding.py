from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from backend.env import load_local_env
from backend.pg_json_store import execute_sql, fetch_one


load_local_env()

_QUERY_EMBED_CACHE_READY = False
_QUERY_EMBED_CACHE_LOCK = threading.Lock()
_QUERY_EMBED_STATS_LOCK = threading.Lock()
_QUERY_EMBED_STATS: dict[str, int] = {
    "requests": 0,
    "hits": 0,
    "misses": 0,
    "writes": 0,
}
_QUERY_EMBED_SHORT_TTL_DAYS = max(1, int(os.getenv("PAPERRADAR_QUERY_EMBEDDING_CACHE_SHORT_TTL_DAYS", "14")))
_QUERY_EMBED_DEFAULT_TTL_DAYS = max(1, int(os.getenv("PAPERRADAR_QUERY_EMBEDDING_CACHE_TTL_DAYS", "30")))
_QUERY_EMBED_PROMOTE_HIT_COUNT = max(1, int(os.getenv("PAPERRADAR_QUERY_EMBEDDING_CACHE_PROMOTE_HIT_COUNT", "3")))
_QUERY_EMBED_PROMOTE_TTL_DAYS = max(_QUERY_EMBED_DEFAULT_TTL_DAYS, int(os.getenv("PAPERRADAR_QUERY_EMBEDDING_CACHE_PROMOTE_TTL_DAYS", "90")))
_QUERY_EMBED_PIN_HIT_COUNT = max(_QUERY_EMBED_PROMOTE_HIT_COUNT, int(os.getenv("PAPERRADAR_QUERY_EMBEDDING_CACHE_PIN_HIT_COUNT", "10")))
_QUERY_EMBED_PIN_TTL_DAYS = max(_QUERY_EMBED_PROMOTE_TTL_DAYS, int(os.getenv("PAPERRADAR_QUERY_EMBEDDING_CACHE_PIN_TTL_DAYS", "365")))
_QUERY_EMBED_LONG_QUERY_LENGTH = max(16, int(os.getenv("PAPERRADAR_QUERY_EMBEDDING_CACHE_LONG_QUERY_LENGTH", "48")))
_QUERY_EMBED_NOISY_REPEAT_RE = re.compile(r"(.)\\1{3,}")


class EmbeddingProvider:
    def embed_text(self, text: str) -> list[float]:
        raise NotImplementedError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_query_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _normalize_query_alias(text: str) -> str:
    normalized = _normalize_query_text(text).lower()
    for prefix in ("请 ", "请", "帮我 ", "给我 ", "我想 "):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
    return re.sub(r"\s+", " ", normalized).strip()


def _detect_query_kind(query: str) -> str:
    text = _normalize_query_text(query)
    if not text:
        return "empty"
    if len(text) >= _QUERY_EMBED_LONG_QUERY_LENGTH:
        return "long"
    weird_punct_count = len(re.findall(r"[^\w\s\u4e00-\u9fff-]", text))
    ascii_count = len(re.findall(r"[A-Za-z]", text))
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    digit_count = len(re.findall(r"\d", text))
    if _QUERY_EMBED_NOISY_REPEAT_RE.search(text):
        return "suspicious"
    if weird_punct_count >= max(3, len(text) // 4):
        return "suspicious"
    alias = _normalize_query_alias(text)
    if ascii_count and cjk_count and (ascii_count + cjk_count + digit_count) <= max(6, len(text) // 2):
        return "suspicious"
    if alias and alias != text.lower() and abs(len(alias) - len(text)) >= max(4, len(text) // 3):
        return "suspicious"
    return "normal"


def _compute_expiry(*, now: datetime, hit_count: int, is_pinned: bool, query_kind: str) -> datetime | None:
    if is_pinned:
        return now + timedelta(days=_QUERY_EMBED_PIN_TTL_DAYS)
    if hit_count >= _QUERY_EMBED_PROMOTE_HIT_COUNT:
        return now + timedelta(days=_QUERY_EMBED_PROMOTE_TTL_DAYS)
    ttl_days = _QUERY_EMBED_SHORT_TTL_DAYS if query_kind in {"suspicious", "empty"} else _QUERY_EMBED_DEFAULT_TTL_DAYS
    return now + timedelta(days=ttl_days)


def _cache_hash(query_text: str, provider: str, model: str, task_type: str) -> str:
    payload = f"raw\n{_normalize_query_text(query_text)}\n{provider}\n{model}\n{task_type}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _alias_hash(query_text: str, provider: str, model: str, task_type: str) -> str:
    payload = f"alias\n{_normalize_query_alias(query_text)}\n{provider}\n{model}\n{task_type}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _record_cache_stat(name: str, delta: int = 1) -> None:
    with _QUERY_EMBED_STATS_LOCK:
        _QUERY_EMBED_STATS[name] = int(_QUERY_EMBED_STATS.get(name) or 0) + delta


def get_query_embedding_cache_stats() -> dict[str, int]:
    with _QUERY_EMBED_STATS_LOCK:
        return {key: int(value) for key, value in _QUERY_EMBED_STATS.items()}


def reset_query_embedding_cache_stats() -> None:
    with _QUERY_EMBED_STATS_LOCK:
        for key in list(_QUERY_EMBED_STATS.keys()):
            _QUERY_EMBED_STATS[key] = 0


def _ensure_query_embedding_cache_table() -> None:
    global _QUERY_EMBED_CACHE_READY
    if _QUERY_EMBED_CACHE_READY:
        return
    with _QUERY_EMBED_CACHE_LOCK:
        if _QUERY_EMBED_CACHE_READY:
            return
        execute_sql(
            """
            CREATE TABLE IF NOT EXISTS query_embedding_cache (
              query_hash TEXT PRIMARY KEY,
              query_text TEXT NOT NULL,
              normalized_key TEXT,
              cache_scope TEXT NOT NULL DEFAULT 'raw',
              canonical_query_hash TEXT,
              provider TEXT NOT NULL,
              model TEXT NOT NULL,
              task_type TEXT NOT NULL DEFAULT 'RETRIEVAL_QUERY',
              embedding JSONB NOT NULL,
              embedding_dim INTEGER NOT NULL,
              first_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              last_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              hit_count INTEGER NOT NULL DEFAULT 1,
              expires_at TIMESTAMPTZ,
              is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
              query_kind TEXT NOT NULL DEFAULT 'normal',
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS normalized_key TEXT;
            ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS cache_scope TEXT NOT NULL DEFAULT 'raw';
            ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS canonical_query_hash TEXT;
            ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS first_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
            ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS last_hit_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
            ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS hit_count INTEGER NOT NULL DEFAULT 1;
            ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
            ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS query_kind TEXT NOT NULL DEFAULT 'normal';
            ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS task_type TEXT NOT NULL DEFAULT 'RETRIEVAL_QUERY';
            ALTER TABLE query_embedding_cache ADD COLUMN IF NOT EXISTS embedding_dim INTEGER NOT NULL DEFAULT 0;

            CREATE INDEX IF NOT EXISTS idx_query_embedding_cache_expires_at
              ON query_embedding_cache(expires_at)
              WHERE is_pinned = FALSE;
            CREATE INDEX IF NOT EXISTS idx_query_embedding_cache_normalized_key
              ON query_embedding_cache(normalized_key, provider, model, task_type);
            CREATE INDEX IF NOT EXISTS idx_query_embedding_cache_canonical_query_hash
              ON query_embedding_cache(canonical_query_hash);
            """
        )
        _QUERY_EMBED_CACHE_READY = True


def _is_row_expired(row: dict) -> bool:
    expires_at_raw = row.get("expires_at")
    if not expires_at_raw or bool(row.get("is_pinned")):
        return False
    expires_at = datetime.fromisoformat(str(expires_at_raw).replace("Z", "+00:00"))
    return expires_at < _utcnow()


def _touch_cache_row(row: dict, *, query_hash: str) -> None:
    next_hit_count = int(row.get("hit_count") or 0) + 1
    next_is_pinned = bool(row.get("is_pinned")) or next_hit_count >= _QUERY_EMBED_PIN_HIT_COUNT
    query_kind = str(row.get("query_kind") or "normal")
    next_expires_at = _compute_expiry(now=_utcnow(), hit_count=next_hit_count, is_pinned=next_is_pinned, query_kind=query_kind)
    execute_sql(
        """
        UPDATE query_embedding_cache
        SET hit_count = %s,
            last_hit_at = NOW(),
            is_pinned = %s,
            expires_at = %s,
            updated_at = NOW()
        WHERE query_hash = %s
        """,
        [next_hit_count, next_is_pinned, next_expires_at.isoformat() if next_expires_at else None, query_hash],
    )


def _load_cached_embedding(query_text: str, provider: str, model: str, task_type: str) -> list[float] | None:
    _ensure_query_embedding_cache_table()
    raw_hash = _cache_hash(query_text, provider, model, task_type)
    row = fetch_one(
        """
        SELECT query_hash, query_text, embedding, hit_count, is_pinned, query_kind, expires_at
        FROM query_embedding_cache
        WHERE query_hash = %s
        """,
        [raw_hash],
    )
    if row and not _is_row_expired(row):
        _touch_cache_row(row, query_hash=raw_hash)
        _record_cache_stat("hits")
        values = row.get("embedding") or []
        return [float(v) for v in values] if isinstance(values, list) else None

    alias_key = _normalize_query_alias(query_text)
    if not alias_key:
        return None
    alias_hash = _alias_hash(query_text, provider, model, task_type)
    alias_row = fetch_one(
        """
        SELECT query_hash, embedding, hit_count, is_pinned, query_kind, expires_at, canonical_query_hash
        FROM query_embedding_cache
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
            SELECT query_hash, embedding, hit_count, is_pinned, query_kind, expires_at
            FROM query_embedding_cache
            WHERE query_hash = %s
            """,
            [canonical_hash],
        )
    resolved_row = canonical_row if canonical_row and not _is_row_expired(canonical_row) else alias_row
    resolved_hash = str(resolved_row.get("query_hash") or alias_hash)
    _touch_cache_row(resolved_row, query_hash=resolved_hash)
    if resolved_hash != alias_hash:
        _touch_cache_row(alias_row, query_hash=alias_hash)
    _record_cache_stat("hits")
    values = resolved_row.get("embedding") or []
    return [float(v) for v in values] if isinstance(values, list) else None


def _save_cached_embedding(query_text: str, provider: str, model: str, task_type: str, embedding: list[float]) -> None:
    _ensure_query_embedding_cache_table()
    query_kind = _detect_query_kind(query_text)
    now = _utcnow()
    raw_hash = _cache_hash(query_text, provider, model, task_type)
    normalized_key = _normalize_query_alias(query_text)
    expires_at = _compute_expiry(now=now, hit_count=1, is_pinned=False, query_kind=query_kind)
    embedding_json = json.dumps([float(v) for v in embedding], ensure_ascii=False)
    execute_sql(
        """
        INSERT INTO query_embedding_cache (
          query_hash, query_text, normalized_key, cache_scope, canonical_query_hash,
          provider, model, task_type, embedding, embedding_dim,
          first_hit_at, last_hit_at, hit_count, expires_at, is_pinned, query_kind,
          created_at, updated_at
        ) VALUES (
          %s, %s, %s, 'raw', NULL,
          %s, %s, %s, %s::jsonb, %s,
          NOW(), NOW(), 1, %s, FALSE, %s,
          NOW(), NOW()
        )
        ON CONFLICT (query_hash)
        DO UPDATE SET
          query_text = EXCLUDED.query_text,
          normalized_key = EXCLUDED.normalized_key,
          provider = EXCLUDED.provider,
          model = EXCLUDED.model,
          task_type = EXCLUDED.task_type,
          embedding = EXCLUDED.embedding,
          embedding_dim = EXCLUDED.embedding_dim,
          query_kind = EXCLUDED.query_kind,
          expires_at = COALESCE(query_embedding_cache.expires_at, EXCLUDED.expires_at),
          updated_at = NOW()
        """,
        [
            raw_hash,
            query_text,
            normalized_key,
            provider,
            model,
            task_type,
            embedding_json,
            len(embedding),
            expires_at.isoformat() if expires_at else None,
            query_kind,
        ],
    )

    _record_cache_stat("writes")
    alias_key = _normalize_query_alias(query_text)
    if alias_key and alias_key != _normalize_query_text(query_text).lower():
        alias_hash = _alias_hash(query_text, provider, model, task_type)
        alias_expires_at = _compute_expiry(now=now, hit_count=1, is_pinned=False, query_kind=query_kind)
        execute_sql(
            """
            INSERT INTO query_embedding_cache (
              query_hash, query_text, normalized_key, cache_scope, canonical_query_hash,
              provider, model, task_type, embedding, embedding_dim,
              first_hit_at, last_hit_at, hit_count, expires_at, is_pinned, query_kind,
              created_at, updated_at
            ) VALUES (
              %s, %s, %s, 'alias', %s,
              %s, %s, %s, %s::jsonb, %s,
              NOW(), NOW(), 1, %s, FALSE, %s,
              NOW(), NOW()
            )
            ON CONFLICT (query_hash)
            DO UPDATE SET
              query_text = EXCLUDED.query_text,
              normalized_key = EXCLUDED.normalized_key,
              canonical_query_hash = EXCLUDED.canonical_query_hash,
              provider = EXCLUDED.provider,
              model = EXCLUDED.model,
              task_type = EXCLUDED.task_type,
              embedding = EXCLUDED.embedding,
              embedding_dim = EXCLUDED.embedding_dim,
              query_kind = EXCLUDED.query_kind,
              expires_at = COALESCE(query_embedding_cache.expires_at, EXCLUDED.expires_at),
              updated_at = NOW()
            """,
            [
                alias_hash,
                query_text,
                alias_key,
                raw_hash,
                provider,
                model,
                task_type,
                embedding_json,
                len(embedding),
                alias_expires_at.isoformat() if alias_expires_at else None,
                query_kind,
            ],
        )


class GoogleEmbeddingProvider(EmbeddingProvider):
    def __init__(self) -> None:
        self.api_key = os.getenv("GOOGLE_API_KEY", "")
        self.model = os.getenv("PAPERRADAR_EMBEDDING_MODEL", "gemini-embedding-001")
        self.provider_name = "google"
        self.task_type = "RETRIEVAL_QUERY"

    def _embed_text_uncached(self, text: str) -> list[float]:
        if not self.api_key:
            raise RuntimeError("GOOGLE_API_KEY is not configured")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:embedContent"
        response = requests.post(
            url,
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json={"model": f"models/{self.model}", "content": {"parts": [{"text": text}]}, "taskType": self.task_type},
            timeout=6,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        values = payload.get("embedding", {}).get("values", [])
        if not values:
            raise RuntimeError("Google embedding API returned empty values")
        return [float(v) for v in values]

    def embed_text(self, text: str) -> list[float]:
        normalized_text = _normalize_query_text(text)
        if not normalized_text:
            return []
        _record_cache_stat("requests")
        cached = _load_cached_embedding(normalized_text, self.provider_name, self.model, self.task_type)
        if cached:
            return cached
        _record_cache_stat("misses")
        values = self._embed_text_uncached(normalized_text)
        if values:
            _save_cached_embedding(normalized_text, self.provider_name, self.model, self.task_type, values)
        return values


def get_embedding_provider() -> EmbeddingProvider:
    provider = os.getenv("PAPERRADAR_EMBEDDING_PROVIDER", "google")
    if provider == "google":
        return GoogleEmbeddingProvider()
    raise RuntimeError(f"Unsupported embedding provider: {provider}")
