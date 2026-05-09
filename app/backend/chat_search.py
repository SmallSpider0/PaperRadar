from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import os

from backend.chat_models import ChatSearchResponse, CitationAnchor, PaperToolResponse, RetrievalPaper, RetrievalRelevance
from backend.chat_parser import parse_query, rules_parse_query
from backend.search import count_search_records, pgvector_search_ready, search_metadata_with_summary
from backend.topic_profile_config import infer_prototype_bucket, match_runtime_profile, profile_to_serializable_dict


INTENT_LABELS = {
    "search": "智能检索",
    "qa": "论文问答",
    "compare": "多论文比较",
    "summarize": "主题归纳",
}
NON_RETRIEVAL_INTENTS = {"chat", "meta", "help", "ask_clarification"}


def _emit_progress(progress_callback: Callable[[dict], None] | None, **payload) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(payload)
    except Exception:
        return


def _merge_year_filters(structured_query) -> tuple[int | None, int | None]:
    year_from = structured_query.filters.year_from
    year_to = structured_query.filters.year_to

    if structured_query.filters.years:
        min_year = min(structured_query.filters.years)
        max_year = max(structured_query.filters.years)
        year_from = min_year if year_from is None else min(year_from, min_year)
        year_to = max_year if year_to is None else max(year_to, max_year)

    return year_from, year_to


def _build_match_reasons(structured_query, record: dict, debug: dict | None = None) -> list[str]:
    reasons: list[str] = []
    debug = debug or {}

    signal_parts: list[str] = []
    if debug.get("exact_phrase_hits"):
        signal_parts.append("短语精确")
    if debug.get("title_hits"):
        signal_parts.append("标题")
    if debug.get("abstract_hits"):
        signal_parts.append("摘要")
    if debug.get("cjk_hits"):
        signal_parts.append("中文片段")
    if debug.get("topic_hits"):
        signal_parts.append("主题画像")
    embedding_score = debug.get("embedding")
    if embedding_score is not None:
        signal_parts.append(f"语义:{float(embedding_score):.3f}")
    keyword_score = debug.get("keyword")
    if keyword_score is not None:
        signal_parts.append(f"词法:{float(keyword_score):.3f}")

    if structured_query.topic:
        reasons.append(f"主题匹配：{structured_query.topic}")
    if signal_parts:
        reasons.append("命中概览：" + " / ".join(signal_parts))
    if structured_query.query_type == "generic":
        reasons.append("泛词检索：语义匹配优先")
    if structured_query.topic_labels:
        reasons.append("主题扩展：" + " / ".join(structured_query.topic_labels[:3]))
    if structured_query.must_terms:
        reasons.append("覆盖核心术语：" + " / ".join(structured_query.must_terms[:2]))
    matched_must_count = int(debug.get("matched_must_count") or 0)
    if matched_must_count >= 2:
        reasons.append("同时命中多个核心术语")
    if structured_query.negative_terms:
        reasons.append("已尝试避开：" + " / ".join(structured_query.negative_terms[:2]))
    if record.get("venue_code"):
        reasons.append(f"会议：{record['venue_code']}")
    if record.get("year"):
        reasons.append(f"年份：{record['year']}")
    if structured_query.needs_fulltext:
        reasons.append("该问题可能后续需要全文证据")
    return reasons


def _result_merge_key(record: dict) -> str:
    return str(record.get("id") or record.get("paper_url") or record.get("title") or "")


