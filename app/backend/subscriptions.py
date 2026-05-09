from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backend.pg_json_store import load_table, run_sql
from backend.search import search_metadata


BASE_DIR = Path(__file__).resolve().parents[2]
STATE_DIR = BASE_DIR / "data" / "generated"
SUBSCRIPTIONS_PATH = STATE_DIR / "subscriptions.json"
MATCHES_PATH = STATE_DIR / "subscription_matches.json"
NOTIFICATIONS_PATH = STATE_DIR / "notifications.json"


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _escape(value: str) -> str:
    return (value or "").replace("'", "''")


def list_subscriptions(user_id: str) -> list[dict]:
    escaped_user_id = _escape(user_id)
    try:
        rows = load_table("subscriptions")
        if rows:
            result = []
            for row in rows:
                if row.get("user_id") != user_id:
                    continue
                filters_json = row.get("filters_json") or {}
                result.append({
                    "id": row.get("id"),
                    "type": row.get("type"),
                    "name": row.get("name"),
                    "query_text": row.get("query_text"),
                    "venue_codes": filters_json.get("venue_codes", []),
                    "threshold": row.get("threshold", 0.5),
                    "enabled": row.get("enabled", True),
                })
            return result
    except Exception:
        pass
    return [item for item in _load_json(SUBSCRIPTIONS_PATH, []) if item.get("user_id") == user_id]


def create_subscription(user_id: str, name: str, query_text: str, type_: str = "topic", venue_codes: list[str] | None = None, threshold: float = 0.5) -> dict:
    subscriptions = list_subscriptions(user_id)
    key = f"{type_}:{name}:{query_text}:{venue_codes}:{threshold}"
    sub_id = "sub_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    record = {
        "id": sub_id,
        "type": type_,
        "name": name,
        "query_text": query_text,
        "venue_codes": venue_codes or [],
        "threshold": threshold,
        "enabled": True,
        "user_id": user_id,
    }
    subscriptions = [s for s in subscriptions if s["id"] != sub_id] + [record]
    all_subscriptions = _load_json(SUBSCRIPTIONS_PATH, [])
    all_subscriptions = [s for s in all_subscriptions if s.get("user_id") != user_id] + subscriptions
    _save_json(SUBSCRIPTIONS_PATH, all_subscriptions)
    try:
        run_sql(
            f"""
            INSERT INTO subscriptions (id, user_id, type, name, query_text, filters_json, threshold, enabled)
            VALUES (
              '{_escape(record["id"])}',
              '{_escape(record["user_id"])}',
              '{_escape(record.get("type", "topic"))}',
              '{_escape(record.get("name", record["id"]))}',
              '{_escape(record.get("query_text") or "")}',
              '{{"venue_codes": {json.dumps(record.get("venue_codes", []), ensure_ascii=False)} }}'::jsonb,
              {float(record.get("threshold", 0.5))},
              {'TRUE' if record.get("enabled", True) else 'FALSE'}
            )
            ON CONFLICT (id) DO UPDATE SET
              user_id = EXCLUDED.user_id,
              type = EXCLUDED.type,
              name = EXCLUDED.name,
              query_text = EXCLUDED.query_text,
              filters_json = EXCLUDED.filters_json,
              threshold = EXCLUDED.threshold,
              enabled = EXCLUDED.enabled,
              updated_at = NOW();
            """
        )
    except Exception:
        pass
    return record


def delete_subscription(user_id: str, sub_id: str) -> dict:
    subscriptions = list_subscriptions(user_id)
    remaining = [s for s in subscriptions if s["id"] != sub_id]
    all_subscriptions = _load_json(SUBSCRIPTIONS_PATH, [])
    all_subscriptions = [s for s in all_subscriptions if s.get("user_id") != user_id] + remaining
    _save_json(SUBSCRIPTIONS_PATH, all_subscriptions)
    try:
        run_sql(f"DELETE FROM subscriptions WHERE id = '{_escape(sub_id)}' AND user_id = '{_escape(user_id)}';")
    except Exception:
        pass
    return {"deleted": sub_id, "remaining": len(remaining)}


