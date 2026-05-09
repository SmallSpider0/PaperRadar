"""Runtime topic profiles for retrieval: prototypes, drift clusters, expansion, candidate shaping, scoring.

Benchmark JSON is diagnostic-only; strategy lives in config/topic_profiles.json.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_CONFIG_LOCK = threading.Lock()
_CACHED_PAYLOAD: dict[str, Any] | None = None
_CACHED_MTIME: float | None = None


def _config_path() -> Path:
    return Path(__file__).resolve().parent / "config" / "topic_profiles.json"


@dataclass
class PrototypeCluster:
    id: str
    match_terms: tuple[str, ...] = ()


@dataclass
class NeighborDriftCluster:
    id: str
    match_terms: tuple[str, ...] = ()


@dataclass
class ParserHints:
    boost_topic_labels: tuple[str, ...] = ()
    extra_should_terms: tuple[str, ...] = ()
    extra_negative_terms: tuple[str, ...] = ()


@dataclass
class ExpansionPolicy:
    extra_topic_expansions_generic: tuple[str, ...] = ()
    strip_topic_expansions_generic: tuple[str, ...] = ()
    variant_expansions_generic: tuple[str, ...] = ()


@dataclass
class CandidatePolicy:
    per_route_limit_scale: dict[str, float] = field(default_factory=dict)
    broad_aggregate_max_per_prototype: int = 0
    broad_aggregate_other_cap: int = 3
    broad_aggregate_head_limit: int = 48
    query_targeted_bucket_caps: dict[str, int] = field(default_factory=dict)
    query_suppressed_bucket_caps: dict[str, int] = field(default_factory=dict)


@dataclass
class NeighborScoring:
    positive_terms: tuple[str, ...] = ()
    negative_terms: tuple[str, ...] = ()
    positive_weight: float = 0.07
    negative_weight: float = 0.08
    title_bonus: float = 0.08
    title_penalty: float = 0.1


@dataclass
class PurityScoring:
    canonical_terms: tuple[str, ...] = ()
    drift_terms: tuple[str, ...] = ()
    title_anchor_terms: tuple[str, ...] = ()
    malware_title_anchor: bool = False
    fhe_purity: bool = False


@dataclass
class ScoringPolicy:
    neighbor: NeighborScoring = field(default_factory=NeighborScoring)
    purity: PurityScoring = field(default_factory=PurityScoring)


@dataclass(frozen=True)
class TopicRuntimeProfile:
    topic_id: str
    primary_canonical_topics: tuple[str, ...]
    strategy_type: str
    query_scopes_default: tuple[str, ...]
    prototype_clusters: tuple[PrototypeCluster, ...]
    neighbor_drift_clusters: tuple[NeighborDriftCluster, ...]
    parser: ParserHints
    expansion: ExpansionPolicy
    candidate: CandidatePolicy
    scoring: ScoringPolicy


def _as_tuple_strs(items: Any) -> tuple[str, ...]:
    if not items:
        return ()
    out: list[str] = []
    for item in items:
        s = str(item).strip()
        if s:
            out.append(s)
    return tuple(out)


def _parse_prototype(raw: dict[str, Any]) -> PrototypeCluster:
    return PrototypeCluster(
        id=str(raw.get("id") or "").strip() or "unknown",
        match_terms=_as_tuple_strs(raw.get("match_terms")),
    )


def _parse_neighbor_drift(raw: dict[str, Any]) -> NeighborDriftCluster:
    return NeighborDriftCluster(
        id=str(raw.get("id") or "").strip() or "unknown",
        match_terms=_as_tuple_strs(raw.get("match_terms")),
    )


def _parse_profile(raw: dict[str, Any]) -> TopicRuntimeProfile:
    parser_raw = raw.get("parser") or {}
    expansion_raw = raw.get("expansion") or {}
    candidate_raw = raw.get("candidate") or {}
    scoring_raw = raw.get("scoring") or {}
    neighbor_raw = scoring_raw.get("neighbor") or {}
    purity_raw = scoring_raw.get("purity") or {}

    per_route = candidate_raw.get("per_route_limit_scale") or {}
    if not isinstance(per_route, dict):
        per_route = {}

    return TopicRuntimeProfile(
        topic_id=str(raw.get("topic_id") or "").strip() or "unknown",
        primary_canonical_topics=_as_tuple_strs(raw.get("primary_canonical_topics")),
        strategy_type=str(raw.get("strategy_type") or "single_cluster").strip().lower(),
        query_scopes_default=tuple(
            str(x).strip().lower()
            for x in (raw.get("query_scopes_default") or ["broad_topic"])
            if str(x).strip()
        )
        or ("broad_topic",),
        prototype_clusters=tuple(_parse_prototype(p) for p in (raw.get("prototype_clusters") or []) if isinstance(p, dict)),
        neighbor_drift_clusters=tuple(
            _parse_neighbor_drift(p) for p in (raw.get("neighbor_drift_clusters") or []) if isinstance(p, dict)
        ),
        parser=ParserHints(
            boost_topic_labels=_as_tuple_strs(parser_raw.get("boost_topic_labels")),
            extra_should_terms=_as_tuple_strs(parser_raw.get("extra_should_terms")),
            extra_negative_terms=_as_tuple_strs(parser_raw.get("extra_negative_terms")),
        ),
        expansion=ExpansionPolicy(
            extra_topic_expansions_generic=_as_tuple_strs(expansion_raw.get("extra_topic_expansions_generic")),
            strip_topic_expansions_generic=_as_tuple_strs(expansion_raw.get("strip_topic_expansions_generic")),
            variant_expansions_generic=_as_tuple_strs(expansion_raw.get("variant_expansions_generic")),
        ),
        candidate=CandidatePolicy(
            per_route_limit_scale={str(k): float(v) for k, v in per_route.items() if str(k).strip()},
            broad_aggregate_max_per_prototype=int(candidate_raw.get("broad_aggregate_max_per_prototype") or 0),
            broad_aggregate_other_cap=int(candidate_raw.get("broad_aggregate_other_cap") or 3),
            broad_aggregate_head_limit=int(candidate_raw.get("broad_aggregate_head_limit") or 48),
            query_targeted_bucket_caps={
                str(k): int(v) for k, v in (candidate_raw.get("query_targeted_bucket_caps") or {}).items() if str(k).strip()
            },
            query_suppressed_bucket_caps={
                str(k): int(v) for k, v in (candidate_raw.get("query_suppressed_bucket_caps") or {}).items() if str(k).strip()
            },
        ),
        scoring=ScoringPolicy(
            neighbor=NeighborScoring(
                positive_terms=_as_tuple_strs(neighbor_raw.get("positive_terms")),
                negative_terms=_as_tuple_strs(neighbor_raw.get("negative_terms")),
                positive_weight=float(neighbor_raw.get("positive_weight") or 0.07),
                negative_weight=float(neighbor_raw.get("negative_weight") or 0.08),
                title_bonus=float(neighbor_raw.get("title_bonus") or 0.08),
                title_penalty=float(neighbor_raw.get("title_penalty") or 0.1),
            ),
            purity=PurityScoring(
                canonical_terms=_as_tuple_strs(purity_raw.get("canonical_terms")),
                drift_terms=_as_tuple_strs(purity_raw.get("drift_terms")),
                title_anchor_terms=_as_tuple_strs(purity_raw.get("title_anchor_terms")),
                malware_title_anchor=bool(purity_raw.get("malware_title_anchor")),
                fhe_purity=bool(purity_raw.get("fhe_purity")),
            ),
        ),
    )


def load_topic_profiles_payload(*, force_reload: bool = False) -> dict[str, Any]:
    global _CACHED_PAYLOAD, _CACHED_MTIME
    path = _config_path()
    with _CONFIG_LOCK:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        if not force_reload and _CACHED_PAYLOAD is not None and _CACHED_MTIME == mtime:
            return _CACHED_PAYLOAD
        if path.is_file():
            _CACHED_PAYLOAD = json.loads(path.read_text(encoding="utf-8"))
        else:
            _CACHED_PAYLOAD = {"version": 0, "profiles": []}
        _CACHED_MTIME = mtime
        return _CACHED_PAYLOAD


def iter_runtime_profiles(*, force_reload: bool = False) -> tuple[TopicRuntimeProfile, ...]:
    payload = load_topic_profiles_payload(force_reload=force_reload)
    profiles = payload.get("profiles") or []
    if not isinstance(profiles, list):
        return ()
    return tuple(_parse_profile(p) for p in profiles if isinstance(p, dict))


def _normalize_topic_key(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def match_runtime_profile(topic_labels: list[str] | None, topic: str | None = None) -> TopicRuntimeProfile | None:
    """Pick profile if primary label or topic string matches configured canonical topics."""
    labels = [ _normalize_topic_key(x) for x in (topic_labels or []) if str(x).strip() ]
    topic_n = _normalize_topic_key(topic or "")
    haystack = set(labels)
    if topic_n:
        haystack.add(topic_n)
    for profile in iter_runtime_profiles():
        for canonical in profile.primary_canonical_topics:
            c = _normalize_topic_key(canonical)
            if not c:
                continue
            if c in haystack:
                return profile
            for lab in labels:
                if lab and (c in lab or lab in c):
                    return profile
            if topic_n and (c in topic_n or topic_n in c):
                return profile
    return None


def infer_prototype_bucket(record: dict, profile: TopicRuntimeProfile) -> str:
    """Map record text to first matching prototype cluster id, else 'other'."""
    title = str(record.get("title") or "").lower()
    abstract = str(record.get("abstract") or "").lower()
    topic_summary = str(record.get("topic_summary") or "").lower()
    tags = " ".join(str(t) for t in (record.get("topic_tags") or [])).lower()
    blob = f"{title} {abstract} {topic_summary} {tags}"
    for cluster in profile.prototype_clusters:
        if any(term.lower() in blob for term in cluster.match_terms if term):
            return cluster.id
    return "other"


def profile_to_serializable_dict(profile: TopicRuntimeProfile | None) -> dict[str, Any] | None:
    """Snapshot for multiprocessing retrieval workers (pickle-friendly)."""
    if profile is None:
        return None
    return {
        "topic_id": profile.topic_id,
        "strategy_type": profile.strategy_type,
        "primary_canonical_topics": list(profile.primary_canonical_topics),
        "prototype_clusters": [
            {"id": c.id, "match_terms": list(c.match_terms)} for c in profile.prototype_clusters
        ],
        "expansion": {
            "extra_topic_expansions_generic": list(profile.expansion.extra_topic_expansions_generic),
            "strip_topic_expansions_generic": list(profile.expansion.strip_topic_expansions_generic),
        },
        "candidate": {
            "per_route_limit_scale": dict(profile.candidate.per_route_limit_scale),
            "broad_aggregate_max_per_prototype": profile.candidate.broad_aggregate_max_per_prototype,
            "broad_aggregate_other_cap": profile.candidate.broad_aggregate_other_cap,
            "broad_aggregate_head_limit": profile.candidate.broad_aggregate_head_limit,
            "query_targeted_bucket_caps": dict(profile.candidate.query_targeted_bucket_caps),
            "query_suppressed_bucket_caps": dict(profile.candidate.query_suppressed_bucket_caps),
        },
        "scoring": {
            "neighbor": {
                "positive_terms": list(profile.scoring.neighbor.positive_terms),
                "negative_terms": list(profile.scoring.neighbor.negative_terms),
                "positive_weight": profile.scoring.neighbor.positive_weight,
                "negative_weight": profile.scoring.neighbor.negative_weight,
                "title_bonus": profile.scoring.neighbor.title_bonus,
                "title_penalty": profile.scoring.neighbor.title_penalty,
            },
            "purity": {
                "canonical_terms": list(profile.scoring.purity.canonical_terms),
                "drift_terms": list(profile.scoring.purity.drift_terms),
                "title_anchor_terms": list(profile.scoring.purity.title_anchor_terms),
                "malware_title_anchor": profile.scoring.purity.malware_title_anchor,
                "fhe_purity": profile.scoring.purity.fhe_purity,
            },
        },
    }


def profile_from_snapshot(data: dict[str, Any] | None) -> TopicRuntimeProfile | None:
    if not data:
        return None
    protos = tuple(
        PrototypeCluster(id=str(p.get("id") or ""), match_terms=tuple(p.get("match_terms") or []))
        for p in (data.get("prototype_clusters") or [])
        if isinstance(p, dict)
    )
    exp = data.get("expansion") or {}
    cand = data.get("candidate") or {}
    sc = data.get("scoring") or {}
    nb = sc.get("neighbor") or {}
    pu = sc.get("purity") or {}
    prs = cand.get("per_route_limit_scale") or {}
    if not isinstance(prs, dict):
        prs = {}
    return TopicRuntimeProfile(
        topic_id=str(data.get("topic_id") or ""),
        primary_canonical_topics=tuple(data.get("primary_canonical_topics") or []),
        strategy_type=str(data.get("strategy_type") or "single_cluster"),
        query_scopes_default=("broad_topic",),
        prototype_clusters=protos,
        neighbor_drift_clusters=(),
        parser=ParserHints(),
        expansion=ExpansionPolicy(
            extra_topic_expansions_generic=tuple(exp.get("extra_topic_expansions_generic") or []),
            strip_topic_expansions_generic=tuple(exp.get("strip_topic_expansions_generic") or []),
            variant_expansions_generic=(),
        ),
        candidate=CandidatePolicy(
            per_route_limit_scale={str(k): float(v) for k, v in prs.items()},
            broad_aggregate_max_per_prototype=int(cand.get("broad_aggregate_max_per_prototype") or 0),
            broad_aggregate_other_cap=int(cand.get("broad_aggregate_other_cap") or 3),
            broad_aggregate_head_limit=int(cand.get("broad_aggregate_head_limit") or 48),
            query_targeted_bucket_caps={
                str(k): int(v) for k, v in (cand.get("query_targeted_bucket_caps") or {}).items() if str(k).strip()
            },
            query_suppressed_bucket_caps={
                str(k): int(v) for k, v in (cand.get("query_suppressed_bucket_caps") or {}).items() if str(k).strip()
            },
        ),
        scoring=ScoringPolicy(
            neighbor=NeighborScoring(
                positive_terms=tuple(nb.get("positive_terms") or []),
                negative_terms=tuple(nb.get("negative_terms") or []),
                positive_weight=float(nb.get("positive_weight") or 0.07),
                negative_weight=float(nb.get("negative_weight") or 0.08),
                title_bonus=float(nb.get("title_bonus") or 0.08),
                title_penalty=float(nb.get("title_penalty") or 0.1),
            ),
            purity=PurityScoring(
                canonical_terms=tuple(pu.get("canonical_terms") or []),
                drift_terms=tuple(pu.get("drift_terms") or []),
                title_anchor_terms=tuple(pu.get("title_anchor_terms") or []),
                malware_title_anchor=bool(pu.get("malware_title_anchor")),
                fhe_purity=bool(pu.get("fhe_purity")),
            ),
        ),
    )