def _merge_rows(row_groups: list[list[dict]], limit: int, structured_query=None) -> list[dict]:
    """Keep best per-paper score per variant, then rank with cross-variant agreement bonus."""
    agreement_bonus = max(0.0, float(os.getenv("PAPERRADAR_VARIANT_AGREEMENT_BONUS", "0.048")))
    agreement_cap = max(0.0, float(os.getenv("PAPERRADAR_VARIANT_AGREEMENT_CAP", "0.16")))

    best_by_key: dict[str, dict] = {}
    hit_counts: dict[str, int] = {}

    for rows in row_groups:
        seen_in_variant: set[str] = set()
        for item in rows:
            record = item.get("record") or {}
            key = _result_merge_key(record)
            if not key:
                continue
            if key not in seen_in_variant:
                seen_in_variant.add(key)
                hit_counts[key] = hit_counts.get(key, 0) + 1
            sc = float(item.get("score") or 0.0)
            if key not in best_by_key or sc > float(best_by_key[key].get("score") or 0.0):
                best_by_key[key] = item

    ranked: list[dict] = []
    for key, item in best_by_key.items():
        hits = hit_counts.get(key, 0)
        extra = min(agreement_cap, agreement_bonus * max(0, hits - 1))
        base = float(item.get("score") or 0.0)
        dbg = dict(item.get("debug") or {})
        dbg["variant_hit_count"] = hits
        dbg["variant_agreement_bonus"] = round(extra, 5)
        ranked.append(
            {
                **item,
                "score": base + extra,
                "debug": dbg,
            }
        )

    ranked.sort(key=lambda it: float(it.get("score") or 0.0), reverse=True)

    if structured_query and getattr(structured_query, "profile_id", None) == "ai-security" and ranked:
        runtime_profile = match_runtime_profile(
            topic_labels=list(getattr(structured_query, "topic_labels", []) or []),
            topic=getattr(structured_query, "topic", None),
        )
        family_caps_all = dict(getattr(getattr(runtime_profile, "candidate", None), "query_specific_family_head_caps", {}) or {}) if runtime_profile else {}
        if family_caps_all:
            from backend.search import _query_matched_prototype_terms

            matched = _query_matched_prototype_terms(
                str(getattr(structured_query, "topic", "") or ""),
                runtime_profile,
                extra_terms=list(getattr(structured_query, "topic_labels", []) or [])
                + list(getattr(structured_query, "must_terms", []) or [])
                + list(getattr(structured_query, "should_terms", []) or []),
            )
            family_caps: dict[str, int] = {}
            for bid in matched:
                caps = family_caps_all.get(bid)
                if isinstance(caps, dict):
                    family_caps = {str(k): int(v) for k, v in caps.items()}
                    break
            if family_caps:
                head = list(ranked[:limit])
                tail = list(ranked[limit:])
                bucket_counts: dict[str, int] = {}
                shaped: list[dict] = []
                deferred: list[dict] = []

                def _cap_for(bucket: str) -> int:
                    return max(0, int(family_caps.get(bucket, limit)))

                for item in head:
                    bucket = infer_prototype_bucket(item.get("record") or {}, runtime_profile)
                    count = bucket_counts.get(bucket, 0)
                    cap = _cap_for(bucket)
                    if count < cap:
                        shaped.append(item)
                        bucket_counts[bucket] = count + 1
                    else:
                        deferred.append(item)

                if deferred:
                    remaining_tail: list[dict] = []
                    for item in tail:
                        bucket = infer_prototype_bucket(item.get("record") or {}, runtime_profile)
                        count = bucket_counts.get(bucket, 0)
                        cap = _cap_for(bucket)
                        if len(shaped) < limit and count < cap:
                            shaped.append(item)
                            bucket_counts[bucket] = count + 1
                        else:
                            remaining_tail.append(item)
                    ranked = shaped + deferred + remaining_tail
                else:
                    ranked = shaped + tail

    if structured_query and structured_query.intent == "compare" and len(structured_query.must_terms) >= 2:
        balanced = sorted(
            ranked,
            key=lambda item: (
                int((item.get("debug") or {}).get("matched_must_count") or 0),
                float(item.get("score") or 0.0),
            ),
            reverse=True,
        )
        return balanced[:limit]

    return ranked[:limit]


