import json
import os
import time
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.auth import (
    AuthUser,
    clear_login_failures,
    create_session as create_auth_session,
    create_user,
    delete_user,
    ensure_admin_user,
    ensure_auth_tables,
    ensure_user_scope_tables,
    get_user_by_session_token,
    get_user_by_id,
    get_user_by_username,
    is_login_locked,
    list_users,
    mark_login_failure,
    revoke_session_by_token,
    update_user,
    verify_password,
)
from backend.chat_models import (
    ChatAnswerRequest,
    ChatMessageRequest,
    ChatSearchRequest,
)
from backend.chat_session_store import delete_session, get_session, list_messages, list_sessions
from backend.config import settings
from backend.fulltext import fetch_fulltext_by_url, get_fulltext_status, parse_saved_fulltext
from backend.llm_usage import ensure_llm_usage_table
from backend.reader import get_reader_payload
from backend.pg_json_store import run_sql
from backend.review_models import ReviewGenerateRequest, ReviewPrepareRequest
from backend.retrieval_queue import (
    JobNotFoundError,
    JobTimeoutError,
    QueueFullError,
    get_job,
    get_queue_metrics,
    get_search_session,
    ping as queue_ping,
    submit_job,
    wait_for_job,
)
from backend.review_service import delete_review_session_detail, get_review_session_detail, list_review_session_details
from backend.search_api import SearchRequest, slice_search_session
from backend.subscriptions import (
    create_subscription,
    delete_subscription,
    list_matches,
    list_notifications,
    list_subscriptions,
    run_subscription_matching,
)


app = FastAPI(title=settings.app_name)
LEGACY_RETRIEVAL_WAIT_SECONDS = max(5.0, float(settings.retrieval_sync_wait_timeout_seconds))


def _queue_metrics_or_default() -> dict:
    try:
        metrics = get_queue_metrics()
    except Exception:
        metrics = {
            "pending_jobs": None,
            "active_jobs": None,
            "queue_capacity": max(1, int(settings.retrieval_queue_max_size)),
            "max_concurrency": max(1, int(settings.retrieval_max_concurrency)),
        }
    metrics["online"] = queue_ping()
    return metrics


def _queue_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, QueueFullError):
        return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    if isinstance(exc, JobTimeoutError):
        return HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="retrieval job timed out")
    if isinstance(exc, JobNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="retrieval job not found")
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


def _submit_retrieval_job(job_type: str, user_id: str, payload: dict, metadata: dict | None = None) -> dict:
    try:
        return submit_job(job_type=job_type, user_id=user_id, payload=payload, metadata=metadata)
    except Exception as exc:
        raise _queue_http_error(exc) from exc


def _get_retrieval_job(job_id: str, user_id: str) -> dict:
    try:
        return get_job(job_id, user_id)
    except Exception as exc:
        raise _queue_http_error(exc) from exc


def _wait_for_retrieval_result(job_id: str, user_id: str) -> dict:
    try:
        snapshot = wait_for_job(job_id, user_id, LEGACY_RETRIEVAL_WAIT_SECONDS)
    except Exception as exc:
        raise _queue_http_error(exc) from exc
    if snapshot.get("status") == "error":
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=snapshot.get("error") or "retrieval job failed")
    result = snapshot.get("result")
    if not isinstance(result, dict):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="retrieval job returned no result")
    return result


def _job_event_response(job_id: str, user_id: str) -> StreamingResponse:
    def event_stream():
        last_payload = ""
        while True:
            snapshot = _get_retrieval_job(job_id, user_id)
            payload = json.dumps(snapshot, ensure_ascii=False)
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload = payload
            if snapshot["status"] in {"completed", "error"}:
                break
            time.sleep(0.35)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class FetchFulltextRequest(BaseModel):
    paper_url: str
    pdf_url: str | None = None


class CreateSubscriptionRequest(BaseModel):
    name: str
    query_text: str
    type: str = "topic"
    venue_codes: list[str] | None = None
    threshold: float = 0.5


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"


class UpdateUserRequest(BaseModel):
    password: str | None = None
    role: str | None = None
    status: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


