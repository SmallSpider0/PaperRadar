from __future__ import annotations

from collections.abc import Callable

from backend.chat_answer import run_chat_answer
from backend.chat_message import run_chat_message
from backend.chat_models import ChatAnswerRequest, ChatMessageRequest, ChatSearchRequest
from backend.review_models import ReviewGenerateRequest, ReviewPrepareRequest
from backend.review_service import generate_review_from_session, prepare_review_request
from backend.chat_search import run_fast_search
from backend.search_api import SearchRequest, build_search_job_payload


def execute_search_job(payload: dict, progress_callback: Callable[[dict], None] | None = None) -> dict:
    request = SearchRequest.model_validate(payload)
    return build_search_job_payload(request, progress_callback=progress_callback)


def execute_chat_search_job(payload: dict, progress_callback: Callable[[dict], None] | None = None) -> dict:
    request = ChatSearchRequest.model_validate(payload)
    return run_fast_search(query=request.query, top_k=request.top_k, progress_callback=progress_callback).model_dump()


def execute_chat_answer_job(payload: dict, progress_callback: Callable[[dict], None] | None = None) -> dict:
    request = ChatAnswerRequest.model_validate(payload)
    return run_chat_answer(
        query=request.query,
        paper_ids=request.paper_ids,
        top_k=request.top_k,
        context_hint=request.context_hint,
        progress_callback=progress_callback,
    ).model_dump()


def execute_chat_message_job(payload: dict, progress_callback: Callable[[dict], None] | None = None) -> dict:
    request = ChatMessageRequest.model_validate(payload)
    user_id = str(payload.get("user_id") or "").strip()
    if not user_id:
        raise RuntimeError("chat_message job missing user_id")
    return run_chat_message(
        user_id=user_id,
        query=request.query,
        session_id=request.session_id,
        top_k=request.top_k,
        progress_callback=progress_callback,
    ).model_dump()


def execute_review_prepare_job(payload: dict, progress_callback: Callable[[dict], None] | None = None) -> dict:
    request = ReviewPrepareRequest.model_validate(payload)
    user_id = str(payload.get("user_id") or "").strip()
    if not user_id:
        raise RuntimeError("review_prepare job missing user_id")
    return prepare_review_request(
        user_id=user_id,
        query=request.query,
        preview_limit=request.preview_limit,
        candidate_limit=request.candidate_limit,
        progress_callback=progress_callback,
    )


def execute_review_generate_job(payload: dict, progress_callback: Callable[[dict], None] | None = None) -> dict:
    request = ReviewGenerateRequest.model_validate(payload)
    user_id = str(payload.get("user_id") or "").strip()
    if not user_id:
        raise RuntimeError("review_generate job missing user_id")
    return generate_review_from_session(
        user_id=user_id,
        review_session_id=request.review_session_id,
        confirmed=request.confirmed,
        confirmed_paper_ids=request.confirmed_paper_ids,
        progress_callback=progress_callback,
    )


JOB_EXECUTORS = {
    "search": execute_search_job,
    "chat_search": execute_chat_search_job,
    "chat_answer": execute_chat_answer_job,
    "chat_message": execute_chat_message_job,
    "review_prepare": execute_review_prepare_job,
    "review_generate": execute_review_generate_job,
}


def execute_job(job_type: str, payload: dict, progress_callback: Callable[[dict], None] | None = None) -> dict:
    executor = JOB_EXECUTORS.get(job_type)
    if not executor:
        raise RuntimeError(f"unsupported retrieval job type: {job_type}")
    return executor(payload, progress_callback=progress_callback)
