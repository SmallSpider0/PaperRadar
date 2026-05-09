from __future__ import annotations

import json
import threading
from typing import Any

from backend.pg_json_store import run_sql

_llm_usage_table_ready = False
_llm_usage_table_lock = threading.Lock()


def _escape_sql(value: str | None) -> str:
    return (value or "").replace("'", "''")


def ensure_llm_usage_table() -> None:
    global _llm_usage_table_ready
    if _llm_usage_table_ready:
        return
    with _llm_usage_table_lock:
        if _llm_usage_table_ready:
            return
        run_sql(
            """
            CREATE TABLE IF NOT EXISTS llm_usage_logs (
                id BIGSERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                model TEXT NOT NULL,
                finish_reason TEXT,
                prompt_tokens BIGINT NOT NULL DEFAULT 0,
                completion_tokens BIGINT NOT NULL DEFAULT 0,
                total_tokens BIGINT NOT NULL DEFAULT 0,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_llm_usage_logs_created_at
            ON llm_usage_logs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_llm_usage_logs_source_created_at
            ON llm_usage_logs(source, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_llm_usage_logs_model_created_at
            ON llm_usage_logs(model, created_at DESC);
            """
        )
        _llm_usage_table_ready = True


def log_llm_usage(
    *,
    source: str,
    model: str,
    token_usage: dict[str, Any] | None,
    finish_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    usage = token_usage or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    payload = json.dumps(metadata or {}, ensure_ascii=False).replace("'", "''")

    try:
        ensure_llm_usage_table()
        run_sql(
            f"""
            INSERT INTO llm_usage_logs (
                source,
                model,
                finish_reason,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                metadata_json
            ) VALUES (
                '{_escape_sql(source)}',
                '{_escape_sql(model or "unknown")}',
                {f"'{_escape_sql(finish_reason)}'" if finish_reason else "NULL"},
                {prompt_tokens},
                {completion_tokens},
                {total_tokens},
                '{payload}'::jsonb
            );
            """
        )
    except Exception:
        # Usage logging should never affect the main request path.
        return
