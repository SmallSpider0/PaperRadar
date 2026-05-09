#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from workers.enrich_metadata import enrich_record

BASE = Path(__file__).resolve().parents[2] / 'data' / 'generated'
FILES = [
    'ieee_sp_2025_normalized.json',
    'acm_ccs_2025_normalized.json',
    'ndss_2025_normalized.json',
    'usenix_security_2025_normalized.json',
]


def main() -> None:
    for name in FILES:
        path = BASE / name
        rows = json.loads(path.read_text(encoding='utf-8'))
        before = sum(1 for r in rows if (r.get('abstract') or '').strip())
        changed = 0
        for i, row in enumerate(rows):
            if (row.get('abstract') or '').strip():
                continue
            new_row = enrich_record(dict(row))
            if (new_row.get('abstract') or '').strip() and not (row.get('abstract') or '').strip():
                changed += 1
            rows[i] = new_row
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        after = sum(1 for r in rows if (r.get('abstract') or '').strip())
        print(f'{name}: before={before}, after={after}, gained={after-before}, total={len(rows)}')


if __name__ == '__main__':
    main()
