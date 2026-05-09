from __future__ import annotations

import json
import re
from pathlib import Path

from backend.fulltext import PAPERS_DIR, PARSED_DIR, _load_records, safe_paper_id


def _find_record_by_paper_id(paper_id: str) -> dict | None:
    for record in _load_records():
        if safe_paper_id(record.get("paper_url", "")) == paper_id:
            return record
    return None


def _normalize_text(raw_text: str) -> str:
    text = raw_text.replace("\x0c", "\n\n")
    text = re.sub(r"(?<=[a-z])-(?=[a-z])", "", text)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([a-z])([0-9])", r"\1 \2", text)
    text = re.sub(r"([0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([^\n\s]{2,})(\f|\n)([^\n\s]{2,})", r"\1 \3", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_paragraphs(text: str) -> list[str]:
    chunks = re.split(r"\n\s*\n", text)
    paragraphs: list[str] = []
    for chunk in chunks:
        cleaned = chunk.strip()
        if not cleaned:
            continue
        if len(cleaned) > 1200:
            sentences = re.split(r"(?<=[.!?])\s+", cleaned)
            buffer = ""
            for sentence in sentences:
                candidate = f"{buffer} {sentence}".strip() if buffer else sentence.strip()
                if len(candidate) > 900 and buffer:
                    paragraphs.append(buffer.strip())
                    buffer = sentence.strip()
                else:
                    buffer = candidate
            if buffer:
                paragraphs.append(buffer.strip())
        else:
            paragraphs.append(cleaned)
    return paragraphs


def get_reader_payload(paper_id: str) -> dict:
    parsed_path = PARSED_DIR / f"{paper_id}.json"
    if not parsed_path.exists():
        raise ValueError("parsed fulltext not found")

    parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
    record = _find_record_by_paper_id(paper_id)

    preview_text = parsed.get("parsed_text_preview") or ""
    normalized_preview = _normalize_text(preview_text)
    paragraphs = _split_paragraphs(normalized_preview)

    stored_chunks = parsed.get("chunks") or []
    reader_chunks = [
        {
            "chunk_index": chunk.get("chunk_index"),
            "text": _normalize_text(chunk.get("text", "")),
        }
        for chunk in stored_chunks
        if (chunk.get("text") or "").strip()
    ]

    status_path = PAPERS_DIR / paper_id / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}

    return {
        "paper_id": paper_id,
        "paper": {
            "title": record.get("title") if record else paper_id,
            "paper_url": record.get("paper_url") if record else None,
            "venue_code": record.get("venue_code") if record else None,
            "year": record.get("year") if record else None,
            "authors_text": record.get("authors_text") if record else None,
            "abstract": record.get("abstract") if record else None,
            "source_pdf_url": record.get("source_pdf_url") if record else None,
        },
        "status": {
            "fulltext_status": status.get("fulltext_status", "parsed"),
            "source_url": status.get("source_url"),
            "storage_path": status.get("storage_path"),
            "parsed_path": str(parsed_path),
        },
        "preview": {
            "text": normalized_preview,
            "paragraphs": paragraphs,
        },
        "chunks": reader_chunks,
        "chunk_count": parsed.get("chunk_count", len(reader_chunks)),
    }
