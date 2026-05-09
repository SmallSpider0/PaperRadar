from __future__ import annotations

import html
import re
import unicodedata
from typing import Any

import requests

USER_AGENT = "PaperRadar/0.1 (metadata enrichment; contact: 568442079@qq.com)"
OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/works"

MOJIBAKE_REPLACEMENTS = {
    "â": "'",
    "â": "'",
    "â": '"',
    "â": '"',
    "â": "-",
    "â": "-",
    "Ã": "É",
    "Ã©": "é",
    "â€™": "'",
    "â€œ": '"',
    "â€": '"',
    "â€": '"',
}


def _fix_mojibake(text: str) -> str:
    out = text or ""
    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        out = out.replace(bad, good)
    return out


def _ascii_fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _normalize_title(text: str) -> str:
    text = html.unescape(_fix_mojibake(text or ""))
    text = _ascii_fold(text)
    text = text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("tls-layer", "tls layer")
    text = text.replace("check-before-you-solve", "check before you solve")
    text = re.sub(r"[`´]", "'", text)
    text = re.sub(r"[$]O\(n\^2\)[$]", "o n 2", text, flags=re.I)
    text = re.sub(r"\$[^$]+\$", " ", text)
    text = re.sub(r"[^\w\s-]", " ", text, flags=re.UNICODE)
    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def _title_similarity(a: str, b: str) -> float:
    na = _normalize_title(a)
    nb = _normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    set_a = set(na.split())
    set_b = set(nb.split())
    if not set_a or not set_b:
        return 0.0
    overlap = len(set_a & set_b) / max(len(set_a), len(set_b))
    coverage = len(set_a & set_b) / min(len(set_a), len(set_b))
    prefix_bonus = 0.1 if na[:48] == nb[:48] else 0.0
    contains_bonus = 0.1 if na in nb or nb in na else 0.0
    return min(1.0, 0.55 * overlap + 0.25 * coverage + prefix_bonus + contains_bonus)


def _reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    if not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, indexes in inverted_index.items():
        for index in indexes:
            positions[index] = word
    if not positions:
        return None
    words = [positions[i] for i in sorted(positions.keys())]
    return html.unescape(" ".join(words)).strip() or None


def _clean_abstract(text: str | None) -> str | None:
    if not text:
        return None
    text = html.unescape(text)
    text = re.sub(r"</?(jats:)?[^>]+>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _venue_matches_name(venue: str, venue_code: str) -> bool:
    venue = _normalize_title(venue)
    if venue_code == "IEEE_SP":
        return "security and privacy" in venue or "ieee symposium on security and privacy" in venue
    return False


def _venue_matches(work: dict[str, Any], venue_code: str) -> bool:
    candidates = [
        ((work.get("primary_location") or {}).get("source") or {}).get("display_name") or "",
        work.get("host_venue", {}).get("display_name") or "",
        work.get("biblio", {}).get("venue") or "",
    ]
    return any(_venue_matches_name(name, venue_code) for name in candidates if name)


def find_best_openalex_match(title: str, venue_code: str, year: int) -> dict[str, Any] | None:
    params = {
        "search": _fix_mojibake(title),
        "per-page": 10,
        "filter": f"publication_year:{year}",
    }
    resp = requests.get(OPENALEX_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("results", [])

    best = None
    best_score = 0.0
    for work in results:
        work_title = work.get("title") or ""
        score = _title_similarity(title, work_title)
        if _venue_matches(work, venue_code):
            score += 0.2
        if score > best_score:
            best = work
            best_score = score

    return best if best_score >= 0.62 else None


def _crossref_authors(item: dict[str, Any]) -> str | None:
    authors = []
    for author in item.get("author") or []:
        given = (author.get("given") or "").strip()
        family = (author.get("family") or "").strip()
        name = " ".join(part for part in [given, family] if part).strip() or (author.get("name") or "").strip()
        if name:
            authors.append(name)
    return ", ".join(authors) if authors else None


def find_best_crossref_match(title: str, venue_code: str, year: int) -> dict[str, Any] | None:
    params = {
        "query.title": _fix_mojibake(title),
        "rows": 10,
        "filter": f"from-pub-date:{year}-01-01,until-pub-date:{year}-12-31",
    }
    resp = requests.get(CROSSREF_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    items = ((resp.json() or {}).get("message") or {}).get("items") or []

    best = None
    best_score = 0.0
    for item in items:
        item_title = ((item.get("title") or [""]) or [""])[0]
        score = _title_similarity(title, item_title)
        containers = item.get("container-title") or []
        if any(_venue_matches_name(name, venue_code) for name in containers):
            score += 0.2
        if score > best_score:
            best = item
            best_score = score

    return best if best_score >= 0.62 else None


def enrich_record_with_openalex(record: dict[str, Any]) -> dict[str, Any]:
    record["title"] = _fix_mojibake(record.get("title", ""))
    if record.get("authors_text"):
        record["authors_text"] = _fix_mojibake(record.get("authors_text", ""))

    work = find_best_openalex_match(record.get("title", ""), record.get("venue_code", ""), int(record.get("year") or 0))
    if work:
        abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))
        if abstract and not record.get("abstract"):
            record["abstract"] = abstract

        if not record.get("authors_text"):
            authors = [item.get("author", {}).get("display_name") for item in (work.get("authorships") or [])]
            authors = [name for name in authors if name]
            if authors:
                record["authors_text"] = ", ".join(authors)

    if not record.get("abstract") or not record.get("authors_text"):
        item = find_best_crossref_match(record.get("title", ""), record.get("venue_code", ""), int(record.get("year") or 0))
        if item:
            if not record.get("abstract"):
                abstract = _clean_abstract(item.get("abstract"))
                if abstract:
                    record["abstract"] = abstract
            if not record.get("authors_text"):
                authors_text = _crossref_authors(item)
                if authors_text:
                    record["authors_text"] = authors_text

    return record
