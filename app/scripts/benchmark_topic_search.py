#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
import unicodedata

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.chat_search import run_chat_search
from backend.search import load_search_records
from backend.search_api import SearchRequest, build_search_session_payload
from backend.chat_parser import rules_parse_query
from backend.topic_profile_config import infer_prototype_bucket, match_runtime_profile

BENCHMARK_PATH = BASE_DIR.parent / "docs" / "topic-search-benchmark.json"
DEFAULT_MODES = ("direct", "chat")
RECALL_CUTOFFS = (10, 20, 50, 100)
GOLD_REQUIRED_TIERS = {"core", "required"}
EXPANDED_GOLD_TIERS = {"core", "required", "strong"}


def _normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    replacements = {
        "“": '"',
        "”": '"',
        "’": "'",
        "‘": "'",
        "–": "-",
        "—": "-",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return " ".join(value.strip().lower().split())


def load_benchmark_cases() -> tuple[list[dict], dict]:
    payload = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    cases = payload.get("cases") or []
    config = payload.get("config") or {}
    return (cases if isinstance(cases, list) else []), (config if isinstance(config, dict) else {})


def _build_corpus_index() -> tuple[dict[str, list[dict]], dict[str, dict]]:
    records = load_search_records(include_embeddings=False)
    by_title: dict[str, list[dict]] = defaultdict(list)
    by_id: dict[str, dict] = {}
    for record in records:
        paper_id = str(record.get("id") or "").strip()
        title_key = _normalize_text(record.get("title") or "")
        if title_key:
            by_title[title_key].append(record)
        if paper_id:
            by_id[paper_id] = record
    return dict(by_title), by_id


CORPUS_BY_TITLE, CORPUS_BY_ID = _build_corpus_index()


def _case_modes(case: dict) -> list[str]:
    raw = case.get("modes")
    if not isinstance(raw, list) or not raw:
        return list(DEFAULT_MODES)
    normalized = [str(item).strip().lower() for item in raw if str(item).strip()]
    deduped: list[str] = []
    for item in normalized:
        if item in DEFAULT_MODES and item not in deduped:
            deduped.append(item)
    return deduped or list(DEFAULT_MODES)


def _resolve_case_query(case: dict, mode: str) -> str:
    query_map = case.get("queries") or {}
    if isinstance(query_map, dict):
        mode_query = str(query_map.get(mode) or "").strip()
        if mode_query:
            return mode_query
    return str(case.get("query") or "").strip()


def _extract_results(mode: str, query: str, top_k: int) -> tuple[list[dict], dict, list[str]]:
    recall_depth = max(top_k, max(RECALL_CUTOFFS))
    if mode == "chat":
        response = run_chat_search(query=query, top_k=recall_depth)
        results = [item.model_dump() for item in response.results]
        topic_labels = [str(x).strip().lower() for x in (response.structured_query.topic_labels or [])]
        return results, response.retrieval_summary, topic_labels, response.structured_query.model_dump()

    session = build_search_session_payload(SearchRequest(query=query, limit=recall_depth, page=1))
    results = []
    for item in session.get("results") or []:
        record = item.get("record") or {}
        results.append(
            {
                "paper_id": record.get("id"),
                "title": record.get("title"),
                "abstract": record.get("abstract"),
                "authors_text": record.get("authors_text"),
                "venue_code": record.get("venue_code"),
                "year": record.get("year"),
                "paper_url": record.get("paper_url"),
                "source_pdf_url": record.get("source_pdf_url"),
                "content_policy": record.get("content_policy"),
                "score": float(item.get("score") or 0.0),
                "match_reasons": item.get("match_reasons") or [],
                "relevance": item.get("relevance"),
            }
        )
    structured_query = session.get("structured_query") or {}
    topic_labels = [str(x).strip().lower() for x in (structured_query.get("topic_labels") or [])]
    return results, session.get("retrieval_summary") or {}, topic_labels, structured_query


def _load_gold_papers(case: dict, field: str = "gold_papers") -> list[dict]:
    raw = case.get(field)
    papers: list[dict] = []
    if isinstance(raw, list) and raw:
        for item in raw:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            papers.append(
                {
                    "paper_id": str(item.get("paper_id") or "").strip() or None,
                    "title": title,
                    "title_normalized": _normalize_text(title),
                    "tier": str(item.get("tier") or "core").strip().lower(),
                    "notes": str(item.get("notes") or "").strip() or None,
                    "role": str(item.get("role") or "").strip() or None,
                }
            )
    if papers or field != "gold_papers":
        return papers
    legacy_titles = [str(x).strip() for x in case.get("must_have_titles", []) if str(x).strip()]
    return [
        {
            "paper_id": None,
            "title": title,
            "title_normalized": _normalize_text(title),
            "tier": "core",
            "notes": None,
            "role": None,
        }
        for title in legacy_titles
    ]


def _enrich_gold_papers(gold_papers: list[dict]) -> list[dict]:
    enriched: list[dict] = []
    for item in gold_papers:
        paper_id = item.get("paper_id")
        normalized_title = item.get("title_normalized") or ""
        corpus_record = None
        if paper_id and paper_id in CORPUS_BY_ID:
            corpus_record = CORPUS_BY_ID[paper_id]
        elif normalized_title and normalized_title in CORPUS_BY_TITLE:
            corpus_record = CORPUS_BY_TITLE[normalized_title][0]
        enriched.append(
            {
                **item,
                "present_in_corpus": bool(corpus_record),
                "resolved_paper_id": corpus_record.get("id") if corpus_record else paper_id,
                "corpus_title": corpus_record.get("title") if corpus_record else None,
            }
        )
    return enriched


def _gold_key(item: dict) -> str:
    return str(item.get("resolved_paper_id") or item.get("paper_id") or item.get("title_normalized") or "")


def _result_keys(results: list[dict]) -> set[str]:
    keys: set[str] = set()
    for item in results:
        paper_id = str(item.get("paper_id") or "").strip()
        if paper_id:
            keys.add(paper_id)
            continue
        title_key = _normalize_text(item.get("title") or "")
        if title_key:
            keys.add(title_key)
    return keys


def _gold_subset(gold_papers: list[dict], *, tiers: set[str], in_corpus_only: bool) -> list[dict]:
    selected = [item for item in gold_papers if str(item.get("tier") or "").lower() in tiers]
    if in_corpus_only:
        selected = [item for item in selected if item.get("present_in_corpus")]
    return selected


def _recall_at_gold(results: list[dict], gold_papers: list[dict], cutoff: int, *, tiers: set[str]) -> float | None:
    selected = _gold_subset(gold_papers, tiers=tiers, in_corpus_only=True)
    if not selected:
        return None
    top_keys = _result_keys(results[:cutoff])
    hits = sum(1 for item in selected if _gold_key(item) in top_keys)
    return hits / len(selected)


def _gold_hits(results: list[dict], gold_papers: list[dict]) -> list[dict]:
    result_keys = _result_keys(results)
    return [item for item in gold_papers if _gold_key(item) and _gold_key(item) in result_keys]


def _top10_gold_purity(results: list[dict], gold_papers: list[dict], cutoff: int = 10) -> float | None:
    top_keys = _result_keys(results[:cutoff])
    if not top_keys:
        return None
    gold_keys = {_gold_key(item) for item in gold_papers if item.get("present_in_corpus") and _gold_key(item)}
    if not gold_keys:
        return None
    return len([key for key in top_keys if key in gold_keys]) / len(top_keys)


def _canonical_purity_at_k(results: list[dict], canonical_gold_papers: list[dict], cutoff: int = 10) -> float | None:
    top_keys = _result_keys(results[:cutoff])
    if not top_keys:
        return None
    canonical_keys = {_gold_key(item) for item in canonical_gold_papers if item.get("present_in_corpus") and _gold_key(item)}
    if not canonical_keys:
        return None
    return len([key for key in top_keys if key in canonical_keys]) / len(top_keys)


def _prototype_role_coverage_at_k(
    results: list[dict],
    canonical_gold_papers: list[dict],
    cutoff: int = 10,
) -> float | None:
    """Fraction of distinct canonical `role` values represented in top-k (broad aggregate / prototype diagnostic)."""
    roles_defined = {
        str(item.get("role") or "").strip()
        for item in canonical_gold_papers
        if item.get("present_in_corpus") and _gold_key(item) and str(item.get("role") or "").strip()
    }
    if not roles_defined:
        return None
    top_keys = _result_keys(results[:cutoff])
    if not top_keys:
        return None
    roles_hit: set[str] = set()
    for item in canonical_gold_papers:
        role = str(item.get("role") or "").strip()
        if not role or not item.get("present_in_corpus"):
            continue
        if _gold_key(item) in top_keys:
            roles_hit.add(role)
    return len(roles_hit) / len(roles_defined)


def _case_family_id(case: dict) -> str:
    return str(case.get("family_id") or case.get("id") or "general").strip()


def _label_jaccard(a: list[str], b: list[str]) -> float:
    sa = {str(x).strip().lower() for x in a if str(x).strip()}
    sb = {str(x).strip().lower() for x in b if str(x).strip()}
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _variant_agreement_fraction_at_k(results: list[dict], cutoff: int = 10) -> float | None:
    top = results[:cutoff]
    if not top:
        return None
    multi = sum(
        1
        for item in top
        if int(((item.get("relevance") or {}).get("raw_signals") or {}).get("variant_hit_count") or 0) >= 2
    )
    return multi / len(top)


def _parser_divergence_vs_rules(
    query: str,
    top_k: int,
    *,
    predicted_topic_labels: list[str],
    predicted_query_type: str | None,
    predicted_profile_id: str | None,
) -> dict:
    """How far chat (or any) parser output is from deterministic rules_parse_query."""
    try:
        rule_sq = rules_parse_query(query, default_top_k=top_k)
    except Exception as exc:
        return {"error": str(exc)}
    r_labels = [str(x).strip().lower() for x in (rule_sq.topic_labels or []) if str(x).strip()]
    p_labels = [str(x).strip().lower() for x in predicted_topic_labels if str(x).strip()]
    return {
        "topic_label_jaccard_vs_rules": _label_jaccard(r_labels, p_labels),
        "query_type_match_vs_rules": (str(predicted_query_type or "").lower() == str(rule_sq.query_type or "").lower()),
        "profile_id_match_vs_rules": (str(predicted_profile_id or "") == str(rule_sq.profile_id or "")),
        "rules_topic_labels": r_labels,
        "rules_query_type": rule_sq.query_type,
        "rules_profile_id": rule_sq.profile_id,
    }


def _prototype_bucket_diagnostics(results: list[dict], predicted_topic_labels: list[str], query: str, cutoff: int = 10) -> dict | None:
    labels = [str(x).strip() for x in predicted_topic_labels if str(x).strip()]
    profile = match_runtime_profile(labels, query)
    if not profile or profile.strategy_type != "broad_aggregate" or not profile.prototype_clusters:
        return None
    buckets: list[str] = []
    for item in results[:cutoff]:
        pid = str(item.get("paper_id") or "").strip()
        corp = CORPUS_BY_ID.get(pid, {}) if pid else {}
        rec = {
            "title": item.get("title") or corp.get("title") or "",
            "abstract": item.get("abstract") or corp.get("abstract") or "",
            "topic_summary": corp.get("topic_summary") or "",
            "topic_tags": corp.get("topic_tags") or [],
        }
        buckets.append(infer_prototype_bucket(rec, profile))
    if not buckets:
        return None
    counts: dict[str, int] = defaultdict(int)
    for b in buckets:
        counts[b] += 1
    cluster_ids = [c.id for c in profile.prototype_clusters]
    covered = sum(1 for cid in cluster_ids if any(b == cid for b in buckets))
    max_share = max(counts.values()) / len(buckets)
    return {
        "topic_profile_id": profile.topic_id,
        "prototype_bucket_counts_top10": dict(counts),
        "prototype_cluster_coverage_ratio_top10": (covered / len(cluster_ids)) if cluster_ids else None,
        "prototype_overflow_ratio_top10": max_share,
    }


def _evaluate_mode(case: dict, mode: str) -> dict:
    query = _resolve_case_query(case, mode)
    top_k = int(case.get("top_k") or 10)
    recall_depth = max(top_k, max(RECALL_CUTOFFS))
    results, retrieval_summary, predicted_topic_labels, structured_payload = _extract_results(mode, query, top_k)
    gold_papers = _enrich_gold_papers(_load_gold_papers(case))
    canonical_gold_papers = _enrich_gold_papers(_load_gold_papers(case, field="canonical_gold_papers"))
    core_gold = _gold_subset(gold_papers, tiers=GOLD_REQUIRED_TIERS, in_corpus_only=True)
    core_gold_all = _gold_subset(gold_papers, tiers=GOLD_REQUIRED_TIERS, in_corpus_only=False)
    expanded_gold = _gold_subset(gold_papers, tiers=EXPANDED_GOLD_TIERS, in_corpus_only=True)
    expanded_gold_all = _gold_subset(gold_papers, tiers=EXPANDED_GOLD_TIERS, in_corpus_only=False)
    expected_topic_labels = [str(x).strip().lower() for x in case.get("expected_topic_labels", []) if str(x).strip()]
    matched_topic_labels = [label for label in expected_topic_labels if label in predicted_topic_labels]
    hit_gold = _gold_hits(results, gold_papers)
    missing_from_corpus = [item for item in gold_papers if not item.get("present_in_corpus")]
    present_but_not_returned = [item for item in gold_papers if item.get("present_in_corpus") and _gold_key(item) not in _result_keys(results)]
    core_recall_by_cutoff = {
        f"core_recall_at_{cutoff}": _recall_at_gold(results, gold_papers, cutoff, tiers=GOLD_REQUIRED_TIERS)
        for cutoff in RECALL_CUTOFFS
    }
    expanded_recall_by_cutoff = {
        f"expanded_recall_at_{cutoff}": _recall_at_gold(results, gold_papers, cutoff, tiers=EXPANDED_GOLD_TIERS)
        for cutoff in RECALL_CUTOFFS
    }
    variant_agreement_at_10 = _variant_agreement_fraction_at_k(results, 10)
    proto_diag = _prototype_bucket_diagnostics(results, predicted_topic_labels, query, 10)
    pred_qt = str(structured_payload.get("query_type") or "").strip().lower() or None
    pred_prof = str(structured_payload.get("profile_id") or "").strip() or None
    parser_div = _parser_divergence_vs_rules(
        query,
        recall_depth,
        predicted_topic_labels=predicted_topic_labels,
        predicted_query_type=pred_qt,
        predicted_profile_id=pred_prof,
    )
    return {
        "mode": mode,
        "query": query,
        "top_k": top_k,
        "expected_topic_labels": expected_topic_labels,
        "predicted_topic_labels": predicted_topic_labels,
        "matched_topic_labels": matched_topic_labels,
        "gold_papers": gold_papers,
        "canonical_gold_papers": canonical_gold_papers,
        "required_gold_count": len(core_gold),
        "expanded_gold_count": len(expanded_gold),
        "canonical_gold_count": len([item for item in canonical_gold_papers if item.get("present_in_corpus")]),
        "has_in_corpus_required_gold": bool(core_gold),
        "has_in_corpus_expanded_gold": bool(expanded_gold),
        "full_corpus_coverage": bool(gold_papers) and all(item.get("present_in_corpus") for item in core_gold_all),
        "full_expanded_corpus_coverage": bool(gold_papers) and all(item.get("present_in_corpus") for item in expanded_gold_all),
        "gold_hit_titles": [item.get("title") for item in hit_gold],
        "missing_from_corpus_titles": [item.get("title") for item in missing_from_corpus],
        "present_but_not_returned_titles": [item.get("title") for item in present_but_not_returned],
        "corpus_coverage": (len(core_gold) / len(core_gold_all)) if core_gold_all else None,
        "expanded_corpus_coverage": (len(expanded_gold) / len(expanded_gold_all)) if expanded_gold_all else None,
        "recall_at_k": core_recall_by_cutoff.get(f"core_recall_at_{top_k}"),
        "expanded_recall_at_k": expanded_recall_by_cutoff.get(f"expanded_recall_at_{top_k}"),
        "top10_topic_purity": _top10_gold_purity(results, gold_papers, cutoff=10),
        "top10_canonical_purity": _canonical_purity_at_k(results, canonical_gold_papers, cutoff=10),
        "prototype_role_coverage_at_10": _prototype_role_coverage_at_k(results, canonical_gold_papers, cutoff=10),
        "variant_agreement_at_10": variant_agreement_at_10,
        "parser_divergence_vs_rules": parser_div,
        "prototype_bucket_diagnostics_top10": proto_diag,
        "tier_breakdown": {
            "core": {
                "in_corpus_gold_count": len(core_gold),
                "total_gold_count": len(core_gold_all),
                "corpus_coverage": (len(core_gold) / len(core_gold_all)) if core_gold_all else None,
            },
            "expanded": {
                "in_corpus_gold_count": len(expanded_gold),
                "total_gold_count": len(expanded_gold_all),
                "corpus_coverage": (len(expanded_gold) / len(expanded_gold_all)) if expanded_gold_all else None,
            },
        },
        **core_recall_by_cutoff,
        **expanded_recall_by_cutoff,
        "retrieval_summary": retrieval_summary,
        "top_results": [
            {
                "rank": idx + 1,
                "title": item.get("title"),
                "venue_code": item.get("venue_code"),
                "year": item.get("year"),
                "score": item.get("score"),
                "match_reasons": item.get("match_reasons"),
                "variant_hit_count": int(
                    ((item.get("relevance") or {}).get("raw_signals") or {}).get("variant_hit_count") or 0
                ),
            }
            for idx, item in enumerate(results[:10])
        ],
    }


def _metric_gap(lhs: float | None, rhs: float | None) -> float | None:
    if lhs is None or rhs is None:
        return None
    return lhs - rhs


def evaluate_case(case: dict, selected_modes: set[str] | None = None) -> dict:
    modes = [mode for mode in _case_modes(case) if not selected_modes or mode in selected_modes]
    evaluations = [_evaluate_mode(case, mode) for mode in modes]
    by_mode = {item["mode"]: item for item in evaluations}
    comparison = {}
    if "direct" in by_mode and "chat" in by_mode:
        ch_div = by_mode["chat"].get("parser_divergence_vs_rules") or {}
        comparison = {
            "core_recall_at_10_gap": _metric_gap(by_mode["chat"].get("core_recall_at_10"), by_mode["direct"].get("core_recall_at_10")),
            "core_recall_at_20_gap": _metric_gap(by_mode["chat"].get("core_recall_at_20"), by_mode["direct"].get("core_recall_at_20")),
            "expanded_recall_at_10_gap": _metric_gap(by_mode["chat"].get("expanded_recall_at_10"), by_mode["direct"].get("expanded_recall_at_10")),
            "expanded_recall_at_20_gap": _metric_gap(by_mode["chat"].get("expanded_recall_at_20"), by_mode["direct"].get("expanded_recall_at_20")),
            "top10_topic_purity_gap": _metric_gap(by_mode["chat"].get("top10_topic_purity"), by_mode["direct"].get("top10_topic_purity")),
            "chat_topic_label_jaccard_vs_rules": ch_div.get("topic_label_jaccard_vs_rules"),
            "chat_query_type_match_vs_rules": ch_div.get("query_type_match_vs_rules"),
            "chat_profile_id_match_vs_rules": ch_div.get("profile_id_match_vs_rules"),
        }

    paraphrase_evaluations: list[dict] = []
    raw_pq = case.get("paraphrase_queries") or []
    if isinstance(raw_pq, list):
        for pq in raw_pq:
            if not isinstance(pq, dict):
                continue
            label = str(pq.get("label") or "").strip() or "paraphrase"
            qtext = str(pq.get("query") or "").strip()
            if not qtext:
                continue
            pmodes = [str(m).strip().lower() for m in (pq.get("modes") or []) if str(m).strip()]
            if not pmodes:
                pmodes = list(DEFAULT_MODES)
            pmodes = [m for m in pmodes if m in DEFAULT_MODES and (not selected_modes or m in selected_modes)]
            if not pmodes:
                continue
            pseudo = dict(case)
            pseudo["query"] = qtext
            pseudo["queries"] = {m: qtext for m in pmodes}
            for m in pmodes:
                row = _evaluate_mode(pseudo, m)
                row["paraphrase_label"] = label
                paraphrase_evaluations.append(row)

    return {
        "id": case.get("id"),
        "family_id": _case_family_id(case),
        "description": case.get("description"),
        "bucket": case.get("bucket") or "general",
        "modes": evaluations,
        "comparison": comparison,
        "paraphrase_evaluations": paraphrase_evaluations,
    }


def _safe_avg(values: list[float | None]) -> float | None:
    filtered = [value for value in values if value is not None]
    return (sum(filtered) / len(filtered)) if filtered else None


def _collect_mode_summary(cases: list[dict], mode: str) -> dict:
    mode_rows: list[dict] = []
    for case in cases:
        for item in case.get("modes") or []:
            if item.get("mode") == mode:
                mode_rows.append(item)
    core_recall_keys = [f"core_recall_at_{cutoff}" for cutoff in RECALL_CUTOFFS]
    expanded_recall_keys = [f"expanded_recall_at_{cutoff}" for cutoff in RECALL_CUTOFFS]
    summary: dict[str, object] = {
        "case_count": len(mode_rows),
        "topic_label_hit_cases": sum(1 for item in mode_rows if item.get("matched_topic_labels")),
        "cases_with_missing_gold_in_corpus": sum(1 for item in mode_rows if item.get("missing_from_corpus_titles")),
        "cases_with_any_in_corpus_required_gold": sum(1 for item in mode_rows if item.get("has_in_corpus_required_gold")),
        "cases_with_full_corpus_coverage": sum(1 for item in mode_rows if item.get("full_corpus_coverage")),
        "cases_with_any_in_corpus_expanded_gold": sum(1 for item in mode_rows if item.get("has_in_corpus_expanded_gold")),
        "cases_with_full_expanded_corpus_coverage": sum(1 for item in mode_rows if item.get("full_expanded_corpus_coverage")),
    }
    for key in core_recall_keys + expanded_recall_keys + [
        "top10_topic_purity",
        "top10_canonical_purity",
        "prototype_role_coverage_at_10",
        "variant_agreement_at_10",
        "corpus_coverage",
        "expanded_corpus_coverage",
    ]:
        values = [item.get(key) for item in mode_rows if item.get(key) is not None]
        summary[f"avg_{key}"] = (sum(values) / len(values)) if values else None
        summary[f"{key}_evaluable_case_count"] = len(values)
    buckets: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        for item in case.get("modes") or []:
            if item.get("mode") == mode:
                buckets[str(case.get("bucket") or "general")].append(item)
    summary["bucket_breakdown"] = {
        bucket: {
            "case_count": len(items),
            "avg_core_recall_at_10": _safe_avg([item.get("core_recall_at_10") for item in items]),
            "avg_core_recall_at_20": _safe_avg([item.get("core_recall_at_20") for item in items]),
            "avg_expanded_recall_at_10": _safe_avg([item.get("expanded_recall_at_10") for item in items]),
            "avg_expanded_recall_at_20": _safe_avg([item.get("expanded_recall_at_20") for item in items]),
            "avg_top10_topic_purity": _safe_avg([item.get("top10_topic_purity") for item in items]),
            "avg_top10_canonical_purity": _safe_avg([item.get("top10_canonical_purity") for item in items]),
            "avg_prototype_role_coverage_at_10": _safe_avg([item.get("prototype_role_coverage_at_10") for item in items]),
        }
        for bucket, items in sorted(buckets.items())
    }
    jacs = [
        (item.get("parser_divergence_vs_rules") or {}).get("topic_label_jaccard_vs_rules")
        for item in mode_rows
        if isinstance((item.get("parser_divergence_vs_rules") or {}).get("topic_label_jaccard_vs_rules"), (int, float))
    ]
    summary["avg_parser_topic_label_jaccard_vs_rules"] = (sum(jacs) / len(jacs)) if jacs else None
    summary["parser_topic_label_jaccard_vs_rules_evaluable_case_count"] = len(jacs)
    summary["runtime_profile_matched_case_count"] = sum(
        1
        for item in mode_rows
        if ((item.get("retrieval_summary") or {}).get("topic_profile_id"))
    )
    query_embedding_caches = [
        (item.get("retrieval_summary") or {}).get("query_embedding_cache") or {}
        for item in mode_rows
    ]
    summary["query_embedding_cache_hit_case_count"] = sum(1 for cache in query_embedding_caches if cache.get("cache_hit") or (cache.get("cache_hit_variants") or 0) > 0)
    summary["query_embedding_cache_miss_case_count"] = sum(1 for cache in query_embedding_caches if cache.get("cache_miss") or (cache.get("cache_miss_variants") or 0) > 0)
    summary["query_embedding_cache_write_case_count"] = sum(1 for cache in query_embedding_caches if cache.get("cache_write") or (cache.get("cache_write_variants") or 0) > 0)
    summary["query_embedding_cache_requests_total"] = sum(
        int(((cache.get("stats_delta") or {}).get("requests") or ((cache.get("stats_delta_total") or {}).get("requests") or 0)))
        for cache in query_embedding_caches
    )
    summary["query_embedding_cache_hits_total"] = sum(
        int(((cache.get("stats_delta") or {}).get("hits") or ((cache.get("stats_delta_total") or {}).get("hits") or 0)))
        for cache in query_embedding_caches
    )
    summary["query_embedding_cache_misses_total"] = sum(
        int(((cache.get("stats_delta") or {}).get("misses") or ((cache.get("stats_delta_total") or {}).get("misses") or 0)))
        for cache in query_embedding_caches
    )
    summary["query_embedding_cache_writes_total"] = sum(
        int(((cache.get("stats_delta") or {}).get("writes") or ((cache.get("stats_delta_total") or {}).get("writes") or 0)))
        for cache in query_embedding_caches
    )
    requests_total = int(summary["query_embedding_cache_requests_total"] or 0)
    hits_total = int(summary["query_embedding_cache_hits_total"] or 0)
    summary["query_embedding_cache_hit_rate"] = (hits_total / requests_total) if requests_total > 0 else None
    summary["query_embedding_cache_hit_rate_percent"] = (round((hits_total / requests_total) * 100, 2) if requests_total > 0 else None)
    cov = [
        item["prototype_bucket_diagnostics_top10"]["prototype_cluster_coverage_ratio_top10"]
        for item in mode_rows
        if isinstance(item.get("prototype_bucket_diagnostics_top10"), dict)
        and item["prototype_bucket_diagnostics_top10"].get("prototype_cluster_coverage_ratio_top10") is not None
    ]
    summary["avg_prototype_cluster_coverage_ratio_top10"] = (sum(cov) / len(cov)) if cov else None
    overflow = [
        item["prototype_bucket_diagnostics_top10"]["prototype_overflow_ratio_top10"]
        for item in mode_rows
        if isinstance(item.get("prototype_bucket_diagnostics_top10"), dict)
        and item["prototype_bucket_diagnostics_top10"].get("prototype_overflow_ratio_top10") is not None
    ]
    summary["avg_prototype_overflow_ratio_top10"] = (sum(overflow) / len(overflow)) if overflow else None
    return summary


def _collect_family_summary(evaluated: list[dict], mode: str) -> dict[str, dict[str, object]]:
    """Aggregate primary + paraphrase rows by family_id for cross-phrase stability."""
    by_family: dict[str, list[dict]] = defaultdict(list)
    for case in evaluated:
        fid = str(case.get("family_id") or case.get("id") or "").strip() or "general"
        for item in case.get("modes") or []:
            if item.get("mode") == mode:
                by_family[fid].append(item)
        for item in case.get("paraphrase_evaluations") or []:
            if item.get("mode") == mode:
                by_family[fid].append(item)

    out: dict[str, dict[str, object]] = {}
    for fid, rows in sorted(by_family.items()):
        recalls_10 = [float(r["core_recall_at_10"]) for r in rows if r.get("core_recall_at_10") is not None]
        out[fid] = {
            "row_count": len(rows),
            "avg_core_recall_at_10": _safe_avg([r.get("core_recall_at_10") for r in rows]),
            "min_core_recall_at_10": min(recalls_10) if recalls_10 else None,
            "max_core_recall_at_10": max(recalls_10) if recalls_10 else None,
            "stdev_core_recall_at_10": (
                (sum((x - sum(recalls_10) / len(recalls_10)) ** 2 for x in recalls_10) / len(recalls_10)) ** 0.5
                if len(recalls_10) > 1
                else None
            ),
            "avg_top10_canonical_purity": _safe_avg([r.get("top10_canonical_purity") for r in rows]),
            "avg_prototype_role_coverage_at_10": _safe_avg([r.get("prototype_role_coverage_at_10") for r in rows]),
            "topic_label_hit_rate": (
                sum(1 for r in rows if r.get("matched_topic_labels")) / len(rows) if rows else None
            ),
        }
    return out


def _filter_cases(cases: list[dict], case_ids: set[str] | None = None, buckets: set[str] | None = None) -> list[dict]:
    filtered: list[dict] = []
    for case in cases:
        case_id = str(case.get("id") or "").strip()
        bucket = str(case.get("bucket") or "general").strip()
        if case_ids and case_id not in case_ids:
            continue
        if buckets and bucket not in buckets:
            continue
        filtered.append(case)
    return filtered


def _parse_csv_set(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    out: set[str] = set()
    for raw in values:
        for item in str(raw).split(','):
            value = item.strip()
            if value:
                out.add(value)
    return out or None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark PaperRadar topic retrieval.")
    parser.add_argument("--mode", choices=["direct", "chat", "all"], default="all")
    parser.add_argument("--case", action="append", dest="cases", help="Case id, repeatable or comma-separated")
    parser.add_argument("--bucket", action="append", dest="buckets", help="Bucket name, repeatable or comma-separated")
    parser.add_argument("--summary-only", action="store_true", help="Print summary JSON only")
    parser.add_argument("--output", help="Write full JSON to file")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases, config = load_benchmark_cases()
    selected_modes = None if args.mode == "all" else {args.mode}
    filtered_cases = _filter_cases(cases, case_ids=_parse_csv_set(args.cases), buckets=_parse_csv_set(args.buckets))
    evaluated = [evaluate_case(case, selected_modes=selected_modes) for case in filtered_cases]
    modes_in_run = [mode for mode in DEFAULT_MODES if selected_modes is None or mode in selected_modes]
    summary = {
        "benchmark_version": config.get("version") or 2,
        "case_count": len(evaluated),
        "selected_mode": args.mode,
        "selected_cases": sorted(_parse_csv_set(args.cases) or []),
        "selected_buckets": sorted(_parse_csv_set(args.buckets) or []),
        "modes": {mode: _collect_mode_summary(evaluated, mode) for mode in modes_in_run},
        "families": {mode: _collect_family_summary(evaluated, mode) for mode in modes_in_run},
    }
    output = {"summary": summary, "cases": evaluated}
    if args.output:
        Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.summary_only:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
