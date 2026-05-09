from __future__ import annotations

import json
import uuid

from backend.pg_json_store import run_sql


SESSION_CONTEXT_LIMIT = 6


def ensure_rag_tables() -> None:
    sql = '''
    CREATE TABLE IF NOT EXISTS rag_sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT 'local-user',
        title TEXT,
        latest_query TEXT,
        latest_intent TEXT,
        latest_answer TEXT,
        message_count INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS rag_messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES rag_sessions(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        structured_query_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        answer_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    ALTER TABLE rag_sessions ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'local-user';
    '''
    run_sql(sql)


def create_session(user_id: str, title: str | None = None) -> dict:
    ensure_rag_tables()
    session_id = f"rag_{uuid.uuid4().hex[:16]}"
    escaped_title = (title or "新对话").replace("'", "''")
    escaped_user_id = user_id.replace("'", "''")
    sql = f"""
    INSERT INTO rag_sessions (id, user_id, title)
    VALUES ('{session_id}', '{escaped_user_id}', '{escaped_title}')
    RETURNING row_to_json(rag_sessions)::text;
    """
    output = run_sql(sql)
    return json.loads(output)


def touch_session(user_id: str, session_id: str, latest_query: str, latest_intent: str | None = None, latest_answer: str | None = None) -> None:
    ensure_rag_tables()
    escaped_user_id = user_id.replace("'", "''")
    escaped_query = latest_query.replace("'", "''")
    escaped_intent = (latest_intent or "").replace("'", "''")
    escaped_answer = (latest_answer or "").replace("'", "''")
    sql = f"""
    INSERT INTO rag_sessions (id, user_id, title, latest_query, latest_intent, latest_answer, message_count)
    VALUES ('{session_id}', '{escaped_user_id}', '新对话', '{escaped_query}', '{escaped_intent}', '{escaped_answer}', 0)
    ON CONFLICT (id) DO UPDATE SET
      latest_query = EXCLUDED.latest_query,
      latest_intent = EXCLUDED.latest_intent,
      latest_answer = EXCLUDED.latest_answer,
      updated_at = NOW();
    """
    run_sql(sql)


def append_message(session_id: str, role: str, content: str, structured_query: dict | None = None, answer_json: dict | None = None) -> dict:
    ensure_rag_tables()
    message_id = f"msg_{uuid.uuid4().hex[:16]}"
    escaped_content = content.replace("'", "''")
    structured_json = json.dumps(structured_query or {}, ensure_ascii=False).replace("'", "''")
    answer_payload = json.dumps(answer_json or {}, ensure_ascii=False).replace("'", "''")
    sql = f"""
    INSERT INTO rag_messages (id, session_id, role, content, structured_query_json, answer_json)
    VALUES (
      '{message_id}',
      '{session_id}',
      '{role}',
      '{escaped_content}',
      '{structured_json}'::jsonb,
      '{answer_payload}'::jsonb
    )
    RETURNING row_to_json(rag_messages)::text;
    """
    output = run_sql(sql)
    run_sql(f"UPDATE rag_sessions SET message_count = message_count + 1, updated_at = NOW() WHERE id = '{session_id}';")
    return json.loads(output)


def list_messages(session_id: str, limit: int = 20) -> list[dict]:
    ensure_rag_tables()
    sql = f"""
    SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
    FROM (
      SELECT * FROM rag_messages
      WHERE session_id = '{session_id}'
      ORDER BY created_at DESC
      LIMIT {int(limit)}
    ) t;
    """
    output = run_sql(sql)
    rows = json.loads(output or '[]')
    rows.reverse()
    return rows


def get_session(user_id: str, session_id: str) -> dict | None:
    ensure_rag_tables()
    escaped_user_id = user_id.replace("'", "''")
    sql = f"SELECT row_to_json(t)::text FROM (SELECT * FROM rag_sessions WHERE id = '{session_id}' AND user_id = '{escaped_user_id}' LIMIT 1) t;"
    output = run_sql(sql)
    if not output:
        return None
    return json.loads(output)


def list_sessions(user_id: str, limit: int = 20) -> list[dict]:
    ensure_rag_tables()
    escaped_user_id = user_id.replace("'", "''")
    sql = f"""
    SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
    FROM (
      SELECT *
      FROM rag_sessions
      WHERE user_id = '{escaped_user_id}'
      ORDER BY updated_at DESC, created_at DESC
      LIMIT {int(limit)}
    ) t;
    """
    output = run_sql(sql)
    return json.loads(output or '[]')


def delete_session(user_id: str, session_id: str) -> bool:
    ensure_rag_tables()
    escaped_user_id = user_id.replace("'", "''")
    output = run_sql(
        f"""
        DELETE FROM rag_sessions
        WHERE id = '{session_id}' AND user_id = '{escaped_user_id}'
        RETURNING id;
        """
    )
    if output:
        run_sql(f"DELETE FROM rag_messages WHERE session_id = '{session_id}';")
    return bool(output)


def get_latest_answer_payload(session_id: str) -> dict | None:
    ensure_rag_tables()
    sql = f"""
    SELECT COALESCE(answer_json::text, '{{}}')
    FROM rag_messages
    WHERE session_id = '{session_id}' AND role = 'assistant'
    ORDER BY created_at DESC
    LIMIT 1;
    """
    output = run_sql(sql)
    if not output:
        return None
    payload = json.loads(output)
    return payload if isinstance(payload, dict) and payload else None


def get_recent_messages(session_id: str, limit: int = SESSION_CONTEXT_LIMIT) -> list[dict]:
    ensure_rag_tables()
    sql = f"""
    SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
    FROM (
      SELECT id, role, content, structured_query_json, answer_json, created_at
      FROM rag_messages
      WHERE session_id = '{session_id}'
      ORDER BY created_at DESC
      LIMIT {int(limit)}
    ) t;
    """
    output = run_sql(sql)
    rows = json.loads(output or '[]')
    rows.reverse()
    return rows