WINDOW_TO_SQL_INTERVAL = {
    "1d": "INTERVAL '1 day'",
    "7d": "INTERVAL '7 days'",
    "30d": "INTERVAL '30 days'",
}


def _normalize_window(window: str | None) -> str:
    normalized = (window or "7d").strip().lower()
    if normalized in WINDOW_TO_SQL_INTERVAL or normalized == "all":
        return normalized
    return "7d"


def _window_filter_clause(window: str) -> str:
    if window == "all":
        return ""
    interval = WINDOW_TO_SQL_INTERVAL[window]
    return f"WHERE created_at >= NOW() - {interval}"


def _safe_sql_string(value: str) -> str:
    return value.replace("'", "''")


def _to_int(value: object, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_rows(value: str) -> list[dict]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _build_token_window_filter(window: str, created_at_expr: str = "created_at") -> str:
    if window == "all":
        return ""
    interval = WINDOW_TO_SQL_INTERVAL[window]
    return f"AND {created_at_expr} >= NOW() - {interval}"


def _ensure_api_usage_table() -> None:
    run_sql(
        """
        CREATE TABLE IF NOT EXISTS api_usage_logs (
            id BIGSERIAL PRIMARY KEY,
            path TEXT NOT NULL,
            method TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            latency_ms INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_api_usage_logs_created_at
        ON api_usage_logs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_api_usage_logs_path_created_at
        ON api_usage_logs(path, created_at DESC);
        """
    )


@app.on_event("startup")
def startup_bootstrap() -> None:
    ensure_auth_tables()
    ensure_user_scope_tables()
    ensure_admin_user()
    _ensure_api_usage_table()


def get_current_user(
    session_token: str | None = Cookie(default=None, alias=settings.auth_cookie_name),
) -> AuthUser:
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    user = get_user_by_session_token(session_token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired session")
    return user


def require_admin(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin role required")
    return user


@app.middleware("http")
async def strip_single_container_api_prefix(request: Request, call_next):
    # The static frontend defaults to API_BASE=/paperradar-api so it can work
    # behind a reverse proxy. In app-only Docker mode there is no nginx rewrite,
    # so accept that prefix directly inside FastAPI.
    prefix = "/paperradar-api"
    path = request.scope.get("path") or ""
    if path == prefix:
        request.scope["path"] = "/"
    elif path.startswith(prefix + "/"):
        request.scope["path"] = path[len(prefix):] or "/"
    return await call_next(request)


@app.middleware("http")
async def log_api_usage(request: Request, call_next):
    started_at = time.perf_counter()
    response = await call_next(request)

    path = request.url.path
    should_log = path.startswith("/api/") or path == "/health"
    if not should_log:
        return response

    try:
        _ensure_api_usage_table()
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        escaped_path = _safe_sql_string(path)
        escaped_method = _safe_sql_string(request.method.upper())
        run_sql(
            f"""
            INSERT INTO api_usage_logs (path, method, status_code, latency_ms)
            VALUES ('{escaped_path}', '{escaped_method}', {int(response.status_code)}, {latency_ms});
            """
        )
    except Exception:
        # Usage logging should never impact business responses.
        pass

    return response


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "retrieval_queue": _queue_metrics_or_default(),
    }


@app.post("/api/auth/login")
def api_auth_login(request: LoginRequest, response: Response, http_request: Request) -> dict:
    username = request.username.strip().lower()
    if is_login_locked(username, http_request.client.host if http_request.client else ""):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many failed login attempts")

    user = get_user_by_username(username)
    if not user or not verify_password(request.password, user["password_hash"]) or user.get("status") != "active":
        mark_login_failure(username, http_request.client.host if http_request.client else "")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid username or password")

    clear_login_failures(username, http_request.client.host if http_request.client else "")
    session_token, expires_at = create_auth_session(
        user_id=user["id"],
        ip=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=session_token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        max_age=60 * 60 * 12,
        path="/",
    )
    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
        },
        "expires_at": expires_at.isoformat(),
    }


