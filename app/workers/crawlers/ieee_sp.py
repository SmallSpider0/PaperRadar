from __future__ import annotations

from bs4 import BeautifulSoup

from workers.fetch_html import fetch_html
from workers.schemas import PaperRecord


ACCEPTED_PAPERS_URL = "https://www.ieee-security.org/TC/SP2025/accepted-papers.html"


def crawl_ieee_sp_2025() -> list[PaperRecord]:
    html = fetch_html(ACCEPTED_PAPERS_URL)
    soup = BeautifulSoup(html, "lxml")
    records: list[PaperRecord] = []

    for link in soup.select("div b a[href]"):
        href = (link.get("href") or "").strip()
        title = " ".join(link.get_text(" ", strip=True).split())
        if not href or not title:
            continue
        if href == "accepted-papers.html":
            continue

        paper_url = f"{ACCEPTED_PAPERS_URL}{href}" if href.startswith("#") else (
            href if href.startswith("http") else f"https://www.ieee-security.org/TC/SP2025/{href.lstrip('./')}"
        )

        parent = link.parent
        if parent is None or parent.name != "b":
            continue

        item_container = parent.parent
        authors_text = None
        if item_container:
            inner_divs = item_container.find_all("div", recursive=False)
            if len(inner_divs) >= 2:
                authors_text = " ".join(inner_divs[1].get_text(" ", strip=True).split()) or None

        records.append(
            PaperRecord(
                source="ieee_sp",
                venue_code="IEEE_SP",
                year=2025,
                title=title,
                paper_url=paper_url,
                authors_text=authors_text,
                source_pdf_url=None,
            )
        )

    unique: dict[str, PaperRecord] = {}
    for item in records:
        unique[item.paper_url] = item
    return list(unique.values())
