from __future__ import annotations

import json
import uuid

from backend.pg_json_store import run_sql


def ensure_review_tables() -> None:
    sql = '''
    CREATE TABLE IF NOT EXISTS review_sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT 'local-user',
        title TEXT,
        query TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'prepared',
        confirmed BOOLEAN NOT NULL DEFAULT FALSE,
        prepared_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        review_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_review_sessions_user_updated
    ON review_sessions(user_id, updated_at DESC, created_at DESC);
    '''
    run_sql(sql)


def _escape(value: str) -> str:
    return (value or "").replace("'", "''")


def _json_literal(payload: dict | None) -> str:
    return json.dumps(payload or {}, ensure_ascii=False).replace("'", "''")


def create_review_session(user_id: str, query: str, *, status: str = "prepared", confirmed: bool = False, prepared_payload: dict | None = None, review_payload: dict | None = None) -> dict:
    ensure_review_tables()
    session_id = f"review_{uuid.uuid4().hex[:16]}"
    sql = f"""
    INSERT INTO review_sessions (
      id,
      user_id,
      title,
      query,
      status,
      confirmed,
      prepared_payload_json,
      review_payload_json
    )
    VALUES (
      '{session_id}',
      '{_escape(user_id)}',
      '{_escape(query[:80] or "文献综述")}',
      '{_escape(query)}',
      '{_escape(status)}',
      {'TRUE' if confirmed else 'FALSE'},
      '{_json_literal(prepared_payload)}'::jsonb,
      '{_json_literal(review_payload)}'::jsonb
    )
    RETURNING row_to_json(review_sessions)::text;
    """
    output = run_sql(sql)
    return json.loads(output)


def update_review_session(
    session_id: str,
    *,
    status: str | None = None,
    confirmed: bool | None = None,
    prepared_payload: dict | None = None,
    review_payload: dict | None = None,
) -> dict | None:
    ensure_review_tables()
    assignments = ["updated_at = NOW()"]
    if status is not None:
        assignments.append(f"status = '{_escape(status)}'")
    if confirmed is not None:
        assignments.append(f"confirmed = {'TRUE' if confirmed else 'FALSE'}")
    if prepared_payload is not None:
        assignments.append(f"prepared_payload_json = '{_json_literal(prepared_payload)}'::jsonb")
    if review_payload is not None:
        assignments.append(f"review_payload_json = '{_json_literal(review_payload)}'::jsonb")
    sql = f"""
    UPDATE review_sessions
    SET {", ".join(assignments)}
    WHERE id = '{_escape(session_id)}'
    RETURNING row_to_json(review_sessions)::text;
    """
    output = run_sql(sql)
    return json.loads(output) if output else None


def get_review_session(user_id: str, session_id: str) -> dict | None:
    ensure_review_tables()
    sql = f"""
    SELECT row_to_json(t)::text
    FROM (
      SELECT *
      FROM review_sessions
      WHERE id = '{_escape(session_id)}' AND user_id = '{_escape(user_id)}'
      LIMIT 1
    ) t;
    """
    output = run_sql(sql)
    return json.loads(output) if output else None


def list_review_sessions(user_id: str, limit: int = 20) -> list[dict]:
    ensure_review_tables()
    sql = f"""
    SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
    FROM (
      SELECT id, user_id, title, query, status, confirmed, created_at, updated_at
      FROM review_sessions
      WHERE user_id = '{_escape(user_id)}'
      ORDER BY updated_at DESC, created_at DESC
      LIMIT {max(1, int(limit))}
    ) t;
    """
    output = run_sql(sql)
    return json.loads(output or "[]")


def delete_review_session(user_id: str, session_id: str) -> bool:
    ensure_review_tables()
    output = run_sql(
        f"""
        DELETE FROM review_sessions
        WHERE id = '{_escape(session_id)}' AND user_id = '{_escape(user_id)}'
        RETURNING id;
        """
    )
    return bool(output)
