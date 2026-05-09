from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.config import settings
from backend.pg_json_store import run_sql


PBKDF2_ITERATIONS = 210_000
SESSION_TTL_SECONDS = 60 * 60 * 12
MAX_FAILED_ATTEMPTS = 8
LOCK_WINDOW_SECONDS = 15 * 60

_FAILED_LOGIN_STATE: dict[str, list[float]] = {}


@dataclass
class AuthUser:
    id: str
    username: str
    role: str
    status: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_active(status: str) -> bool:
    return (status or "").lower() == "active"


def ensure_auth_tables() -> None:
    run_sql(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

        CREATE TABLE IF NOT EXISTS user_sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_token_hash TEXT NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            ip TEXT,
            user_agent TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_user_sessions_token_hash ON user_sessions(session_token_hash);
        CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at);
        """
    )


def ensure_user_scope_tables() -> None:
    run_sql(
        """
        ALTER TABLE rag_sessions ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'local-user';
        ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'local-user';
        """
    )


def _normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def _password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iter_text, salt_b64, hash_b64 = encoded_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64.encode())
        expected = base64.b64decode(hash_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iter_text))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _cleanup_failed_attempts(key: str) -> None:
    now = time.time()
    values = [value for value in _FAILED_LOGIN_STATE.get(key, []) if now - value < LOCK_WINDOW_SECONDS]
    if values:
        _FAILED_LOGIN_STATE[key] = values
    elif key in _FAILED_LOGIN_STATE:
        del _FAILED_LOGIN_STATE[key]


def is_login_locked(username: str, client_ip: str) -> bool:
    for key in [f"user:{_normalize_username(username)}", f"ip:{client_ip or 'unknown'}"]:
        _cleanup_failed_attempts(key)
        if len(_FAILED_LOGIN_STATE.get(key, [])) >= MAX_FAILED_ATTEMPTS:
            return True
    return False


def mark_login_failure(username: str, client_ip: str) -> None:
    now = time.time()
    for key in [f"user:{_normalize_username(username)}", f"ip:{client_ip or 'unknown'}"]:
        _cleanup_failed_attempts(key)
        _FAILED_LOGIN_STATE.setdefault(key, []).append(now)


def clear_login_failures(username: str, client_ip: str) -> None:
    for key in [f"user:{_normalize_username(username)}", f"ip:{client_ip or 'unknown'}"]:
        _FAILED_LOGIN_STATE.pop(key, None)


def get_user_by_username(username: str) -> dict | None:
    ensure_auth_tables()
    normalized = _normalize_username(username)
    escaped = normalized.replace("'", "''")
    output = run_sql(
        f"""
        SELECT row_to_json(t)::text
        FROM (
          SELECT id, username, role, password_hash, status
          FROM users
          WHERE username = '{escaped}'
          LIMIT 1
        ) t;
        """
    )
    if not output:
        return None
    return json.loads(output)


def get_user_by_id(user_id: str) -> dict | None:
    ensure_auth_tables()
    escaped = user_id.replace("'", "''")
    output = run_sql(
        f"""
        SELECT row_to_json(t)::text
        FROM (
          SELECT id, username, role, password_hash, status
          FROM users
          WHERE id = '{escaped}'
          LIMIT 1
        ) t;
        """
    )
    if not output:
        return None
    return json.loads(output)


def create_user(username: str, password: str, role: str = "user", status: str = "active") -> dict:
    ensure_auth_tables()
    normalized = _normalize_username(username)
    role = "admin" if role == "admin" else "user"
    user_id = f"user_{uuid.uuid4().hex[:16]}"
    encoded = _password_hash(password)
    output = run_sql(
        f"""
        INSERT INTO users (id, username, role, password_hash, status)
        VALUES (
          '{user_id}',
          '{normalized.replace("'", "''")}',
          '{role}',
          '{encoded.replace("'", "''")}',
          '{status.replace("'", "''")}'
        )
        RETURNING row_to_json(users)::text;
        """
    )
    return json.loads(output)


def update_user(user_id: str, *, password: str | None = None, role: str | None = None, status: str | None = None) -> dict | None:
    ensure_auth_tables()
    sets: list[str] = ["updated_at = NOW()"]
    if password:
        sets.append("password_hash = %s")
        encoded = _password_hash(password).replace("'", "''")
        sets[-1] = f"password_hash = '{encoded}'"
    if role:
        sets.append(f"role = '{'admin' if role == 'admin' else 'user'}'")
    if status:
        sets.append(f"status = '{status.replace(chr(39), chr(39) + chr(39))}'")
    output = run_sql(
        f"""
        UPDATE users
        SET {", ".join(sets)}
        WHERE id = '{user_id.replace("'", "''")}'
        RETURNING row_to_json(users)::text;
        """
    )
    if not output:
        return None
    return json.loads(output)


def list_users() -> list[dict]:
    ensure_auth_tables()
    output = run_sql(
        """
        SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
        FROM (
          SELECT id, username, role, status, created_at, updated_at
          FROM users
          ORDER BY created_at ASC
        ) t;
        """
    )
    return json.loads(output or "[]")


def delete_user(user_id: str) -> bool:
    ensure_auth_tables()
    escaped_user_id = user_id.replace("'", "''")
    run_sql(f"DELETE FROM user_sessions WHERE user_id = '{escaped_user_id}';")
    output = run_sql(f"DELETE FROM users WHERE id = '{escaped_user_id}' RETURNING id;")
    return bool(output)


def create_session(user_id: str, ip: str | None = None, user_agent: str | None = None) -> tuple[str, datetime]:
    ensure_auth_tables()
    token = secrets.token_urlsafe(48)
    token_hash = hash_session_token(token)
    session_id = f"sess_{uuid.uuid4().hex[:16]}"
    expires_at = _utcnow() + timedelta(seconds=SESSION_TTL_SECONDS)
    run_sql(
        f"""
        INSERT INTO user_sessions (id, user_id, session_token_hash, expires_at, ip, user_agent)
        VALUES (
          '{session_id}',
          '{user_id.replace("'", "''")}',
          '{token_hash}',
          '{expires_at.isoformat()}',
          {'NULL' if not ip else "'" + ip.replace("'", "''") + "'"},
          {'NULL' if not user_agent else "'" + user_agent.replace("'", "''") + "'"}
        );
        """
    )
    return token, expires_at


def revoke_session_by_token(token: str) -> None:
    ensure_auth_tables()
    token_hash = hash_session_token(token)
    run_sql(
        f"""
        UPDATE user_sessions
        SET revoked_at = NOW()
        WHERE session_token_hash = '{token_hash}';
        """
    )


def get_user_by_session_token(token: str) -> AuthUser | None:
    ensure_auth_tables()
    if not token:
        return None
    token_hash = hash_session_token(token)
    output = run_sql(
        f"""
        SELECT row_to_json(t)::text
        FROM (
          SELECT u.id, u.username, u.role, u.status
          FROM user_sessions s
          JOIN users u ON u.id = s.user_id
          WHERE s.session_token_hash = '{token_hash}'
            AND s.revoked_at IS NULL
            AND s.expires_at > NOW()
          LIMIT 1
        ) t;
        """
    )
    if not output:
        return None
    row = json.loads(output)
    user = AuthUser(id=row.get("id", ""), username=row.get("username", ""), role=row.get("role", ""), status=row.get("status", ""))
    if not _is_active(user.status):
        return None
    return user


def ensure_admin_user() -> None:
    ensure_auth_tables()
    username = _normalize_username(settings.auth_admin_username)
    password = settings.auth_admin_password
    if not username or not password:
        return
    existing = get_user_by_username(username)
    if existing:
        return
    create_user(username=username, password=password, role="admin", status="active")

