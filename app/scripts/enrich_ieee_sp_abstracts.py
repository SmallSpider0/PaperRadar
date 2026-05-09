#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from workers.enrich_openalex import enrich_record_with_openalex

DEFAULT_BATCH_SIZE = 40
SLEEP_SECONDS = 0.2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=int, default=None)
    parser.add_argument('--limit', type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()

    base = Path(__file__).resolve().parents[2] / 'data'
    raw_path = base / 'raw' / 'ieee_sp_2025_metadata.json'
    generated_path = base / 'generated' / 'ieee_sp_2025_normalized.json'
    state_path = base / 'generated' / 'ieee_sp_2025_enrich_state.json'

    raw_records = json.loads(raw_path.read_text(encoding='utf-8'))
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'next_index': 0}
    start = args.start if args.start is not None else int(state.get('next_index', 0))
    end = min(start + max(args.limit, 1), len(raw_records))

    enriched_abstracts = 0
    enriched_authors = 0

    for index in range(start, end):
        record = raw_records[index]
        before_abstract = bool(record.get('abstract'))
        before_authors = bool(record.get('authors_text'))
        updated = enrich_record_with_openalex(dict(record))
        if not before_abstract and updated.get('abstract'):
            enriched_abstracts += 1
        if not before_authors and updated.get('authors_text'):
            enriched_authors += 1
        updated['content_policy'] = 'metadata_only'
        raw_records[index] = updated
        time.sleep(SLEEP_SECONDS)

    raw_path.write_text(json.dumps(raw_records, ensure_ascii=False, indent=2), encoding='utf-8')
    generated_path.write_text(json.dumps(raw_records, ensure_ascii=False, indent=2), encoding='utf-8')

    finished = end >= len(raw_records)
    state = {'next_index': 0 if finished else end, 'finished': finished, 'total': len(raw_records)}
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'processed range: [{start}, {end}) / {len(raw_records)}')
    print(f'enriched IEEE S&P abstracts: {enriched_abstracts}')
    print(f'enriched IEEE S&P authors: {enriched_authors}')
    print(f'finished: {finished}')
    print(f'wrote: {raw_path}')
    print(f'wrote: {generated_path}')
    print(f'state: {state_path}')


if __name__ == '__main__':
    main()
