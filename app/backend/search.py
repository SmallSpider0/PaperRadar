from __future__ import annotations

import json
import math
import os
import traceback
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from backend.embedding import get_embedding_provider, get_query_embedding_cache_stats
from backend.pg_json_store import fetch_all, fetch_value
from backend.topic_profile_config import (
    infer_prototype_bucket,
    match_runtime_profile,
    profile_from_snapshot,
    profile_to_serializable_dict,
)
from backend.topic_taxonomy import expand_topics

WORD_RE = re.compile(r"[a-z0-9][a-z0-9_+.#/-]*", re.IGNORECASE)
CJK_RE = re.compile(r"[\u4e00-\u9fff]+")

EN_STOPWORDS = {
    "the", "a", "an", "of", "to", "for", "on", "in", "and", "or", "with", "about", "paper", "papers",
    "find", "search", "show", "list", "what", "which", "are", "is", "there", "any", "recent",
}

DOMAIN_SYNONYMS: dict[str, list[str]] = {
    "jailbreak": ["prompt injection", "guardrail bypass", "alignment attack"],
    "prompt injection": ["jailbreak", "indirect prompt injection"],
    "fuzzing": ["fuzzer", "fuzz testing", "coverage-guided fuzzing", "greybox fuzzing", "kernel fuzzing"],
    "fuzz": ["fuzzing", "fuzzer", "fuzz testing"],
    "browser": ["web", "extension", "website"],
    "fingerprinting": ["fingerprint", "browser fingerprinting", "device fingerprinting"],
    "watermark": ["watermarking"],
    "llm": ["large language model", "language model", "foundation model"],
    "large language model": ["llm"],
    "malware": ["trojan", "ransomware"],
    "phishing": ["credential theft"],
    "side channel": ["side-channel"],
    "federated learning": ["fl"],
    "privacy": ["private", "private learning"],
    "cryptography": ["cryptographic", "crypto", "proof system", "secure computation"],
    "crypto": ["cryptography", "cryptographic"],
    "homomorphic encryption": ["fhe", "fully homomorphic encryption", "encrypted computation"],
    "fhe": ["homomorphic encryption", "fully homomorphic encryption"],
    "zero-knowledge proofs": ["zero knowledge proof", "zkp", "zk-snark", "zk-stark"],
    "zkp": ["zero-knowledge proofs", "zero knowledge proof", "zk-snark", "zk-stark"],
    "secure multiparty computation": ["mpc", "multi-party computation", "private set intersection"],
    "mpc": ["secure multiparty computation", "multi-party computation"],
    "privacy-preserving computation": ["private computation", "privacy preserving computation", "private inference", "private training"],
    "private inference": ["privacy-preserving computation", "homomorphic encryption"],
    "llm safety": ["model safety", "jailbreak defense", "safety refusal", "refusal behavior"],
    "llm security": ["ai security", "prompt injection", "jailbreak"],
}

EMBEDDING_DIM = 3072
RECORDS_CACHE_TTL_SECONDS = max(10, int(os.getenv("PAPERRADAR_RECORDS_CACHE_TTL_SECONDS", "300")))
DEFAULT_VECTOR_MIN_CANDIDATES = max(32, int(os.getenv("PAPERRADAR_VECTOR_MIN_CANDIDATES", "120")))
DEFAULT_LEXICAL_MIN_CANDIDATES = max(24, int(os.getenv("PAPERRADAR_LEXICAL_MIN_CANDIDATES", "120")))
DEFAULT_TOPIC_MIN_CANDIDATES = max(16, int(os.getenv("PAPERRADAR_TOPIC_MIN_CANDIDATES", "80")))
DEFAULT_EXACT_MIN_CANDIDATES = max(12, int(os.getenv("PAPERRADAR_EXACT_MIN_CANDIDATES", "60")))
_records_cache_lock = threading.Lock()
_records_cache: dict[bool, dict[str, object]] = {
    False: {"loaded_at": 0.0, "records": []},
    True: {"loaded_at": 0.0, "records": []},
}
_record_count_cache: dict[str, float | int] = {"loaded_at": 0.0, "count": 0}
PGVECTOR_STATE_CACHE_TTL_SECONDS = max(10, int(os.getenv("PAPERRADAR_PGVECTOR_STATE_CACHE_TTL_SECONDS", "60")))
_pgvector_state_cache: dict[str, object] = {"checked_at": 0.0, "state": {}}


def _coerce_json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return []
        if isinstance(parsed, list):
            return parsed
    return []


def _row_to_record(row: dict, include_embeddings: bool = False) -> dict:
    record = {
        "id": row.get("id"),
        "title": row.get("title"),
        "abstract": row.get("abstract"),
        "authors_text": row.get("authors_text"),
        "paper_url": row.get("paper_url"),
        "source_pdf_url": row.get("source_pdf_url"),
        "source": row.get("source"),
        "content_policy": row.get("content_policy"),
        "year": row.get("year"),
        "venue_code": row.get("venue_code"),
        "topic_tags": _coerce_json_list(row.get("topic_tags")),
        "topic_summary": row.get("topic_summary") or "",
    }
    if include_embeddings:
        record["embedding"] = _coerce_json_list(row.get("embedding"))
    return record


def _build_record_filters(
    venue_codes: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    paper_ids: list[str] | None = None,
) -> tuple[list[str], list[object]]:
    where_clauses: list[str] = []
    params: list[object] = []
    if venue_codes:
        where_clauses.append("v.code = ANY(%s)")
        params.append(list(venue_codes))
    if year_from is not None:
        where_clauses.append("ve.year >= %s")
        params.append(int(year_from))
    if year_to is not None:
        where_clauses.append("ve.year <= %s")
        params.append(int(year_to))
    if paper_ids:
        where_clauses.append("p.id = ANY(%s)")
        params.append(list(paper_ids))
    return where_clauses, params


def _record_select_sql(include_embeddings: bool = False, extra_selects: list[str] | None = None) -> str:
    selects = [
        "p.id",
        "p.title",
        "p.abstract",
        "p.authors_text",
        "p.paper_url",
        "p.source_pdf_url",
        "p.source",
        "p.content_policy",
        "ve.year",
        "v.code AS venue_code",
        "tp.topic_tags",
        "tp.topic_summary",
    ]
    if include_embeddings:
        selects.append("e.embedding")
    if extra_selects:
        selects.extend(extra_selects)
    return """
    SELECT
      {selects}
    FROM papers p
    JOIN venue_editions ve ON ve.id = p.venue_edition_id
    JOIN venues v ON v.id = ve.venue_id
    LEFT JOIN paper_metadata_embeddings e ON e.paper_id = p.id
    LEFT JOIN paper_topic_profiles tp ON tp.paper_id = p.id
    """.format(selects=",\n      ".join(selects))


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.17g}" for value in values) + "]"


def _pgvector_state() -> dict[str, bool]:
    raw = os.getenv("PAPERRADAR_ENABLE_PGVECTOR", "1").strip().lower()
    if raw in {"0", "false", "off", "no"}:
        return {
            "ready": False,
            "has_vector_type": False,
            "has_halfvec_type": False,
            "has_embedding_vec": False,
            "halfvec_index_ready": False,
        }

    now = time.time()
    with _records_cache_lock:
        checked_at = float(_pgvector_state_cache.get("checked_at") or 0.0)
        if now - checked_at < PGVECTOR_STATE_CACHE_TTL_SECONDS:
            cached_state = _pgvector_state_cache.get("state")
            if isinstance(cached_state, dict):
                return dict(cached_state)

        try:
            row = fetch_all(
                """
                SELECT
                  EXISTS (
                    SELECT 1
                    FROM pg_type
                    WHERE typname = 'vector'
                  ) AS has_vector_type,
                  EXISTS (
                    SELECT 1
                    FROM pg_type
                    WHERE typname = 'halfvec'
                  ) AS has_halfvec_type,
                  EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'paper_metadata_embeddings'
                      AND column_name = 'embedding_vec'
                  ) AS has_embedding_vec,
                  EXISTS (
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'paper_metadata_embeddings'
                      AND indexname = 'idx_paper_metadata_embeddings_embedding_halfvec_hnsw'
                  ) AS halfvec_index_ready
                """
            )[0]
            state = {
                "has_vector_type": bool(row.get("has_vector_type")),
                "has_halfvec_type": bool(row.get("has_halfvec_type")),
                "has_embedding_vec": bool(row.get("has_embedding_vec")),
                "halfvec_index_ready": bool(row.get("halfvec_index_ready")),
            }
            state["ready"] = bool(state["has_vector_type"]) and bool(state["has_embedding_vec"])
        except Exception:
            state = {
                "ready": False,
                "has_vector_type": False,
                "has_halfvec_type": False,
                "has_embedding_vec": False,
                "halfvec_index_ready": False,
            }

        _pgvector_state_cache["checked_at"] = now
        _pgvector_state_cache["state"] = state
        return state


def pgvector_search_ready() -> bool:
    return bool(_pgvector_state().get("ready"))


def pgvector_halfvec_ready() -> bool:
    state = _pgvector_state()
    return bool(state.get("ready")) and bool(state.get("has_halfvec_type"))

def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return -1.0
    return dot / (norm_a * norm_b)


