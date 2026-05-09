#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.pg_json_store import run_sql
from scripts.topic_profile_lib import DEFAULT_MODEL, q


def count_targets(repair_mode: str, model: str) -> int:
    if repair_mode == "empty_tags":
        sql = f"""
        SELECT COUNT(*)::text
        FROM paper_topic_profiles tp
        WHERE tp.model_name = {q(model)}
          AND jsonb_array_length(tp.topic_tags) = 0;
        """
    elif repair_mode == "max_tokens":
        sql = f"""
        SELECT COUNT(DISTINCT paper_id)::text
        FROM paper_topic_profile_runs
        WHERE model_name = {q(model)}
          AND finish_reason = 'MAX_TOKENS'
          AND paper_id IS NOT NULL;
        """
    elif repair_mode == "missing":
        sql = f"""
        SELECT COUNT(*)::text
        FROM papers p
        LEFT JOIN paper_topic_profiles tp ON tp.paper_id = p.id AND tp.model_name = {q(model)}
        WHERE tp.paper_id IS NULL;
        """
    else:
        raise ValueError(f"unsupported repair mode: {repair_mode}")
    return int(run_sql(sql) or "0")


def main() -> None:
    repair_mode = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("PAPERRADAR_TOPIC_REPAIR_MODE", "empty_tags")).strip()
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else int(os.getenv("PAPERRADAR_TOPIC_REPAIR_LIMIT", "50"))
    model = DEFAULT_MODEL

    total_targets = count_targets(repair_mode, model)
    print(f"topic profile maintenance mode={repair_mode} total_targets={total_targets} limit={limit}")

    env = os.environ.copy()
    cmd = [sys.executable, str(BASE_DIR / "scripts" / "build_topic_profiles.py"), str(limit)]

    if repair_mode == "empty_tags":
        env["PAPERRADAR_TOPIC_ONLY_MISSING"] = "0"
        env["PAPERRADAR_TOPIC_RETRY_EMPTY"] = "1"
    elif repair_mode == "missing":
        env["PAPERRADAR_TOPIC_ONLY_MISSING"] = "1"
        env["PAPERRADAR_TOPIC_RETRY_EMPTY"] = "0"
    elif repair_mode == "max_tokens":
        sql = f"""
        SELECT COALESCE(json_agg(paper_id), '[]'::json)::text
        FROM (
          SELECT DISTINCT paper_id
          FROM paper_topic_profile_runs
          WHERE model_name = {q(model)}
            AND finish_reason = 'MAX_TOKENS'
            AND paper_id IS NOT NULL
          ORDER BY paper_id
          LIMIT {limit}
        ) t;
        """
        payload = run_sql(sql)
        paper_ids = __import__("json").loads(payload or "[]")
        if not paper_ids:
            print("topic profile maintenance: no MAX_TOKENS targets")
            return
        cmd = [sys.executable, str(BASE_DIR / "scripts" / "build_topic_profiles_incremental.py"), *paper_ids]
    else:
        raise SystemExit(f"unsupported repair mode: {repair_mode}")

    subprocess.run(cmd, check=True, env=env)


if __name__ == "__main__":
    main()
