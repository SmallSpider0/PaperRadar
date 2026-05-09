from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import time
from collections.abc import Callable
from typing import Any

from backend.chat_answer import _build_citations, _call_gemini, _merge_usage, _resolve_gemini_model, _truncate
from backend.chat_models import RetrievalPaper, StructuredQuery
from backend.config import settings
from backend.review_models import ReviewPreparedPayload, ReviewSummary
from backend.review_session_store import (
    create_review_session,
    delete_review_session,
    get_review_session,
    list_review_sessions,
    update_review_session,
)
from backend.search_api import SearchRequest, build_search_session_payload

REVIEW_DEFAULT_PREVIEW_LIMIT = max(5, min(int(os.getenv("PAPERRADAR_REVIEW_PREVIEW_LIMIT", "20")), 50))
REVIEW_DEFAULT_CANDIDATE_LIMIT = max(10, min(int(os.getenv("PAPERRADAR_REVIEW_CANDIDATE_LIMIT", "60")), 120))
REVIEW_BATCH_SIZE = max(2, min(int(os.getenv("PAPERRADAR_REVIEW_BATCH_SIZE", "4")), 8))
REVIEW_CONTEXT_ABSTRACT_CHARS = max(120, min(int(os.getenv("PAPERRADAR_REVIEW_ABSTRACT_CHARS", "260")), 600))
REVIEW_CITATION_LIMIT = max(5, min(int(os.getenv("PAPERRADAR_REVIEW_CITATION_LIMIT", "12")), 20))
REVIEW_FILTER_MAX_OUTPUT_TOKENS = max(800, int(os.getenv("PAPERRADAR_REVIEW_FILTER_MAX_OUTPUT_TOKENS", "4096")))
REVIEW_FILTER_RETRY_MAX_OUTPUT_TOKENS = max(REVIEW_FILTER_MAX_OUTPUT_TOKENS, int(os.getenv("PAPERRADAR_REVIEW_FILTER_RETRY_MAX_OUTPUT_TOKENS", "6144")))
REVIEW_SYNTHESIS_MAX_OUTPUT_TOKENS = max(3200, int(os.getenv("PAPERRADAR_REVIEW_SYNTHESIS_MAX_OUTPUT_TOKENS", "8192")))
REVIEW_FILTER_TIMEOUT_SECONDS = max(20.0, float(os.getenv("PAPERRADAR_REVIEW_FILTER_TIMEOUT_SECONDS", "60")))
REVIEW_SYNTHESIS_TIMEOUT_SECONDS = max(40.0, float(os.getenv("PAPERRADAR_REVIEW_SYNTHESIS_TIMEOUT_SECONDS", "150")))
REVIEW_SYNTHESIS_RETRY_LIMIT = max(1, min(int(os.getenv("PAPERRADAR_REVIEW_SYNTHESIS_RETRY_LIMIT", "3")), 5))
REVIEW_SYNTHESIS_RETRY_BACKOFF_SECONDS = max(1.0, min(float(os.getenv("PAPERRADAR_REVIEW_SYNTHESIS_RETRY_BACKOFF_SECONDS", "3.0")), 15.0))
REVIEW_SCORE_PREFILTER_TOP_RATIO = min(0.95, max(0.0, float(os.getenv("PAPERRADAR_REVIEW_SCORE_PREFILTER_TOP_RATIO", "0.55"))))
REVIEW_SCORE_PREFILTER_ABS = max(0.0, float(os.getenv("PAPERRADAR_REVIEW_SCORE_PREFILTER_ABS", "0.10")))
REVIEW_SCORE_PREFILTER_MIN_KEEP = max(4, min(int(os.getenv("PAPERRADAR_REVIEW_SCORE_PREFILTER_MIN_KEEP", "16")), 40))
REVIEW_SCORE_PREFILTER_MIN_RELATIVE_GAP = max(0.02, min(float(os.getenv("PAPERRADAR_REVIEW_SCORE_PREFILTER_MIN_RELATIVE_GAP", "0.18")), 0.9))
REVIEW_SCORE_PREFILTER_MIN_ABSOLUTE_GAP = max(0.01, min(float(os.getenv("PAPERRADAR_REVIEW_SCORE_PREFILTER_MIN_ABSOLUTE_GAP", "0.08")), 2.0))
REVIEW_FILTER_PARALLELISM = max(1, min(int(os.getenv("PAPERRADAR_REVIEW_FILTER_PARALLELISM", "16")), 16))


