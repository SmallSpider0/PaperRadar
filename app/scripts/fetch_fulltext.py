#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from backend.fulltext import fetch_fulltext_by_url


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: fetch_fulltext.py <paper_url> [pdf_url]")
    paper_url = sys.argv[1]
    pdf_url = sys.argv[2] if len(sys.argv) > 2 else None
    result = fetch_fulltext_by_url(paper_url=paper_url, pdf_url=pdf_url)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
