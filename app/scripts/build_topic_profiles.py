#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.topic_profile_lib import (
    DEFAULT_MODEL,
    DEFAULT_WORKERS,
    REQUESTS_PER_SECOND,
    load_papers,
    process_one,
    save_topic_profile_run,
)


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    only_missing = os.getenv("PAPERRADAR_TOPIC_ONLY_MISSING", "1") != "0"
    retry_empty = os.getenv("PAPERRADAR_TOPIC_RETRY_EMPTY", "0") == "1"
    workers = max(1, DEFAULT_WORKERS)
    model = DEFAULT_MODEL

    papers = load_papers(limit=limit, only_missing=only_missing, retry_empty=retry_empty)
    print(f"topic profile target papers: {len(papers)} | workers={workers} | rps<={REQUESTS_PER_SECOND}")
    success_count = 0
    failure_count = 0
    submitted = 0
    futures = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for paper in papers:
            futures.append(executor.submit(process_one, paper, model))
            submitted += 1
            if REQUESTS_PER_SECOND > 0:
                time.sleep(1.0 / REQUESTS_PER_SECOND)

        for idx, future in enumerate(as_completed(futures), start=1):
            try:
                result = future.result()
                success_count += 1
                payload = result.get("payload") or {}
                meta = result.get("meta") or {}
                print(f"[{idx}/{len(papers)}] saved topic profile for {result['paper_id']}: {payload.get('topic_tags')} | finish={meta.get('finish_reason')} | tokens={meta.get('token_usage')}")
            except Exception as exc:
                failure_count += 1
                error_text = str(exc)
                raw_response_text = None
                finish_reason = None
                token_usage = {}
                try:
                    parsed_error = json.loads(error_text)
                    if isinstance(parsed_error, dict):
                        meta = parsed_error.get("meta") or {}
                        raw_response_text = meta.get("raw_response_text")
                        finish_reason = meta.get("finish_reason")
                        token_usage = meta.get("token_usage") or {}
                        error_text = parsed_error.get("error") or error_text
                except Exception:
                    pass
                save_topic_profile_run(
                    paper_id=None,
                    model=model,
                    status="failed",
                    finish_reason=finish_reason,
                    token_usage=token_usage,
                    error_message=error_text,
                    raw_response_text=raw_response_text,
                )
                print(f"[{idx}/{len(papers)}] failed: {type(exc).__name__}: {error_text} | finish={finish_reason} | tokens={token_usage}")
    print(f"topic profile run complete: submitted={submitted} success={success_count} failed={failure_count}")


if __name__ == "__main__":
    main()