@app.post("/api/auth/logout")
def api_auth_logout(response: Response, session_token: str | None = Cookie(default=None, alias=settings.auth_cookie_name)) -> dict:
    if session_token:
        revoke_session_by_token(session_token)
    response.delete_cookie(key=settings.auth_cookie_name, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def api_auth_me(user: AuthUser = Depends(get_current_user)) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
    }


@app.post("/api/auth/password")
def api_auth_change_password(request: ChangePasswordRequest, user: AuthUser = Depends(get_current_user)) -> dict:
    if len((request.new_password or "").strip()) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="new password is too short")
    db_user = get_user_by_id(user.id)
    if not db_user or not verify_password(request.current_password, db_user.get("password_hash", "")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="current password is incorrect")
    updated = update_user(user.id, password=request.new_password)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return {"ok": True}


@app.get("/api/admin/users")
def api_admin_list_users(_: AuthUser = Depends(require_admin)) -> dict:
    return {"users": list_users()}


@app.post("/api/admin/users")
def api_admin_create_user(request: CreateUserRequest, _: AuthUser = Depends(require_admin)) -> dict:
    existing = get_user_by_username(request.username)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username already exists")
    role = "admin" if request.role == "admin" else "user"
    if role == "admin":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="only admin can create regular users here")
    created = create_user(username=request.username, password=request.password, role=role)
    return {"ok": True, "user": created}


@app.patch("/api/admin/users/{user_id}")
def api_admin_update_user(user_id: str, request: UpdateUserRequest, current: AuthUser = Depends(require_admin)) -> dict:
    if user_id == current.id and request.status == "disabled":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cannot disable current admin account")
    if request.role == "admin" and user_id != current.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="promoting extra admin is blocked")
    updated = update_user(user_id, password=request.password, role=request.role, status=request.status)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return {"ok": True, "user": updated}


@app.delete("/api/admin/users/{user_id}")
def api_admin_delete_user(user_id: str, current: AuthUser = Depends(require_admin)) -> dict:
    if user_id == current.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cannot delete current admin account")
    deleted = delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return {"ok": True, "user_id": user_id}