def _prioritize_query_variants(
    topic: str,
    topic_labels: list[str],
    original_query: str,
    query_type: str,
) -> list[str]:
    """Prefer core topic + labels before long taxonomy-joined variants (reduces chat noise)."""
    from backend.chat_parser import build_query_variants

    out: list[str] = []
    seen: set[str] = set()

    def push(v: str) -> None:
        s = (v or "").strip()
        if not s:
            return
        k = s.lower()
        if k in seen:
            return
        seen.add(k)
        out.append(s)

    push(topic)
    for lab in topic_labels[:4]:
        push(lab)

    rule_variants = build_query_variants(topic, original_query, query_type=query_type)
    # De-prioritize very long space-joined expansions (often low precision for generic).
    short_first: list[str] = []
    long_tail: list[str] = []
    for rv in rule_variants:
        rvs = (rv or "").strip()
        if not rvs:
            continue
        if rvs.lower() in seen:
            continue
        if query_type == "generic" and rvs.count(" ") >= 6 and len(rvs) > 80:
            long_tail.append(rvs)
        else:
            short_first.append(rvs)
    for rv in short_first:
        push(rv)
    for rv in long_tail:
        push(rv)

    push(original_query.strip())
    return out


def _resolve_chat_variant_workers(variant_count: int) -> int:
    raw = (os.getenv("PAPERRADAR_CHAT_VARIANT_WORKERS", "") or "").strip()
    if raw:
        try:
            workers = max(1, int(raw))
        except ValueError:
            workers = min(4, max(1, variant_count))
    else:
        workers = min(4, max(1, variant_count))
    return min(workers, max(1, variant_count))


def _build_relevance_payload(debug: dict | None = None, match_reasons: list[str] | None = None, score: float = 0.0) -> RetrievalRelevance:
    debug = debug or {}
    return RetrievalRelevance(
        score=float(score or 0.0),
        why_matched=list(match_reasons or []),
        raw_signals={
            "exact_phrase_hits": debug.get("exact_phrase_hits") or [],
            "title_hits": debug.get("title_hits") or [],
            "abstract_hits": debug.get("abstract_hits") or [],
            "cjk_hits": debug.get("cjk_hits") or [],
            "topic_hits": debug.get("topic_hits") or [],
            "embedding": debug.get("embedding"),
            "keyword": debug.get("keyword"),
            "matched_must_count": debug.get("matched_must_count") or 0,
            "variant_hit_count": int(debug.get("variant_hit_count") or 0),
            "variant_agreement_bonus": debug.get("variant_agreement_bonus"),
        },
    )


def _build_citation_anchor(index: int, title: str, venue_code: str | None, year: int | None) -> CitationAnchor:
    suffix = " ".join(part for part in [venue_code or "", str(year) if year else ""] if part).strip()
    display_text = f"{title} ({suffix})" if suffix else title
    return CitationAnchor(label=f"P{index}", display_text=display_text)


