from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

import requests

from backend.pg_json_store import run_sql
from backend.topic_taxonomy import TOPIC_TAXONOMY

DEFAULT_MODEL = os.getenv("PAPERRADAR_TOPIC_MODEL", "gemini-2.5-flash")
DEFAULT_MAX_OUTPUT_TOKENS = int(os.getenv("PAPERRADAR_TOPIC_MAX_OUTPUT_TOKENS", "1400"))
RETRY_LIMIT = int(os.getenv("PAPERRADAR_TOPIC_RETRY_LIMIT", "3"))
DEFAULT_WORKERS = int(os.getenv("PAPERRADAR_TOPIC_WORKERS", "16"))
REQUESTS_PER_SECOND = float(os.getenv("PAPERRADAR_TOPIC_RPS", "8"))


def q(text: str | None) -> str:
    if text is None:
        return 'NULL'
    return "'" + str(text).replace("'", "''") + "'"


def qjson(obj: Any) -> str:
    return "'" + json.dumps(obj, ensure_ascii=False).replace("'", "''") + "'::jsonb"


def candidate_taxonomy(title: str, abstract: str | None, limit: int = 10) -> list[dict[str, Any]]:
    lowered_text = f"{title}\n\n{abstract or ''}".lower()
    scored: list[tuple[int, Any]] = []
    for entry in TOPIC_TAXONOMY:
        terms = entry.all_terms()
        score = sum(1 for term in terms if term.lower() in lowered_text)
        if entry.canonical in lowered_text:
            score += 3
        if score > 0:
            scored.append((score, entry))
    if not scored:
        scored = [(1, entry) for entry in TOPIC_TAXONOMY[:limit]]
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [entry for _, entry in scored[:limit]]
    return [
        {
            "canonical": entry.canonical,
            "aliases": list(entry.aliases),
            "subtopics": list(entry.subtopics[:4]),
            "zh_aliases": list(entry.zh_aliases[:4]),
        }
        for entry in selected
    ]


def build_prompt(title: str, abstract: str | None) -> str:
    taxonomy_text = json.dumps(candidate_taxonomy(title, abstract), ensure_ascii=False)
    return f"""
Return strict JSON only:
{{"topic_tags":["canonical topic label"],"topic_summary":"one short English sentence"}}

Rules:
- Choose topic_tags ONLY from the candidate taxonomy below.
- topic_tags should usually contain 1-4 tags, max 6.
- Prefer the closest higher-level security topic rather than returning [].
- Return [] only if the paper is clearly outside security/privacy/trust/safety/governance themes.
- topic_summary must be one short sentence.
- No markdown. No explanation. JSON only.

Candidate taxonomy:
{taxonomy_text}

Title: {title}
Abstract: {abstract or 'N/A'}
""".strip()


def parse_json_payload(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    candidates: list[str] = [raw]

    if "```json" in raw:
        start = raw.find("```json") + len("```json")
        end = raw.find("```", start)
        if end != -1:
            candidates.insert(0, raw[start:end].strip())
    elif "```" in raw:
        start = raw.find("```") + len("```")
        end = raw.find("```", start)
        if end != -1:
            candidates.insert(0, raw[start:end].strip())

    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.insert(0, raw[first_brace:last_brace + 1].strip())

    seen: set[str] = set()
    for candidate in candidates:
        item = candidate.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        try:
            parsed = json.loads(item)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, str):
                reparsed = json.loads(parsed)
                if isinstance(reparsed, dict):
                    return reparsed
        except Exception:
            continue

    raise json.JSONDecodeError("Unable to parse JSON object from model output", raw, 0)


def call_gemini_json(prompt: str, model: str) -> tuple[dict[str, Any], dict[str, Any]]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY is required")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    last_error: Exception | None = None
    last_meta: dict[str, Any] = {}
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            max_output_tokens = DEFAULT_MAX_OUTPUT_TOKENS if attempt == 1 else int(DEFAULT_MAX_OUTPUT_TOKENS * 1.5)
            response = requests.post(
                url,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.0,
                        "topP": 0.8,
                        "responseMimeType": "application/json",
                        "maxOutputTokens": max_output_tokens,
                    },
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            candidates = payload.get("candidates") or []
            if not candidates:
                raise RuntimeError("Gemini returned no candidates")
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()
            finish_reason = candidates[0].get("finishReason")
            usage = payload.get("usageMetadata") or {}
            last_meta = {
                "finish_reason": finish_reason,
                "token_usage": {
                    "prompt_tokens": int(usage.get("promptTokenCount") or 0),
                    "completion_tokens": int(usage.get("candidatesTokenCount") or 0),
                    "total_tokens": int(usage.get("totalTokenCount") or 0),
                },
                "raw_response_text": text,
                "attempt": attempt,
            }
            if not text:
                raise RuntimeError("Gemini returned empty text")
            parsed = parse_json_payload(text)
            return parsed, last_meta
        except Exception as exc:
            if last_meta.get("finish_reason") == "MAX_TOKENS" and attempt < RETRY_LIMIT:
                time.sleep(min(2 * attempt, 5))
                continue
            last_error = exc
            if attempt < RETRY_LIMIT:
                time.sleep(min(2 * attempt, 5))
            continue
    raise RuntimeError(json.dumps({"error": str(last_error), "meta": last_meta}, ensure_ascii=False))


