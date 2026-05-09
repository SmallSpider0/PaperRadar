from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from backend.chat_answer import (
    _call_gemini,
    _build_search_response_from_context,
    run_direct_chat_answer,
    run_grounded_chat_answer,
)
from backend.chat_models import ChatAnswerResponse, ChatSearchResponse, PaperToolResponse, RetrievalPaper, StructuredQuery
from backend.chat_parser import parse_query
from backend.chat_search import run_chat_search
from backend.chat_tools import compare_papers, filter_or_rerank_candidates

COMPARE_KEYWORDS = ["compare", "比较", "对比", "区别", "不同", "vs", "versus"]
EXPAND_KEYWORDS = ["expand", "扩大", "扩展", "更多", "更多论文", "再找", "继续找", "补充", "相关工作"]
REFINE_KEYWORDS = ["refine", "缩小", "进一步", "聚焦", "限定", "只看", "具体到", "细化"]
REFERENCE_KEYWORDS = ["这些论文", "上面这些", "它们", "其中", "上一轮", "刚才", "前面"]
NON_RETRIEVAL_INTENTS = {"chat", "meta", "help", "ask_clarification"}
MAX_TOOL_STEPS = 3


def _emit_progress(progress_callback: Callable[[dict], None] | None, **payload) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(payload)
    except Exception:
        return


def _contains_any(text: str, keywords: list[str]) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in keywords)


def derive_route_mode(
    query: str,
    structured_query: StructuredQuery,
    *,
    context_papers: list[dict] | None = None,
    follow_up_overrides: dict | None = None,
) -> str:
    if structured_query.intent in NON_RETRIEVAL_INTENTS:
        return structured_query.intent

    if follow_up_overrides and context_papers:
        if _contains_any(query, COMPARE_KEYWORDS):
            return "compare"
        if _contains_any(query, REFINE_KEYWORDS):
            return "refine"
        if _contains_any(query, EXPAND_KEYWORDS):
            return "expand"
        if _contains_any(query, REFERENCE_KEYWORDS):
            return "answer_from_context"

    if context_papers and _contains_any(query, REFERENCE_KEYWORDS):
        if structured_query.intent == "compare":
            return "compare"
        return "answer_from_context"

    if context_papers and structured_query.intent == "compare":
        return "compare"

    return structured_query.intent or "search"


def _summarize_tool_call(tool: str, summary: str, paper_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "tool": tool,
        "summary": summary,
        "paper_ids": list(paper_ids or []),
    }


