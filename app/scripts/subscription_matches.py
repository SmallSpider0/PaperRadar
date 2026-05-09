#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from backend.subscriptions import list_matches


if __name__ == "__main__":
    sub_id = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(list_matches(sub_id), ensure_ascii=False, indent=2))
