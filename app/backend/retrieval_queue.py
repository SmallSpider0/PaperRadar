from __future__ import annotations

import json
import threading
import time
from uuid import uuid4

import redis

from backend.config import settings

TERMINAL_JOB_STATUSES = {"completed", "error"}

_redis_client: redis.Redis | None = None
_redis_lock = threading.Lock()


class QueueFullError(RuntimeError):
    pass


class JobNotFoundError(RuntimeError):
    pass


class JobTimeoutError(RuntimeError):
    pass


def _prefix() -> str:
    return settings.retrieval_queue_prefix.rstrip(":")


def _pending_queue_key() -> str:
    return f"{_prefix()}:pending"


def _processing_queue_key() -> str:
    return f"{_prefix()}:processing"


def _job_key(job_id: str) -> str:
    return f"{_prefix()}:job:{job_id}"


def get_redis_client() -> redis.Redis:
    global _redis_client
    with _redis_lock:
        if _redis_client is None:
            _redis_client = redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                health_check_interval=30,
            )
        return _redis_client


def _estimate_eta_seconds(
    started_at: float | None,
    progress: float,
    previous_total: float | None = None,
) -> tuple[float | None, float | None]:
    if not started_at:
        return None, previous_total
    elapsed = max(0.0, time.time() - started_at)
    if progress <= 0.0 or elapsed <= 0.0:
        return None, previous_total
    projected_total = elapsed / max(progress, 1e-3)
    if previous_total and previous_total > 0:
        projected_total = previous_total * 0.55 + projected_total * 0.45
    projected_total = max(projected_total, elapsed)
    return max(0.0, projected_total - elapsed), projected_total


def _load_job(job_id: str) -> dict:
    raw = get_redis_client().get(_job_key(job_id))
    if not raw:
        raise JobNotFoundError(job_id)
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise JobNotFoundError(job_id)
    return payload


def _store_job(job: dict, *, expire_seconds: int | None = None) -> None:
    client = get_redis_client()
    client.set(_job_key(job["job_id"]), json.dumps(job, ensure_ascii=False))
    if expire_seconds:
        client.expire(_job_key(job["job_id"]), max(1, int(expire_seconds)))
    else:
        client.persist(_job_key(job["job_id"]))


def _remove_processing_marker(job_id: str) -> None:
    get_redis_client().lrem(_processing_queue_key(), 0, job_id)


def _pending_ids() -> list[str]:
    return list(get_redis_client().lrange(_pending_queue_key(), 0, -1))


def _processing_ids() -> list[str]:
    return list(get_redis_client().lrange(_processing_queue_key(), 0, -1))


def _queue_position(job_id: str) -> tuple[int | None, int]:
    pending_ids = _pending_ids()
    pending_count = len(pending_ids)
    if job_id not in pending_ids:
        return None, pending_count
    idx = pending_ids.index(job_id)
    position = pending_count - idx
    return position, pending_count


def _serialize_job(job: dict) -> dict:
    now = time.time()
    started_at = float(job.get("started_at") or 0.0) or None
    created_at = float(job.get("created_at") or now)
    base_started_at = started_at or created_at
    elapsed_seconds = max(0.0, now - base_started_at)
    queue_position, pending_count = _queue_position(job["job_id"])
    active_count = len(_processing_ids())
    payload = {
        "job_id": job["job_id"],
        "job_type": job.get("job_type"),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "message": job.get("message"),
        "progress": float(job.get("progress") or 0.0),
        "eta_seconds": job.get("eta_seconds"),
        "elapsed_seconds": round(elapsed_seconds, 2),
        "queue_position": queue_position,
        "queue_ahead": max(0, (queue_position or 1) - 1) if queue_position else 0,
        "pending_jobs": pending_count,
        "active_jobs": active_count,
        "max_concurrency": max(1, int(settings.retrieval_max_concurrency)),
        "error": job.get("error"),
        "result": job.get("result"),
        "updated_at": job.get("updated_at"),
    }
    for key in [
        "query",
        "page",
        "limit",
        "top_k",
        "session_id",
        "query_type",
        "intent",
        "query_variants",
        "variant",
        "variant_index",
        "variant_total",
        "search_stage",
        "search_message",
        "candidate_count",
        "completed_chunks",
        "total_chunks",
        "recall_limit",
        "total_records",
        "result_count",
    ]:
        if key in job:
            payload[key] = job.get(key)
    return payload


def _update_job_state(job_id: str, **payload) -> dict:
    job = _load_job(job_id)
    if "progress" in payload and payload["progress"] is not None:
        job["progress"] = max(0.0, min(float(payload["progress"]), 1.0))
        eta_seconds, expected_total = _estimate_eta_seconds(
            float(job.get("started_at") or 0.0) or None,
            float(job["progress"]),
            job.get("expected_total_seconds"),
        )
        job["eta_seconds"] = None if eta_seconds is None else round(eta_seconds, 2)
        job["expected_total_seconds"] = expected_total
    for key, value in payload.items():
        if key == "progress":
            continue
        job[key] = value
    job["updated_at"] = time.time()
    _store_job(job)
    return job


