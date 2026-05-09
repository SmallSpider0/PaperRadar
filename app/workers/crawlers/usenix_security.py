from __future__ import annotations

from bs4 import BeautifulSoup

from workers.fetch_html import fetch_html
from workers.schemas import PaperRecord


TECHNICAL_SESSIONS_URL = "https://www.usenix.org/conference/usenixsecurity25/technical-sessions"


def crawl_usenix_security_2025() -> list[PaperRecord]:
    html = fetch_html(TECHNICAL_SESSIONS_URL)
    soup = BeautifulSoup(html, "lxml")
    records: list[PaperRecord] = []

    for link in soup.select("a[href*='/conference/usenixsecurity25/presentation/']"):
        title = " ".join(link.get_text(" ", strip=True).split())
        href = link.get("href", "").strip()
        if not title or not href:
            continue
        paper_url = href if href.startswith("http") else f"https://www.usenix.org{href}"
        records.append(
            PaperRecord(
                source="usenix",
                venue_code="USENIX_SECURITY",
                year=2025,
                title=title,
                paper_url=paper_url,
            )
        )

    unique = {}
    for item in records:
        unique[item.paper_url] = item
    return list(unique.values())
