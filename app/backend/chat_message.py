from __future__ import annotations

from collections.abc import Callable

from backend.chat_models import ChatFilters, ChatMessageResponse
from backend.chat_orchestrator import orchestrate_chat_turn
from backend.chat_session_store import (
    append_message,
    create_session,
    get_latest_answer_payload,
    get_recent_messages,
    get_session,
    list_messages,
    touch_session,
)

FOLLOW_UP_COMPARE_KEYWORDS = ["compare", "比较", "对比", "区别", "不同", "vs", "versus"]
FOLLOW_UP_EXPAND_KEYWORDS = ["expand", "扩大", "扩展", "更多", "更多论文", "再找", "继续找", "补充", "相关工作"]
FOLLOW_UP_REFINE_KEYWORDS = ["refine", "缩小", "进一步", "聚焦", "限定", "只看", "具体到", "细化"]
FOLLOW_UP_REFERENCE_KEYWORDS = ["这些论文", "上面这些", "它们", "其中", "上一轮", "刚才", "前面"]
EMPTY_TOPIC_PHRASES = {"再扩大一点", "补充更多", "再找一些", "更多相关工作", "只看", "比较一下这些论文的差异", "比较这些论文", "这些论文的差异"}


def _emit_progress(progress_callback: Callable[[dict], None] | None, **payload) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(payload)
    except Exception:
        return


def _load_context_papers(user_id: str, session_id: str | None) -> list[dict] | None:
    if not session_id:
        return None
    latest_answer = get_latest_answer_payload(session_id)
    if not latest_answer:
        return None
    papers = latest_answer.get("papers") or []
    return papers if isinstance(papers, list) and papers else None


def _latest_structured_query(user_id: str, session_id: str | None) -> dict | None:
    if not session_id:
        return None
    if not get_session(user_id, session_id):
        return None
    recent = get_recent_messages(session_id, limit=6)
    for message in reversed(recent):
        payload = message.get("structured_query_json") or {}
        if isinstance(payload, dict) and payload:
            return payload
    return None


def _contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def _looks_like_follow_up(query: str) -> bool:
    return _contains_any(query, FOLLOW_UP_COMPARE_KEYWORDS + FOLLOW_UP_EXPAND_KEYWORDS + FOLLOW_UP_REFINE_KEYWORDS + FOLLOW_UP_REFERENCE_KEYWORDS)


def _normalize_topic(topic: str | None) -> str:
    value = (topic or "").strip()
    return "" if value in EMPTY_TOPIC_PHRASES else value


def _merge_filters(previous_filters: dict | None, query: str) -> ChatFilters:
    previous_filters = previous_filters or {}
    venues = list(previous_filters.get("venues") or [])
    years = list(previous_filters.get("years") or [])

    lowered = query.lower()
    if "ndss" in lowered and "NDSS" not in venues:
        venues = ["NDSS"]
    elif any(token in lowered for token in ["usenix", "usenix security"]) and "USENIX_SECURITY" not in venues:
        venues = ["USENIX_SECURITY"]
    elif any(token in lowered for token in ["ieee sp", "oakland", "s&p", "sp "]) and "IEEE_SP" not in venues:
        venues = ["IEEE_SP"]

    return ChatFilters(
        venues=venues,
        years=years,
        year_from=previous_filters.get("year_from"),
        year_to=previous_filters.get("year_to"),
    )


def _derive_follow_up_overrides(query: str, latest_structured_query: dict | None, context_papers: list[dict] | None) -> dict | None:
    if not _looks_like_follow_up(query):
        return None

    previous_query = latest_structured_query or {}
    previous_topic = _normalize_topic(previous_query.get("topic"))
    previous_filters = previous_query.get("filters") or {}

    if _contains_any(query, FOLLOW_UP_EXPAND_KEYWORDS):
        return {
            "topic": previous_topic,
            "filters": _merge_filters(previous_filters, query).model_dump(),
            "paper_ids": [],
        }

    if _contains_any(query, FOLLOW_UP_REFINE_KEYWORDS):
        return {
            "topic": previous_topic,
            "filters": _merge_filters(previous_filters, query).model_dump(),
            "paper_ids": [paper.get("paper_id") for paper in (context_papers or []) if paper.get("paper_id")],
        }

    if _contains_any(query, FOLLOW_UP_COMPARE_KEYWORDS) or _contains_any(query, FOLLOW_UP_REFERENCE_KEYWORDS):
        return {
            "topic": previous_topic,
            "filters": _merge_filters(previous_filters, query).model_dump(),
            "paper_ids": [paper.get("paper_id") for paper in (context_papers or []) if paper.get("paper_id")],
        }

    return None