def load_papers(limit: int = 0, only_missing: bool = True, retry_empty: bool = False) -> list[dict[str, Any]]:
    where_clause = ""
    if retry_empty:
        where_clause = "WHERE tp.paper_id IS NOT NULL AND jsonb_array_length(tp.topic_tags) = 0"
    elif only_missing:
        where_clause = "WHERE tp.paper_id IS NULL"
    sql = f'''
    SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
    FROM (
      SELECT
        p.id,
        p.title,
        p.abstract
      FROM papers p
      LEFT JOIN paper_topic_profiles tp ON tp.paper_id = p.id AND tp.model_name = {q(DEFAULT_MODEL)}
      {where_clause}
      ORDER BY p.created_at DESC
      {f'LIMIT {int(limit)}' if limit > 0 else ''}
    ) t;
    '''
    output = run_sql(sql)
    rows = json.loads(output or "[]")
    return rows if isinstance(rows, list) else []


def load_papers_by_ids(paper_ids: list[str], model: str | None = None, only_missing: bool = False) -> list[dict[str, Any]]:
    ids = [paper_id.strip() for paper_id in paper_ids if str(paper_id).strip()]
    if not ids:
        return []
    escaped_ids = ", ".join(q(paper_id) for paper_id in ids)
    join_clause = ""
    where_extra = ""
    if only_missing:
        join_clause = f"LEFT JOIN paper_topic_profiles tp ON tp.paper_id = p.id AND tp.model_name = {q(model or DEFAULT_MODEL)}"
        where_extra = "AND tp.paper_id IS NULL"
    sql = f'''
    SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)::text
    FROM (
      SELECT p.id, p.title, p.abstract
      FROM papers p
      {join_clause}
      WHERE p.id IN ({escaped_ids})
      {where_extra}
      ORDER BY p.created_at DESC
    ) t;
    '''
    output = run_sql(sql)
    rows = json.loads(output or "[]")
    return rows if isinstance(rows, list) else []


def save_topic_profile_run(
    *,
    paper_id: str | None,
    model: str,
    status: str,
    finish_reason: str | None = None,
    token_usage: dict[str, Any] | None = None,
    error_message: str | None = None,
    raw_response_text: str | None = None,
) -> None:
    run_id = "topicrun_" + hashlib.sha256(f"{paper_id or 'none'}:{model}:{time.time_ns()}".encode("utf-8")).hexdigest()[:16]
    sql = f'''
    INSERT INTO paper_topic_profile_runs (
      id, paper_id, model_name, status, finish_reason, token_usage_json, error_message, raw_response_text
    ) VALUES (
      {q(run_id)}, {q(paper_id)}, {q(model)}, {q(status)}, {q(finish_reason)}, {qjson(token_usage or {})}, {q(error_message)}, {q(raw_response_text)}
    );
    '''
    run_sql(sql)


