from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Sequence

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - runtime fallback for minimal envs
    psycopg = None
    dict_row = None

from backend.db import db_settings


def run_sql(sql: str) -> str:
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".sql") as f:
        f.write(sql)
        temp_path = f.name
    try:
        command = ["psql", db_settings.dsn, "-Atqf", temp_path]
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        return result.stdout.strip()
    finally:
        Path(temp_path).unlink(missing_ok=True)


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        escaped = json.dumps(value, ensure_ascii=False).replace("'", "''")
        return f"'{escaped}'"
    if isinstance(value, (list, tuple)):
        if all(not isinstance(item, (dict, list, tuple)) for item in value):
            return "ARRAY[" + ", ".join(_sql_literal(item) for item in value) + "]"
        escaped = json.dumps(value, ensure_ascii=False).replace("'", "''")
        return f"'{escaped}'"
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _format_sql(sql: str, params: Sequence[Any] | None = None) -> str:
    if not params:
        return sql
    parts = sql.split("%s")
    if len(parts) - 1 != len(params):
        raise ValueError("SQL placeholder count does not match params")
    rendered = [parts[0]]
    for part, value in zip(parts[1:], params):
        rendered.append(_sql_literal(value))
        rendered.append(part)
    return "".join(rendered)


def execute_sql(sql: str, params: Sequence[Any] | None = None) -> None:
    if psycopg is None:
        run_sql(_format_sql(sql, params))
        return
    with psycopg.connect(db_settings.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
        conn.commit()


def fetch_all(sql: str, params: Sequence[Any] | None = None) -> list[dict]:
    if psycopg is None:
        rendered_sql = _format_sql(sql, params).strip().rstrip(";")
        wrapped = f"""
        SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
        FROM (
        {rendered_sql}
        ) t;
        """
        output = run_sql(wrapped)
        return json.loads(output or "[]")
    with psycopg.connect(db_settings.dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_one(sql: str, params: Sequence[Any] | None = None) -> dict | None:
    rows = fetch_all(sql, params=params)
    return rows[0] if rows else None


def fetch_value(sql: str, params: Sequence[Any] | None = None, default: Any = None) -> Any:
    row = fetch_one(sql, params=params)
    if not row:
        return default
    return next(iter(row.values()), default)


def load_table(table: str) -> list[dict]:
    sql = f"SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text FROM (SELECT * FROM {table}) t;"
    output = run_sql(sql)
    return json.loads(output or "[]")


def replace_table(table: str, columns: list[str], rows: list[dict]) -> None:
    delete_sql = f"DELETE FROM {table};"
    run_sql(delete_sql)
    if not rows:
        return

    values_sql = []
    for row in rows:
        vals = []
        for col in columns:
            value = row.get(col)
            if value is None:
                vals.append("NULL")
            elif isinstance(value, bool):
                vals.append("TRUE" if value else "FALSE")
            elif isinstance(value, (int, float)):
                vals.append(str(value))
            elif isinstance(value, (dict, list)):
                escaped = json.dumps(value, ensure_ascii=False).replace("'", "''")
                vals.append(f"'{escaped}'::jsonb")
            else:
                escaped = str(value).replace("'", "''")
                vals.append(f"'{escaped}'")
        values_sql.append("(" + ", ".join(vals) + ")")

    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES\n" + ",\n".join(values_sql) + ";"
    run_sql(sql)