def _build_context_hint(query: str, latest_structured_query: dict | None, context_papers: list[dict] | None) -> str | None:
    if not latest_structured_query and not context_papers:
        return None

    intent = (latest_structured_query or {}).get("intent") or "search"
    topic = (latest_structured_query or {}).get("topic") or ""
    filters = (latest_structured_query or {}).get("filters") or {}
    venues = ", ".join(filters.get("venues") or [])
    years = ", ".join(str(year) for year in (filters.get("years") or []))

    base_lines = []
    if topic:
        base_lines.append(f"上一轮主题：{topic}")
    if venues:
        base_lines.append(f"上一轮 venues：{venues}")
    if years:
        base_lines.append(f"上一轮 years：{years}")
    if context_papers:
        titles = [paper.get("title") for paper in context_papers[:5] if paper.get("title")]
        if titles:
            base_lines.append("上一轮候选论文：" + " | ".join(titles))

    if _contains_any(query, FOLLOW_UP_COMPARE_KEYWORDS):
        mode = "compare"
        instruction = "请把当前问题视为基于上一轮候选论文的比较请求，优先沿用上一轮论文集合做比较，不要重新扩大范围。"
    elif _contains_any(query, FOLLOW_UP_REFINE_KEYWORDS):
        mode = "refine"
        instruction = "请把当前问题视为对上一轮检索结果的进一步缩小/细化，优先保留上一轮主题与过滤条件，再叠加本轮限制。"
    elif _contains_any(query, FOLLOW_UP_EXPAND_KEYWORDS):
        mode = "expand"
        instruction = "请把当前问题视为在上一轮主题基础上的扩展检索，保留上一轮主题，但允许放宽限制并补充更多相关论文。"
    else:
        mode = intent
        instruction = "请结合上一轮主题和候选论文理解当前追问；若当前问题引用了“这些论文/上面这些”，优先继承上一轮论文集合。"

    return "\n".join([f"[Session Context Mode] {mode}", *base_lines, instruction]).strip()


def _build_follow_up_context(user_id: str, query: str, session_id: str | None, context_papers: list[dict] | None) -> tuple[str | None, dict | None]:
    if not session_id or not _looks_like_follow_up(query):
        return None, None
    latest_structured_query = _latest_structured_query(user_id, session_id)
    return (
        _build_context_hint(query, latest_structured_query, context_papers),
        _derive_follow_up_overrides(query, latest_structured_query, context_papers),
    )


def _build_assistant_payload(answer, mode: str, tool_calls: list[dict] | None = None) -> dict:
    return {
        "mode": mode,
        "answer_markdown": answer.answer_markdown or answer.answer,
        "citations": [citation.model_dump() for citation in answer.citations],
        "used_papers": answer.used_papers,
        "followup_suggestions": answer.followup_suggestions,
        "compare_result": answer.compare_result,
        "filter_result": answer.filter_result,
        "answer_summary": answer.answer_summary,
        "tool_calls": tool_calls or [],
    }


def _build_trace_payload(
    mode: str,
    context_hint: str | None,
    follow_up_overrides: dict | None,
    tool_calls: list[dict] | None = None,
) -> dict:
    return {
        "mode": mode,
        "context_hint_present": bool(context_hint),
        "follow_up_overrides": follow_up_overrides or {},
        "tool_calls": tool_calls or [],
    }


def run_chat_message(
    user_id: str,
    query: str,
    session_id: str | None = None,
    top_k: int = 8,
    progress_callback: Callable[[dict], None] | None = None,
) -> ChatMessageResponse:
    _emit_progress(progress_callback, progress=0.02, stage="session_prepare", message="准备会话上下文")
    session = get_session(user_id, session_id) if session_id else None
    if not session:
        session = create_session(user_id=user_id, title=query[:80])
        session_id = session["id"]

    context_papers = _load_context_papers(user_id, session_id)
    context_hint, follow_up_overrides = _build_follow_up_context(user_id, query, session_id, context_papers)
    _emit_progress(progress_callback, progress=0.05, stage="context_ready", message="会话上下文已就绪", session_id=session_id)
    answer, mode, tool_calls = orchestrate_chat_turn(
        query=query,
        top_k=top_k,
        context_papers=context_papers,
        context_hint=context_hint,
        follow_up_overrides=follow_up_overrides,
        progress_callback=progress_callback,
    )
    assistant_payload = _build_assistant_payload(answer, mode, tool_calls)
    trace_payload = _build_trace_payload(mode, context_hint, follow_up_overrides, tool_calls)
    _emit_progress(progress_callback, progress=0.98, stage="session_persist", message="写入会话记录")

    append_message(
        session_id=session_id,
        role="user",
        content=query,
        structured_query=answer.structured_query.model_dump(),
    )
    append_message(
        session_id=session_id,
        role="assistant",
        content=answer.answer,
        structured_query=answer.structured_query.model_dump(),
        answer_json={
            **answer.model_dump(),
            "assistant": assistant_payload,
            "trace": trace_payload,
        },
    )
    touch_session(
        user_id=user_id,
        session_id=session_id,
        latest_query=query,
        latest_intent=answer.structured_query.intent,
        latest_answer=answer.answer,
    )
    _emit_progress(progress_callback, progress=1.0, stage="done", message="会话回答已完成", session_id=session_id)

    return ChatMessageResponse(
        session=get_session(user_id, session_id) or {"id": session_id},
        messages=list_messages(session_id, limit=20),
        answer=answer,
        assistant=assistant_payload,
        trace=trace_payload,
    )