def _run_search(
    query: str,
    top_k: int = 8,
    use_llm: bool = True,
    structured_query=None,
    progress_callback: Callable[[dict], None] | None = None,
) -> ChatSearchResponse:
    _emit_progress(progress_callback, progress=0.04, stage="parse_query", message="解析查询")
    structured_query = structured_query or (
        parse_query(query, default_top_k=top_k) if use_llm else rules_parse_query(query, default_top_k=top_k)
    )
    if structured_query.intent in NON_RETRIEVAL_INTENTS:
        structured_query = structured_query.model_copy(update={"intent": "search", "topic": structured_query.topic or query})
    # Respect caller-requested top_k (used by paginated /api/search).
    structured_query.top_k = max(1, int(top_k))
    _emit_progress(
        progress_callback,
        progress=0.12,
        stage="parse_query_done",
        message="已生成结构化查询",
        intent=structured_query.intent,
        query_type=structured_query.query_type,
    )
    year_from, year_to = _merge_year_filters(structured_query)
    seed_query = structured_query.translated_query or query
    query_variants = _prioritize_query_variants(
        structured_query.topic or "",
        [*structured_query.translation_canonical_topics, *structured_query.topic_labels],
        seed_query,
        structured_query.query_type,
    )
    if not query_variants:
        query_variants = [structured_query.topic or query]

    generic_variant_cap = max(2, min(int(os.getenv("PAPERRADAR_GENERIC_VARIANT_CAP", "4")), 8))
    specific_variant_cap = max(1, min(int(os.getenv("PAPERRADAR_SPECIFIC_VARIANT_CAP", "3")), 6))
    variant_max_chars = max(80, int(os.getenv("PAPERRADAR_GENERIC_VARIANT_MAX_CHARS", "220")))
    variant_cap = generic_variant_cap if structured_query.query_type == "generic" else specific_variant_cap

    compact_variants: list[str] = []
    seen_variants: set[str] = set()
    for item in query_variants:
        value = (item or "").strip()
        if not value:
            continue
        if len(value) > variant_max_chars:
            value = value[:variant_max_chars].rstrip()
        key = value.lower()
        if key in seen_variants:
            continue
        seen_variants.add(key)
        compact_variants.append(value)
        if len(compact_variants) >= variant_cap:
            break
    query_variants = compact_variants or [structured_query.topic or query]
    _emit_progress(
        progress_callback,
        progress=0.18,
        stage="query_variants",
        message=f"生成 {len(query_variants)} 个检索变体",
        query_variants=query_variants,
    )

    matched_runtime_profile = match_runtime_profile(structured_query.topic_labels, structured_query.topic)
    retrieval_profile = profile_to_serializable_dict(matched_runtime_profile)

    if structured_query.query_type == "generic":
        recall_limit = max(structured_query.top_k * 8, 48)
        recall_limit = max(recall_limit, max(structured_query.top_k * 10, 80))
    else:
        recall_limit = max(structured_query.top_k * 4, 24)
    max_recall_limit = max(40, int(os.getenv("PAPERRADAR_MAX_RECALL_LIMIT", "240")))
    recall_limit = min(recall_limit, max_recall_limit)
    _emit_progress(
        progress_callback,
        progress=0.22,
        stage="recall_plan",
        message=f"计划召回 {recall_limit} 条候选",
        recall_limit=recall_limit,
        max_recall_limit=max_recall_limit,
    )
    total_records = count_search_records()
    _emit_progress(
        progress_callback,
        progress=0.28,
        stage="records_ready",
        message=f"检索库当前共有 {total_records} 篇论文元数据",
        total_records=total_records,
        retrieval_backend="pgvector" if pgvector_search_ready() else "python_scan",
    )
    if structured_query.query_type == "generic":
        embedding_variant_limit = max(
            2,
            min(
                int(os.getenv("PAPERRADAR_EMBEDDING_VARIANT_LIMIT_GENERIC", "3")),
                len(query_variants),
            ),
        )
    else:
        embedding_variant_limit = max(
            1,
            min(int(os.getenv("PAPERRADAR_EMBEDDING_VARIANT_LIMIT_SPECIFIC", "2")), len(query_variants)),
        )
    search_start = 0.28
    search_span = 0.6
    row_groups_by_index: dict[int, list[dict]] = {}
    variant_summaries_by_index: dict[int, dict] = {}
    variant_workers = _resolve_chat_variant_workers(len(query_variants))
    variant_progress_map: dict[int, float] = {index: 0.0 for index in range(len(query_variants))}
    variant_stage_map: dict[int, str | None] = {index: None for index in range(len(query_variants))}
    variant_message_map: dict[int, str | None] = {index: None for index in range(len(query_variants))}
    variant_candidate_count_map: dict[int, int | None] = {index: None for index in range(len(query_variants))}
    variant_chunk_progress_map: dict[int, dict[str, int | None]] = {
        index: {"completed_chunks": None, "total_chunks": None} for index in range(len(query_variants))
    }
    completed_variants = 0
    progress_lock = Lock()

    def _emit_parallel_search_progress(*, current_index: int | None = None, force_stage: str | None = None, force_message: str | None = None) -> None:
        nonlocal completed_variants
        with progress_lock:
            aggregate_ratio = (
                sum(max(0.0, min(variant_progress_map.get(index, 0.0), 1.0)) for index in range(len(query_variants)))
                / max(1, len(query_variants))
            )
            overall_progress = min(0.9, search_start + search_span * aggregate_ratio)
            active_indexes = [index for index, value in variant_progress_map.items() if 0.0 < value < 1.0]
            waiting_indexes = [index for index, value in variant_progress_map.items() if value <= 0.0]
            running_variants = [query_variants[index] for index in active_indexes]
            latest_index = current_index
            if latest_index is None and active_indexes:
                latest_index = active_indexes[0]
            elif latest_index is None and waiting_indexes:
                latest_index = waiting_indexes[0]
            latest_variant = query_variants[latest_index] if latest_index is not None and 0 <= latest_index < len(query_variants) else None
            latest_stage = force_stage or (variant_stage_map.get(latest_index) if latest_index is not None else None)
            latest_message = force_message or (variant_message_map.get(latest_index) if latest_index is not None else None)
            latest_candidate_count = variant_candidate_count_map.get(latest_index) if latest_index is not None else None
            latest_chunk_progress = variant_chunk_progress_map.get(latest_index) if latest_index is not None else None
            status_message = force_message
            if not status_message:
                if completed_variants >= len(query_variants):
                    status_message = f"并行检索完成（{completed_variants}/{len(query_variants)}）"
                elif active_indexes:
                    status_message = f"正在并行检索（完成 {completed_variants}/{len(query_variants)}，运行中 {len(active_indexes)} 个）"
                else:
                    status_message = f"正在启动并行检索（0/{len(query_variants)}）"
            _emit_progress(
                progress_callback,
                progress=overall_progress,
                stage=force_stage or "search_parallel",
                message=status_message,
                variant=latest_variant,
                variant_index=(latest_index + 1) if latest_index is not None else None,
                variant_total=len(query_variants),
                variant_parallel_workers=variant_workers,
                active_variant_indexes=[index + 1 for index in active_indexes],
                active_variants=running_variants,
                completed_variants=completed_variants,
                search_stage=latest_stage,
                search_message=latest_message,
                candidate_count=latest_candidate_count,
                completed_chunks=(latest_chunk_progress or {}).get("completed_chunks"),
                total_chunks=(latest_chunk_progress or {}).get("total_chunks"),
            )

    def _run_variant(index: int, variant: str) -> tuple[int, list[dict], dict]:
        def _variant_progress(payload: dict, *, current_index: int = index, current_variant: str = variant) -> None:
            local_progress = max(0.0, min(float(payload.get("progress") or 0.0), 1.0))
            with progress_lock:
                variant_progress_map[current_index] = local_progress
                variant_stage_map[current_index] = payload.get("stage")
                variant_message_map[current_index] = payload.get("message")
                variant_candidate_count_map[current_index] = payload.get("candidate_count")
                variant_chunk_progress_map[current_index] = {
                    "completed_chunks": payload.get("completed_chunks"),
                    "total_chunks": payload.get("total_chunks"),
                }
            _emit_parallel_search_progress(current_index=current_index)

        rows, variant_summary = search_metadata_with_summary(
            query=(structured_query.translated_query if index == 0 and structured_query.translated_query else variant),
            venue_codes=structured_query.filters.venues or None,
            year_from=year_from,
            year_to=year_to,
            limit=recall_limit,
            must_terms=structured_query.must_terms,
            should_terms=structured_query.should_terms,
            negative_terms=structured_query.negative_terms,
            topic_labels=structured_query.topic_labels,
            use_embedding=index < embedding_variant_limit,
            query_type=structured_query.query_type,
            progress_callback=_variant_progress,
            retrieval_profile=retrieval_profile,
        )
        with progress_lock:
            variant_progress_map[index] = 1.0
            variant_stage_map[index] = "done"
            variant_message_map[index] = f"检索变体 {index + 1}/{len(query_variants)} 已完成"
            variant_candidate_count_map[index] = int(variant_summary.get("candidate_count") or len(rows) or 0)
            variant_chunk_progress_map[index] = {
                "completed_chunks": None,
                "total_chunks": None,
            }
        _emit_parallel_search_progress(current_index=index)
        return index, rows, {
            "variant": variant,
            "use_embedding": bool(index < embedding_variant_limit),
            **variant_summary,
        }

    if variant_workers <= 1 or len(query_variants) <= 1:
        for index, variant in enumerate(query_variants):
            idx, rows, variant_summary = _run_variant(index, variant)
            row_groups_by_index[idx] = rows
            variant_summaries_by_index[idx] = variant_summary
            with progress_lock:
                completed_variants += 1
            _emit_parallel_search_progress(current_index=idx)
    else:
        _emit_parallel_search_progress(
            force_stage="search_parallel",
            force_message=f"正在并行检索 {len(query_variants)} 个变体",
        )
        with ThreadPoolExecutor(max_workers=variant_workers) as executor:
            futures = [executor.submit(_run_variant, index, variant) for index, variant in enumerate(query_variants)]
            for future in as_completed(futures):
                idx, rows, variant_summary = future.result()
                row_groups_by_index[idx] = rows
                variant_summaries_by_index[idx] = variant_summary
                with progress_lock:
                    completed_variants += 1
                _emit_parallel_search_progress(current_index=idx)

    row_groups = [row_groups_by_index[index] for index in range(len(query_variants))]
    variant_summaries = [variant_summaries_by_index[index] for index in range(len(query_variants))]
    _emit_progress(progress_callback, progress=0.92, stage="merge", message="合并并重排结果")
    rows = _merge_rows(row_groups, structured_query.top_k, structured_query=structured_query)

    results = []
    for index, item in enumerate(rows, start=1):
        record = item["record"]
        debug = item.get("debug") or {}
        match_reasons = _build_match_reasons(structured_query, record, debug)
        topic_tags = list(record.get("topic_tags") or [])
        results.append(
            RetrievalPaper(
                paper_id=record.get("id"),
                title=record.get("title") or "",
                abstract=record.get("abstract"),
                authors_text=record.get("authors_text"),
                venue_code=record.get("venue_code"),
                year=record.get("year"),
                paper_url=record.get("paper_url"),
                source_pdf_url=record.get("source_pdf_url"),
                content_policy=record.get("content_policy"),
                score=float(item.get("score") or 0.0),
                match_reasons=match_reasons,
                topic_tags=topic_tags,
                topic_summary=record.get("topic_summary"),
                relevance=_build_relevance_payload(debug, match_reasons, float(item.get("score") or 0.0)),
                citation=_build_citation_anchor(index, record.get("title") or "", record.get("venue_code"), record.get("year")),
            )
        )

    retrieval_summary = {
        "retrieval_contract_version": 2,
        "entrypoint": "chat_search",
        "intent_label": INTENT_LABELS.get(structured_query.intent, structured_query.intent),
        "applied_filters": {
            "venues": structured_query.filters.venues,
            "years": structured_query.filters.years,
            "year_from": year_from,
            "year_to": year_to,
        },
        "query_variants": query_variants,
        "variant_parallel_workers": variant_workers,
        "query_type": structured_query.query_type,
        "profile_id": structured_query.profile_id,
        "topic_profile_id": matched_runtime_profile.topic_id if matched_runtime_profile else None,
        "runtime_profile": retrieval_profile,
        "query_scope": structured_query.query_scope,
        "risk_of_neighbor_drift": structured_query.risk_of_neighbor_drift,
        "embedding_variant_limit": embedding_variant_limit,
        "recall_limit": recall_limit,
        "max_recall_limit": max_recall_limit,
        "result_count": len(results),
        "needs_fulltext": structured_query.needs_fulltext,
        "retrieval_backend": "pgvector" if pgvector_search_ready() else "python_scan",
        "variants": variant_summaries,
        "query_embedding_cache": {
            "variant_count_with_embedding": sum(1 for item in variant_summaries if item.get("use_embedding")),
            "cache_hit_variants": sum(1 for item in variant_summaries if ((item.get("query_embedding_cache") or {}).get("cache_hit"))),
            "cache_miss_variants": sum(1 for item in variant_summaries if ((item.get("query_embedding_cache") or {}).get("cache_miss"))),
            "cache_write_variants": sum(1 for item in variant_summaries if ((item.get("query_embedding_cache") or {}).get("cache_write"))),
            "stats_delta_total": {
                "requests": sum(int((((item.get("query_embedding_cache") or {}).get("stats_delta") or {}).get("requests") or 0)) for item in variant_summaries),
                "hits": sum(int((((item.get("query_embedding_cache") or {}).get("stats_delta") or {}).get("hits") or 0)) for item in variant_summaries),
                "misses": sum(int((((item.get("query_embedding_cache") or {}).get("stats_delta") or {}).get("misses") or 0)) for item in variant_summaries),
                "writes": sum(int((((item.get("query_embedding_cache") or {}).get("stats_delta") or {}).get("writes") or 0)) for item in variant_summaries),
            },
            "summary": {
                "requests_total": sum(int((((item.get("query_embedding_cache") or {}).get("stats_delta") or {}).get("requests") or 0)) for item in variant_summaries),
                "hits_total": sum(int((((item.get("query_embedding_cache") or {}).get("stats_delta") or {}).get("hits") or 0)) for item in variant_summaries),
                "misses_total": sum(int((((item.get("query_embedding_cache") or {}).get("stats_delta") or {}).get("misses") or 0)) for item in variant_summaries),
                "writes_total": sum(int((((item.get("query_embedding_cache") or {}).get("stats_delta") or {}).get("writes") or 0)) for item in variant_summaries),
                "hit_rate": (
                    sum(int((((item.get("query_embedding_cache") or {}).get("stats_delta") or {}).get("hits") or 0)) for item in variant_summaries)
                    / sum(int((((item.get("query_embedding_cache") or {}).get("stats_delta") or {}).get("requests") or 0)) for item in variant_summaries)
                    if sum(int((((item.get("query_embedding_cache") or {}).get("stats_delta") or {}).get("requests") or 0)) for item in variant_summaries) > 0 else None
                ),
                "hit_rate_percent": (
                    round(
                        100 * sum(int((((item.get("query_embedding_cache") or {}).get("stats_delta") or {}).get("hits") or 0)) for item in variant_summaries)
                        / sum(int((((item.get("query_embedding_cache") or {}).get("stats_delta") or {}).get("requests") or 0)) for item in variant_summaries),
                        2,
                    )
                    if sum(int((((item.get("query_embedding_cache") or {}).get("stats_delta") or {}).get("requests") or 0)) for item in variant_summaries) > 0 else None
                ),
            },
        },
        "candidate_union_count": sum(int((item.get("candidate_generation") or {}).get("union_candidate_count") or 0) for item in variant_summaries),
        "route_counts": {
            "vector": sum(int(((item.get("candidate_generation") or {}).get("route_counts") or {}).get("vector") or 0) for item in variant_summaries),
            "lexical": sum(int(((item.get("candidate_generation") or {}).get("route_counts") or {}).get("lexical") or 0) for item in variant_summaries),
            "exact": sum(int(((item.get("candidate_generation") or {}).get("route_counts") or {}).get("exact") or 0) for item in variant_summaries),
            "topic": sum(int(((item.get("candidate_generation") or {}).get("route_counts") or {}).get("topic") or 0) for item in variant_summaries),
        },
        "reranker": next((item.get("rerank", {}).get("reranker") for item in variant_summaries if item.get("rerank")), "feature"),
        "fulltext_candidates_enabled": False,
        "citation_expansion_enabled": False,
    }
    _emit_progress(
        progress_callback,
        progress=1.0,
        stage="done",
        message=f"检索完成，返回 {len(results)} 条结果",
        result_count=len(results),
    )

    return ChatSearchResponse(
        query=query,
        structured_query=structured_query,
        results=results,
        retrieval_summary=retrieval_summary,
        paper_tool=PaperToolResponse(
            tool_name="search_papers",
            query_summary=structured_query.topic or query,
            applied_filters=retrieval_summary.get("applied_filters") or {},
            results=results,
        ),
    )


def run_chat_search(
    query: str,
    top_k: int = 8,
    structured_query=None,
    progress_callback: Callable[[dict], None] | None = None,
) -> ChatSearchResponse:
    try:
        return _run_search(query=query, top_k=top_k, use_llm=True, structured_query=structured_query, progress_callback=progress_callback)
    except Exception:
        return _run_search(query=query, top_k=top_k, use_llm=False, structured_query=structured_query, progress_callback=progress_callback)


def run_fast_search(
    query: str,
    top_k: int = 8,
    progress_callback: Callable[[dict], None] | None = None,
) -> ChatSearchResponse:
    return _run_search(query=query, top_k=top_k, use_llm=False, progress_callback=progress_callback)