def _emit_progress(progress_callback: Callable[[dict], None] | None, **payload) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(payload)
    except Exception:
        return


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    candidates = [text]
    if "```json" in text:
        start = text.find("```json") + len("```json")
        end = text.find("```", start)
        if end != -1:
            candidates.insert(0, text[start:end].strip())
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.insert(0, text[first_brace:last_brace + 1].strip())
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("model did not return valid JSON object")


def _paper_from_search_row(row: dict[str, Any]) -> RetrievalPaper:
    record = row.get("record") or {}
    return RetrievalPaper(
        paper_id=record.get("id"),
        title=record.get("title") or "Untitled paper",
        abstract=record.get("abstract"),
        authors_text=record.get("authors_text"),
        venue_code=record.get("venue_code"),
        year=record.get("year"),
        paper_url=record.get("paper_url"),
        source_pdf_url=record.get("source_pdf_url"),
        content_policy=record.get("content_policy"),
        score=float(row.get("score") or 0.0),
        match_reasons=list(row.get("match_reasons") or []),
        relevance=row.get("relevance"),
    )


def _coarse_filter_candidates_by_score(
    candidates: list[RetrievalPaper],
    *,
    candidate_limit: int,
) -> tuple[list[RetrievalPaper], dict[str, Any]]:
    ranked = sorted(candidates, key=lambda item: (float(item.score or 0.0), item.year or 0), reverse=True)
    if not ranked:
        return [], {
            "raw_candidate_count": 0,
            "kept_candidate_count": 0,
            "threshold_score": None,
            "top_score": None,
            "min_keep": REVIEW_SCORE_PREFILTER_MIN_KEEP,
            "top_ratio": REVIEW_SCORE_PREFILTER_TOP_RATIO,
        }

    top_score = float(ranked[0].score or 0.0)
    min_keep = min(REVIEW_SCORE_PREFILTER_MIN_KEEP, len(ranked), max(1, int(candidate_limit)))
    best_gap_index: int | None = None
    best_gap_metric = -1.0
    best_gap_relative = None
    best_gap_absolute = None
    for index in range(max(0, min_keep - 1), min(len(ranked) - 1, max(1, int(candidate_limit)) - 1)):
        current_score = float(ranked[index].score or 0.0)
        next_score = float(ranked[index + 1].score or 0.0)
        absolute_gap = current_score - next_score
        if absolute_gap <= 0:
            continue
        denominator = max(abs(current_score), 1e-6)
        relative_gap = absolute_gap / denominator
        if relative_gap < REVIEW_SCORE_PREFILTER_MIN_RELATIVE_GAP and absolute_gap < REVIEW_SCORE_PREFILTER_MIN_ABSOLUTE_GAP:
            continue
        metric = relative_gap * 1000.0 + absolute_gap
        if metric > best_gap_metric:
            best_gap_metric = metric
            best_gap_index = index
            best_gap_relative = relative_gap
            best_gap_absolute = absolute_gap

    if best_gap_index is not None:
        keep_count = best_gap_index + 1
        threshold_score = float(ranked[keep_count - 1].score or 0.0)
        filter_mode = "distribution_gap"
        gap_summary = {
            "selected_gap_after_rank": keep_count,
            "selected_gap_relative": best_gap_relative,
            "selected_gap_absolute": best_gap_absolute,
        }
    else:
        threshold_score = max(REVIEW_SCORE_PREFILTER_ABS, top_score * REVIEW_SCORE_PREFILTER_TOP_RATIO) if top_score > 0 else REVIEW_SCORE_PREFILTER_ABS
        keep_count = len([item for item in ranked if float(item.score or 0.0) >= threshold_score])
        filter_mode = "threshold_fallback"
        gap_summary = {
            "selected_gap_after_rank": None,
            "selected_gap_relative": None,
            "selected_gap_absolute": None,
        }

    keep_count = max(min_keep, min(keep_count, max(1, int(candidate_limit))))
    filtered = ranked[:keep_count]
    return filtered, {
        "raw_candidate_count": len(ranked),
        "kept_candidate_count": len(filtered),
        "threshold_score": threshold_score,
        "top_score": top_score,
        "min_keep": REVIEW_SCORE_PREFILTER_MIN_KEEP,
        "top_ratio": REVIEW_SCORE_PREFILTER_TOP_RATIO,
        "filter_mode": filter_mode,
        "min_relative_gap": REVIEW_SCORE_PREFILTER_MIN_RELATIVE_GAP,
        "min_absolute_gap": REVIEW_SCORE_PREFILTER_MIN_ABSOLUTE_GAP,
        **gap_summary,
    }