@app.get("/api/system/stats")
def api_system_stats(window: str = "7d", _: AuthUser = Depends(require_admin)) -> dict:
    normalized_window = _normalize_window(window)
    usage_filter = _window_filter_clause(normalized_window)
    session_filter = _window_filter_clause(normalized_window)
    message_filter = _window_filter_clause(normalized_window)

    _ensure_api_usage_table()
    ensure_llm_usage_table()

    papers_total = _to_int(run_sql("SELECT COUNT(*)::text FROM papers;"))
    papers_by_year_raw = run_sql(
        """
        SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
        FROM (
          SELECT ve.year, COUNT(*)::int AS count
          FROM papers p
          JOIN venue_editions ve ON ve.id = p.venue_edition_id
          GROUP BY ve.year
          ORDER BY ve.year DESC
          LIMIT 12
        ) t;
        """
    )
    papers_by_year = _to_rows(papers_by_year_raw)

    api_total = _to_int(run_sql(f"SELECT COUNT(*)::text FROM api_usage_logs {usage_filter};"))
    api_by_endpoint_raw = run_sql(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
        FROM (
          SELECT path, COUNT(*)::int AS count
          FROM api_usage_logs
          {usage_filter}
          GROUP BY path
          ORDER BY count DESC, path ASC
          LIMIT 20
        ) t;
        """
    )
    api_by_endpoint = _to_rows(api_by_endpoint_raw)

    session_count = _to_int(run_sql(f"SELECT COUNT(*)::text FROM rag_sessions {session_filter};"))
    message_count = _to_int(run_sql(f"SELECT COUNT(*)::text FROM rag_messages {message_filter};"))
    answer_token_window_filter = _build_token_window_filter(normalized_window, "rm.created_at")
    topic_run_window_filter = _build_token_window_filter(normalized_window, "tpr.created_at")
    llm_log_window_filter = _build_token_window_filter(normalized_window, "lul.created_at")
    llm_usage_union_sql = f"""
        SELECT
          COALESCE((rm.answer_json->'answer_summary'->'token_usage'->>'prompt_tokens')::bigint, 0)::bigint AS prompt_tokens,
          COALESCE((rm.answer_json->'answer_summary'->'token_usage'->>'completion_tokens')::bigint, 0)::bigint AS completion_tokens,
          COALESCE((rm.answer_json->'answer_summary'->'token_usage'->>'total_tokens')::bigint, 0)::bigint AS total_tokens,
          COALESCE(NULLIF(rm.answer_json->'answer_summary'->>'model', ''), 'unknown') AS model
        FROM rag_messages rm
        WHERE rm.role = 'assistant'
          AND rm.answer_json ? 'answer_summary'
          AND rm.answer_json->'answer_summary' ? 'token_usage'
          {answer_token_window_filter}
        UNION ALL
        SELECT
          COALESCE((tpr.token_usage_json->>'prompt_tokens')::bigint, 0)::bigint AS prompt_tokens,
          COALESCE((tpr.token_usage_json->>'completion_tokens')::bigint, 0)::bigint AS completion_tokens,
          COALESCE((tpr.token_usage_json->>'total_tokens')::bigint, 0)::bigint AS total_tokens,
          COALESCE(NULLIF(tpr.model_name, ''), 'unknown') AS model
        FROM paper_topic_profile_runs tpr
        WHERE tpr.token_usage_json <> '{{}}'::jsonb
          {topic_run_window_filter}
        UNION ALL
        SELECT
          COALESCE(lul.prompt_tokens, 0)::bigint AS prompt_tokens,
          COALESCE(lul.completion_tokens, 0)::bigint AS completion_tokens,
          COALESCE(lul.total_tokens, 0)::bigint AS total_tokens,
          COALESCE(NULLIF(lul.model, ''), 'unknown') AS model
        FROM llm_usage_logs lul
        WHERE 1 = 1
          {llm_log_window_filter}
    """
    llm_tokens_raw = run_sql(
        f"""
        SELECT row_to_json(t)::text
        FROM (
          SELECT
            COALESCE(SUM(prompt_tokens), 0)::bigint AS prompt_tokens,
            COALESCE(SUM(completion_tokens), 0)::bigint AS completion_tokens,
            COALESCE(SUM(total_tokens), 0)::bigint AS total_tokens
          FROM (
            {llm_usage_union_sql}
          ) usage_rows
        ) t;
        """
    )
    llm_tokens = json.loads(llm_tokens_raw) if llm_tokens_raw else {}
    llm_by_model_raw = run_sql(
        f"""
        SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
        FROM (
          SELECT
            model,
            COALESCE(SUM(total_tokens), 0)::bigint AS total_tokens
          FROM (
            {llm_usage_union_sql}
          ) usage_rows
          GROUP BY model
          ORDER BY total_tokens DESC, model ASC
          LIMIT 10
        ) t;
        """
    )
    llm_by_model = _to_rows(llm_by_model_raw)

    return {
        "window": normalized_window,
        "health": health(),
        "papers": {
            "total_count": papers_total,
            "by_year": papers_by_year,
        },
        "api_usage": {
            "total_calls": api_total,
            "by_endpoint": api_by_endpoint,
        },
        "sessions": {
            "session_count": session_count,
            "message_count": message_count,
        },
        "llm_usage": {
            "prompt_tokens": _to_int(llm_tokens.get("prompt_tokens")),
            "completion_tokens": _to_int(llm_tokens.get("completion_tokens")),
            "total_tokens": _to_int(llm_tokens.get("total_tokens")),
            "by_model": llm_by_model,
        },
        "retrieval_queue": _queue_metrics_or_default(),
    }


@app.post("/api/search")
def api_search(request: SearchRequest, user: AuthUser = Depends(get_current_user)) -> dict:
    job = _submit_retrieval_job(
        "search",
        user.id,
        request.model_dump(),
        metadata={
            "query": request.query,
            "page": max(int(request.page or 1), 1),
            "limit": max(int(request.limit or 20), 1),
        },
    )
    return _wait_for_retrieval_result(job["job_id"], user.id)


@app.post("/api/search/jobs")
def api_search_jobs_create(request: SearchRequest, user: AuthUser = Depends(get_current_user)) -> dict:
    return _submit_retrieval_job(
        "search",
        user.id,
        request.model_dump(),
        metadata={
            "query": request.query,
            "page": max(int(request.page or 1), 1),
            "limit": max(int(request.limit or 20), 1),
        },
    )


@app.get("/api/search/jobs/{job_id}")
def api_search_job_detail(job_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    return _get_retrieval_job(job_id, user.id)


@app.get("/api/search/jobs/{job_id}/events")
def api_search_job_events(job_id: str, user: AuthUser = Depends(get_current_user)) -> StreamingResponse:
    return _job_event_response(job_id, user.id)


@app.get("/api/search/sessions/{session_id}")
def api_search_session_page(
    session_id: str,
    page: int = 1,
    limit: int = 20,
    user: AuthUser = Depends(get_current_user),
) -> dict:
    try:
        session_payload = get_search_session(session_id, user.id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="search session expired or not found") from exc
    return slice_search_session(session_payload, page=page, limit=limit, search_session_id=session_id)


@app.post("/api/chat/search/jobs")
def api_chat_search_jobs_create(request: ChatSearchRequest, user: AuthUser = Depends(get_current_user)) -> dict:
    return _submit_retrieval_job(
        "chat_search",
        user.id,
        request.model_dump(),
        metadata={"query": request.query, "top_k": request.top_k},
    )


@app.get("/api/chat/search/jobs/{job_id}")
def api_chat_search_job_detail(job_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    return _get_retrieval_job(job_id, user.id)


@app.get("/api/chat/search/jobs/{job_id}/events")
def api_chat_search_job_events(job_id: str, user: AuthUser = Depends(get_current_user)) -> StreamingResponse:
    return _job_event_response(job_id, user.id)


@app.post("/api/review/prepare/jobs")
def api_review_prepare_jobs_create(request: ReviewPrepareRequest, user: AuthUser = Depends(get_current_user)) -> dict:
    payload = request.model_dump()
    payload["user_id"] = user.id
    return _submit_retrieval_job(
        "review_prepare",
        user.id,
        payload,
        metadata={"query": request.query},
    )


@app.get("/api/review/prepare/jobs/{job_id}")
def api_review_prepare_job_detail(job_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    return _get_retrieval_job(job_id, user.id)


@app.get("/api/review/prepare/jobs/{job_id}/events")
def api_review_prepare_job_events(job_id: str, user: AuthUser = Depends(get_current_user)) -> StreamingResponse:
    return _job_event_response(job_id, user.id)


@app.post("/api/review/generate/jobs")
def api_review_generate_jobs_create(request: ReviewGenerateRequest, user: AuthUser = Depends(get_current_user)) -> dict:
    payload = request.model_dump()
    payload["user_id"] = user.id
    return _submit_retrieval_job(
        "review_generate",
        user.id,
        payload,
        metadata={"review_session_id": request.review_session_id},
    )


@app.get("/api/review/generate/jobs/{job_id}")
def api_review_generate_job_detail(job_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    return _get_retrieval_job(job_id, user.id)


@app.get("/api/review/generate/jobs/{job_id}/events")
def api_review_generate_job_events(job_id: str, user: AuthUser = Depends(get_current_user)) -> StreamingResponse:
    return _job_event_response(job_id, user.id)


@app.post("/api/chat/answer/jobs")
def api_chat_answer_jobs_create(request: ChatAnswerRequest, user: AuthUser = Depends(get_current_user)) -> dict:
    return _submit_retrieval_job(
        "chat_answer",
        user.id,
        request.model_dump(),
        metadata={"query": request.query, "top_k": request.top_k, "session_id": request.session_id},
    )


@app.get("/api/chat/answer/jobs/{job_id}")
def api_chat_answer_job_detail(job_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    return _get_retrieval_job(job_id, user.id)


@app.get("/api/chat/answer/jobs/{job_id}/events")
def api_chat_answer_job_events(job_id: str, user: AuthUser = Depends(get_current_user)) -> StreamingResponse:
    return _job_event_response(job_id, user.id)


@app.post("/api/chat/message/jobs")
def api_chat_message_jobs_create(request: ChatMessageRequest, user: AuthUser = Depends(get_current_user)) -> dict:
    payload = request.model_dump()
    payload["user_id"] = user.id
    return _submit_retrieval_job(
        "chat_message",
        user.id,
        payload,
        metadata={"query": request.query, "top_k": request.top_k, "session_id": request.session_id},
    )


@app.get("/api/chat/message/jobs/{job_id}")
def api_chat_message_job_detail(job_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    return _get_retrieval_job(job_id, user.id)


@app.get("/api/chat/message/jobs/{job_id}/events")
def api_chat_message_job_events(job_id: str, user: AuthUser = Depends(get_current_user)) -> StreamingResponse:
    return _job_event_response(job_id, user.id)


@app.post("/api/chat/search")
def api_chat_search(request: ChatSearchRequest, user: AuthUser = Depends(get_current_user)) -> dict:
    job = _submit_retrieval_job(
        "chat_search",
        user.id,
        request.model_dump(),
        metadata={"query": request.query, "top_k": request.top_k},
    )
    return _wait_for_retrieval_result(job["job_id"], user.id)


@app.post("/api/chat/answer")
def api_chat_answer(request: ChatAnswerRequest, user: AuthUser = Depends(get_current_user)) -> dict:
    job = _submit_retrieval_job(
        "chat_answer",
        user.id,
        request.model_dump(),
        metadata={"query": request.query, "top_k": request.top_k, "session_id": request.session_id},
    )
    return _wait_for_retrieval_result(job["job_id"], user.id)


@app.post("/api/chat/message")
def api_chat_message(request: ChatMessageRequest, user: AuthUser = Depends(get_current_user)) -> dict:
    payload = request.model_dump()
    payload["user_id"] = user.id
    job = _submit_retrieval_job(
        "chat_message",
        user.id,
        payload,
        metadata={"query": request.query, "top_k": request.top_k, "session_id": request.session_id},
    )
    return _wait_for_retrieval_result(job["job_id"], user.id)


@app.post("/api/review/prepare")
def api_review_prepare(request: ReviewPrepareRequest, user: AuthUser = Depends(get_current_user)) -> dict:
    payload = request.model_dump()
    payload["user_id"] = user.id
    job = _submit_retrieval_job(
        "review_prepare",
        user.id,
        payload,
        metadata={"query": request.query},
    )
    return _wait_for_retrieval_result(job["job_id"], user.id)


@app.post("/api/review/generate")
def api_review_generate(request: ReviewGenerateRequest, user: AuthUser = Depends(get_current_user)) -> dict:
    payload = request.model_dump()
    payload["user_id"] = user.id
    job = _submit_retrieval_job(
        "review_generate",
        user.id,
        payload,
        metadata={"review_session_id": request.review_session_id},
    )
    return _wait_for_retrieval_result(job["job_id"], user.id)


@app.get("/api/review/sessions")
def api_review_sessions(limit: int = 20, user: AuthUser = Depends(get_current_user)) -> dict:
    return {"sessions": list_review_session_details(user.id, limit=limit)}


@app.get("/api/review/sessions/{session_id}")
def api_review_session_detail(session_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    detail = get_review_session_detail(user.id, session_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review session not found")
    return detail


@app.delete("/api/review/sessions/{session_id}")
def api_review_session_delete(session_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    deleted = delete_review_session_detail(user.id, session_id)
    if not deleted:
        return {"ok": False, "session_id": session_id, "error": "review session not found"}
    return {"ok": True, "session_id": session_id}


@app.get("/api/chat/sessions")
def api_chat_sessions(limit: int = 20, user: AuthUser = Depends(get_current_user)) -> dict:
    return {
        "sessions": list_sessions(user_id=user.id, limit=limit),
    }


@app.get("/api/chat/sessions/{session_id}")
def api_chat_session_detail(session_id: str, limit: int = 50, user: AuthUser = Depends(get_current_user)) -> dict:
    session = get_session(user.id, session_id)
    return {
        "session": session or {"id": session_id},
        "messages": list_messages(session_id, limit=limit) if session else [],
    }


@app.delete("/api/chat/sessions/{session_id}")
def api_chat_session_delete(session_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    deleted = delete_session(user.id, session_id)
    if not deleted:
        return {"ok": False, "session_id": session_id, "error": "session not found"}
    return {"ok": True, "session_id": session_id}


@app.post("/api/fulltext/fetch")
def api_fetch_fulltext(request: FetchFulltextRequest, _: AuthUser = Depends(require_admin)) -> dict:
    return fetch_fulltext_by_url(request.paper_url, request.pdf_url)


@app.post("/api/fulltext/parse/{paper_id}")
def api_parse_fulltext(paper_id: str, _: AuthUser = Depends(require_admin)) -> dict:
    return parse_saved_fulltext(paper_id)


@app.get("/api/fulltext/status/{paper_id}")
def api_fulltext_status(paper_id: str, _: AuthUser = Depends(require_admin)) -> dict:
    return get_fulltext_status(paper_id)


@app.get("/api/reader/{paper_id}")
def api_reader(paper_id: str, _: AuthUser = Depends(require_admin)) -> dict:
    return get_reader_payload(paper_id)


@app.get("/api/subscriptions")
def api_list_subscriptions(user: AuthUser = Depends(get_current_user)) -> list[dict]:
    return list_subscriptions(user.id)


@app.post("/api/subscriptions")
def api_create_subscription(request: CreateSubscriptionRequest, user: AuthUser = Depends(get_current_user)) -> dict:
    return create_subscription(
        user_id=user.id,
        name=request.name,
        query_text=request.query_text,
        type_=request.type,
        venue_codes=request.venue_codes,
        threshold=request.threshold,
    )


@app.delete("/api/subscriptions/{sub_id}")
def api_delete_subscription(sub_id: str, user: AuthUser = Depends(get_current_user)) -> dict:
    return delete_subscription(user.id, sub_id)


@app.post("/api/subscriptions/match")
def api_run_matching(user: AuthUser = Depends(get_current_user)) -> dict:
    return run_subscription_matching(user.id)


@app.get("/api/subscriptions/{sub_id}/matches")
def api_list_matches(sub_id: str, user: AuthUser = Depends(get_current_user)) -> list[dict]:
    return list_matches(user.id, sub_id)


@app.get("/api/notifications")
def api_list_notifications(user: AuthUser = Depends(get_current_user)) -> list[dict]:
    return list_notifications(user.id)


# Optional single-container/static deployment support.
# When PAPERRADAR_STATIC_DIR points to a Next.js static export, the API process
# also serves the frontend. API routes are declared above, so these catch-all
# frontend routes do not intercept /api/* or /health.
_STATIC_DIR = os.getenv("PAPERRADAR_STATIC_DIR", "").strip()
if _STATIC_DIR:
    _static_path = Path(_STATIC_DIR).resolve()
    _next_path = _static_path / "_next"
    if _next_path.exists():
        app.mount("/paperradar/_next", StaticFiles(directory=str(_next_path)), name="paperradar_next_static")

    @app.get("/paperradar")
    @app.get("/paperradar/")
    def paperradar_frontend_index() -> FileResponse:
        index_path = _static_path / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="frontend index not found")
        return FileResponse(index_path)

    @app.get("/paperradar/{path:path}")
    def paperradar_frontend_asset_or_page(path: str) -> FileResponse:
        candidates = []
        if path:
            candidates.extend([
                _static_path / path,
                _static_path / f"{path}.html",
                _static_path / path / "index.html",
            ])
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except FileNotFoundError:
                continue
            if _static_path in resolved.parents or resolved == _static_path:
                if resolved.is_file():
                    return FileResponse(resolved)
        index_path = _static_path / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        raise HTTPException(status_code=404, detail="frontend asset not found")
