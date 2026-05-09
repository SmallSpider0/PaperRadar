from __future__ import annotations

from bs4 import BeautifulSoup

from workers.fetch_html import fetch_html
from workers.schemas import PaperRecord


ACCEPTED_PAPERS_URL = "https://www.ndss-symposium.org/ndss2025/accepted-papers/"


def crawl_ndss_2025() -> list[PaperRecord]:
    html = fetch_html(ACCEPTED_PAPERS_URL)
    soup = BeautifulSoup(html, "lxml")
    records: list[PaperRecord] = []

    for link in soup.select("a[href]"):
        href = link.get("href", "").strip()
        title = " ".join(link.get_text(" ", strip=True).split())
        if not href or not title:
            continue
        if "/ndss-paper/" not in href and "/wp-content/uploads/" not in href:
            continue
        paper_url = href if href.startswith("http") else f"https://www.ndss-symposium.org{href}"
        records.append(
            PaperRecord(
                source="ndss",
                venue_code="NDSS",
                year=2025,
                title=title,
                paper_url=paper_url,
            )
        )

    unique = {}
    for item in records:
        unique[item.paper_url] = item
    return list(unique.values())
