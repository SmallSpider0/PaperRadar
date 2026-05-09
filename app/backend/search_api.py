from __future__ import annotations

from collections.abc import Callable
import os

from pydantic import BaseModel

from backend.chat_parser import rules_parse_query
from backend.query_translation import normalize_query_for_retrieval
from backend.chat_search import run_chat_search
from backend.search import count_search_records
from backend.topic_profile_config import match_runtime_profile, profile_to_serializable_dict

SEARCH_SCORE_THRESHOLD = max(0.0, float(os.getenv("PAPERRADAR_SEARCH_SCORE_THRESHOLD", "0.0")))
DIRECT_SEARCH_RESULT_CAP = max(50, int(os.getenv("PAPERRADAR_DIRECT_SEARCH_RESULT_CAP", "200")))


class SearchRequest(BaseModel):
    query: str
    venue_codes: list[str] | None = None
    year_from: int | None = None
    year_to: int | None = None
    limit: int = 20
    page: int = 1


def _normalize_search_session_results(search_response: object) -> list[dict]:
    rows = []
    for item in search_response.results:
        rel = getattr(item, "relevance", None)
        rows.append(
            {
                "score": item.score,
                "record": {
                    "id": item.paper_id,
                    "title": item.title,
                    "abstract": item.abstract,
                    "authors_text": item.authors_text,
                    "paper_url": item.paper_url,
                    "source_pdf_url": item.source_pdf_url,
                    "content_policy": item.content_policy,
                    "venue_code": item.venue_code,
                    "year": item.year,
                },
                "match_reasons": item.match_reasons,
                "relevance": rel.model_dump() if rel is not None else None,
            }
        )
    return rows


def slice_search_session(
    session_payload: dict,
    page: int,
    limit: int,
    *,
    search_session_id: str | None = None,
) -> dict:
    page_number = max(int(page or 1), 1)
    page_size = max(int(limit or 20), 1)
    all_results = session_payload.get("results") or []
    total_count = int(session_payload.get("total_count") or len(all_results))
    total_pages = (total_count + page_size - 1) // page_size if total_count else 0
    start = (page_number - 1) * page_size
    end = start + page_size
    page_results = all_results[start:end]
    return {
        "query": session_payload.get("query", ""),
        "page": page_number,
        "limit": page_size,
        "count": len(page_results),
        "total_count": total_count,
        "total_pages": total_pages,
        "score_threshold": session_payload.get("score_threshold"),
        "results": page_results,
        "structured_query": session_payload.get("structured_query"),
        "retrieval_summary": session_payload.get("retrieval_summary"),
        "search_session_id": search_session_id,
    }


