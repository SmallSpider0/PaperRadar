#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.chat_parser import extract_topic, rules_parse_query

CASES_PATH = BASE_DIR.parent / "docs" / "chinese-query-normalization-regression.json"


def main() -> None:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = payload.get("cases") or []
    results = []
    passed = 0
    for case in cases:
        query = case["query"]
        expected = case["expected_topic"]
        extracted = extract_topic(query)
        structured = rules_parse_query(query)
        ok = extracted == expected and structured.topic == expected
        if ok:
            passed += 1
        results.append(
            {
                "query": query,
                "expected_topic": expected,
                "extracted_topic": extracted,
                "structured_topic": structured.topic,
                "must_terms": structured.must_terms,
                "should_terms": structured.should_terms[:4],
                "ok": ok,
            }
        )

    print(json.dumps({
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
        },
        "results": results,
    }, ensure_ascii=False, indent=2))

    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
