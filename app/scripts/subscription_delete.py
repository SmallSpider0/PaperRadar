#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from backend.subscriptions import delete_subscription


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: subscription_delete.py <subscription_id>")
    print(json.dumps(delete_subscription(sys.argv[1]), ensure_ascii=False, indent=2))
