#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.query_translation import cleanup_expired_query_translation_cache


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean expired query translation cache rows.")
    parser.add_argument("--limit", type=int, default=None, help="Optional max rows to delete in one run")
    parser.add_argument("--cron", action="store_true", help="Print a recommended cron entry and exit")
    args = parser.parse_args()
    if args.cron:
        print("30 3 * * * cd /opt/paperradar/app && PYTHONPATH=. python3 scripts/cleanup_query_translation_cache.py >> /var/log/paperradar-query-translation-cache-cleanup.log 2>&1")
        return 0
    deleted = cleanup_expired_query_translation_cache(limit=args.limit)
    print(f"deleted={deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
