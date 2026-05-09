#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from backend.search import search_metadata


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: search_metadata.py <query>")
    query = " ".join(sys.argv[1:])
    results = search_metadata(query=query)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