def _build_confirmation_prompt(query: str, structured_query: StructuredQuery, candidate_count: int) -> str:
    topic = structured_query.topic or query
    venue_bits = list(structured_query.filters.venues or [])
    year_bits = []
    if structured_query.filters.year_from is not None or structured_query.filters.year_to is not None:
        year_bits.append(f"{structured_query.filters.year_from or '不限'}-{structured_query.filters.year_to or '不限'}")
    elif structured_query.filters.years:
        year_bits.append(",".join(str(item) for item in structured_query.filters.years))
    constraints = "；".join(bit for bit in [", ".join(venue_bits) if venue_bits else "", ", ".join(year_bits) if year_bits else ""] if bit)
    suffix = f"；附加约束：{constraints}" if constraints else ""
    return (
        f"我已按“{topic}”准备了 {candidate_count} 篇候选论文{suffix}。"
        "确认后我才会启动大模型综述，并先逐条判断每篇论文是否真正属于该主题，以尽可能完整地纳入相关工作。"
    )


def _session_summary(row: dict[str, Any], prepared_payload: dict[str, Any] | None = None, review_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    prepared_payload = prepared_payload or row.get("prepared_payload_json") or {}
    review_payload = review_payload or row.get("review_payload_json") or {}
    return {
        "id": row.get("id"),
        "title": row.get("title") or row.get("query") or row.get("id"),
        "query": row.get("query") or "",
        "status": row.get("status") or "prepared",
        "confirmed": bool(row.get("confirmed")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "candidate_count": len(prepared_payload.get("candidate_papers") or []),
        "preview_count": len(prepared_payload.get("preview_results") or []),
        "included_count": len(review_payload.get("included_papers") or []),
        "excluded_count": len(review_payload.get("excluded_papers") or []),
    }


def build_review_session_detail(row: dict[str, Any]) -> dict[str, Any]:
    prepared_payload = row.get("prepared_payload_json") or {}
    review_payload = row.get("review_payload_json") or {}
    prepared = ReviewPreparedPayload.model_validate(prepared_payload) if prepared_payload else None
    review = ReviewSummary.model_validate(review_payload) if review_payload else None
    return {
        "session": _session_summary(row, prepared_payload=prepared_payload, review_payload=review_payload),
        "prepared": prepared.model_dump() if prepared else None,
        "review": review.model_dump() if review else None,
    }


def list_review_session_details(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    return [_session_summary(row) for row in list_review_sessions(user_id, limit=limit)]


def get_review_session_detail(user_id: str, review_session_id: str) -> dict[str, Any] | None:
    row = get_review_session(user_id, review_session_id)
    return build_review_session_detail(row) if row else None


def delete_review_session_detail(user_id: str, review_session_id: str) -> bool:
    return delete_review_session(user_id, review_session_id)


def prepare_review_request(
    *,
    user_id: str,
    query: str,
    preview_limit: int = REVIEW_DEFAULT_PREVIEW_LIMIT,
    candidate_limit: int = REVIEW_DEFAULT_CANDIDATE_LIMIT,
    progress_callback: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    preview_limit = max(5, min(int(preview_limit or REVIEW_DEFAULT_PREVIEW_LIMIT), 50))
    candidate_limit = max(preview_limit, min(int(candidate_limit or REVIEW_DEFAULT_CANDIDATE_LIMIT), REVIEW_DEFAULT_CANDIDATE_LIMIT))
    _emit_progress(progress_callback, progress=0.04, stage="review_prepare", message="准备文献综述检索")
    request = SearchRequest(query=query, limit=preview_limit, page=1)

    def _search_progress(payload: dict) -> None:
        local_progress = float(payload.get("progress") or 0.0)
        overall_progress = 0.08 + 0.72 * max(0.0, min(local_progress, 1.0))
        _emit_progress(progress_callback, progress=overall_progress, **payload)

    search_session_payload = build_search_session_payload(request, progress_callback=_search_progress)
    structured_query = StructuredQuery.model_validate(search_session_payload.get("structured_query") or {"topic": query})
    raw_candidates = [_paper_from_search_row(row) for row in (search_session_payload.get("results") or [])[:candidate_limit]]
    all_candidates, coarse_filter_summary = _coarse_filter_candidates_by_score(raw_candidates, candidate_limit=candidate_limit)
    preview_results = all_candidates[:preview_limit]
    confirmation_prompt = _build_confirmation_prompt(query, structured_query, len(all_candidates))
    retrieval_summary = dict(search_session_payload.get("retrieval_summary") or {})
    retrieval_summary["review_score_prefilter"] = coarse_filter_summary
    prepared_payload = ReviewPreparedPayload(
        query=query,
        structured_query=structured_query.model_dump(),
        retrieval_summary=retrieval_summary,
        confirmation_prompt=confirmation_prompt,
        preview_limit=preview_limit,
        candidate_limit=candidate_limit,
        preview_results=preview_results,
        candidate_papers=all_candidates,
        search_session_payload=search_session_payload,
    ).model_dump()
    _emit_progress(progress_callback, progress=0.88, stage="review_session_create", message="保存待确认综述会话")
    row = create_review_session(
        user_id=user_id,
        query=query,
        status="prepared",
        confirmed=False,
        prepared_payload=prepared_payload,
        review_payload={},
    )
    _emit_progress(progress_callback, progress=1.0, stage="done", message="综述候选已准备完成", review_session_id=row.get("id"))
    return build_review_session_detail(row)


def _build_classification_prompt(query: str, papers: list[RetrievalPaper], *, abstract_char_limit: int = REVIEW_CONTEXT_ABSTRACT_CHARS) -> str:
    schema = {
        "decisions": [
            {
                "paper_id": "string",
                "decision": "include|exclude|uncertain",
                "reason": "string",
            }
        ]
    }
    paper_blocks = []
    for index, paper in enumerate(papers, start=1):
        paper_blocks.append(
            "\n".join(
                [
                    f"[Paper {index}]",
                    f"paper_id: {paper.paper_id or f'paper-{index}'}",
                    f"title: {paper.title}",
                    f"venue: {paper.venue_code or 'unknown'}",
                    f"year: {paper.year or 'unknown'}",
                    f"match_reasons: {'; '.join((paper.match_reasons or [])[:2]) or 'N/A'}",
                    f"abstract: {_truncate(paper.abstract, abstract_char_limit) or 'N/A'}",
                ]
            )
        )
    return f"""
你需要为一篇“中文文献综述”筛选候选论文。目标是尽量不要漏掉明显相关论文。

判断规则：
1. `include`：明显属于用户主题，应纳入综述。
2. `exclude`：明显偏题，不应纳入综述。
3. `uncertain`：可能相关但证据不够，理由简短说明。

输出必须是 JSON，对象结构如下：
{json.dumps(schema, ensure_ascii=False)}

额外要求：
- reason 用中文，控制在 25 字内。
- 宁可保守纳入，也不要轻易排除边界相关论文。
- 只根据给定标题、摘要和检索信号判断，不要补造事实。

用户主题：
{query}

候选论文：
{chr(10).join(paper_blocks)}
""".strip()


def _decision_map_covers_batch(batch: list[RetrievalPaper], decision_map: dict[str, dict[str, str]]) -> bool:
    if not batch:
        return False
    expected_ids = {str(paper.paper_id or paper.title).strip() for paper in batch if str(paper.paper_id or paper.title).strip()}
    if not expected_ids:
        return False
    return expected_ids.issubset(set(decision_map.keys()))


def _classify_batch_with_retry(query: str, batch: list[RetrievalPaper]) -> tuple[dict[str, dict[str, str]], dict[str, int], bool]:
    attempts = [
        {
            "abstract_char_limit": REVIEW_CONTEXT_ABSTRACT_CHARS,
            "max_output_tokens": REVIEW_FILTER_MAX_OUTPUT_TOKENS,
            "timeout_seconds": REVIEW_FILTER_TIMEOUT_SECONDS,
        },
        {
            "abstract_char_limit": max(100, REVIEW_CONTEXT_ABSTRACT_CHARS // 2),
            "max_output_tokens": REVIEW_FILTER_RETRY_MAX_OUTPUT_TOKENS,
            "timeout_seconds": REVIEW_FILTER_TIMEOUT_SECONDS + 20.0,
        },
    ]
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for attempt_index, attempt in enumerate(attempts):
        try:
            raw_text, finish_reason, usage = _call_gemini(
                _build_classification_prompt(query, batch, abstract_char_limit=int(attempt["abstract_char_limit"])),
                system_instruction="你是严格但偏召回优先的论文筛选助手。只输出 JSON。",
                max_output_tokens=int(attempt["max_output_tokens"]),
                response_mime_type="application/json",
                temperature=0.0,
                usage_source="review_filter",
                timeout_seconds=float(attempt["timeout_seconds"]),
                thinking_budget=0,
            )
            usage_total = _merge_usage(usage_total, usage)
            payload = _parse_json_object(raw_text)
            decision_map = {
                str(item.get("paper_id") or "").strip(): {
                    "decision": str(item.get("decision") or "uncertain").strip().lower(),
                    "reason": str(item.get("reason") or "").strip(),
                }
                for item in (payload.get("decisions") or [])
                if str(item.get("paper_id") or "").strip()
            }
            if finish_reason == "MAX_TOKENS" and not _decision_map_covers_batch(batch, decision_map) and attempt_index + 1 < len(attempts):
                continue
            if decision_map:
                return decision_map, usage_total, attempt_index > 0
        except Exception:
            continue
    return {}, usage_total, True


def _classify_candidates(
    query: str,
    papers: list[RetrievalPaper],
    *,
    progress_callback: Callable[[dict], None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int], dict[str, int]]:
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    stats = {"retried_batches": 0, "fallback_batches": 0}
    indexed_batches = [
        (batch_index, papers[start : start + REVIEW_BATCH_SIZE])
        for batch_index, start in enumerate(range(0, len(papers), REVIEW_BATCH_SIZE), start=1)
    ]
    total_batches = max(1, len(indexed_batches))
    max_workers = min(total_batches, REVIEW_FILTER_PARALLELISM)
    stats["total_batches"] = total_batches
    stats["parallel_batches"] = max_workers
    _emit_progress(
        progress_callback,
        progress=0.18,
        stage="review_filter_parallel_start",
        message=f"并行筛选候选论文 0/{total_batches}",
        completed_batches=0,
        total_batches=total_batches,
        parallel_batches=max_workers,
    )

    batch_results: dict[int, tuple[list[RetrievalPaper], dict[str, dict[str, str]], dict[str, int], bool]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_classify_batch_with_retry, query, batch): (batch_index, batch)
            for batch_index, batch in indexed_batches
        }
        completed = 0
        for future in as_completed(future_map):
            batch_index, batch = future_map[future]
            decision_map, batch_usage, retried = future.result()
            batch_results[batch_index] = (batch, decision_map, batch_usage, retried)
            usage_total = _merge_usage(usage_total, batch_usage)
            if retried:
                stats["retried_batches"] += 1
            if not decision_map:
                stats["fallback_batches"] += 1
            completed += 1
            _emit_progress(
                progress_callback,
                progress=0.18 + 0.34 * (completed / total_batches),
                stage="review_filter_batch",
                message=f"并行筛选候选论文 {completed}/{total_batches}",
                completed_batches=completed,
                total_batches=total_batches,
                parallel_batches=max_workers,
            )

    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for batch_index, _ in indexed_batches:
        batch, decision_map, _, _ = batch_results[batch_index]
        for paper in batch:
            paper_id = paper.paper_id or paper.title
            decision_payload = decision_map.get(paper_id) or {
                "decision": "uncertain",
                "reason": "模型筛选异常，保守纳入",
            }
            entry = {
                **paper.model_dump(),
                "decision": decision_payload["decision"],
                "decision_reason": decision_payload["reason"],
            }
            if decision_payload["decision"] == "exclude":
                excluded.append(entry)
            else:
                included.append(entry)
    return included, excluded, usage_total, stats


def _build_review_prompt(query: str, included_papers: list[dict[str, Any]], excluded_count: int) -> str:
    included_count = len(included_papers)
    if included_count >= 32:
        target_length_guidance = "目标篇幅约 5000-7000 字中文，接近 5 页及以上的中文综述深度。"
    elif included_count >= 20:
        target_length_guidance = "目标篇幅约 4000-6000 字中文，接近 4-5 页中文综述。"
    elif included_count >= 10:
        target_length_guidance = "目标篇幅约 3000-4500 字中文，至少达到 3-4 页中文综述。"
    else:
        target_length_guidance = "在保证不编造事实的前提下尽量写成完整长文，通常不少于 2000 字中文。"
    paper_blocks = []
    for index, paper in enumerate(included_papers, start=1):
        paper_blocks.append(
            "\n".join(
                [
                    f"[Included Paper {index}]",
                    f"paper_id: {paper.get('paper_id') or f'paper-{index}'}",
                    f"title: {paper.get('title') or 'Untitled'}",
                    f"venue: {paper.get('venue_code') or 'unknown'}",
                    f"year: {paper.get('year') or 'unknown'}",
                    f"include_reason: {paper.get('decision_reason') or '与主题相关'}",
                    f"abstract: {_truncate(paper.get('abstract'), REVIEW_CONTEXT_ABSTRACT_CHARS) or 'N/A'}",
                ]
            )
        )
    return f"""
你要写一篇尽可能完整的中文文献综述，只能基于给定纳入论文的信息，不要编造未提供的事实。

写作要求：
- 直接输出中文 Markdown，不要输出 JSON，不要输出代码块。
- 标题和术语可保留英文。
- {target_length_guidance}
- 默认按“约 5 页中文文档”的密度来写；如果纳入论文更多，可以更长；如果论文较少，也要尽量展开到一篇完整综述，而不是短摘要。
- 结构至少包含：`## 主题界定`、`## 分类框架`、`## 研究脉络`、`## 方法路线`、`## 类内比较`、`## 跨类别比较`、`## 代表性工作`、`## 共识与分歧`、`## 局限与空白`、`## 参考论文清单`。
- “参考论文清单”尽量覆盖全部纳入论文，至少按标题逐条列出。
- 明确说明这是一份基于检索候选与摘要级证据的综述。
- 尽量覆盖所有纳入论文，但可以按方法路线或子主题分组，不必逐篇平均展开。
- 如果纳入论文很多，优先保证结构完整和覆盖面，不要为了压缩篇幅省略关键脉络。
- `## 分类框架` 必须给出你用于组织论文的分类维度，并说明每一类包含哪些工作。
- `## 类内比较` 必须比较每个类别内部代表论文在问题设定、方法思路、适用场景、优缺点上的差异。
- `## 跨类别比较` 必须比较不同类别之间的路线差异、取舍关系和适用边界。
- 每个核心章节至少写成 2-4 个自然段，优先展开研究问题、方法路线、代表工作之间的承接关系，不要只列要点。
- 对代表性工作不能只点名，至少要概括其核心问题、方法特点、主要贡献或局限。
- 禁止把综述写成“按论文顺序逐篇翻译摘要”的形式；综述应以“主题 -> 分类 -> 比较 -> 归纳”为主线。

当前综述主题：
{query}

已纳入论文数：{len(included_papers)}
已排除论文数：{excluded_count}

纳入论文：
{chr(10).join(paper_blocks)}
""".strip()


def _extract_review_markdown(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if not text:
        return ""
    if "```markdown" in text:
        start = text.find("```markdown") + len("```markdown")
        end = text.find("```", start)
        if end != -1:
            return text[start:end].strip()
    if "```" in text:
        start = text.find("```") + len("```")
        end = text.find("```", start)
        if end != -1:
            extracted = text[start:end].strip()
            if extracted:
                return extracted
    return text


REVIEW_REQUIRED_SECTIONS = [
    "## 主题界定",
    "## 分类框架",
    "## 类内比较",
    "## 跨类别比较",
    "## 参考论文清单",
]


_REVIEW_SECTION_ALIASES = {
    "## 类内对比": "## 类内比较",
    "## 跨类别对比": "## 跨类别比较",
    "## 参考文献": "## 参考论文清单",
    "## 参考文献清单": "## 参考论文清单",
}


def _normalize_review_sections(review_markdown: str) -> str:
    text = (review_markdown or "").strip()
    if not text:
        return ""
    for alias, canonical in _REVIEW_SECTION_ALIASES.items():
        text = text.replace(alias, canonical)
    return text


def _has_required_review_sections(review_markdown: str) -> bool:
    text = _normalize_review_sections(review_markdown)
    return bool(text) and all(section in text for section in REVIEW_REQUIRED_SECTIONS)


def _repair_review_markdown_sections(review_markdown: str, query: str, included_papers: list[dict[str, Any]]) -> tuple[str, list[str]]:
    text = _normalize_review_sections(review_markdown)
    if not text:
        return "", []
    repair_notes: list[str] = []
    missing_sections = [section for section in REVIEW_REQUIRED_SECTIONS if section not in text]
    if not missing_sections:
        return text, repair_notes

    blocks: list[str] = [text.rstrip()]
    for section in missing_sections:
        if section == "## 主题界定":
            blocks.append(f"{section}\n当前主题为“{query}”。该节由系统自动补齐，请人工复核。")
        elif section == "## 分类框架":
            blocks.append(f"{section}\n该节由系统自动补齐：建议按任务子方向或方法路线分组。")
        elif section == "## 类内比较":
            blocks.append(f"{section}\n该节由系统自动补齐：请比较同类论文在问题设定、方法与优缺点上的差异。")
        elif section == "## 跨类别比较":
            blocks.append(f"{section}\n该节由系统自动补齐：请比较不同类别的取舍关系与适用边界。")
        elif section == "## 参考论文清单":
            lines = [section]
            for paper in included_papers:
                lines.append(f"- {paper.get('title')}")
            blocks.append("\n".join(lines))
        else:
            blocks.append(f"{section}\n该节由系统自动补齐，请人工复核。")
    repair_notes.append(f"模型输出缺少 {len(missing_sections)} 个必需章节，系统已自动补齐结构。")
    return "\n\n".join(blocks).strip(), repair_notes


def _synthesize_review_with_retry(prompt: str) -> tuple[str, str | None, dict[str, int], int]:
    return _synthesize_review_with_retry_with_progress(prompt, progress_callback=None)


def _synthesize_review_with_retry_with_progress(
    prompt: str,
    *,
    progress_callback: Callable[[dict], None] | None = None,
) -> tuple[str, str | None, dict[str, int], int]:
    last_exc: Exception | None = None
    total_attempts = REVIEW_SYNTHESIS_RETRY_LIMIT
    for attempt_index in range(REVIEW_SYNTHESIS_RETRY_LIMIT):
        attempt_no = attempt_index + 1
        _emit_progress(
            progress_callback,
            progress=min(0.82, 0.70 + 0.10 * (attempt_index / max(1, total_attempts))),
            stage="review_synthesis_attempt",
            message=f"生成中文综述（第 {attempt_no}/{total_attempts} 次）",
            attempt=attempt_no,
            max_attempts=total_attempts,
        )
        try:
            raw_text, finish_reason, usage = _call_gemini(
                prompt,
                system_instruction="你是 PaperRadar 的中文文献综述助手。必须严格基于提供的论文信息写综述，不要补造论文事实。",
                max_output_tokens=REVIEW_SYNTHESIS_MAX_OUTPUT_TOKENS,
                response_mime_type=None,
                temperature=0.1,
                usage_source="review_synthesis",
                timeout_seconds=REVIEW_SYNTHESIS_TIMEOUT_SECONDS,
            )
            return raw_text, finish_reason, usage, attempt_index
        except Exception as exc:
            last_exc = exc
            if attempt_index + 1 >= REVIEW_SYNTHESIS_RETRY_LIMIT:
                break
            _emit_progress(
                progress_callback,
                progress=min(0.86, 0.74 + 0.10 * (attempt_index / max(1, total_attempts))),
                stage="review_synthesis_retry_wait",
                message=f"综述模型调用异常，等待后重试（{attempt_no}/{total_attempts}）",
                attempt=attempt_no,
                max_attempts=total_attempts,
                error_type=type(exc).__name__,
            )
            time.sleep(REVIEW_SYNTHESIS_RETRY_BACKOFF_SECONDS * (attempt_index + 1))
    raise last_exc or RuntimeError("review synthesis failed")


def _fallback_review_markdown(query: str, included_papers: list[dict[str, Any]]) -> str:
    lines = [
        "## 主题界定",
        f"当前主题为“{query}”。以下内容为模型不可用时基于候选论文生成的保守综述骨架。",
        "",
        "## 分类框架",
        "当前无法稳定生成可靠的分类框架，请先根据下方论文清单人工按方法路线或任务子方向分组。",
        "",
        "## 研究脉络",
        "当前无法自动生成高质量归纳，请优先查看下方纳入论文清单。",
        "",
        "## 类内比较",
        "当前无法自动生成可靠的类内比较，请优先查看每类代表论文后再补充比较。",
        "",
        "## 跨类别比较",
        "当前无法自动生成可靠的跨类别比较，请优先根据方法路线和应用场景自行归纳。",
        "",
        "## 代表性工作",
    ]
    for paper in included_papers[:10]:
        lines.append(f"- {paper.get('title')}（{paper.get('venue_code') or 'unknown'} {paper.get('year') or 'unknown'}）")
    lines.extend(["", "## 参考论文清单"])
    for paper in included_papers:
        lines.append(f"- {paper.get('title')}")
    return "\n".join(lines).strip()


def generate_review_from_session(
    *,
    user_id: str,
    review_session_id: str,
    confirmed: bool = True,
    confirmed_paper_ids: list[str] | None = None,
    progress_callback: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("review generation requires explicit confirmation")
    row = get_review_session(user_id, review_session_id)
    if not row:
        raise ValueError("review session not found")
    prepared_payload = ReviewPreparedPayload.model_validate(row.get("prepared_payload_json") or {})
    candidate_papers = list(prepared_payload.candidate_papers)
    if confirmed_paper_ids:
        confirmed_set = set(confirmed_paper_ids)
        filtered = [paper for paper in candidate_papers if paper.paper_id in confirmed_set]
        if filtered:
            candidate_papers = filtered
    if not candidate_papers:
        raise ValueError("review session has no candidate papers")

    update_review_session(review_session_id, status="generating", confirmed=True)
    _emit_progress(progress_callback, progress=0.08, stage="review_confirmed", message="已确认主题，开始筛选纳入论文", review_session_id=review_session_id)

    included_papers, excluded_papers, filter_usage, filter_stats = _classify_candidates(
        prepared_payload.query,
        candidate_papers,
        progress_callback=progress_callback,
    )
    if not included_papers:
        included_papers = [
            {
                **paper.model_dump(),
                "decision": "uncertain",
                "decision_reason": "未获得可靠排除依据，保守纳入",
            }
            for paper in candidate_papers[: max(1, min(8, len(candidate_papers)))]
        ]

    _emit_progress(progress_callback, progress=0.66, stage="review_synthesis_prompt", message="准备中文综述提示词")
    synthesis_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    limitations: list[str] = []
    model_status = "ok"
    try:
        prompt = _build_review_prompt(prepared_payload.query, included_papers, len(excluded_papers))
        raw_text, finish_reason, synthesis_usage, synthesis_retry_count = _synthesize_review_with_retry_with_progress(
            prompt,
            progress_callback=progress_callback,
        )
        review_markdown = _extract_review_markdown(raw_text)
        if (not _has_required_review_sections(review_markdown)) and finish_reason != "MAX_TOKENS":
            _emit_progress(progress_callback, progress=0.88, stage="review_synthesis_structure_retry", message="综述结构未达标，尝试补生成")
            retry_text, retry_finish_reason, retry_usage = _call_gemini(
                prompt + "\n\n重要补充：上一次输出未满足综述结构要求。这一次必须明确写出“分类框架、类内比较、跨类别比较”三个模块，否则视为失败。",
                system_instruction="你是 PaperRadar 的中文文献综述助手。必须严格基于提供的论文信息写综述，不要补造论文事实。",
                max_output_tokens=REVIEW_SYNTHESIS_MAX_OUTPUT_TOKENS,
                response_mime_type=None,
                temperature=0.1,
                usage_source="review_synthesis",
                timeout_seconds=REVIEW_SYNTHESIS_TIMEOUT_SECONDS,
            )
            synthesis_usage = _merge_usage(synthesis_usage, retry_usage)
            finish_reason = retry_finish_reason or finish_reason
            review_markdown = _extract_review_markdown(retry_text)
        if synthesis_retry_count > 0:
            limitations.append(f"综述正文请求曾出现瞬时失败，已自动重试 {synthesis_retry_count} 次后成功。")
        if not review_markdown:
            raise ValueError("empty review markdown")
        review_markdown, repair_notes = _repair_review_markdown_sections(review_markdown, prepared_payload.query, included_papers)
        if repair_notes:
            limitations.extend(repair_notes)
            model_status = "ok_with_structure_repair"
        if not _has_required_review_sections(review_markdown):
            raise ValueError("review markdown missing required sections after repair")
        if finish_reason == "MAX_TOKENS":
            limitations.append("综述输出达到模型单次输出上限，结果可能在末尾被截断。")
    except Exception as exc:
        review_markdown = _fallback_review_markdown(prepared_payload.query, included_papers)
        limitations = ["模型综述生成失败，已回退为保守的纳入论文骨架。"]
        model_status = f"fallback:{type(exc).__name__}"
        _emit_progress(progress_callback, progress=0.84, stage="review_synthesis_fallback", message="模型异常，已回退到保守综述骨架")

    citation_source = [RetrievalPaper.model_validate(item) for item in included_papers[:REVIEW_CITATION_LIMIT]]
    citations = _build_citations(citation_source, [], prepared_payload.query)[:REVIEW_CITATION_LIMIT]
    if filter_stats["fallback_batches"] > 0:
        limitations.append(f"候选筛选中有 {filter_stats['fallback_batches']} 个分批未获得稳定判断，已按保守策略纳入。")
    answer_summary = {
        "model": _resolve_gemini_model(settings.gemini_model),
        "requested_model": settings.gemini_model,
        "model_status": model_status,
        "language": "zh-CN",
        "candidate_count": len(candidate_papers),
        "included_count": len(included_papers),
        "excluded_count": len(excluded_papers),
        "filter_total_batches": filter_stats["total_batches"],
        "filter_parallel_batches": filter_stats["parallel_batches"],
        "filter_retry_batches": filter_stats["retried_batches"],
        "filter_fallback_batches": filter_stats["fallback_batches"],
        "synthesis_retry_count": synthesis_retry_count if 'synthesis_retry_count' in locals() else 0,
        "filter_token_usage": filter_usage,
        "synthesis_token_usage": synthesis_usage,
        "token_usage": _merge_usage(filter_usage, synthesis_usage),
        "limitations": limitations,
    }
    review_payload = ReviewSummary(
        review_markdown=review_markdown,
        included_papers=included_papers,
        excluded_papers=excluded_papers,
        citations=citations,
        answer_summary=answer_summary,
    ).model_dump()
    row = update_review_session(
        review_session_id,
        status="completed",
        confirmed=True,
        review_payload=review_payload,
    )
    if not row:
        raise ValueError("failed to persist review session")
    _emit_progress(progress_callback, progress=1.0, stage="done", message="中文综述已生成完成", review_session_id=review_session_id)
    return build_review_session_detail(row)
