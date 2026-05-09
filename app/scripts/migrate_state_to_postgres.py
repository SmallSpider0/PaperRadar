#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from backend.pg_json_store import replace_table


BASE_DIR = Path(__file__).resolve().parents[2]
STATE_DIR = BASE_DIR / "data" / "generated"


def load_json(name: str):
    path = STATE_DIR / name
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    subscriptions = load_json("subscriptions.json")
    matches = load_json("subscription_matches.json")
    notifications = load_json("notifications.json")

    replace_table(
        "subscriptions",
        ["id", "user_id", "type", "name", "query_text", "filters_json", "threshold", "enabled"],
        [
            {
                "id": item["id"],
                "user_id": "local-user",
                "type": item.get("type", "topic"),
                "name": item.get("name", item["id"]),
                "query_text": item.get("query_text"),
                "filters_json": {"venue_codes": item.get("venue_codes", [])},
                "threshold": item.get("threshold", 0.5),
                "enabled": item.get("enabled", True),
            }
            for item in subscriptions
        ],
    )

    replace_table(
        "subscription_matches",
        ["id", "subscription_id", "paper_id", "match_score", "match_reason", "evidence_json"],
        [
            {
                "id": item["id"],
                "subscription_id": item["subscription_id"],
                "paper_id": item.get("paper_url", ""),
                "match_score": item.get("score", 0.0),
                "match_reason": item.get("reason", "metadata_search_match"),
                "evidence_json": {"title": item.get("title"), "paper_url": item.get("paper_url")},
            }
            for item in matches
        ],
    )

    replace_table(
        "notifications",
        ["id", "subscription_id", "paper_id", "channel", "status", "payload_json"],
        [
            {
                "id": item["id"],
                "subscription_id": item["subscription_id"],
                "paper_id": item.get("paper_url", ""),
                "channel": "internal",
                "status": item.get("status", "pending"),
                "payload_json": {"title": item.get("title"), "paper_url": item.get("paper_url")},
            }
            for item in notifications
        ],
    )

    print(f"migrated subscriptions={len(subscriptions)} matches={len(matches)} notifications={len(notifications)}")


if __name__ == "__main__":
    main()
