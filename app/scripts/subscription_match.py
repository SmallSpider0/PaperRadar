#!/usr/bin/env python3
from __future__ import annotations

import json

from backend.subscriptions import run_subscription_matching


if __name__ == "__main__":
    print(json.dumps(run_subscription_matching(), ensure_ascii=False, indent=2))
