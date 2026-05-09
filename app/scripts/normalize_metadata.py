#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


REQUIRED_KEYS = [
    "source",
    "venue_code",
    "year",
    "title",
    "paper_url",
]


def normalize_record(record: dict) -> dict:
    normalized = {key: record.get(key) for key in REQUIRED_KEYS}
    normalized["abstract"] = record.get("abstract")
    normalized["authors_text"] = record.get("authors_text")
    normalized["source_pdf_url"] = record.get("source_pdf_url")
    normalized["content_policy"] = record.get("content_policy", "on_demand_allowed")
    return normalized


def main() -> None:
    raw_dir = Path(__file__).resolve().parents[2] / "data" / "raw"
    out_dir = Path(__file__).resolve().parents[2] / "data" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)

    for path in raw_dir.glob("*_metadata.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        out_path = out_dir / path.name.replace("_metadata", "_normalized")
        existing_by_url = {}
        if out_path.exists():
            try:
                existing_payload = json.loads(out_path.read_text(encoding="utf-8"))
                existing_by_url = {
                    item.get("paper_url"): item
                    for item in existing_payload
                    if item.get("paper_url")
                }
            except Exception:
                existing_by_url = {}

        normalized = []
        for item in payload:
            row = normalize_record(item)
            existing = existing_by_url.get(row.get("paper_url"))
            if existing:
                if not row.get("abstract") and existing.get("abstract"):
                    row["abstract"] = existing.get("abstract")
                if not row.get("authors_text") and existing.get("authors_text"):
                    row["authors_text"] = existing.get("authors_text")
                if not row.get("source_pdf_url") and existing.get("source_pdf_url"):
                    row["source_pdf_url"] = existing.get("source_pdf_url")
                if not row.get("embedding") and existing.get("embedding"):
                    row["embedding"] = existing.get("embedding")
            normalized.append(row)

        out_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"normalized {path.name} -> {out_path.name} ({len(normalized)})")


if __name__ == "__main__":
    main()