def infer_topic_tags_fallback(title: str, abstract: str | None, topic_summary: str | None = None) -> list[str]:
    lowered_text = f"{title}\n\n{abstract or ''}\n\n{topic_summary or ''}".lower()
    scored: list[tuple[int, str]] = []
    for entry in TOPIC_TAXONOMY:
        score = 0
        alias_lowers = [alias.lower() for alias in entry.aliases]
        zh_lowers = [zh.lower() for zh in entry.zh_aliases]
        for term in entry.all_terms():
            t = term.lower()
            if t and t in lowered_text:
                if t == entry.canonical.lower():
                    score += 4
                elif t in alias_lowers:
                    score += 3
                elif t in zh_lowers:
                    score += 3
                else:
                    score += 1
        if score > 0:
            scored.append((score, entry.canonical))

    coarse_rules = [
        ("trusted execution security", ["enclave", "tee", "trusted execution", "sgx", "confidential computing"]),
        ("systems security", ["kernel", "sandbox", "privilege", "isolation", "compartmentalization"]),
        ("network security", ["bgp", "routing", "proxy protocol", "network", "aspa", "route origin validation", "hijack", "dns forwarder"]),
        ("internet measurement", ["measurement study", "large-scale measurement", "internet scanning", "scanner", "protocol measurement"]),
        ("cyber-physical security", ["lidar", "electromagnetic interference", "signal injection", "wireless jamming", "sensor", "autonomous driving", "power inverter", "radar"]),
        ("hardware attacks", ["rowhammer", "fault injection", "electromagnetic attack", "side-channel", "hardware attack"]),
        ("abuse and fraud detection", ["scam", "fraud", "blocklist", "harmful meme", "abuse", "domain squatting", "brand protection"]),
        ("ransomware", ["ransomware", "ransom note", "extortion", "database ransom"]),
        ("usable security", ["password", "password manager", "accessibility", "blind", "low-vision", "usability"]),
        ("iot security", ["iot", "internet of things", "device identification", "smart device", "connected device"]),
        ("media authenticity and deepfakes", ["deepfake", "synthetic audio", "voice conversion", "harmful meme", "multimodal"]),
        ("content moderation and platform integrity", ["captcha", "warning label", "community notes", "hateful meme", "inauthentic content", "platform integrity"]),
        ("privacy and security behavior", ["smartphone theft", "security behavior", "privacy concerns", "recovery behavior"]),
        ("blockchain security", ["blockchain", "staking", "consensus", "smart contract", "distributed ledger"]),
        ("ai model integrity and watermarking", ["watermark", "model attribution", "training integrity", "inference integrity", "rag-wm", "concept shift"]),
        ("security governance", ["board", "cybersecurity risk", "oversight", "policy", "compliance", "privacy policy"]),
    ]
    for label, terms in coarse_rules:
        coarse_score = sum(1 for term in terms if term in lowered_text)
        if coarse_score > 0:
            scored.append((coarse_score + 2, label))

    deduped_scores: dict[str, int] = {}
    for score, label in scored:
        deduped_scores[label] = max(score, deduped_scores.get(label, 0))

    ordered = sorted(deduped_scores.items(), key=lambda item: item[1], reverse=True)
    return [label for label, _ in ordered[:6]]


def save_topic_profile(paper_id: str, title: str, abstract: str | None, payload: dict[str, Any], model: str) -> None:
    content_hash = hashlib.sha256(f"{title}\n\n{abstract or ''}".encode("utf-8")).hexdigest()
    profile_id = f"topic_{paper_id}_{hashlib.sha256(model.encode('utf-8')).hexdigest()[:8]}"
    canonical_labels = {entry.canonical for entry in TOPIC_TAXONOMY}
    topic_tags = [str(item).strip() for item in (payload.get("topic_tags") or []) if str(item).strip() in canonical_labels]
    topic_summary = str(payload.get("topic_summary") or "").strip()

    if not topic_tags:
        topic_tags = infer_topic_tags_fallback(title, abstract, topic_summary)

    if not topic_summary:
        topic_summary = (abstract or title or "").strip()
        if len(topic_summary) > 240:
            topic_summary = topic_summary[:237].rstrip() + "..."

    sql = f'''
    INSERT INTO paper_topic_profiles (id, paper_id, model_name, topic_tags, topic_summary, content_hash)
    VALUES ({q(profile_id)}, {q(paper_id)}, {q(model)}, {qjson(topic_tags)}, {q(topic_summary)}, {q(content_hash)})
    ON CONFLICT (paper_id, model_name)
    DO UPDATE SET
      topic_tags = EXCLUDED.topic_tags,
      topic_summary = EXCLUDED.topic_summary,
      content_hash = EXCLUDED.content_hash,
      updated_at = NOW();
    '''
    run_sql(sql)


def process_one(paper: dict[str, Any], model: str) -> dict[str, Any]:
    payload, meta = call_gemini_json(build_prompt(paper.get("title") or "", paper.get("abstract")), model=model)
    save_topic_profile(paper["id"], paper.get("title") or "", paper.get("abstract"), payload, model)
    save_topic_profile_run(
        paper_id=paper["id"],
        model=model,
        status="success",
        finish_reason=meta.get("finish_reason"),
        token_usage=meta.get("token_usage") or {},
        raw_response_text=meta.get("raw_response_text"),
    )
    return {
        "paper_id": paper["id"],
        "status": "success",
        "payload": payload,
        "meta": meta,
    }
