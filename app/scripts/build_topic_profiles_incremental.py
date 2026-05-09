#!/usr/bin/env python3
from __future__ import annotations

import json
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
    load_papers_by_ids,
    process_one,
    save_topic_profile_run,
)


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: build_topic_profiles_incremental.py <paper_id> [paper_id ...]")
        raise SystemExit(1)

    paper_ids = [arg.strip() for arg in sys.argv[1:] if arg.strip()]
    workers = max(1, DEFAULT_WORKERS)
    model = DEFAULT_MODEL
    papers = load_papers_by_ids(paper_ids, model=model, only_missing=False)

    print(f"incremental topic profile target papers: {len(papers)} / requested={len(paper_ids)} | workers={workers} | rps<={REQUESTS_PER_SECOND}")
    if not papers:
        return

    success_count = 0
    failure_count = 0
    futures = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for paper in papers:
            futures.append(executor.submit(process_one, paper, model))
            if REQUESTS_PER_SECOND > 0:
                time.sleep(1.0 / REQUESTS_PER_SECOND)

        for idx, future in enumerate(as_completed(futures), start=1):
            try:
                result = future.result()
                success_count += 1
                payload = result.get("payload") or {}
                print(f"[{idx}/{len(papers)}] incremental topic profile saved for {result['paper_id']}: {payload.get('topic_tags')}")
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
                print(f"[{idx}/{len(papers)}] incremental failed: {type(exc).__name__}: {error_text}")

    print(f"incremental topic profile complete: success={success_count} failed={failure_count}")


if __name__ == "__main__":
    main()