def _safe_json_load(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    candidates = [raw]
    if "```json" in raw:
        start = raw.find("```json") + len("```json")
        end = raw.find("```", start)
        if end != -1:
            candidates.insert(0, raw[start:end].strip())
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.insert(0, raw[first_brace:last_brace + 1].strip())
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    raise json.JSONDecodeError("unable to parse planner json", raw, 0)


def _serialize_candidates(candidates: list[RetrievalPaper]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for paper in candidates[:8]:
        serialized.append(
            {
                "paper_id": paper.paper_id,
                "title": paper.title,
                "venue_code": paper.venue_code,
                "year": paper.year,
                "score": round(float(paper.score or 0.0), 4),
                "topic_tags": paper.topic_tags[:3],
            }
        )
    return serialized


def _build_search_response_from_results(
    query: str,
    structured_query: StructuredQuery,
    results: list[RetrievalPaper],
    *,
    tool_name: str,
    applied_filters: dict[str, Any] | None = None,
    retrieval_backend: str = "tool_result",
) -> ChatSearchResponse:
    return ChatSearchResponse(
        query=query,
        structured_query=structured_query,
        results=results,
        retrieval_summary={
            "intent_label": structured_query.intent,
            "applied_filters": applied_filters or {},
            "query_variants": [],
            "query_type": structured_query.query_type,
            "embedding_variant_limit": 0,
            "recall_limit": len(results),
            "result_count": len(results),
            "needs_fulltext": structured_query.needs_fulltext,
            "retrieval_backend": retrieval_backend,
        },
        paper_tool=PaperToolResponse(
            tool_name=tool_name,
            query_summary=structured_query.topic or query,
            applied_filters=applied_filters or {},
            results=results,
        ),
    )


def _build_planner_prompt(
    query: str,
    *,
    structured_query: StructuredQuery,
    heuristic_mode: str,
    step: int,
    tool_history: list[dict[str, Any]],
    context_hint: str | None = None,
    context_papers: list[dict] | None = None,
    current_candidates: list[RetrievalPaper] | None = None,
) -> str:
    schema = {
        "mode": "chat|meta|help|ask_clarification|search|qa|compare|summarize|refine|expand|answer_from_context",
        "tool": "none|search_papers|reuse_session_papers|compare_papers|filter_or_rerank_candidates",
        "tool_args": {
            "query": "string",
            "top_k": 8,
            "instruction": "string",
            "limit": 6,
            "paper_ids": ["string"],
            "candidate_ids": ["string"],
        },
        "needs_more_tools": False,
        "final_response": "direct|grounded",
        "reason": "string",
    }
    return f"""
你是 PaperRadar Chat 的工具规划器。你要决定本轮消息是否需要调用论文工具，以及下一步该调用什么工具。

只输出一个 JSON 对象，不要输出 markdown。

输出 schema:
{json.dumps(schema, ensure_ascii=False)}

规则:
- 问候、身份介绍、帮助说明、缺少上下文的“继续/然后呢”优先直接回答，不要查论文。
- 若用户引用“这些论文/上面这些/上一轮”且当前已有候选论文，优先 `reuse_session_papers` 或基于这些论文继续比较/筛选。
- `search_papers` 用于从库里找论文。
- `compare_papers` 仅在已有 paper_ids 时使用。
- `filter_or_rerank_candidates` 仅在已有 candidate_ids 时使用。
- 单步最多选择一个工具。
- 总体目标是像 ChatGPT 一样自然，但所有论文事实都要靠工具结果支撑。

当前 step: {step}/{MAX_TOOL_STEPS}
用户消息: {query}
heuristic_mode: {heuristic_mode}
structured_query: {json.dumps(structured_query.model_dump(), ensure_ascii=False)}
会话上下文提示: {context_hint or 'N/A'}
上一轮候选论文标题: {json.dumps([paper.get('title') for paper in (context_papers or [])[:6] if paper.get('title')], ensure_ascii=False)}
当前候选论文: {json.dumps(_serialize_candidates(current_candidates or []), ensure_ascii=False)}
已执行工具历史: {json.dumps(tool_history, ensure_ascii=False)}
""".strip()


def _normalize_planner_decision(
    payload: dict[str, Any],
    *,
    heuristic_mode: str,
    context_papers: list[dict] | None = None,
    current_candidates: list[RetrievalPaper] | None = None,
) -> dict[str, Any]:
    tool = str(payload.get("tool") or "none").strip()
    mode = str(payload.get("mode") or heuristic_mode).strip() or heuristic_mode
    final_response = str(payload.get("final_response") or ("direct" if mode in NON_RETRIEVAL_INTENTS else "grounded")).strip()
    tool_args = payload.get("tool_args") or {}
    if not isinstance(tool_args, dict):
        tool_args = {}
    decision = {
        "mode": mode,
        "tool": tool if tool in {"none", "search_papers", "reuse_session_papers", "compare_papers", "filter_or_rerank_candidates"} else "none",
        "tool_args": tool_args,
        "needs_more_tools": bool(payload.get("needs_more_tools")),
        "final_response": final_response if final_response in {"direct", "grounded"} else "grounded",
        "reason": str(payload.get("reason") or "").strip(),
    }
    if decision["tool"] == "compare_papers" and not (tool_args.get("paper_ids") or [paper.paper_id for paper in (current_candidates or []) if paper.paper_id]):
        decision["tool"] = "reuse_session_papers" if context_papers else "search_papers"
    if decision["tool"] == "filter_or_rerank_candidates" and not (tool_args.get("candidate_ids") or [paper.paper_id for paper in (current_candidates or []) if paper.paper_id]):
        decision["tool"] = "search_papers"
    return decision


def _heuristic_planner_decision(
    query: str,
    *,
    structured_query: StructuredQuery,
    heuristic_mode: str,
    context_papers: list[dict] | None = None,
    current_candidates: list[RetrievalPaper] | None = None,
) -> dict[str, Any]:
    candidate_ids = [paper.paper_id for paper in (current_candidates or []) if paper.paper_id]
    context_ids = [paper.get("paper_id") for paper in (context_papers or []) if paper.get("paper_id")]
    if heuristic_mode in NON_RETRIEVAL_INTENTS:
        return {
            "mode": heuristic_mode,
            "tool": "none",
            "tool_args": {},
            "needs_more_tools": False,
            "final_response": "direct",
            "reason": "non retrieval intent",
        }
    if heuristic_mode == "answer_from_context" and context_papers and not current_candidates:
        return {
            "mode": heuristic_mode,
            "tool": "reuse_session_papers",
            "tool_args": {},
            "needs_more_tools": False,
            "final_response": "grounded",
            "reason": "reuse session candidates",
        }
    if heuristic_mode == "compare":
        if candidate_ids:
            return {
                "mode": heuristic_mode,
                "tool": "compare_papers",
                "tool_args": {"paper_ids": candidate_ids[:6]},
                "needs_more_tools": False,
                "final_response": "grounded",
                "reason": "compare existing candidates",
            }
        if context_ids:
            return {
                "mode": heuristic_mode,
                "tool": "reuse_session_papers",
                "tool_args": {},
                "needs_more_tools": True,
                "final_response": "grounded",
                "reason": "need session candidates before compare",
            }
        return {
            "mode": heuristic_mode,
            "tool": "search_papers",
            "tool_args": {"query": query, "top_k": structured_query.top_k},
            "needs_more_tools": True,
            "final_response": "grounded",
            "reason": "search once before compare",
        }
    if heuristic_mode == "refine" and candidate_ids:
        return {
            "mode": heuristic_mode,
            "tool": "filter_or_rerank_candidates",
            "tool_args": {
                "candidate_ids": candidate_ids,
                "instruction": "prefer practical deployment papers",
                "limit": min(max(len(candidate_ids), 1), 6),
            },
            "needs_more_tools": False,
            "final_response": "grounded",
            "reason": "refine current candidates",
        }
    search_query = structured_query.topic or query
    return {
        "mode": heuristic_mode,
        "tool": "search_papers",
        "tool_args": {"query": search_query, "top_k": structured_query.top_k},
        "needs_more_tools": heuristic_mode in {"expand", "compare"},
        "final_response": "grounded",
        "reason": "search papers for grounded answer",
    }


def _plan_tool_step(
    query: str,
    *,
    structured_query: StructuredQuery,
    heuristic_mode: str,
    step: int,
    tool_history: list[dict[str, Any]],
    context_hint: str | None = None,
    context_papers: list[dict] | None = None,
    current_candidates: list[RetrievalPaper] | None = None,
) -> dict[str, Any]:
    heuristic_decision = _heuristic_planner_decision(
        query,
        structured_query=structured_query,
        heuristic_mode=heuristic_mode,
        context_papers=context_papers,
        current_candidates=current_candidates,
    )

    # 性能优先：默认使用启发式规划，避免每轮额外触发一次 LLM planner。
    # 仅在后续确实需要时再引入更重的 planner。
    return heuristic_decision


def orchestrate_chat_turn(
    query: str,
    *,
    top_k: int = 8,
    context_papers: list[dict] | None = None,
    context_hint: str | None = None,
    follow_up_overrides: dict | None = None,
    progress_callback: Callable[[dict], None] | None = None,
) -> tuple[ChatAnswerResponse, str, list[dict[str, Any]]]:
    _emit_progress(progress_callback, progress=0.08, stage="orchestrator_parse", message="分析消息意图")
    structured_query = parse_query(query, default_top_k=top_k)
    mode = derive_route_mode(
        query,
        structured_query,
        context_papers=context_papers,
        follow_up_overrides=follow_up_overrides,
    )
    _emit_progress(progress_callback, progress=0.12, stage="orchestrator_route", message="已确定消息路由", mode=mode)

    if mode in NON_RETRIEVAL_INTENTS:
        answer = run_direct_chat_answer(
            query=query,
            mode=mode,
            context_papers=context_papers,
            context_hint=context_hint,
            structured_query=structured_query,
            progress_callback=progress_callback,
        )
        return answer, mode, []

    tool_calls: list[dict[str, Any]] = []
    search_response: ChatSearchResponse | None = None
    current_candidates: list[RetrievalPaper] = []
    compare_result: dict[str, Any] | None = None
    filter_result: dict[str, Any] | None = None

    for step in range(1, MAX_TOOL_STEPS + 1):
        _emit_progress(progress_callback, progress=0.12 + 0.08 * step, stage="planner_step", message="规划下一步工具", mode=mode, planner_step=step)
        decision = _plan_tool_step(
            query,
            structured_query=structured_query,
            heuristic_mode=mode,
            step=step,
            tool_history=tool_calls,
            context_hint=context_hint,
            context_papers=context_papers,
            current_candidates=current_candidates,
        )
        mode = decision["mode"] or mode
        tool = decision["tool"]
        tool_args = decision["tool_args"]
        if tool == "none":
            if decision["final_response"] == "direct":
                answer = run_direct_chat_answer(
                    query=query,
                    mode=mode if mode in NON_RETRIEVAL_INTENTS else "chat",
                    context_papers=context_papers,
                    context_hint=context_hint,
                    structured_query=structured_query.model_copy(update={"intent": mode if mode in NON_RETRIEVAL_INTENTS else structured_query.intent}),
                    progress_callback=progress_callback,
                )
                return answer, mode, tool_calls
            break

        if tool == "reuse_session_papers" and context_papers:
            search_response = _build_search_response_from_context(query, structured_query, context_papers)
            current_candidates = list(search_response.results)
            paper_ids = [paper.paper_id for paper in current_candidates if paper.paper_id]
            tool_calls.append(
                {
                    **_summarize_tool_call("reuse_session_papers", f"reused {len(current_candidates)} session papers", paper_ids),
                    "args": {},
                    "result_count": len(current_candidates),
                    "planner_reason": decision.get("reason"),
                }
            )
        elif tool == "search_papers":
            def _search_progress(payload: dict) -> None:
                local_progress = float(payload.get("progress") or 0.0)
                overall_progress = 0.2 + 0.42 * max(0.0, min(local_progress, 1.0))
                _emit_progress(progress_callback, progress=overall_progress, **payload)

            search_response = run_chat_search(
                query=str(tool_args.get("query") or query),
                top_k=max(1, min(int(tool_args.get("top_k") or top_k), 20)),
                structured_query=structured_query,
                progress_callback=_search_progress,
            )
            current_candidates = list(search_response.results)
            paper_ids = [paper.paper_id for paper in current_candidates if paper.paper_id]
            tool_name = search_response.paper_tool.tool_name if search_response.paper_tool else "search_papers"
            tool_calls.append(
                {
                    **_summarize_tool_call(tool_name, f"retrieved {len(current_candidates)} papers for mode={mode}", paper_ids),
                    "args": {"query": str(tool_args.get("query") or query), "top_k": max(1, min(int(tool_args.get("top_k") or top_k), 20))},
                    "result_count": len(current_candidates),
                    "planner_reason": decision.get("reason"),
                }
            )
        elif tool == "compare_papers":
            paper_ids = [str(item) for item in (tool_args.get("paper_ids") or [paper.paper_id for paper in current_candidates if paper.paper_id]) if item]
            if paper_ids:
                compare_result = compare_papers(paper_ids[: min(len(paper_ids), 6)]).model_dump()
                tool_calls.append(
                    {
                        **_summarize_tool_call(
                            "compare_papers",
                            compare_result.get("summary") or f"compared {len(compare_result.get('rows') or [])} papers",
                            compare_result.get("paper_ids") or paper_ids,
                        ),
                        "args": {"paper_ids": paper_ids[: min(len(paper_ids), 6)]},
                        "result_count": len(compare_result.get("rows") or []),
                        "planner_reason": decision.get("reason"),
                    }
                )
        elif tool == "filter_or_rerank_candidates":
            candidate_ids = [str(item) for item in (tool_args.get("candidate_ids") or [paper.paper_id for paper in current_candidates if paper.paper_id]) if item]
            if candidate_ids:
                instruction = str(tool_args.get("instruction") or "prefer practical deployment papers")
                limit = min(max(int(tool_args.get("limit") or min(len(candidate_ids), 6) or 1), 1), 20)
                filter_result = filter_or_rerank_candidates(candidate_ids, instruction, limit=limit).model_dump()
                current_candidates = [RetrievalPaper.model_validate(item) for item in (filter_result.get("results") or [])]
                search_response = _build_search_response_from_results(
                    query,
                    structured_query,
                    current_candidates,
                    tool_name="filter_or_rerank_candidates",
                    applied_filters={"instruction": instruction, "limit": limit},
                )
                tool_calls.append(
                    {
                        **_summarize_tool_call(
                            "filter_or_rerank_candidates",
                            filter_result.get("summary") or f"reranked {len(current_candidates)} papers",
                            [paper.paper_id for paper in current_candidates if paper.paper_id],
                        ),
                        "args": {"candidate_ids": candidate_ids, "instruction": instruction, "limit": limit},
                        "result_count": len(current_candidates),
                        "planner_reason": decision.get("reason"),
                    }
                )

        if not decision.get("needs_more_tools"):
            break

    if search_response is None and context_papers:
        search_response = _build_search_response_from_context(query, structured_query, context_papers)
        current_candidates = list(search_response.results)

    answer = run_grounded_chat_answer(
        query=query,
        top_k=top_k,
        context_papers=context_papers,
        context_hint=context_hint,
        follow_up_overrides=follow_up_overrides,
        search_response=search_response,
        tool_calls=tool_calls,
        compare_result=compare_result,
        filter_result=filter_result,
        progress_callback=progress_callback,
    )

    return answer, mode, tool_calls
