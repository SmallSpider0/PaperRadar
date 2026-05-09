#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.embedding import get_embedding_provider


def main() -> None:
    provider = get_embedding_provider()
    generated_dir = Path(__file__).resolve().parents[2] / "data" / "generated"
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    for path in generated_dir.glob("*_normalized.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        enriched = []
        working = payload[:limit] if limit > 0 else payload
        untouched = payload[limit:] if limit > 0 else []
        for item in working:
            text = f"{item.get('title', '')}\n\n{item.get('abstract') or ''}".strip()
            item["embedding"] = provider.embed_text(text)
            enriched.append(item)
        final_payload = enriched + untouched if limit > 0 else enriched
        path.write_text(json.dumps(final_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"embedded {path.name}: {len(enriched)} records (limit={limit or 'all'})")


if __name__ == "__main__":
    main()