def _batch_embedding_cosine(query_embedding: list[float], records: list[dict]) -> list[float | None]:
    """与 records 对齐的批量余弦相似度；语义与逐条 cosine_similarity + 原分支一致。"""
    n = len(records)
    if not query_embedding:
        return [None] * n
    dim = len(query_embedding)
    q = np.asarray(query_embedding, dtype=np.float32)
    norm_q = float(np.linalg.norm(q))
    out: list[float | None] = [None] * n
    if norm_q == 0:
        for i, r in enumerate(records):
            emb = r.get("embedding")
            if not isinstance(emb, list):
                out[i] = None
            else:
                out[i] = -1.0
        return out

    valid_indices: list[int] = []
    rows: list[list[float]] = []
    for i, r in enumerate(records):
        emb = r.get("embedding")
        if not isinstance(emb, list):
            out[i] = None
        elif len(emb) != dim or not emb:
            out[i] = -1.0
        else:
            valid_indices.append(i)
            rows.append(emb)

    if not rows:
        return out

    x = np.asarray(rows, dtype=np.float32)
    dots = x @ q
    norms_x = np.linalg.norm(x, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        cos = dots / (norms_x * norm_q)
    cos = np.nan_to_num(cos, nan=-1.0, posinf=-1.0, neginf=-1.0)

    for j, idx in enumerate(valid_indices):
        val = float(cos[j])
        if norms_x[j] == 0:
            out[idx] = -1.0
        else:
            out[idx] = val
    return out


def _build_scored_results(
    query: str,
    records: list[dict],
    embedding_scores: list[float | None],
    topic_labels: list[str] | None,
    query_type: str,
    must_terms: list[str] | None,
    should_terms: list[str] | None,
    negative_terms: list[str] | None,
    retrieval_profile: dict | None = None,
    matched_query_prototypes: list[str] | None = None,
) -> list[dict]:
    scored: list[dict] = []
    primary_topic = str((topic_labels or [""])[0] or "").strip().lower()
    profile_obj = profile_from_snapshot(retrieval_profile) if retrieval_profile else None
    for record, embedding_score in zip(records, embedding_scores):
        if primary_topic and not record.get("_primary_topic"):
            record["_primary_topic"] = primary_topic
        keyword, details = keyword_score(
            query,
            record,
            topic_labels=topic_labels,
            query_type=query_type,
            topic_profile=profile_obj,
            extra_terms=[*(must_terms or []), *(should_terms or []), *(topic_labels or [])],
        )
        score, rerank_debug = _rerank_score(
            keyword,
            embedding_score,
            record,
            details,
            must_terms=must_terms,
            should_terms=should_terms,
            negative_terms=negative_terms,
            topic_labels=topic_labels,
            query_type=query_type,
            topic_profile=profile_obj,
        )
        scored.append(
            {
                "score": score,
                "matched_query_prototypes": list(matched_query_prototypes or []),
                "record": record,
                "debug": {
                    "keyword": round(keyword, 4),
                    "embedding": round(embedding_score, 4) if embedding_score is not None else None,
                    **details,
                    **rerank_debug,
                },
            }
        )
    return scored


def _score_metadata_chunk(
    args: tuple,
) -> list[dict]:
    """子进程内对一段 records 打分（需为顶层函数以便 pickle）。"""
    if len(args) == 10:
        query, records, embedding_scores, topic_labels, query_type, must_terms, should_terms, negative_terms, retrieval_profile, matched_query_prototypes = args
    elif len(args) == 9:
        query, records, embedding_scores, topic_labels, query_type, must_terms, should_terms, negative_terms, retrieval_profile = args
        matched_query_prototypes = None
    else:
        query, records, embedding_scores, topic_labels, query_type, must_terms, should_terms, negative_terms = args
        retrieval_profile = None
        matched_query_prototypes = None
    return _build_scored_results(
        query,
        records,
        embedding_scores,
        topic_labels,
        query_type,
        must_terms,
        should_terms,
        negative_terms,
        retrieval_profile=retrieval_profile,
        matched_query_prototypes=matched_query_prototypes,
    )


def load_normalized_metadata() -> list[dict]:
    generated_dir = Path(__file__).resolve().parents[2] / "data" / "generated"
    records: list[dict] = []
    for path in generated_dir.glob("*_normalized.json"):
        records.extend(json.loads(path.read_text(encoding="utf-8")))
    return records


def load_records_from_postgres(
    *,
    include_embeddings: bool = False,
    venue_codes: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    paper_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    where_clauses, params = _build_record_filters(
        venue_codes=venue_codes,
        year_from=year_from,
        year_to=year_to,
        paper_ids=paper_ids,
    )
    sql = _record_select_sql(include_embeddings=include_embeddings)
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += "\n ORDER BY ve.year DESC NULLS LAST, p.title ASC"
    if limit is not None:
        sql += "\n LIMIT %s"
        params.append(int(limit))
    rows = fetch_all(sql, params)
    return [_row_to_record(row, include_embeddings=include_embeddings) for row in rows]


def load_vector_candidates_from_postgres(
    query_embedding: list[float],
    *,
    venue_codes: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 120,
) -> list[dict]:
    where_clauses, params = _build_record_filters(
        venue_codes=venue_codes,
        year_from=year_from,
        year_to=year_to,
    )
    where_clauses.append("e.embedding_vec IS NOT NULL")
    vector_literal = _vector_literal(query_embedding)
    if pgvector_halfvec_ready():
        score_expr = f"(1 - ((e.embedding_vec::halfvec({EMBEDDING_DIM})) <=> (%s::halfvec({EMBEDDING_DIM}))))"
        order_expr = f"(e.embedding_vec::halfvec({EMBEDDING_DIM})) <=> (%s::halfvec({EMBEDDING_DIM}))"
    else:
        score_expr = "(1 - (e.embedding_vec <=> (%s::vector)))"
        order_expr = "e.embedding_vec <=> (%s::vector)"
    sql = _record_select_sql(
        include_embeddings=False,
        extra_selects=[f"{score_expr} AS embedding_score"],
    )
    params = [vector_literal, *params]
    sql = sql.replace("LEFT JOIN paper_metadata_embeddings e", "JOIN paper_metadata_embeddings e")
    sql += "\n WHERE " + " AND ".join(where_clauses)
    sql += f"\n ORDER BY {order_expr}"
    params.append(vector_literal)
    sql += "\n LIMIT %s"
    params.append(max(1, int(limit)))
    rows = fetch_all(sql, params)
    records: list[dict] = []
    for row in rows:
        record = _row_to_record(row, include_embeddings=False)
        record["_embedding_score"] = float(row.get("embedding_score") or -1.0)
        records.append(record)
    return records


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _dedupe_terms(terms: list[str], *, min_len: int = 2, limit: int = 16) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        value = _normalize_text(term)
        if len(value) < min_len or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
        if len(deduped) >= limit:
            break
    return deduped


def _build_route_terms(
    query: str,
    *,
    topic_labels: list[str] | None = None,
    query_type: str = "specific",
    must_terms: list[str] | None = None,
    should_terms: list[str] | None = None,
    extra_terms: list[str] | None = None,
    topic_profile=None,
) -> dict[str, list[str] | str]:
    profile = _build_query_profile(
        query, topic_labels=topic_labels, query_type=query_type, topic_profile=topic_profile, extra_terms=extra_terms
    )
    english_terms = _dedupe_terms(
        [
            *profile["expanded_tokens"],
            *(must_terms or []),
            *(should_terms or []),
        ],
        min_len=2,
        limit=18,
    )
    exact_terms = _dedupe_terms(
        [
            *(must_terms or []),
            *profile["phrases"],
            *profile["cjk_terms"],
            *(should_terms or []),
        ],
        min_len=2,
        limit=10,
    )
    topic_terms = _dedupe_terms(
        [
            *(topic_labels or []),
            *profile["topic_expansions"],
        ],
        min_len=2,
        limit=14,
    )
    tsquery_text = " ".join(english_terms[:12]).strip()
    return {
        "tsquery_text": tsquery_text,
        "english_terms": english_terms,
        "exact_terms": exact_terms,
        "topic_terms": topic_terms,
        "phrases": profile["phrases"],
    }


def load_lexical_candidates_from_postgres(
    query: str,
    *,
    topic_labels: list[str] | None = None,
    query_type: str = "specific",
    must_terms: list[str] | None = None,
    should_terms: list[str] | None = None,
    venue_codes: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 120,
    topic_profile=None,
) -> list[dict]:
    route_terms = _build_route_terms(
        query,
        topic_labels=topic_labels,
        query_type=query_type,
        must_terms=must_terms,
        should_terms=should_terms,
        topic_profile=topic_profile,
    )
    tsquery_text = str(route_terms.get("tsquery_text") or "").strip()
    exact_terms = list(route_terms.get("exact_terms") or [])
    if not tsquery_text and not exact_terms:
        return []

    title_vec = "to_tsvector('simple', coalesce(p.title, ''))"
    abstract_vec = "to_tsvector('simple', coalesce(p.abstract, ''))"
    authors_vec = "to_tsvector('simple', coalesce(p.authors_text, ''))"
    where_clauses, filter_params = _build_record_filters(
        venue_codes=venue_codes,
        year_from=year_from,
        year_to=year_to,
    )
    rank_parts: list[str] = []
    rank_params: list[object] = []
    match_parts: list[str] = []
    match_params: list[object] = []

    if tsquery_text:
        rank_parts.extend(
            [
                f"(ts_rank_cd({title_vec}, plainto_tsquery('simple', %s)) * 2.2)",
                f"(ts_rank_cd({abstract_vec}, plainto_tsquery('simple', %s)) * 1.15)",
                f"(ts_rank_cd({authors_vec}, plainto_tsquery('simple', %s)) * 0.45)",
            ]
        )
        rank_params.extend([tsquery_text, tsquery_text, tsquery_text])
        match_parts.append(
            f"({title_vec} @@ plainto_tsquery('simple', %s) OR {abstract_vec} @@ plainto_tsquery('simple', %s) OR {authors_vec} @@ plainto_tsquery('simple', %s))"
        )
        match_params.extend([tsquery_text, tsquery_text, tsquery_text])

    for term in exact_terms[:6]:
        pattern = f"%{_escape_like(term)}%"
        rank_parts.append(
            "(CASE WHEN lower(coalesce(p.title, '')) LIKE %s ESCAPE '\\' THEN 1.5 "
            "WHEN lower(coalesce(p.abstract, '')) LIKE %s ESCAPE '\\' THEN 0.95 "
            "WHEN lower(coalesce(p.authors_text, '')) LIKE %s ESCAPE '\\' THEN 0.4 ELSE 0 END)"
        )
        rank_params.extend([pattern, pattern, pattern])
        match_parts.append(
            "(lower(coalesce(p.title, '')) LIKE %s ESCAPE '\\' OR "
            "lower(coalesce(p.abstract, '')) LIKE %s ESCAPE '\\' OR "
            "lower(coalesce(p.authors_text, '')) LIKE %s ESCAPE '\\')"
        )
        match_params.extend([pattern, pattern, pattern])

    score_expr = " + ".join(rank_parts) if rank_parts else "0.0"
    sql = _record_select_sql(include_embeddings=False, extra_selects=[f"({score_expr}) AS lexical_score"])
    if match_parts:
        where_clauses.append("(" + " OR ".join(match_parts) + ")")
    sql += "\n WHERE " + " AND ".join(where_clauses)
    sql += "\n ORDER BY lexical_score DESC, ve.year DESC NULLS LAST, p.title ASC"
    sql += "\n LIMIT %s"
    params = [*rank_params, *filter_params, *match_params, max(1, int(limit))]
    rows = fetch_all(sql, params)
    records: list[dict] = []
    for row in rows:
        record = _row_to_record(row, include_embeddings=False)
        record["_lexical_score"] = float(row.get("lexical_score") or 0.0)
        records.append(record)
    return records


def load_topic_candidates_from_postgres(
    query: str,
    *,
    topic_labels: list[str] | None = None,
    query_type: str = "specific",
    venue_codes: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 80,
    topic_profile=None,
) -> list[dict]:
    route_terms = _build_route_terms(
        query, topic_labels=topic_labels, query_type=query_type, topic_profile=topic_profile
    )
    topic_terms = list(route_terms.get("topic_terms") or [])
    if not topic_terms:
        return []

    where_clauses, filter_params = _build_record_filters(
        venue_codes=venue_codes,
        year_from=year_from,
        year_to=year_to,
    )
    rank_parts: list[str] = []
    rank_params: list[object] = []
    match_parts: list[str] = []
    match_params: list[object] = []
    for term in topic_terms[:8]:
        pattern = f"%{_escape_like(term)}%"
        rank_parts.append(
            "(CASE WHEN lower(coalesce(tp.topic_summary, '')) LIKE %s ESCAPE '\\' THEN 1.2 ELSE 0 END + "
            "CASE WHEN lower(coalesce(tp.topic_tags::text, '')) LIKE %s ESCAPE '\\' THEN 1.55 ELSE 0 END)"
        )
        rank_params.extend([pattern, pattern])
        match_parts.append(
            "(lower(coalesce(tp.topic_summary, '')) LIKE %s ESCAPE '\\' OR "
            "lower(coalesce(tp.topic_tags::text, '')) LIKE %s ESCAPE '\\')"
        )
        match_params.extend([pattern, pattern])

    score_expr = " + ".join(rank_parts) if rank_parts else "0.0"
    sql = _record_select_sql(include_embeddings=False, extra_selects=[f"({score_expr}) AS topic_route_score"])
    where_clauses.append("(" + " OR ".join(match_parts) + ")")
    sql += "\n WHERE " + " AND ".join(where_clauses)
    sql += "\n ORDER BY topic_route_score DESC, ve.year DESC NULLS LAST, p.title ASC"
    sql += "\n LIMIT %s"
    params = [*rank_params, *filter_params, *match_params, max(1, int(limit))]
    rows = fetch_all(sql, params)
    records: list[dict] = []
    for row in rows:
        record = _row_to_record(row, include_embeddings=False)
        record["_topic_route_score"] = float(row.get("topic_route_score") or 0.0)
        records.append(record)
    return records


def load_exact_candidates_from_postgres(
    query: str,
    *,
    must_terms: list[str] | None = None,
    should_terms: list[str] | None = None,
    topic_labels: list[str] | None = None,
    query_type: str = "specific",
    venue_codes: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 60,
    topic_profile=None,
) -> list[dict]:
    route_terms = _build_route_terms(
        query,
        topic_labels=topic_labels,
        query_type=query_type,
        must_terms=must_terms,
        should_terms=should_terms,
        topic_profile=topic_profile,
    )
    exact_terms = list(route_terms.get("exact_terms") or [])
    if not exact_terms:
        return []

    where_clauses, filter_params = _build_record_filters(
        venue_codes=venue_codes,
        year_from=year_from,
        year_to=year_to,
    )
    rank_parts: list[str] = []
    rank_params: list[object] = []
    match_parts: list[str] = []
    match_params: list[object] = []
    for term in exact_terms[:6]:
        pattern = f"%{_escape_like(term)}%"
        rank_parts.append(
            "(CASE WHEN lower(coalesce(p.title, '')) LIKE %s ESCAPE '\\' THEN 1.75 ELSE 0 END + "
            "CASE WHEN lower(coalesce(p.abstract, '')) LIKE %s ESCAPE '\\' THEN 1.0 ELSE 0 END + "
            "CASE WHEN lower(coalesce(p.authors_text, '')) LIKE %s ESCAPE '\\' THEN 0.5 ELSE 0 END)"
        )
        rank_params.extend([pattern, pattern, pattern])
        match_parts.append(
            "(lower(coalesce(p.title, '')) LIKE %s ESCAPE '\\' OR "
            "lower(coalesce(p.abstract, '')) LIKE %s ESCAPE '\\' OR "
            "lower(coalesce(p.authors_text, '')) LIKE %s ESCAPE '\\')"
        )
        match_params.extend([pattern, pattern, pattern])

    score_expr = " + ".join(rank_parts) if rank_parts else "0.0"
    sql = _record_select_sql(include_embeddings=False, extra_selects=[f"({score_expr}) AS exact_route_score"])
    where_clauses.append("(" + " OR ".join(match_parts) + ")")
    sql += "\n WHERE " + " AND ".join(where_clauses)
    sql += "\n ORDER BY exact_route_score DESC, ve.year DESC NULLS LAST, p.title ASC"
    sql += "\n LIMIT %s"
    params = [*rank_params, *filter_params, *match_params, max(1, int(limit))]
    rows = fetch_all(sql, params)
    records: list[dict] = []
    for row in rows:
        record = _row_to_record(row, include_embeddings=False)
        record["_exact_route_score"] = float(row.get("exact_route_score") or 0.0)
        records.append(record)
    return records


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _extract_english_tokens(text: str) -> list[str]:
    tokens = [token.lower() for token in WORD_RE.findall(text or "")]
    return [token for token in tokens if token not in EN_STOPWORDS and len(token) > 1]


def _extract_cjk_terms(text: str) -> list[str]:
    terms: list[str] = []
    for block in CJK_RE.findall(text or ""):
        block = block.strip()
        if not block:
            continue

        # Always keep the full Chinese block first so exact user terms like
        # “中毒攻击” are preserved and scored before any sub-grams.
        terms.append(block)

        # For long blocks, keep only a small amount of local n-grams as fallback
        # recall helpers. Avoid generating every possible internal slice, which
        # can over-emphasize truncated fragments such as “毒攻击”.
        if len(block) <= 4:
            continue

        prefix_lengths = (2, 3, 4)
        suffix_lengths = (2, 3, 4)
        for n in prefix_lengths:
            if len(block) >= n:
                terms.append(block[:n])
        for n in suffix_lengths:
            if len(block) >= n:
                terms.append(block[-n:])
    return list(dict.fromkeys(terms))


def _expand_tokens(tokens: list[str]) -> list[str]:
    expanded = list(tokens)
    lowered_joined = " ".join(tokens)
    for key, aliases in DOMAIN_SYNONYMS.items():
        if key in lowered_joined or key in tokens:
            expanded.extend(aliases)
    return list(dict.fromkeys(expanded))


def _build_query_profile(
    query: str,
    topic_labels: list[str] | None = None,
    query_type: str = "specific",
    topic_profile=None,
    extra_terms: list[str] | None = None,
) -> dict:
    normalized = _normalize_text(query)
    english_tokens = _extract_english_tokens(normalized)
    cjk_terms = _extract_cjk_terms(query)
    phrase_terms = [normalized] if normalized and len(normalized) <= 120 else []
    expanded_tokens = _expand_tokens(english_tokens)

    topic_expansions: list[str] = []
    for label in topic_labels or []:
        topic_expansions.extend(expand_topics(label, generic=(query_type == "generic"), limit=12))

    matched_query_prototypes = _query_matched_prototype_terms(query, topic_profile, extra_terms=extra_terms)
    prototype_specific_terms: list[str] = []
    if query_type == "generic" and topic_profile is not None and matched_query_prototypes:
        for cluster in getattr(topic_profile, "prototype_clusters", ()) or ():
            cluster_id = str(getattr(cluster, "id", "") or "").strip()
            if cluster_id in matched_query_prototypes:
                prototype_specific_terms.extend([str(term).strip() for term in getattr(cluster, "match_terms", ()) if str(term).strip()])

    if query_type == "generic" and topic_profile is not None:
        if matched_query_prototypes and prototype_specific_terms:
            topic_expansions.extend(prototype_specific_terms[:8])
        else:
            topic_expansions.extend(list(topic_profile.expansion.extra_topic_expansions_generic))
        strip_set = {s.strip().lower() for s in topic_profile.expansion.strip_topic_expansions_generic if s}
        if matched_query_prototypes:
            strip_set.update({
                "ai security",
                "llm security",
                "security of ai",
            })
        if strip_set:
            topic_expansions = [item for item in topic_expansions if item.strip().lower() not in strip_set]

    topic_expansions = list(dict.fromkeys([*topic_expansions, *(extra_terms or [])]))
    topic_english_tokens = _extract_english_tokens(" ".join(topic_expansions))
    topic_cjk_terms = _extract_cjk_terms(" ".join(topic_expansions))

    expanded_tokens = list(dict.fromkeys([*expanded_tokens, *topic_english_tokens]))
    cjk_terms = list(dict.fromkeys([*cjk_terms, *topic_cjk_terms]))
    return {
        "normalized": normalized,
        "english_tokens": english_tokens,
        "expanded_tokens": expanded_tokens,
        "cjk_terms": cjk_terms,
        "phrases": phrase_terms,
        "topic_labels": topic_labels or [],
        "topic_expansions": topic_expansions,
        "query_type": query_type,
    }


def keyword_score(
    query: str,
    record: dict,
    topic_labels: list[str] | None = None,
    query_type: str = "specific",
    topic_profile=None,
    extra_terms: list[str] | None = None,
) -> tuple[float, dict]:
    profile = _build_query_profile(
        query, topic_labels=topic_labels, query_type=query_type, topic_profile=topic_profile, extra_terms=extra_terms
    )
    title = _normalize_text(record.get("title") or "")
    abstract = _normalize_text(record.get("abstract") or "")
    authors = _normalize_text(record.get("authors_text") or "")
    topic_summary = _normalize_text(record.get("topic_summary") or "")
    topic_tags = [_normalize_text(item) for item in (record.get("topic_tags") or []) if _normalize_text(item)]

    title_hits = 0.0
    abstract_hits = 0.0
    author_hits = 0.0
    exact_phrase_hits = 0.0
    cjk_hits = 0.0
    topic_hits = 0.0

    for phrase in profile["phrases"]:
        if phrase and phrase in title:
            exact_phrase_hits += 2.5
        elif phrase and phrase in abstract:
            exact_phrase_hits += 1.5

    for token in profile["expanded_tokens"]:
        if token in title:
            title_hits += 1.6
        elif token in abstract:
            abstract_hits += 1.0
        elif token in topic_summary:
            topic_hits += 1.1
        elif token in authors:
            author_hits += 0.3

    for term in profile["cjk_terms"]:
        if term in title:
            cjk_hits += 1.2
        elif term in abstract:
            cjk_hits += 0.8
        elif term in topic_summary or any(term in tag for tag in topic_tags):
            topic_hits += 1.0

    for term in profile["topic_expansions"]:
        needle = _normalize_text(term)
        if not needle:
            continue
        if needle in title:
            topic_hits += 1.8
        elif needle in abstract:
            topic_hits += 1.2
        elif needle in topic_summary:
            topic_hits += 1.35
        elif any(needle in tag for tag in topic_tags):
            topic_hits += 1.7

    token_base = max(1, len(profile["expanded_tokens"]) + len(profile["cjk_terms"]) + max(1, len(profile["topic_expansions"]) // 2))
    raw = exact_phrase_hits + title_hits + abstract_hits + author_hits + cjk_hits + topic_hits
    has_abstract_bonus = 0.15 if abstract else 0.0
    generic_floor = 0.08 if query_type == "generic" and topic_hits > 0 else 0.0
    score = min(1.0, raw / (token_base * 1.15) + has_abstract_bonus + generic_floor)
    details = {
        "exact_phrase_hits": round(exact_phrase_hits, 4),
        "title_hits": round(title_hits, 4),
        "abstract_hits": round(abstract_hits, 4),
        "cjk_hits": round(cjk_hits, 4),
        "topic_hits": round(topic_hits, 4),
    }
    return score, details


def _load_records(
    *,
    include_embeddings: bool = False,
    venue_codes: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    paper_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    try:
        records = load_records_from_postgres(
            include_embeddings=include_embeddings,
            venue_codes=venue_codes,
            year_from=year_from,
            year_to=year_to,
            paper_ids=paper_ids,
            limit=limit,
        )
        if records:
            return records
    except Exception:
        pass
    return load_normalized_metadata()


def _candidate_key(record: dict) -> str:
    return str(record.get("id") or record.get("paper_url") or record.get("title") or "")


def _candidate_premerge_rank_key(record: dict) -> tuple[float, float, float, float]:
    return (
        float(record.get("_embedding_score") or -1.0),
        float(record.get("_lexical_score") or 0.0),
        float(record.get("_exact_route_score") or 0.0),
        float(record.get("_topic_route_score") or 0.0),
    )


def _collect_broad_aggregate_prototype_seeds(
    *,
    topic_labels: list[str] | None,
    query_type: str,
    must_terms: list[str] | None,
    should_terms: list[str] | None,
    venue_codes: list[str] | None,
    year_from: int | None,
    year_to: int | None,
    topic_profile,
    scaled: Callable[[int, str], int],
) -> list[dict]:
    """Per-prototype lexical/topic probes so missing clusters enter the candidate pool before head rebalance."""
    if not topic_profile or topic_profile.strategy_type != "broad_aggregate":
        return []
    clusters = getattr(topic_profile, "prototype_clusters", None) or ()
    if not clusters:
        return []
    per_cluster = max(12, int(os.getenv("PAPERRADAR_PROTOTYPE_SEED_PER_CLUSTER", "40")))
    max_clusters = max(1, min(int(os.getenv("PAPERRADAR_PROTOTYPE_SEED_MAX_CLUSTERS", "8")), len(clusters)))
    out: list[dict] = []
    seen: set[str] = set()
    for cluster in list(clusters)[:max_clusters]:
        terms = [str(t).strip() for t in cluster.match_terms if str(t).strip()][:4]
        if not terms:
            continue
        matched_buckets = _query_matched_prototype_terms(
            " ".join([*(topic_labels or []), *(must_terms or []), *(should_terms or [])]),
            topic_profile,
            extra_terms=list(topic_labels or []) + list(must_terms or []) + list(should_terms or []),
        )
        if matched_buckets and str(getattr(cluster, "id", "") or "") not in matched_buckets:
            continue
        probe = " ".join(terms[:3])
        try:
            lex_lim = scaled(max(per_cluster, 24), "lexical")
            rows_l = load_lexical_candidates_from_postgres(
                probe,
                topic_labels=topic_labels,
                query_type=query_type,
                must_terms=must_terms,
                should_terms=should_terms,
                venue_codes=venue_codes,
                year_from=year_from,
                year_to=year_to,
                limit=lex_lim,
                topic_profile=topic_profile,
            )
        except Exception:
            rows_l = []
        try:
            top_lim = scaled(max(per_cluster // 2, 16), "topic")
            rows_t = load_topic_candidates_from_postgres(
                probe,
                topic_labels=topic_labels,
                query_type=query_type,
                venue_codes=venue_codes,
                year_from=year_from,
                year_to=year_to,
                limit=top_lim,
                topic_profile=topic_profile,
            )
        except Exception:
            rows_t = []
        for r in (*rows_l, *rows_t):
            pid = str(r.get("id") or "").strip()
            if pid and pid in seen:
                continue
            if pid:
                seen.add(pid)
            rr = dict(r)
            rr["_prototype_seed_cluster"] = getattr(cluster, "id", "")
            out.append(rr)
    return out


def _collect_specific_query_prototype_seeds(
    *,
    query: str,
    topic_labels: list[str] | None,
    query_type: str,
    must_terms: list[str] | None,
    should_terms: list[str] | None,
    venue_codes: list[str] | None,
    year_from: int | None,
    year_to: int | None,
    topic_profile,
    scaled: Callable[[int, str], int],
) -> list[dict]:
    if not topic_profile or getattr(topic_profile, "topic_id", None) != "ai-security":
        return []
    matched_buckets = _query_matched_prototype_terms(
        query,
        topic_profile,
        extra_terms=list(topic_labels or []) + list(must_terms or []) + list(should_terms or []),
    )
    if not matched_buckets:
        return []
    targeted = {"rag-codegen-security", "privacy-extraction-stealing", "watermark-ownership-integrity", "prompt-ip-and-ecosystem"}
    matched_buckets = [bid for bid in matched_buckets if bid in targeted]
    if not matched_buckets:
        return []

    out: list[dict] = []
    seen: set[str] = set()
    cluster_map = {str(getattr(c, "id", "") or "").strip(): c for c in (getattr(topic_profile, "prototype_clusters", ()) or ())}
    for bid in matched_buckets:
        cluster = cluster_map.get(bid)
        if cluster is None:
            continue
        terms = [str(t).strip() for t in getattr(cluster, "match_terms", ()) if str(t).strip()][:6]
        if not terms:
            continue
        probe = " ".join(terms[:4])
        for loader_name, loader, route in [
            ("lexical", load_lexical_candidates_from_postgres, "lexical"),
            ("exact", load_exact_candidates_from_postgres, "exact"),
            ("topic", load_topic_candidates_from_postgres, "topic"),
        ]:
            try:
                lim = scaled(36, route)
                if loader_name == "lexical":
                    rows = loader(
                        probe,
                        topic_labels=topic_labels,
                        query_type=query_type,
                        must_terms=must_terms,
                        should_terms=should_terms,
                        venue_codes=venue_codes,
                        year_from=year_from,
                        year_to=year_to,
                        limit=lim,
                        topic_profile=topic_profile,
                    )
                elif loader_name == "exact":
                    rows = loader(
                        probe,
                        must_terms=must_terms,
                        should_terms=should_terms,
                        topic_labels=topic_labels,
                        query_type=query_type,
                        venue_codes=venue_codes,
                        year_from=year_from,
                        year_to=year_to,
                        limit=lim,
                        topic_profile=topic_profile,
                    )
                else:
                    rows = loader(
                        probe,
                        topic_labels=topic_labels,
                        query_type=query_type,
                        venue_codes=venue_codes,
                        year_from=year_from,
                        year_to=year_to,
                        limit=lim,
                        topic_profile=topic_profile,
                    )
            except Exception:
                rows = []
            for r in rows:
                pid = str(r.get("id") or "").strip()
                if pid and pid in seen:
                    continue
                if pid:
                    seen.add(pid)
                rr = dict(r)
                rr["_prototype_seed_cluster"] = bid
                rr["_prototype_seed_route"] = loader_name
                out.append(rr)
    return out


def _rebalance_broad_aggregate_candidates(records: list[dict], topic_profile, query: str = "") -> list[dict]:
    """Cap per-prototype presence in the head of the candidate pool (pre-rerank)."""
    if not records or not topic_profile or topic_profile.strategy_type != "broad_aggregate":
        return records
    max_per = int(topic_profile.candidate.broad_aggregate_max_per_prototype or 0)
    if max_per <= 0:
        return records
    other_cap = max(1, int(topic_profile.candidate.broad_aggregate_other_cap or 3))
    head_n = min(len(records), max(1, int(topic_profile.candidate.broad_aggregate_head_limit or 48)))
    sorted_recs = sorted(records, key=_candidate_premerge_rank_key, reverse=True)
    out: list[dict] = []
    bucket_counts: dict[str, int] = {}
    seen: set[str] = set()
    matched_query_buckets = _query_matched_prototype_terms(query, topic_profile)
    targeted_caps = dict(getattr(topic_profile.candidate, "query_targeted_bucket_caps", {}) or {})
    suppressed_caps = dict(getattr(topic_profile.candidate, "query_suppressed_bucket_caps", {}) or {})
    family_head_caps_all = dict(getattr(topic_profile.candidate, "query_specific_family_head_caps", {}) or {})
    if matched_query_buckets and getattr(topic_profile, "topic_id", None) == "ai-security":
        targeted_caps = {
            **targeted_caps,
            **dict(getattr(topic_profile.candidate, "query_specific_targeted_bucket_caps", {}) or {}),
        }
        suppressed_caps = {
            **suppressed_caps,
            **dict(getattr(topic_profile.candidate, "query_specific_suppressed_bucket_caps", {}) or {}),
        }
    family_head_caps: dict[str, int] = {}
    if matched_query_buckets and family_head_caps_all:
        for bid in matched_query_buckets:
            caps = family_head_caps_all.get(bid)
            if isinstance(caps, dict):
                family_head_caps = {str(k): int(v) for k, v in caps.items()}
                break

    for r in sorted_recs:
        if len(out) >= head_n:
            break
        bid = infer_prototype_bucket(r, topic_profile)
        cap = other_cap if bid == "other" else max_per
        if matched_query_buckets:
            if bid in matched_query_buckets:
                cap = max(cap, int(targeted_caps.get(bid) or cap))
            elif bid in suppressed_caps:
                cap = min(cap, max(0, int(suppressed_caps.get(bid) or cap)))
            if family_head_caps and bid in family_head_caps:
                cap = min(cap, max(0, int(family_head_caps.get(bid) or cap))) if bid not in matched_query_buckets else max(cap, int(family_head_caps.get(bid) or cap))
        if bucket_counts.get(bid, 0) >= cap:
            continue
        key = str(r.get("id") or r.get("paper_url") or r.get("title") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(r)
        bucket_counts[bid] = bucket_counts.get(bid, 0) + 1

    for r in sorted_recs:
        key = str(r.get("id") or r.get("paper_url") or r.get("title") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(r)
    return out if out else records


def _merge_candidate_routes(route_groups: dict[str, list[dict]]) -> tuple[list[dict], dict]:
    merged: dict[str, dict] = {}
    route_counts: dict[str, int] = {}
    for route_name, rows in route_groups.items():
        route_counts[route_name] = len(rows)
        for rank, record in enumerate(rows, start=1):
            key = _candidate_key(record)
            if not key:
                continue
            existing = merged.get(key)
            if existing is None:
                existing = dict(record)
                existing["_candidate_sources"] = []
                existing["_candidate_route_ranks"] = {}
                merged[key] = existing

            if route_name not in existing["_candidate_sources"]:
                existing["_candidate_sources"].append(route_name)
            existing["_candidate_route_ranks"][route_name] = rank

            if float(record.get("_embedding_score") or -1.0) > float(existing.get("_embedding_score") or -1.0):
                existing["_embedding_score"] = float(record.get("_embedding_score") or -1.0)
            for field in ("_lexical_score", "_topic_route_score", "_exact_route_score"):
                if float(record.get(field) or 0.0) > float(existing.get(field) or 0.0):
                    existing[field] = float(record.get(field) or 0.0)
    return list(merged.values()), {
        "route_counts": route_counts,
        "union_candidate_count": len(merged),
    }


def _hydrate_candidate_embeddings(records: list[dict]) -> list[dict]:
    paper_ids = [record.get("id") for record in records if record.get("id")]
    if not paper_ids:
        return records
    try:
        hydrated_rows = load_records_from_postgres(include_embeddings=True, paper_ids=paper_ids)
    except Exception:
        return records

    hydrated_by_id = {row.get("id"): row for row in hydrated_rows if row.get("id")}
    merged_records: list[dict] = []
    for record in records:
        paper_id = record.get("id")
        hydrated = hydrated_by_id.get(paper_id)
        if not hydrated:
            merged_records.append(record)
            continue
        merged = dict(hydrated)
        for key, value in record.items():
            if key.startswith("_") or key in {"topic_tags", "topic_summary"}:
                merged[key] = value
        merged_records.append(merged)
    return merged_records


def expand_citation_candidates(
    query: str,
    *,
    seed_records: list[dict] | None = None,
    limit: int = 40,
) -> tuple[list[dict], dict]:
    return [], {
        "enabled": False,
        "reason": "citation_graph_not_available",
        "seed_count": len(seed_records or []),
        "limit": max(1, int(limit)),
        "query": query,
    }


def retrieve_metadata_candidates(
    query: str,
    *,
    query_embedding: list[float],
    venue_codes: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 20,
    must_terms: list[str] | None = None,
    should_terms: list[str] | None = None,
    negative_terms: list[str] | None = None,
    topic_labels: list[str] | None = None,
    records: list[dict] | None = None,
    use_embedding: bool = True,
    query_type: str = "specific",
    topic_profile=None,
) -> tuple[list[dict], dict]:
    if records is not None:
        return records, {
            "strategy": "provided_records",
            "route_counts": {"provided": len(records)},
            "union_candidate_count": len(records),
            "backend": "provided",
        }

    route_groups: dict[str, list[dict]] = {}
    route_errors: dict[str, str] = {}
    backend = "python_scan"
    scales: dict[str, float] = {}
    if topic_profile is not None:
        scales = dict(topic_profile.candidate.per_route_limit_scale or {})

    def _scaled(base: int, route: str) -> int:
        s = float(scales.get(route, 1.0))
        return max(1, int(round(base * s)))

    if use_embedding and query_embedding and pgvector_search_ready():
        vector_limit = _scaled(max(limit, DEFAULT_VECTOR_MIN_CANDIDATES), "vector")
        try:
            route_groups["vector"] = load_vector_candidates_from_postgres(
                query_embedding,
                venue_codes=venue_codes,
                year_from=year_from,
                year_to=year_to,
                limit=vector_limit,
            )
            if route_groups["vector"]:
                backend = "pgvector+hybrid"
        except Exception:
            route_groups["vector"] = []
            route_errors["vector"] = traceback.format_exc(limit=1).strip().splitlines()[-1]

    force_seed_query = _ai_security_force_seed_query(
        query,
        topic_profile,
        extra_terms=list(topic_labels or []) + list(must_terms or []) + list(should_terms or []),
    )

    try:
        lexical_limit = _scaled(max(limit, DEFAULT_LEXICAL_MIN_CANDIDATES), "lexical")
        route_groups["lexical"] = load_lexical_candidates_from_postgres(
            force_seed_query or query,
            topic_labels=topic_labels,
            query_type=query_type,
            must_terms=must_terms,
            should_terms=should_terms,
            venue_codes=venue_codes,
            year_from=year_from,
            year_to=year_to,
            limit=lexical_limit,
            topic_profile=topic_profile,
        )
    except Exception:
        route_groups["lexical"] = []
        route_errors["lexical"] = traceback.format_exc(limit=1).strip().splitlines()[-1]

    try:
        exact_limit = _scaled(max(limit, DEFAULT_EXACT_MIN_CANDIDATES), "exact")
        route_groups["exact"] = load_exact_candidates_from_postgres(
            force_seed_query or query,
            must_terms=must_terms,
            should_terms=should_terms,
            topic_labels=topic_labels,
            query_type=query_type,
            venue_codes=venue_codes,
            year_from=year_from,
            year_to=year_to,
            limit=exact_limit,
            topic_profile=topic_profile,
        )
    except Exception:
        route_groups["exact"] = []
        route_errors["exact"] = traceback.format_exc(limit=1).strip().splitlines()[-1]

    try:
        topic_limit = _scaled(max(limit, DEFAULT_TOPIC_MIN_CANDIDATES), "topic")
        route_groups["topic"] = load_topic_candidates_from_postgres(
            force_seed_query or query,
            topic_labels=topic_labels,
            query_type=query_type,
            venue_codes=venue_codes,
            year_from=year_from,
            year_to=year_to,
            limit=topic_limit,
            topic_profile=topic_profile,
        )
    except Exception:
        route_groups["topic"] = []
        route_errors["topic"] = traceback.format_exc(limit=1).strip().splitlines()[-1]

    seed_rows = _collect_broad_aggregate_prototype_seeds(
        topic_labels=topic_labels,
        query_type=query_type,
        must_terms=must_terms,
        should_terms=should_terms,
        venue_codes=venue_codes,
        year_from=year_from,
        year_to=year_to,
        topic_profile=topic_profile,
        scaled=_scaled,
    )
    if seed_rows:
        route_groups["prototype_seed"] = seed_rows

    specific_seed_rows = _collect_specific_query_prototype_seeds(
        query=query,
        topic_labels=topic_labels,
        query_type=query_type,
        must_terms=must_terms,
        should_terms=should_terms,
        venue_codes=venue_codes,
        year_from=year_from,
        year_to=year_to,
        topic_profile=topic_profile,
        scaled=_scaled,
    )
    if specific_seed_rows:
        route_groups["prototype_seed_specific"] = specific_seed_rows

    merged_records, route_summary = _merge_candidate_routes(route_groups)
    citation_records, citation_summary = expand_citation_candidates(
        query,
        seed_records=merged_records[: min(20, len(merged_records))],
        limit=max(limit, 40),
    )
    if citation_records:
        route_groups["citation"] = citation_records
        merged_records, route_summary = _merge_candidate_routes(route_groups)
    if merged_records:
        shaped = _rebalance_broad_aggregate_candidates(merged_records, topic_profile, query=query)
        return shaped, {
            "strategy": "candidate_union",
            "backend": backend,
            **route_summary,
            "negative_terms_applied": len(negative_terms or []),
            "citation_expansion": citation_summary,
            "broad_aggregate_shaping": bool(topic_profile and topic_profile.strategy_type == "broad_aggregate"),
            "prototype_seed_count": len(seed_rows),
            "prototype_seed_specific_count": len(specific_seed_rows),
            "route_errors": route_errors,
        }

    fallback_records = _prepare_filtered_records(
        None,
        include_embeddings=bool(use_embedding and query_embedding),
        venue_codes=venue_codes,
        year_from=year_from,
        year_to=year_to,
    )
    return fallback_records, {
        "strategy": "full_scan_fallback",
        "backend": "python_scan",
        "route_counts": {name: len(rows) for name, rows in route_groups.items()},
        "union_candidate_count": len(fallback_records),
        "negative_terms_applied": len(negative_terms or []),
        "citation_expansion": citation_summary,
        "prototype_seed_specific_count": len(specific_seed_rows),
        "route_errors": route_errors,
    }


def _match_term_score(term: str, title: str, abstract: str, topic_summary: str = "", topic_tags: list[str] | None = None) -> float:
    needle = _normalize_text(term)
    if not needle:
        return 0.0
    if needle in title:
        return 1.0
    if needle in abstract:
        return 0.6
    normalized_summary = _normalize_text(topic_summary)
    if needle in normalized_summary:
        return 0.75
    tags_joined = _normalize_text(" ".join(topic_tags or []))
    if needle in tags_joined:
        return 0.95
    return 0.0


CRYPTO_SUBAREA_TERMS = [
    "encryption",
    "signature",
    "proof",
    "zero-knowledge",
    "homomorphic",
    "mpc",
    "multi-party computation",
    "secure computation",
    "accumulator",
    "threshold",
    "protocol",
    "key recovery",
    "snark",
    "stark",
    "lattice",
]

CRYPTO_META_PENALTY_TERMS = [
    "competition",
    "competitions",
    "interview",
    "experiences",
    "practices",
    "updating code",
    "perspective",
]

SYSTEMS_NEIGHBOR_PREFERENCES: dict[str, dict[str, object]] = {
    "program analysis": {
        "positive_terms": [
            "program analysis",
            "static analysis",
            "dynamic analysis",
            "binary analysis",
            "taint analysis",
            "symbolic execution",
            "deobfuscation",
            "program synthesis",
            "indirect call analysis",
        ],
        "negative_terms": [
            "fuzzing",
            "fuzzer",
            "greybox fuzzing",
            "coverage-guided fuzzing",
            "vulnerability hunting",
        ],
        "positive_weight": 0.08,
        "negative_weight": 0.07,
        "title_bonus": 0.09,
        "title_penalty": 0.11,
    },
    "fuzzing": {
        "positive_terms": [
            "fuzzing",
            "fuzzer",
            "fuzz testing",
            "coverage-guided fuzzing",
            "kernel fuzzing",
            "protocol fuzzing",
            "firmware fuzzing",
        ],
        "negative_terms": [
            "program analysis",
            "static analysis",
            "dynamic analysis",
            "binary analysis",
            "symbolic execution",
        ],
        "positive_weight": 0.07,
        "negative_weight": 0.05,
        "title_bonus": 0.08,
        "title_penalty": 0.07,
    },
    "privacy-preserving computation": {
        "positive_terms": [
            "privacy-preserving computation",
            "private computation",
            "private inference",
            "private training",
            "secure aggregation",
            "encrypted search",
            "private set intersection",
            "privacy-preserving machine learning",
            "ppml",
        ],
        "negative_terms": [
            "local differential privacy",
            "frequency estimation",
            "shuffle protocol",
            "randomized response",
            "privacy-boosting",
        ],
        "positive_weight": 0.07,
        "negative_weight": 0.08,
        "title_bonus": 0.08,
        "title_penalty": 0.1,
    },
    "malware detection": {
        "positive_terms": [
            "malware detection",
            "malware analysis",
            "packed executables detection",
            "android malware detection",
            "packed malware detection",
            "malware classification",
            "packer detection",
            "ransomware detection",
        ],
        "negative_terms": [
            "malicious traffic detection",
            "traffic detection",
            "binary function matching",
            "stripped binary",
            "binary function",
            "binary reverse engineering",
            "reverse engineering",
            "binary analysis",
            "phishing detection",
            "pdf malware",
            "pdf malware analysis",
            "pdf malware forensics",
            "variable names",
            "function names",
        ],
        "positive_weight": 0.08,
        "negative_weight": 0.1,
        "title_bonus": 0.1,
        "title_penalty": 0.12,
    },
}


def _blob_contains(term: str, *parts: str) -> bool:
    needle = _normalize_text(term)
    if not needle:
        return False
    return any(needle in _normalize_text(part) for part in parts if part)


def _query_matched_prototype_terms(query_text: str, topic_profile, extra_terms: list[str] | None = None) -> set[str]:
    if topic_profile is None:
        return set()
    probes = [_normalize_text(query_text)]
    probes.extend(_normalize_text(term) for term in (extra_terms or []) if _normalize_text(term))
    probes = [p for p in probes if p]
    if not probes:
        return set()
    matched: set[str] = set()
    for cluster in getattr(topic_profile, "prototype_clusters", ()) or ():
        terms = [str(term or "").strip() for term in getattr(cluster, "match_terms", ()) if str(term or "").strip()]
        if any(any(_blob_contains(term, probe) for probe in probes) for term in terms):
            matched.add(str(getattr(cluster, "id", "") or "").strip())
    return matched


def _ai_security_force_seed_query(query_text: str, topic_profile, extra_terms: list[str] | None = None) -> str | None:
    if topic_profile is None or getattr(topic_profile, "topic_id", None) != "ai-security":
        return None
    matched = _query_matched_prototype_terms(query_text, topic_profile, extra_terms=extra_terms)
    if not matched:
        return None
    priority = [
        "rag-codegen-security",
        "privacy-extraction-stealing",
        "watermark-ownership-integrity",
        "prompt-ip-and-ecosystem",
    ]
    cluster_map = {
        str(getattr(c, "id", "") or "").strip(): [str(t).strip() for t in getattr(c, "match_terms", ()) if str(t).strip()]
        for c in (getattr(topic_profile, "prototype_clusters", ()) or ())
    }
    for cid in priority:
        if cid in matched and cluster_map.get(cid):
            return " ".join(cluster_map[cid][:4])
    cid = next(iter(matched), None)
    if cid and cluster_map.get(cid):
        return " ".join(cluster_map[cid][:4])
    return None


def _ai_security_title_anchor_bonus(title: str, matched_query_prototypes: set[str], record_bucket: str, candidate_sources: list[str]) -> float:
    if not matched_query_prototypes:
        return 0.0
    route_bonus_gate = any(src in candidate_sources for src in ["exact", "topic", "prototype_seed", "prototype_seed_specific"])
    if not route_bonus_gate:
        return 0.0
    bonus = 0.0
    if "prompt-ip-and-ecosystem" in matched_query_prototypes and record_bucket == "prompt-ip-and-ecosystem":
        if any(term in title for term in ["prompt stealing", "system prompt", "prompt obfuscation", "prompt services", "in-the-wild prompts"]):
            bonus += 0.22
    if "rag-codegen-security" in matched_query_prototypes and record_bucket == "rag-codegen-security":
        if any(term in title for term in ["retrieval-augmented code generation", "importsnare", "dependency hijacking", "code manual", "documentation poisoning", "rag code generation"]):
            bonus += 0.22
    if "privacy-extraction-stealing" in matched_query_prototypes and record_bucket == "privacy-extraction-stealing":
        if any(term in title for term in ["model extraction", "model stealing", "model inversion", "training data extraction", "membership inference", "knockoff"]):
            bonus += 0.2
    if "watermark-ownership-integrity" in matched_query_prototypes and record_bucket == "watermark-ownership-integrity":
        if any(term in title for term in ["watermark", "watermarking", "ownership verification", "model attribution", "fingerprint", "tree-ring"]):
            bonus += 0.2
    return bonus


def _neighbor_preference_map(topic_profile, primary_topic: str) -> dict[str, object] | None:
    if topic_profile is not None and topic_profile.scoring.neighbor.positive_terms:
        nb = topic_profile.scoring.neighbor
        return {
            "positive_terms": list(nb.positive_terms),
            "negative_terms": list(nb.negative_terms),
            "positive_weight": nb.positive_weight,
            "negative_weight": nb.negative_weight,
            "title_bonus": nb.title_bonus,
            "title_penalty": nb.title_penalty,
        }
    return SYSTEMS_NEIGHBOR_PREFERENCES.get(primary_topic)


def _topic_purity_adjust_from_profile(
    query_type: str,
    topic_profile,
    primary_topic: str,
    title: str,
    abstract: str,
    normalized_summary: str,
    normalized_tags: str,
) -> float:
    """Feature-style topic purity delta; profile-driven with legacy fallback when no profile."""
    if query_type != "generic":
        return 0.0
    title_abstract_blob = f"{title} {abstract} {normalized_summary} {normalized_tags}"
    adjust = 0.0

    if topic_profile is not None:
        purity = topic_profile.scoring.purity
        if purity.fhe_purity and purity.canonical_terms:
            canonical_hits = sum(1 for term in purity.canonical_terms if term in title_abstract_blob)
            title_anchor_hits = sum(
                1 for term in (purity.title_anchor_terms or purity.canonical_terms) if term in title
            )
            if canonical_hits > 0:
                adjust += min(0.16, canonical_hits * 0.035)
            if title_anchor_hits > 0:
                adjust += min(0.12, title_anchor_hits * 0.04)
            return adjust
        if purity.malware_title_anchor and purity.canonical_terms and purity.drift_terms:
            canonical_hits = sum(1 for term in purity.canonical_terms if term in title_abstract_blob)
            drift_hits = sum(1 for term in purity.drift_terms if term in title_abstract_blob)
            pdf_hits = sum(
                1 for term in ["pdf malware", "pdf malware analysis", "pdf malware forensics"] if term in title_abstract_blob
            )
            binary_naming_hits = sum(
                1
                for term in ["stripped binary", "binary function matching", "variable names", "function names"]
                if term in title_abstract_blob
            )
            binary_re_hits = sum(
                1 for term in ["binary reverse engineering", "reverse engineering", "binary analysis"] if term in title_abstract_blob
            )
            if canonical_hits > 0:
                adjust += min(0.2, canonical_hits * 0.05)
            if drift_hits > 0 and canonical_hits == 0:
                adjust -= min(0.28, drift_hits * 0.075)
            if pdf_hits > 0 and "android malware detection" not in title_abstract_blob and "packed executables detection" not in title_abstract_blob:
                adjust -= min(0.2, pdf_hits * 0.1)
            if binary_naming_hits > 0 and canonical_hits == 0:
                adjust -= min(0.24, binary_naming_hits * 0.1)
            if binary_re_hits > 0 and canonical_hits == 0:
                adjust -= min(0.18, binary_re_hits * 0.08)
            return adjust
        if purity.canonical_terms and purity.drift_terms:
            canonical_hits = sum(1 for term in purity.canonical_terms if term in title_abstract_blob)
            drift_hits = sum(1 for term in purity.drift_terms if term in title_abstract_blob)
            if canonical_hits > 0:
                adjust += min(0.18, canonical_hits * 0.05)
            if drift_hits > 0 and canonical_hits == 0:
                adjust -= min(0.2, drift_hits * 0.06)
            return adjust
        return 0.0

    # Legacy fallback (no runtime profile match)
    if primary_topic == "privacy-preserving computation":
        canonical_hits = sum(
            1
            for term in [
                "private inference",
                "private training",
                "secure aggregation",
                "encrypted search",
                "private set intersection",
                "privacy-preserving machine learning",
                "ppml",
            ]
            if term in title_abstract_blob
        )
        dp_hits = sum(
            1
            for term in [
                "local differential privacy",
                "frequency estimation",
                "shuffle protocol",
                "randomized response",
            ]
            if term in title_abstract_blob
        )
        if canonical_hits > 0:
            adjust += min(0.18, canonical_hits * 0.05)
        if dp_hits > 0 and canonical_hits == 0:
            adjust -= min(0.2, dp_hits * 0.06)
    elif primary_topic == "homomorphic encryption":
        canonical_hits = sum(
            1
            for term in [
                "fully homomorphic encryption",
                "homomorphic encryption",
                "fhe",
                "tfhe",
                "bootstrapping",
                "threshold fhe",
            ]
            if term in title_abstract_blob
        )
        title_anchor_hits = sum(
            1
            for term in ["fully homomorphic encryption", "homomorphic encryption", "fhe", "tfhe"]
            if term in title
        )
        if canonical_hits > 0:
            adjust += min(0.16, canonical_hits * 0.035)
        if title_anchor_hits > 0:
            adjust += min(0.12, title_anchor_hits * 0.04)
    elif primary_topic == "malware detection":
        canonical_hits = sum(
            1
            for term in [
                "malware detection",
                "malware analysis",
                "packed executables detection",
                "android malware detection",
                "malware classification",
                "packer detection",
                "ransomware detection",
                "adversarial android malware detection",
                "android malicious software",
                "malware detectors",
            ]
            if term in title_abstract_blob
        )
        drift_hits = sum(
            1
            for term in [
                "malicious traffic detection",
                "traffic detection",
                "binary function matching",
                "stripped binary",
                "binary reverse engineering",
                "reverse engineering",
                "binary analysis",
                "phishing detection",
                "pdf malware",
                "pdf malware analysis",
                "pdf malware forensics",
                "variable names",
                "function names",
            ]
            if term in title_abstract_blob
        )
        pdf_hits = sum(1 for term in ["pdf malware", "pdf malware analysis", "pdf malware forensics"] if term in title_abstract_blob)
        binary_naming_hits = sum(
            1 for term in ["stripped binary", "binary function matching", "variable names", "function names"] if term in title_abstract_blob
        )
        binary_re_hits = sum(
            1 for term in ["binary reverse engineering", "reverse engineering", "binary analysis"] if term in title_abstract_blob
        )
        if canonical_hits > 0:
            adjust += min(0.2, canonical_hits * 0.05)
        if drift_hits > 0 and canonical_hits == 0:
            adjust -= min(0.28, drift_hits * 0.075)
        if pdf_hits > 0 and "android malware detection" not in title_abstract_blob and "packed executables detection" not in title_abstract_blob:
            adjust -= min(0.2, pdf_hits * 0.1)
        if binary_naming_hits > 0 and canonical_hits == 0:
            adjust -= min(0.24, binary_naming_hits * 0.1)
        if binary_re_hits > 0 and canonical_hits == 0:
            adjust -= min(0.18, binary_re_hits * 0.08)
    return adjust


def _rerank_score(
    keyword: float,
    embedding: float | None,
    record: dict,
    details: dict,
    must_terms: list[str] | None = None,
    should_terms: list[str] | None = None,
    negative_terms: list[str] | None = None,
    topic_labels: list[str] | None = None,
    query_type: str = "specific",
    topic_profile=None,
) -> tuple[float, dict]:
    title_boost = 0.12 if (details.get("title_hits") or 0) > 0 else 0.0
    phrase_boost = 0.18 if (details.get("exact_phrase_hits") or 0) > 0 else 0.0
    abstract_boost = 0.06 if record.get("abstract") else -0.03
    year_boost = min(0.06, max(0.0, ((record.get("year") or 0) - 2020) * 0.01)) if record.get("year") else 0.0
    if query_type == "generic":
        phrase_boost *= 0.45
        title_boost *= 0.75

    if embedding is None or embedding < 0:
        base = 0.88 * keyword
        blend_mode = "keyword_only"
    elif query_type == "generic":
        base = 0.48 * keyword + 0.52 * embedding
        blend_mode = "semantic_first"
    elif keyword >= 0.45:
        base = 0.7 * keyword + 0.3 * embedding
        blend_mode = "keyword_first"
    else:
        base = 0.52 * keyword + 0.48 * embedding
        blend_mode = "balanced"

    title = _normalize_text(record.get("title") or "")
    abstract = _normalize_text(record.get("abstract") or "")
    topic_summary = record.get("topic_summary") or ""
    topic_tags = record.get("topic_tags") or []
    query_text = _normalize_text(" ".join([*(must_terms or []), *(should_terms or []), *(topic_labels or [])]))
    must_scores = [_match_term_score(term, title, abstract, topic_summary, topic_tags) for term in (must_terms or [])]
    should_scores = [_match_term_score(term, title, abstract, topic_summary, topic_tags) for term in (should_terms or [])]
    negative_scores = [_match_term_score(term, title, abstract, topic_summary, topic_tags) for term in (negative_terms or [])]
    topic_scores = [_match_term_score(term, title, abstract, topic_summary, topic_tags) for term in (topic_labels or [])]
    candidate_sources = list(record.get("_candidate_sources") or [])

    must_bonus = sum(must_scores) * 0.16
    should_bonus = sum(should_scores) * 0.08
    topic_bonus = sum(topic_scores) * (0.2 if query_type == "generic" else 0.1)
    negative_penalty = sum(negative_scores) * 0.34
    topic_purity_adjust = 0.0
    route_bonus = 0.0
    systems_neighbor_adjust = 0.0
    if "lexical" in candidate_sources:
        route_bonus += 0.07
    if "vector" in candidate_sources:
        route_bonus += 0.04
    if "topic" in candidate_sources:
        route_bonus += 0.035
    if "exact" in candidate_sources:
        route_bonus += 0.1
    if "prototype_seed" in candidate_sources:
        route_bonus += 0.055
    if "lexical" in candidate_sources and "vector" in candidate_sources:
        route_bonus += 0.07

    crypto_diversity_bonus = 0.0
    normalized_summary = _normalize_text(topic_summary)
    normalized_tags = _normalize_text(" ".join(topic_tags))
    primary_topic = str((topic_labels or [""])[0] or "").strip().lower()
    if query_type == "generic":
        matched_topic_count = sum(1 for item in topic_scores if item > 0)
        matched_must_count = sum(1 for item in must_scores if item > 0)
        if topic_labels:
            if matched_topic_count == 0 and matched_must_count == 0:
                topic_purity_adjust -= 0.18
            elif matched_topic_count == 0:
                topic_purity_adjust -= 0.08
            elif matched_topic_count >= 2:
                topic_purity_adjust += 0.05
        if (details.get("exact_phrase_hits") or 0) == 0 and (details.get("title_hits") or 0) == 0 and matched_topic_count == 0:
            topic_purity_adjust -= 0.04
    if query_type == "generic" and any(term in ["cryptography", "密码学"] for term in (topic_labels or [])):
        subarea_hits = 0
        title_abstract_blob = f"{title} {abstract} {normalized_summary} {normalized_tags}"
        for term in CRYPTO_SUBAREA_TERMS:
            if term in title_abstract_blob:
                subarea_hits += 1
        crypto_diversity_bonus = min(0.28, subarea_hits * 0.045)
        cryptography_literal_hits = sum(1 for term in ["cryptography", "cryptographic"] if term in f"{title} {abstract}")
        meta_penalty_hits = sum(1 for term in CRYPTO_META_PENALTY_TERMS if term in title_abstract_blob)
        if cryptography_literal_hits > 0 and subarea_hits <= 1:
            crypto_diversity_bonus -= 0.08
        if meta_penalty_hits > 0 and subarea_hits <= 2:
            crypto_diversity_bonus -= min(0.16, meta_penalty_hits * 0.05)

    topic_purity_adjust += _topic_purity_adjust_from_profile(
        query_type,
        topic_profile,
        primary_topic,
        title,
        abstract,
        normalized_summary,
        normalized_tags,
    )

    if must_scores and len(must_scores) >= 2:
        matched_must_count = sum(1 for item in must_scores if item > 0)
        if matched_must_count >= 2:
            must_bonus += 0.14
        elif matched_must_count == 1:
            must_bonus -= 0.08

    preference = _neighbor_preference_map(topic_profile, primary_topic)
    if preference and (query_type == "generic" or (query_type == "specific" and topic_profile is not None and getattr(topic_profile, "topic_id", None) == "ai-security")):
        positive_terms = list(preference.get("positive_terms") or [])
        negative_neighbor_terms = list(preference.get("negative_terms") or [])
        positive_weight = float(preference.get("positive_weight") or 0.0)
        negative_weight = float(preference.get("negative_weight") or 0.0)
        title_bonus_weight = float(preference.get("title_bonus") or 0.0)
        title_penalty_weight = float(preference.get("title_penalty") or 0.0)
        body_parts = [title, abstract, normalized_summary, normalized_tags]
        positive_hits = sum(1 for term in positive_terms if _blob_contains(term, *body_parts))
        negative_hits = sum(1 for term in negative_neighbor_terms if _blob_contains(term, *body_parts))
        title_positive_hits = sum(1 for term in positive_terms if _blob_contains(term, title))
        title_negative_hits = sum(1 for term in negative_neighbor_terms if _blob_contains(term, title))
        systems_neighbor_adjust += min(0.22, positive_hits * positive_weight)
        systems_neighbor_adjust -= min(0.22, negative_hits * negative_weight)
        systems_neighbor_adjust += min(0.14, title_positive_hits * title_bonus_weight)
        systems_neighbor_adjust -= min(0.18, title_negative_hits * title_penalty_weight)
        if positive_hits == 0 and negative_hits > 0:
            systems_neighbor_adjust -= 0.08

        matched_query_prototypes = _query_matched_prototype_terms(query_text, topic_profile, extra_terms=(topic_labels or []) + (must_terms or []) + (should_terms or []))
        if matched_query_prototypes:
            record_bucket = infer_prototype_bucket(record, topic_profile) if topic_profile is not None else "other"
            systems_neighbor_adjust += _ai_security_title_anchor_bonus(title, matched_query_prototypes, record_bucket, candidate_sources)
            if record_bucket in matched_query_prototypes:
                systems_neighbor_adjust += 0.14
            elif record_bucket != "other":
                systems_neighbor_adjust -= 0.04

            if topic_profile is not None and getattr(topic_profile, "topic_id", None) == "ai-security":
                targeted_ai_security_buckets = {
                    "model-poisoning-backdoors",
                    "llm-backdoors-adapters",
                    "privacy-extraction-stealing",
                    "watermark-ownership-integrity",
                    "prompt-ip-and-ecosystem",
                    "rag-codegen-security",
                }
                generic_llm_buckets = {"llm-jailbreaks", "prompt-injection-rag", "agentic-llm-systems"}
                if matched_query_prototypes & targeted_ai_security_buckets:
                    if record_bucket in matched_query_prototypes:
                        systems_neighbor_adjust += 0.06
                    elif record_bucket in generic_llm_buckets:
                        systems_neighbor_adjust -= 0.18
                    elif record_bucket in targeted_ai_security_buckets:
                        systems_neighbor_adjust -= 0.06

                if "model-poisoning-backdoors" in matched_query_prototypes:
                    if record_bucket == "model-poisoning-backdoors":
                        systems_neighbor_adjust += 0.18
                    elif record_bucket == "llm-backdoors-adapters":
                        systems_neighbor_adjust += 0.08
                    elif record_bucket in {"llm-jailbreaks", "watermark-ownership-integrity"}:
                        systems_neighbor_adjust -= 0.2
                if "privacy-extraction-stealing" in matched_query_prototypes:
                    if record_bucket == "privacy-extraction-stealing":
                        systems_neighbor_adjust += 0.22
                    elif record_bucket in {"prompt-ip-and-ecosystem", "model-misuse-attacks"}:
                        systems_neighbor_adjust += 0.06
                    elif record_bucket in {"llm-jailbreaks", "prompt-injection-rag"}:
                        systems_neighbor_adjust -= 0.22
                    elif record_bucket == "watermark-ownership-integrity":
                        systems_neighbor_adjust -= 0.2
                    elif record_bucket == "rag-codegen-security":
                        systems_neighbor_adjust -= 0.16
                    if any(term in title for term in ["model extraction", "model stealing", "model inversion", "training data extraction", "membership inference", "knockoff"]):
                        systems_neighbor_adjust += 0.2
                if "watermark-ownership-integrity" in matched_query_prototypes:
                    if record_bucket == "watermark-ownership-integrity":
                        systems_neighbor_adjust += 0.24
                    elif record_bucket in {"prompt-ip-and-ecosystem", "model-misuse-attacks"}:
                        systems_neighbor_adjust -= 0.08
                    elif record_bucket in {"llm-jailbreaks", "prompt-injection-rag"}:
                        systems_neighbor_adjust -= 0.24
                    elif record_bucket == "privacy-extraction-stealing":
                        systems_neighbor_adjust -= 0.18
                    elif record_bucket == "rag-codegen-security":
                        systems_neighbor_adjust -= 0.18
                    if any(term in title for term in ["watermark", "watermarking", "ownership verification", "model attribution", "fingerprint", "tree-ring"]):
                        systems_neighbor_adjust += 0.22
                if "prompt-ip-and-ecosystem" in matched_query_prototypes:
                    if record_bucket == "prompt-ip-and-ecosystem":
                        systems_neighbor_adjust += 0.22
                    elif record_bucket == "llm-app-ecosystem":
                        systems_neighbor_adjust += 0.08
                    elif record_bucket == "model-poisoning-backdoors":
                        systems_neighbor_adjust -= 0.16
                    elif record_bucket in {"llm-jailbreaks", "prompt-injection-rag"}:
                        systems_neighbor_adjust -= 0.22
                    elif record_bucket == "watermark-ownership-integrity":
                        systems_neighbor_adjust -= 0.24
                    elif record_bucket == "privacy-extraction-stealing":
                        systems_neighbor_adjust -= 0.16
                    elif record_bucket == "rag-codegen-security":
                        systems_neighbor_adjust -= 0.14
                    if any(term in title for term in ["prompt stealing", "system prompt", "prompt obfuscation", "prompt services", "in-the-wild prompts"]):
                        systems_neighbor_adjust += 0.24
                if "rag-codegen-security" in matched_query_prototypes:
                    if record_bucket == "rag-codegen-security":
                        systems_neighbor_adjust += 0.28
                    elif record_bucket == "prompt-injection-rag":
                        systems_neighbor_adjust -= 0.24
                    elif record_bucket == "llm-jailbreaks":
                        systems_neighbor_adjust -= 0.24
                    elif record_bucket == "agentic-llm-systems":
                        systems_neighbor_adjust -= 0.1
                    elif record_bucket == "model-poisoning-backdoors":
                        systems_neighbor_adjust -= 0.14
                    elif record_bucket == "watermark-ownership-integrity":
                        systems_neighbor_adjust -= 0.2
                    elif record_bucket == "prompt-ip-and-ecosystem":
                        systems_neighbor_adjust -= 0.18
                    elif record_bucket == "privacy-extraction-stealing":
                        systems_neighbor_adjust -= 0.14
                    if any(term in title for term in ["retrieval-augmented code generation", "importsnare", "dependency hijacking", "code manual", "documentation poisoning", "rag code generation"]):
                        systems_neighbor_adjust += 0.24

        if primary_topic == "malware detection" or (
            topic_profile is not None and topic_profile.scoring.purity.malware_title_anchor
        ):
            has_malware_title_anchor = any(_blob_contains(term, title) for term in [
                "malware detection",
                "malware analysis",
                "android malware detection",
                "packed executables detection",
                "malware classification",
                "ransomware detection",
                "malware",
            ])
            has_binary_neighbor_title_anchor = any(_blob_contains(term, title) for term in [
                "binary function matching",
                "stripped binary",
                "variable names",
                "function names",
                "binary reverse engineering",
                "reverse engineering",
            ])
            has_pdf_neighbor_title_anchor = any(_blob_contains(term, title) for term in [
                "pdf malware",
                "pdf malware analysis",
                "pdf malware forensics",
                "pdf",
            ])
            if has_binary_neighbor_title_anchor and not has_malware_title_anchor:
                systems_neighbor_adjust -= 0.2
            if has_pdf_neighbor_title_anchor and not has_malware_title_anchor:
                systems_neighbor_adjust -= 0.16
        if primary_topic == "program analysis":
            has_program_analysis_title_anchor = any(_blob_contains(term, title) for term in [
                "program analysis",
                "static analysis",
                "dynamic analysis",
                "binary analysis",
                "taint analysis",
                "symbolic execution",
                "deobfuscation",
                "call analysis",
                "constraint reasoning",
                "path prioritization",
            ])
            has_fuzzing_title_anchor = any(_blob_contains(term, title) for term in [
                "fuzzing",
                "fuzzer",
                "greybox fuzzing",
                "coverage-guided fuzzing",
                "directed fuzzing",
            ])
            fuzzing_validation_terms = [
                "vulnerability validation",
                "bug validation",
                "result verification",
                "validation",
            ]
            validation_hits = sum(1 for term in fuzzing_validation_terms if _blob_contains(term, title, abstract))
            if has_fuzzing_title_anchor and not has_program_analysis_title_anchor:
                systems_neighbor_adjust -= 0.22
                if validation_hits > 0:
                    systems_neighbor_adjust -= 0.08
            elif validation_hits > 0 and has_fuzzing_title_anchor:
                systems_neighbor_adjust -= 0.08
        elif primary_topic == "fuzzing":
            has_fuzzing_title_anchor = any(_blob_contains(term, title) for term in [
                "fuzzing",
                "fuzzer",
                "fuzz testing",
            ])
            has_program_analysis_title_anchor = any(_blob_contains(term, title) for term in [
                "program analysis",
                "static analysis",
                "dynamic analysis",
                "binary analysis",
            ])
            if has_program_analysis_title_anchor and not has_fuzzing_title_anchor:
                systems_neighbor_adjust -= 0.12

    if negative_scores:
        title_negative_hits = sum(1 for term in (negative_terms or []) if _normalize_text(term) in title)
        negative_penalty += title_negative_hits * 0.18

    score = base + title_boost + phrase_boost + abstract_boost + year_boost + must_bonus + should_bonus + topic_bonus + route_bonus + crypto_diversity_bonus + topic_purity_adjust + systems_neighbor_adjust - negative_penalty
    debug = {
        "must_bonus": round(must_bonus, 4),
        "should_bonus": round(should_bonus, 4),
        "topic_bonus": round(topic_bonus, 4),
        "route_bonus": round(route_bonus, 4),
        "crypto_diversity_bonus": round(crypto_diversity_bonus, 4),
        "topic_purity_adjust": round(topic_purity_adjust, 4),
        "negative_penalty": round(negative_penalty, 4),
        "systems_neighbor_adjust": round(systems_neighbor_adjust, 4),
        "matched_must_count": sum(1 for item in must_scores if item > 0),
        "matched_topic_count": sum(1 for item in topic_scores if item > 0),
        "blend_mode": blend_mode,
        "query_type": query_type,
        "candidate_sources": candidate_sources,
    }
    return score, debug


def _apply_profile_prototype_diversification(
    ranked: list[dict],
    topic_profile,
    *,
    head_limit: int = 10,
) -> list[dict]:
    if len(ranked) <= 2 or not topic_profile or topic_profile.strategy_type != "broad_aggregate":
        return ranked
    max_per = int(topic_profile.candidate.broad_aggregate_max_per_prototype or 2)
    other_cap = int(topic_profile.candidate.broad_aggregate_other_cap or 3)
    if max_per <= 0:
        return ranked

    head = list(ranked[:head_limit])
    tail = list(ranked[head_limit:])
    bucket_counts: dict[str, int] = {}
    diversified: list[dict] = []
    deferred: list[dict] = []

    for item in head:
        bucket = infer_prototype_bucket(item.get("record") or {}, topic_profile)
        count = bucket_counts.get(bucket, 0)
        cap = other_cap if bucket == "other" else max_per
        if count < cap:
            diversified.append(item)
            bucket_counts[bucket] = count + 1
        else:
            deferred.append(item)

    if deferred:
        remaining = []
        for item in tail:
            bucket = infer_prototype_bucket(item.get("record") or {}, topic_profile)
            count = bucket_counts.get(bucket, 0)
            cap = other_cap if bucket == "other" else max_per
            if len(diversified) < head_limit and count < cap:
                diversified.append(item)
                bucket_counts[bucket] = count + 1
            else:
                remaining.append(item)
        tail = deferred + remaining

    return diversified + tail


def _apply_ai_security_specific_family_cap(
    ranked: list[dict],
    topic_profile,
    *,
    head_limit: int = 10,
) -> list[dict]:
    if len(ranked) <= 2 or not topic_profile or getattr(topic_profile, "topic_id", None) != "ai-security":
        return ranked
    family_head_caps_all = dict(getattr(topic_profile.candidate, "query_specific_family_head_caps", {}) or {})
    if not family_head_caps_all:
        return ranked

    head = list(ranked[:head_limit])
    tail = list(ranked[head_limit:])

    matched_query_buckets: set[str] = set()
    for item in head:
        matched_query_buckets.update(set(item.get("matched_query_prototypes") or []))
    if not matched_query_buckets:
        return ranked

    family_caps: dict[str, int] = {}
    for bid in matched_query_buckets:
        caps = family_head_caps_all.get(bid)
        if isinstance(caps, dict):
            family_caps = {str(k): int(v) for k, v in caps.items()}
            break
    if not family_caps:
        return ranked

    bucket_counts: dict[str, int] = {}
    shaped: list[dict] = []
    deferred: list[dict] = []

    def _cap_for(bucket: str) -> int:
        return max(0, int(family_caps.get(bucket, head_limit)))

    for item in head:
        bucket = infer_prototype_bucket(item.get("record") or {}, topic_profile)
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
            bucket = infer_prototype_bucket(item.get("record") or {}, topic_profile)
            count = bucket_counts.get(bucket, 0)
            cap = _cap_for(bucket)
            if len(shaped) < head_limit and count < cap:
                shaped.append(item)
                bucket_counts[bucket] = count + 1
            else:
                remaining_tail.append(item)
        tail = deferred + remaining_tail

    return shaped + tail


def rerank_scored_results(
    scored: list[dict],
    *,
    query_type: str = "specific",
    topic_profile=None,
    matched_query_prototypes: list[str] | None = None,
) -> tuple[list[dict], dict]:
    strategy = (os.getenv("PAPERRADAR_RERANKER", "feature") or "feature").strip().lower()
    if strategy != "feature":
        strategy = "feature"
    ranked = sorted(
        scored,
        key=lambda item: (
            float(item.get("score") or 0.0),
            len((item.get("record") or {}).get("_candidate_sources") or []),
            (item.get("record") or {}).get("year") or 0,
        ),
        reverse=True,
    )

    if query_type == "generic" and topic_profile is not None:
        ranked = _apply_profile_prototype_diversification(ranked, topic_profile, head_limit=10)
    elif query_type == "specific" and topic_profile is not None and getattr(topic_profile, "topic_id", None) == "ai-security":
        if matched_query_prototypes:
            for item in ranked:
                item["matched_query_prototypes"] = list(matched_query_prototypes)
        ranked = _apply_ai_security_specific_family_cap(ranked, topic_profile, head_limit=10)

    return ranked, {
        "reranker": strategy,
        "query_type": query_type,
        "topic_profile_id": getattr(topic_profile, "topic_id", None),
    }


def _resolve_search_mp_workers() -> int:
    """并行打分进程数：未设置环境变量时默认用多核（上限 4，与 CPU 核数取小）。设为 0 或 1 则关闭进程池。"""
    raw = os.getenv("PAPERRADAR_SEARCH_MP_WORKERS", "").strip()
    if not raw:
        cpu = os.cpu_count() or 4
        return min(4, max(1, cpu))
    try:
        return max(0, int(raw))
    except ValueError:
        cpu = os.cpu_count() or 4
        return min(4, max(1, cpu))


def count_search_records() -> int:
    now = time.time()
    with _records_cache_lock:
        loaded_at = float(_record_count_cache.get("loaded_at") or 0.0)
        cached_count = int(_record_count_cache.get("count") or 0)
        if cached_count > 0 and now - loaded_at < RECORDS_CACHE_TTL_SECONDS:
            return cached_count

        try:
            fresh_count = int(fetch_value("SELECT count(*) AS count FROM papers", default=0) or 0)
        except Exception:
            fresh_count = len(_load_records(include_embeddings=False))

        _record_count_cache["count"] = fresh_count
        _record_count_cache["loaded_at"] = now
        return fresh_count


def load_search_records(include_embeddings: bool = False) -> list[dict]:
    now = time.time()
    with _records_cache_lock:
        cache_entry = _records_cache[include_embeddings]
        loaded_at = float(cache_entry.get("loaded_at") or 0.0)
        cached_records = cache_entry.get("records")
        if isinstance(cached_records, list) and cached_records and now - loaded_at < RECORDS_CACHE_TTL_SECONDS:
            return cached_records

        fresh_records = _load_records(include_embeddings=include_embeddings)
        cache_entry["records"] = fresh_records
        cache_entry["loaded_at"] = now
        return fresh_records


def _prepare_filtered_records(
    records: list[dict] | None,
    *,
    include_embeddings: bool,
    venue_codes: list[str] | None,
    year_from: int | None,
    year_to: int | None,
) -> list[dict]:
    if records is not None:
        filtered = list(records)
    else:
        filtered = _load_records(
            include_embeddings=include_embeddings,
            venue_codes=venue_codes,
            year_from=year_from,
            year_to=year_to,
        )

    if venue_codes:
        venue_set = set(venue_codes)
        filtered = [r for r in filtered if r.get("venue_code") in venue_set]
    if year_from is not None:
        filtered = [r for r in filtered if int(r.get("year", 0)) >= year_from]
    if year_to is not None:
        filtered = [r for r in filtered if int(r.get("year", 0)) <= year_to]
    return filtered


def _emit_progress(progress_callback: Callable[[dict], None] | None, **payload) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(payload)
    except Exception:
        # Progress reporting must never break the main search path.
        return


def _search_metadata_impl(
    query: str,
    venue_codes: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 20,
    must_terms: list[str] | None = None,
    should_terms: list[str] | None = None,
    negative_terms: list[str] | None = None,
    topic_labels: list[str] | None = None,
    records: list[dict] | None = None,
    use_embedding: bool = True,
    query_type: str = "specific",
    progress_callback: Callable[[dict], None] | None = None,
    retrieval_profile: dict | None = None,
) -> tuple[list[dict], dict]:
    profile_obj = profile_from_snapshot(retrieval_profile) if retrieval_profile else None
    if profile_obj is None:
        profile_obj = match_runtime_profile(topic_labels or [], query)
    snapshot = profile_to_serializable_dict(profile_obj) if profile_obj else None

    candidate_count = 0
    query_embedding_cache_before = get_query_embedding_cache_stats() if use_embedding else None
    if use_embedding:
        _emit_progress(
            progress_callback,
            progress=0.18,
            stage="embedding",
            message="生成查询向量",
            candidate_count=candidate_count,
        )
        try:
            query_embedding = get_embedding_provider().embed_text(query)
        except Exception:
            query_embedding = []
            use_embedding = False
    else:
        query_embedding = []
    query_embedding_cache_after = get_query_embedding_cache_stats() if query_embedding_cache_before is not None else None

    records, candidate_summary = retrieve_metadata_candidates(
        query,
        query_embedding=query_embedding,
        venue_codes=venue_codes,
        year_from=year_from,
        year_to=year_to,
        limit=limit,
        must_terms=must_terms,
        should_terms=should_terms,
        negative_terms=negative_terms,
        topic_labels=topic_labels,
        records=records,
        use_embedding=use_embedding,
        query_type=query_type,
        topic_profile=profile_obj,
    )
    retrieval_backend = str(candidate_summary.get("backend") or "python_scan")
    using_pgvector = retrieval_backend.startswith("pgvector")
    candidate_count = len(records or [])

    if candidate_summary.get("strategy") == "candidate_union":
        _emit_progress(
            progress_callback,
            progress=0.08,
            stage="prepare_candidates",
            message=f"多路召回合并出 {candidate_count} 条候选记录",
            candidate_count=candidate_count,
            retrieval_backend=retrieval_backend,
            route_counts=candidate_summary.get("route_counts"),
        )
    else:
        _emit_progress(
            progress_callback,
            progress=0.08,
            stage="prepare_candidates",
            message=f"筛出 {candidate_count} 条候选记录",
            candidate_count=candidate_count,
            retrieval_backend=retrieval_backend,
            route_counts=candidate_summary.get("route_counts"),
        )

    if use_embedding and query_embedding:
        records = _hydrate_candidate_embeddings(records or [])
        supplemental_scores = _batch_embedding_cosine(query_embedding, records or [])
        embedding_scores: list[float | None] = []
        for record, supplemental in zip(records or [], supplemental_scores):
            stored_score = record.get("_embedding_score")
            if stored_score is not None and float(stored_score) > -1:
                embedding_scores.append(float(stored_score))
            else:
                embedding_scores.append(supplemental)
        _emit_progress(
            progress_callback,
            progress=0.36,
            stage="embedding_ready",
            message="已完成语义向量匹配" if not using_pgvector else "已完成 pgvector + 其他候选混合召回",
            candidate_count=candidate_count,
            retrieval_backend=retrieval_backend,
        )
    else:
        embedding_scores = [None] * len(records or [])
        _emit_progress(
            progress_callback,
            progress=0.32,
            stage="keyword_only",
            message="当前使用纯词法检索",
            candidate_count=candidate_count,
        )

    mp_workers = _resolve_search_mp_workers()
    mp_min = max(1, int(os.getenv("PAPERRADAR_SEARCH_MP_MIN_RECORDS", "200")))
    n = len(records or [])
    if mp_workers > 1 and n >= mp_min:
        chunk_size = max(1, (n + mp_workers - 1) // mp_workers)
        chunks: list[tuple] = []
        for offset in range(0, n, chunk_size):
            sl = (records or [])[offset : offset + chunk_size]
            es = embedding_scores[offset : offset + chunk_size]
            matched_query_prototypes = sorted(_query_matched_prototype_terms(query, profile_obj, extra_terms=(topic_labels or []) + (must_terms or []) + (should_terms or []))) if profile_obj else []
            chunks.append(
                (query, sl, es, topic_labels, query_type, must_terms, should_terms, negative_terms, snapshot, matched_query_prototypes)
            )
        _emit_progress(
            progress_callback,
            progress=0.42,
            stage="scoring",
            message=f"并行打分中（{len(chunks)} 个分片）",
            candidate_count=candidate_count,
            completed_chunks=0,
            total_chunks=len(chunks),
        )
        parts: list[list[dict]] = []
        with ProcessPoolExecutor(max_workers=mp_workers) as executor:
            futures = [executor.submit(_score_metadata_chunk, chunk) for chunk in chunks]
            total_chunks = len(futures)
            completed_chunks = 0
            for future in as_completed(futures):
                parts.append(future.result())
                completed_chunks += 1
                local_progress = 0.42 + 0.46 * (completed_chunks / total_chunks)
                _emit_progress(
                    progress_callback,
                    progress=local_progress,
                    stage="scoring",
                    message=f"并行打分中（{completed_chunks}/{total_chunks}）",
                    candidate_count=candidate_count,
                    completed_chunks=completed_chunks,
                    total_chunks=total_chunks,
                )
        scored = [item for part in parts for item in part]
    else:
        _emit_progress(
            progress_callback,
            progress=0.48,
            stage="scoring",
            message="单进程打分中",
            candidate_count=candidate_count,
        )
        matched_query_prototypes = sorted(_query_matched_prototype_terms(query, profile_obj, extra_terms=(topic_labels or []) + (must_terms or []) + (should_terms or []))) if profile_obj else []
        scored = _build_scored_results(
            query,
            records or [],
            embedding_scores,
            topic_labels,
            query_type,
            must_terms,
            should_terms,
            negative_terms,
            retrieval_profile=snapshot,
            matched_query_prototypes=matched_query_prototypes,
        )
        _emit_progress(
            progress_callback,
            progress=0.84,
            stage="scoring",
            message="打分完成，正在排序",
            candidate_count=candidate_count,
        )

    ranked, rerank_summary = rerank_scored_results(scored, query_type=query_type, topic_profile=profile_obj)
    _emit_progress(
        progress_callback,
        progress=1.0,
        stage="done",
        message="候选排序完成",
        candidate_count=candidate_count,
        result_count=min(limit, len(ranked)),
    )
    query_embedding_cache_delta = None
    if query_embedding_cache_before is not None and query_embedding_cache_after is not None:
        keys = set(query_embedding_cache_before) | set(query_embedding_cache_after)
        query_embedding_cache_delta = {
            key: int(query_embedding_cache_after.get(key, 0)) - int(query_embedding_cache_before.get(key, 0))
            for key in sorted(keys)
        }
    summary = {
        "candidate_generation": candidate_summary,
        "rerank": rerank_summary,
        "candidate_count": candidate_count,
        "result_count": min(limit, len(ranked)),
        "retrieval_backend": retrieval_backend,
        "query_embedding_cache": {
            "enabled": bool(use_embedding),
            "provider": os.getenv("PAPERRADAR_EMBEDDING_PROVIDER", "google"),
            "model": os.getenv("PAPERRADAR_EMBEDDING_MODEL", "gemini-embedding-001"),
            "stats_before": query_embedding_cache_before,
            "stats_after": query_embedding_cache_after,
            "stats_delta": query_embedding_cache_delta,
            "cache_hit": bool(query_embedding_cache_delta and query_embedding_cache_delta.get("hits", 0) > 0),
            "cache_miss": bool(query_embedding_cache_delta and query_embedding_cache_delta.get("misses", 0) > 0),
            "cache_write": bool(query_embedding_cache_delta and query_embedding_cache_delta.get("writes", 0) > 0),
        },
    }
    return ranked[:limit], summary


def search_metadata_with_summary(
    query: str,
    venue_codes: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 20,
    must_terms: list[str] | None = None,
    should_terms: list[str] | None = None,
    negative_terms: list[str] | None = None,
    topic_labels: list[str] | None = None,
    records: list[dict] | None = None,
    use_embedding: bool = True,
    query_type: str = "specific",
    progress_callback: Callable[[dict], None] | None = None,
    retrieval_profile: dict | None = None,
) -> tuple[list[dict], dict]:
    return _search_metadata_impl(
        query=query,
        venue_codes=venue_codes,
        year_from=year_from,
        year_to=year_to,
        limit=limit,
        must_terms=must_terms,
        should_terms=should_terms,
        negative_terms=negative_terms,
        topic_labels=topic_labels,
        records=records,
        use_embedding=use_embedding,
        query_type=query_type,
        progress_callback=progress_callback,
        retrieval_profile=retrieval_profile,
    )


def search_metadata(
    query: str,
    venue_codes: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 20,
    must_terms: list[str] | None = None,
    should_terms: list[str] | None = None,
    negative_terms: list[str] | None = None,
    topic_labels: list[str] | None = None,
    records: list[dict] | None = None,
    use_embedding: bool = True,
    query_type: str = "specific",
    progress_callback: Callable[[dict], None] | None = None,
) -> list[dict]:
    rows, _summary = _search_metadata_impl(
        query=query,
        venue_codes=venue_codes,
        year_from=year_from,
        year_to=year_to,
        limit=limit,
        must_terms=must_terms,
        should_terms=should_terms,
        negative_terms=negative_terms,
        topic_labels=topic_labels,
        records=records,
        use_embedding=use_embedding,
        query_type=query_type,
        progress_callback=progress_callback,
    )
    return rows
