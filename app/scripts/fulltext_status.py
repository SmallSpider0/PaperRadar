#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from backend.fulltext import get_fulltext_status


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: fulltext_status.py <paper_id>")
    result = get_fulltext_status(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