def build_search_session_payload(
    request: SearchRequest,
    progress_callback: Callable[[dict], None] | None = None,
) -> dict:
    page_size = max(int(request.limit or 20), 1)
    total_records = count_search_records()
    has_query = bool((request.query or "").strip())
    if has_query:
        top_k = min(total_records, max(page_size * 10, DIRECT_SEARCH_RESULT_CAP)) if total_records else max(page_size * 10, DIRECT_SEARCH_RESULT_CAP)
    else:
        top_k = total_records if total_records else page_size
    translation = normalize_query_for_retrieval(request.query) if has_query else None
    structured_query = rules_parse_query(request.query, default_top_k=top_k, translation=translation)
    if request.venue_codes:
        structured_query.filters.venues = list(dict.fromkeys(request.venue_codes))
    if request.year_from is not None:
        structured_query.filters.year_from = int(request.year_from)
    if request.year_to is not None:
        structured_query.filters.year_to = int(request.year_to)
    if not request.year_from and not request.year_to and structured_query.filters.years:
        if len(structured_query.filters.years) == 1:
            structured_query.filters.year_from = int(structured_query.filters.years[0])
            structured_query.filters.year_to = int(structured_query.filters.years[0])
        else:
            structured_query.filters.year_from = min(int(y) for y in structured_query.filters.years)
            structured_query.filters.year_to = max(int(y) for y in structured_query.filters.years)

    search_response = run_chat_search(
        query=request.query,
        top_k=top_k,
        structured_query=structured_query,
        progress_callback=progress_callback,
    )
    normalized_results_all = _normalize_search_session_results(search_response)
    filtered_out_by_threshold = 0
    if has_query:
        if SEARCH_SCORE_THRESHOLD > 0:
            normalized_results = [
                row for row in normalized_results_all
                if float(row.get("score") or 0.0) >= SEARCH_SCORE_THRESHOLD
            ]
            filtered_out_by_threshold = len(normalized_results_all) - len(normalized_results)
        else:
            normalized_results = normalized_results_all
        total_count = len(normalized_results)
    else:
        normalized_results = normalized_results_all
        total_count = total_records
    retrieval_summary = dict(search_response.retrieval_summary or {})
    matched_runtime_profile = match_runtime_profile(
        structured_query.topic_labels,
        structured_query.topic,
    )
    if matched_runtime_profile and retrieval_summary.get("topic_profile_id") is None:
        retrieval_summary["topic_profile_id"] = matched_runtime_profile.topic_id
    if matched_runtime_profile and retrieval_summary.get("runtime_profile") is None:
        retrieval_summary["runtime_profile"] = profile_to_serializable_dict(matched_runtime_profile)
    query_embedding_cache = dict(retrieval_summary.get("query_embedding_cache") or {})
    stats_delta = dict(query_embedding_cache.get("stats_delta") or query_embedding_cache.get("stats_delta_total") or {})
    requests_total = int(stats_delta.get("requests") or 0)
    hits_total = int(stats_delta.get("hits") or 0)
    misses_total = int(stats_delta.get("misses") or 0)
    writes_total = int(stats_delta.get("writes") or 0)
    hit_rate = (hits_total / requests_total) if requests_total > 0 else None
    query_embedding_cache["summary"] = {
        "requests_total": requests_total,
        "hits_total": hits_total,
        "misses_total": misses_total,
        "writes_total": writes_total,
        "hit_rate": hit_rate,
        "hit_rate_percent": (round(hit_rate * 100, 2) if hit_rate is not None else None),
    }
    retrieval_summary["query_embedding_cache"] = query_embedding_cache
    retrieval_summary.update(
        {
            "entrypoint": "direct_search",
            "requested_filters": {
                "venues": list(request.venue_codes or []),
                "year_from": request.year_from,
                "year_to": request.year_to,
            },
            "pre_threshold_count": len(normalized_results_all),
            "post_threshold_count": len(normalized_results),
            "filtered_out_by_threshold": filtered_out_by_threshold,
            "score_threshold": SEARCH_SCORE_THRESHOLD if has_query else None,
            "query_translation": (translation.model_dump() if translation is not None else None),
            "effective_query": (translation.normalized_query if translation is not None else request.query),
        }
    )
    return {
        "query": request.query,
        "default_limit": page_size,
        "total_count": total_count,
        "score_threshold": SEARCH_SCORE_THRESHOLD if has_query else None,
        "results": normalized_results,
        "structured_query": search_response.structured_query.model_dump(),
        "retrieval_summary": retrieval_summary,
    }


def build_search_job_payload(
    request: SearchRequest,
    progress_callback: Callable[[dict], None] | None = None,
) -> dict:
    session_payload = build_search_session_payload(request, progress_callback=progress_callback)
    page_payload = slice_search_session(
        session_payload,
        max(int(request.page or 1), 1),
        max(int(request.limit or 20), 1),
    )
    return {
        "page_payload": page_payload,
        "search_session_payload": session_payload,
    }


def build_search_response(
    request: SearchRequest,
    progress_callback: Callable[[dict], None] | None = None,
) -> dict:
    return build_search_job_payload(request, progress_callback=progress_callback)["page_payload"]
