#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from backend.subscriptions import create_subscription


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("Usage: subscription_create.py <name> <query>")
    name = sys.argv[1]
    query = " ".join(sys.argv[2:])
    result = create_subscription(name=name, query_text=query)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