def run_subscription_matching(user_id: str, limit_per_subscription: int = 10) -> dict:
    subscriptions = [s for s in list_subscriptions(user_id) if s.get("enabled")]
    matches = list_matches(user_id=user_id)
    notifications = list_notifications(user_id=user_id)
    seen_notification_keys = {
        (n.get("subscription_id"), n.get("paper_url")) for n in notifications
    }

    new_matches = []
    new_notifications = []
    for sub in subscriptions:
        results = search_metadata(
            query=sub["query_text"],
            venue_codes=sub.get("venue_codes") or None,
            limit=limit_per_subscription,
        )
        for item in results:
            score = item.get("score", 0.0)
            record = item.get("record", {})
            if score < sub.get("threshold", 0.5):
                continue
            match_key = f"{sub['id']}:{record.get('paper_url')}"
            match_id = "match_" + hashlib.sha256(match_key.encode("utf-8")).hexdigest()[:12]
            match_record = {
                "id": match_id,
                "subscription_id": sub["id"],
                "paper_url": record.get("paper_url"),
                "title": record.get("title"),
                "score": score,
                "reason": "metadata_search_match",
            }
            new_matches.append(match_record)
            notify_key = (sub["id"], record.get("paper_url"))
            if notify_key not in seen_notification_keys:
                notification_id = "notif_" + hashlib.sha256(match_key.encode("utf-8")).hexdigest()[:12]
                notification = {
                    "id": notification_id,
                    "subscription_id": sub["id"],
                    "paper_url": record.get("paper_url"),
                    "title": record.get("title"),
                    "status": "pending",
                }
                new_notifications.append(notification)
                seen_notification_keys.add(notify_key)

    merged_matches = {m["id"]: m for m in matches}
    for match in new_matches:
        merged_matches[match["id"]] = match

    merged_notifications = {n["id"]: n for n in notifications}
    for notification in new_notifications:
        merged_notifications[notification["id"]] = notification

    merged_matches_list = list(merged_matches.values())
    merged_notifications_list = list(merged_notifications.values())

    _save_json(MATCHES_PATH, merged_matches_list)
    _save_json(NOTIFICATIONS_PATH, merged_notifications_list)

    try:
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
                for item in merged_matches_list
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
                for item in merged_notifications_list
            ],
        )
    except Exception:
        pass

    return {
        "subscriptions": len(subscriptions),
        "new_matches": len(new_matches),
        "new_notifications": len(new_notifications),
    }


def list_matches(user_id: str, sub_id: str | None = None) -> list[dict]:
    user_subscriptions = {sub.get("id") for sub in list_subscriptions(user_id)}
    try:
        rows = load_table("subscription_matches")
        if rows:
            matches = [
                {
                    "id": row.get("id"),
                    "subscription_id": row.get("subscription_id"),
                    "paper_url": (row.get("evidence_json") or {}).get("paper_url"),
                    "title": (row.get("evidence_json") or {}).get("title"),
                    "score": row.get("match_score", 0.0),
                    "reason": row.get("match_reason"),
                }
                for row in rows
            ]
            matches = [m for m in matches if m.get("subscription_id") in user_subscriptions]
            if sub_id:
                matches = [m for m in matches if m.get("subscription_id") == sub_id]
            return matches
    except Exception:
        pass
    matches = _load_json(MATCHES_PATH, [])
    matches = [m for m in matches if m.get("subscription_id") in user_subscriptions]
    if sub_id:
        matches = [m for m in matches if m.get("subscription_id") == sub_id]
    return matches


def list_notifications(user_id: str) -> list[dict]:
    user_subscriptions = {sub.get("id") for sub in list_subscriptions(user_id)}
    try:
        rows = load_table("notifications")
        if rows:
            items = [
                {
                    "id": row.get("id"),
                    "subscription_id": row.get("subscription_id"),
                    "paper_url": (row.get("payload_json") or {}).get("paper_url"),
                    "title": (row.get("payload_json") or {}).get("title"),
                    "status": row.get("status"),
                }
                for row in rows
            ]
            return [item for item in items if item.get("subscription_id") in user_subscriptions]
    except Exception:
        pass
    items = _load_json(NOTIFICATIONS_PATH, [])
    return [item for item in items if item.get("subscription_id") in user_subscriptions]
