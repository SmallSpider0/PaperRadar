"""Unit tests for runtime topic profiles used by retrieval (no DB required)."""

from __future__ import annotations

import unittest

from backend.chat_parser import rules_parse_query
from backend.topic_profile_config import (
    infer_prototype_bucket,
    match_runtime_profile,
    profile_from_snapshot,
    profile_to_serializable_dict,
)


class TopicProfileMatchTests(unittest.TestCase):
    def test_match_privacy_by_label(self) -> None:
        labels = ["privacy-preserving computation", "privacy-preserving machine learning"]
        p = match_runtime_profile(labels, "隐私计算")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.topic_id, "privacy-preserving-computation")
        self.assertEqual(p.strategy_type, "broad_aggregate")

    def test_match_malware(self) -> None:
        p = match_runtime_profile(["malware detection"], "恶意软件检测")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.topic_id, "malware-detection")
        self.assertEqual(p.strategy_type, "broad_aggregate")
        self.assertIn("android malware detection", p.parser.extra_should_terms)

    def test_match_homomorphic_encryption(self) -> None:
        p = match_runtime_profile(["homomorphic encryption"], "同态加密")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.topic_id, "homomorphic-encryption")
        self.assertEqual(p.strategy_type, "broad_aggregate")
        self.assertTrue(len(p.prototype_clusters) >= 2)
        self.assertTrue(p.scoring.purity.fhe_purity)

    def test_snapshot_roundtrip(self) -> None:
        p = match_runtime_profile(["privacy-preserving computation"], "")
        self.assertIsNotNone(p)
        snap = profile_to_serializable_dict(p)
        self.assertIsNotNone(snap)
        p2 = profile_from_snapshot(snap)
        self.assertIsNotNone(p2)
        assert p2 is not None
        self.assertEqual(p2.topic_id, p.topic_id)
        self.assertEqual(len(p2.prototype_clusters), len(p.prototype_clusters))


class RulesParseQueryProfileTests(unittest.TestCase):
    def test_privacy_computing_sets_profile_and_structure(self) -> None:
        sq = rules_parse_query("隐私计算")
        self.assertEqual(sq.profile_id, "privacy-preserving-computation")
        self.assertIn("privacy-preserving computation", sq.topic_labels)
        self.assertTrue(sq.prototype_targets)

    def test_malware_sets_negative_terms_from_profile(self) -> None:
        sq = rules_parse_query("恶意软件检测")
        self.assertEqual(sq.profile_id, "malware-detection")
        self.assertIn("binary function matching", sq.negative_terms)


class PrototypeBucketTests(unittest.TestCase):
    def test_infer_encrypted_search(self) -> None:
        p = match_runtime_profile(["privacy-preserving computation"], "隐私计算")
        self.assertIsNotNone(p)
        assert p is not None
        record = {
            "title": "Encrypted search for fun",
            "abstract": "",
            "topic_summary": "",
            "topic_tags": [],
        }
        self.assertEqual(infer_prototype_bucket(record, p), "encrypted-search")


if __name__ == "__main__":
    unittest.main()
