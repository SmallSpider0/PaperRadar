from __future__ import annotations

import json
import re

import requests

from workers.schemas import PaperRecord

ACCEPTED_PAPERS_JSON_URL = "https://www.sigsac.org/ccs/CCS2025/assets/accepted-papers.json"
USER_AGENT = "PaperRadar/0.1 (metadata crawl; contact: 568442079@qq.com)"


def _clean_title(title: str) -> str:
    title = (title or "").strip()
    title = re.sub(r"^\(#\d+\)\s*", "", title)
    title = re.sub(r"\s+", " ", title)
    return title


def _load_payload() -> dict:
    response = requests.get(
        ACCEPTED_PAPERS_JSON_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def crawl_ccs_2025() -> list[PaperRecord]:
    payload = _load_payload()
    records: list[PaperRecord] = []

    for cycle_name in ["firstCycle", "secondCycle"]:
        for item in payload.get(cycle_name, []) or []:
            title = _clean_title(item.get("title") or "")
            paper_url = (item.get("url") or "").strip()
            authors_text = (item.get("full") or "").strip() or None
            if not title or not paper_url:
                continue
            records.append(
                PaperRecord(
                    source="acm_ccs",
                    venue_code="ACM_CCS",
                    year=2025,
                    title=title,
                    paper_url=paper_url,
                    authors_text=authors_text,
                )
            )

    unique: dict[str, PaperRecord] = {}
    for item in records:
        unique[item.paper_url] = item
    return list(unique.values())