def submit_job(job_type: str, user_id: str, payload: dict, metadata: dict | None = None) -> dict:
    client = get_redis_client()
    pending_count = client.llen(_pending_queue_key())
    processing_count = client.llen(_processing_queue_key())
    total_outstanding = int(pending_count or 0) + int(processing_count or 0)
    max_queue_size = max(1, int(settings.retrieval_queue_max_size))
    if total_outstanding >= max_queue_size:
        raise QueueFullError(f"retrieval queue is full ({total_outstanding}/{max_queue_size})")

    now = time.time()
    job_id = uuid4().hex
    job = {
        "job_id": job_id,
        "job_type": job_type,
        "user_id": user_id,
        "status": "queued",
        "stage": "queued",
        "message": "任务已入队，等待 worker 调度",
        "progress": 0.0,
        "eta_seconds": None,
        "expected_total_seconds": None,
        "created_at": now,
        "started_at": None,
        "updated_at": now,
        "error": None,
        "result": None,
        "payload": payload,
    }
    for key, value in (metadata or {}).items():
        job[key] = value
    _store_job(job)
    client.lpush(_pending_queue_key(), job_id)
    return _serialize_job(job)


def get_job(job_id: str, user_id: str) -> dict:
    job = _load_job(job_id)
    if job.get("user_id") != user_id:
        raise JobNotFoundError(job_id)
    return _serialize_job(job)


def get_search_session(job_id: str, user_id: str) -> dict:
    job = _load_job(job_id)
    if job.get("user_id") != user_id or job.get("job_type") != "search":
        raise JobNotFoundError(job_id)
    payload = job.get("search_session_payload")
    if job.get("status") != "completed" or not isinstance(payload, dict):
        raise JobNotFoundError(job_id)
    return payload


def update_job(job_id: str, **payload) -> dict:
    return _serialize_job(_update_job_state(job_id, **payload))


def complete_job(job_id: str, result: dict) -> dict:
    _remove_processing_marker(job_id)
    job = _load_job(job_id)
    stored_result = result
    extra_payload = {}
    if job.get("job_type") == "search" and isinstance(result, dict):
        page_payload = result.get("page_payload")
        session_payload = result.get("search_session_payload")
        if isinstance(page_payload, dict):
            stored_result = {**page_payload, "search_session_id": job_id}
        if isinstance(session_payload, dict):
            extra_payload["search_session_payload"] = session_payload
    job = _update_job_state(
        job_id,
        status="completed",
        stage="done",
        message="任务已完成",
        progress=1.0,
        eta_seconds=0.0,
        result=stored_result,
        result_count=stored_result.get("count") if isinstance(stored_result, dict) else None,
        **extra_payload,
    )
    _store_job(job, expire_seconds=settings.retrieval_job_ttl_seconds)
    return _serialize_job(job)


def fail_job(job_id: str, error_message: str) -> dict:
    _remove_processing_marker(job_id)
    job = _update_job_state(
        job_id,
        status="error",
        stage="error",
        message="任务执行失败",
        error=error_message,
        eta_seconds=0.0,
    )
    _store_job(job, expire_seconds=settings.retrieval_job_ttl_seconds)
    return _serialize_job(job)


def claim_next_job(timeout: int = 1) -> dict | None:
    client = get_redis_client()
    job_id = client.brpoplpush(_pending_queue_key(), _processing_queue_key(), timeout=max(1, int(timeout)))
    if not job_id:
        return None
    try:
        job = _load_job(job_id)
    except JobNotFoundError:
        _remove_processing_marker(job_id)
        return None
    if job.get("status") in TERMINAL_JOB_STATUSES:
        _remove_processing_marker(job_id)
        return None
    now = time.time()
    if not job.get("started_at"):
        job["started_at"] = now
    job["status"] = "running"
    job["stage"] = "starting"
    job["message"] = "worker 已接单，开始执行"
    job["updated_at"] = now
    _store_job(job)
    return job


def requeue_processing_jobs() -> int:
    client = get_redis_client()
    processing_ids = _processing_ids()
    requeued = 0
    pending_ids = set(_pending_ids())
    for job_id in processing_ids:
        _remove_processing_marker(job_id)
        try:
            job = _load_job(job_id)
        except JobNotFoundError:
            continue
        if job.get("status") in TERMINAL_JOB_STATUSES:
            continue
        job["status"] = "queued"
        job["stage"] = "queued"
        job["message"] = "worker 重启后重新入队"
        job["started_at"] = None
        job["updated_at"] = time.time()
        job["eta_seconds"] = None
        _store_job(job)
        if job_id not in pending_ids:
            client.lpush(_pending_queue_key(), job_id)
            pending_ids.add(job_id)
        requeued += 1
    return requeued


def wait_for_job(job_id: str, user_id: str, timeout_seconds: float) -> dict:
    deadline = time.time() + max(0.1, float(timeout_seconds))
    while time.time() < deadline:
        snapshot = get_job(job_id, user_id)
        if snapshot.get("status") in TERMINAL_JOB_STATUSES:
            return snapshot
        time.sleep(0.2)
    raise JobTimeoutError(job_id)


def get_queue_metrics() -> dict:
    client = get_redis_client()
    pending = int(client.llen(_pending_queue_key()) or 0)
    active = int(client.llen(_processing_queue_key()) or 0)
    return {
        "pending_jobs": pending,
        "active_jobs": active,
        "queue_capacity": max(1, int(settings.retrieval_queue_max_size)),
        "max_concurrency": max(1, int(settings.retrieval_max_concurrency)),
    }


def ping() -> bool:
    try:
        return bool(get_redis_client().ping())
    except Exception:
        return False
