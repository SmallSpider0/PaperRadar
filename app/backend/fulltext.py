from __future__ import annotations

import hashlib
import json
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text_to_fp

from backend.chunking import chunk_text
from backend.embedding import get_embedding_provider
from backend.env import load_local_env


load_local_env()

BASE_DIR = Path(__file__).resolve().parents[2]
GENERATED_DIR = BASE_DIR / "data" / "generated"
PAPERS_DIR = BASE_DIR / "storage" / "papers"
PARSED_DIR = BASE_DIR / "data" / "parsed"
FULLTEXT_RETRIEVAL_CONTRACT_VERSION = 1


def _load_records() -> list[dict]:
    records: list[dict] = []
    for path in GENERATED_DIR.glob("*_normalized.json"):
        records.extend(json.loads(path.read_text(encoding="utf-8")))
    return records


def find_record_by_url(paper_url: str) -> dict | None:
    for record in _load_records():
        if record.get("paper_url") == paper_url:
            return record
    return None


def safe_paper_id(paper_url: str) -> str:
    digest = hashlib.sha256(paper_url.encode("utf-8")).hexdigest()[:16]
    return f"paper_{digest}"


def _detect_pdf_url_from_html(html: str, page_url: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    for link in soup.select("a[href]"):
        href = (link.get("href") or "").strip()
        text = " ".join(link.get_text(" ", strip=True).split()).lower()
        if href.lower().endswith(".pdf") or text in {"paper", "pdf", "download pdf"}:
            if href.startswith("http"):
                return href
            parsed_page = urlparse(page_url)
            return f"{parsed_page.scheme}://{parsed_page.netloc}{href}"
    return None


def fetch_fulltext_by_url(paper_url: str, pdf_url: str | None = None) -> dict:
    record = find_record_by_url(paper_url)
    if not record:
        raise ValueError("paper record not found")

    if record.get("content_policy") == "metadata_only":
        raise ValueError("content policy forbids fulltext fetch")

    target_url = pdf_url or record.get("source_pdf_url") or paper_url
    paper_id = safe_paper_id(paper_url)
    outdir = PAPERS_DIR / paper_id
    outdir.mkdir(parents=True, exist_ok=True)

    response = requests.get(target_url, timeout=60, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    })
    response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if "text/html" in content_type and not pdf_url:
        discovered_pdf = _detect_pdf_url_from_html(response.text, target_url)
        if discovered_pdf:
            pdf_response = requests.get(discovered_pdf, timeout=60, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            })
            pdf_response.raise_for_status()
            response = pdf_response
            target_url = discovered_pdf
            content_type = response.headers.get("content-type", "")

    parsed = urlparse(target_url)
    ext = ".pdf" if target_url.lower().endswith(".pdf") or "pdf" in content_type.lower() else ".html"
    outfile = outdir / f"source{ext}"
    outfile.write_bytes(response.content)

    sha256 = hashlib.sha256(response.content).hexdigest()
    status = {
        "paper_url": paper_url,
        "paper_id": paper_id,
        "source_url": target_url,
        "storage_path": str(outfile),
        "sha256": sha256,
        "size_bytes": len(response.content),
        "content_type": content_type,
        "host": parsed.netloc,
        "fulltext_status": "downloaded",
    }
    status_path = outdir / "status.json"
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


def _extract_pdf_text(source_path: Path) -> str:
    output = StringIO()
    with source_path.open("rb") as f:
        extract_text_to_fp(f, output)
    return output.getvalue()


def parse_saved_fulltext(paper_id: str) -> dict:
    outdir = PAPERS_DIR / paper_id
    status_path = outdir / "status.json"
    if not status_path.exists():
        raise ValueError("fulltext status not found")

    status = json.loads(status_path.read_text(encoding="utf-8"))
    source_path = Path(status["storage_path"])
    if not source_path.exists():
        raise ValueError("saved source file not found")

    if source_path.suffix.lower() == ".html":
        text = source_path.read_text(encoding="utf-8", errors="ignore")
    elif source_path.suffix.lower() == ".pdf":
        text = _extract_pdf_text(source_path)
    else:
        text = ""

    chunks = chunk_text(text)
    provider = get_embedding_provider()
    embedded_chunks = []
    for index, chunk in enumerate(chunks[:10]):
        try:
            embedding = provider.embed_text(chunk)
        except Exception:
            embedding = None
        embedded_chunks.append({
            "chunk_index": index,
            "text": chunk,
            "embedding": embedding,
        })

    parsed_payload = {
        "paper_id": paper_id,
        "source_path": str(source_path),
        "parsed_text_preview": text[:5000],
        "chunk_count": len(chunks),
        "chunks": embedded_chunks,
        "fulltext_status": "parsed",
    }
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    parsed_path = PARSED_DIR / f"{paper_id}.json"
    parsed_path.write_text(json.dumps(parsed_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    status["fulltext_status"] = "parsed"
    status["parsed_path"] = str(parsed_path)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


def get_fulltext_retrieval_capabilities() -> dict:
    return {
        "contract_version": FULLTEXT_RETRIEVAL_CONTRACT_VERSION,
        "enabled": False,
        "reason": "fulltext_data_not_ready",
        "supported_sources": [],
        "paper_level_aggregation": "reserved_only",
    }


def retrieve_fulltext_candidates(
    query: str,
    *,
    paper_ids: list[str] | None = None,
    top_k: int = 20,
) -> dict:
    return {
        "query": query,
        "paper_ids": list(paper_ids or []),
        "top_k": max(1, int(top_k)),
        "results": [],
        "capabilities": get_fulltext_retrieval_capabilities(),
    }


def get_fulltext_status(paper_id: str) -> dict:
    status_path = PAPERS_DIR / paper_id / "status.json"
    if not status_path.exists():
        return {"paper_id": paper_id, "fulltext_status": "not_requested"}
    return json.loads(status_path.read_text(encoding="utf-8"))
