from __future__ import annotations

from backend.chat_models import (
    CandidateFilterResponse,
    ComparePapersResponse,
    CompareRow,
    RetrievalPaper,
)
from backend.search import load_search_records


def _record_to_retrieval_paper(record: dict, score: float = 0.0) -> RetrievalPaper:
    return RetrievalPaper(
        paper_id=record.get("id"),
        title=record.get("title") or "",
        abstract=record.get("abstract"),
        authors_text=record.get("authors_text"),
        venue_code=record.get("venue_code"),
        year=record.get("year"),
        paper_url=record.get("paper_url"),
        source_pdf_url=record.get("source_pdf_url"),
        content_policy=record.get("content_policy"),
        score=float(score or 0.0),
        topic_tags=list(record.get("topic_tags") or []),
        topic_summary=record.get("topic_summary"),
        match_reasons=[],
    )


def filter_or_rerank_candidates(candidate_ids: list[str], instruction: str, limit: int = 8) -> CandidateFilterResponse:
    records = load_search_records()
    by_id = {record.get("id"): record for record in records if record.get("id")}
    selected = [by_id[cid] for cid in candidate_ids if cid in by_id]
    lowered = (instruction or "").lower()

    def sort_key(record: dict) -> tuple:
        tags = [str(item).lower() for item in (record.get("topic_tags") or [])]
        title = str(record.get("title") or "").lower()
        abstract = str(record.get("abstract") or "").lower()
        summary = str(record.get("topic_summary") or "").lower()
        corpus = " ".join([title, abstract, summary, " ".join(tags)])

        practical_bonus = 1 if any(token in corpus for token in ["system", "deployment", "practical", "implementation", "real-world", "工程", "部署", "系统"]) else 0
        survey_penalty = 1 if any(token in corpus for token in ["survey", "overview", "benchmark", "综述"]) else 0
        defense_bonus = 1 if any(token in corpus for token in ["defense", "mitigation", "guardrail", "防御", "缓解"]) else 0
        attack_penalty = 1 if any(token in corpus for token in ["attack", "attacks", "attacking", "攻击"]) else 0

        if "practical" in lowered or "工程" in lowered or "部署" in lowered:
            return (practical_bonus, defense_bonus, -survey_penalty, -attack_penalty, record.get("year") or 0)
        if "survey" in lowered or "综述" in lowered:
            return (survey_penalty, record.get("year") or 0)
        if "defense" in lowered or "防御" in lowered:
            return (defense_bonus, -attack_penalty, record.get("year") or 0)
        return (record.get("year") or 0, practical_bonus, defense_bonus)

    ranked = sorted(selected, key=sort_key, reverse=True)
    kept = ranked[: max(int(limit or 8), 1)]
    kept_ids = {record.get("id") for record in kept}
    removed = [cid for cid in candidate_ids if cid not in kept_ids]
    return CandidateFilterResponse(
        instruction=instruction,
        results=[_record_to_retrieval_paper(record) for record in kept],
        removed_candidates=removed,
        summary=f"kept {len(kept)} of {len(selected)} candidates",
    )


def compare_papers(paper_ids: list[str], compare_dimensions: list[str] | None = None) -> ComparePapersResponse:
    records = load_search_records()
    by_id = {record.get("id"): record for record in records if record.get("id")}
    dimensions = list(compare_dimensions or [])
    rows: list[CompareRow] = []
    for pid in paper_ids:
        record = by_id.get(pid)
        if not record:
            continue
        topic_tags = list(record.get("topic_tags") or [])
        summary = record.get("topic_summary") or record.get("abstract") or ""
        rows.append(
            CompareRow(
                paper_id=record.get("id"),
                title=record.get("title") or "",
                venue_code=record.get("venue_code"),
                year=record.get("year"),
                problem=topic_tags[0] if topic_tags else None,
                approach=summary[:180] if summary else None,
                setting=record.get("venue_code"),
                strengths=[item for item in topic_tags[:3]],
                limitations=["needs deeper paper-level comparison"],
                notable_difference=(f"focuses on {topic_tags[0]}" if topic_tags else None),
            )
        )
    return ComparePapersResponse(
        paper_ids=paper_ids,
        compare_dimensions=dimensions,
        rows=rows,
        summary=f"prepared comparison scaffold for {len(rows)} papers",
    )
