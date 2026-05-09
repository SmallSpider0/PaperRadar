#!/usr/bin/env python3
from __future__ import annotations

import json

from backend.subscriptions import list_subscriptions


if __name__ == "__main__":
    print(json.dumps(list_subscriptions(), ensure_ascii=False, indent=2))
