from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import backend.review_service as review_service
from backend.review_service import (
    REVIEW_REQUIRED_SECTIONS,
    _build_review_prompt,
    generate_review_from_session,
    prepare_review_request,
)


class ReviewServiceTests(unittest.TestCase):
    def test_classify_batch_disables_thinking_for_filtering(self) -> None:
        batch = [
            review_service.RetrievalPaper(
                paper_id="p1",
                title="Paper One",
                abstract="Security paper.",
                venue_code="NDSS",
                year=2025,
                paper_url="https://example.com/p1",
                score=0.91,
                match_reasons=["semantic match"],
            )
        ]

        with patch(
            "backend.review_service._call_gemini",
            return_value=(
                '{"decisions":[{"paper_id":"p1","decision":"include","reason":"相关"}]}',
                "STOP",
                {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "thoughts_tokens": 0},
            ),
        ) as call_mock:
            decision_map, usage, retried = review_service._classify_batch_with_retry("llm security", batch)

        self.assertFalse(retried)
        self.assertEqual(decision_map["p1"]["decision"], "include")
        self.assertEqual(usage["thoughts_tokens"], 0)
        self.assertEqual(call_mock.call_args.kwargs["thinking_budget"], 0)

    def test_build_review_prompt_requires_taxonomy_and_comparison(self) -> None:
        prompt = _build_review_prompt(
            "llm security",
            [
                {
                    "paper_id": "p1",
                    "title": "Paper One",
                    "abstract": "Security paper.",
                    "venue_code": "NDSS",
                    "year": 2025,
                    "decision_reason": "相关",
                }
            ],
            excluded_count=0,
        )
        self.assertIn("## 分类框架", prompt)
        self.assertIn("## 类内比较", prompt)
        self.assertIn("## 跨类别比较", prompt)
        self.assertIn("禁止把综述写成“按论文顺序逐篇翻译摘要”的形式", prompt)
        self.assertIn("约 5 页中文文档", prompt)
        self.assertIn("每个核心章节至少写成 2-4 个自然段", prompt)

    def test_prepare_review_request_reuses_search_payload(self) -> None:
        search_payload = {
            "query": "prompt injection defense",
            "results": [
                {
                    "score": 0.91,
                    "record": {
                        "id": "p1",
                        "title": "Paper One",
                        "abstract": "Defense for prompt injection.",
                        "authors_text": "A. Author",
                        "paper_url": "https://example.com/p1",
                        "source_pdf_url": None,
                        "content_policy": None,
                        "venue_code": "NDSS",
                        "year": 2025,
                    },
                    "match_reasons": ["semantic match"],
                    "relevance": {"score": 0.91, "why_matched": ["semantic match"], "raw_signals": {}},
                }
            ],
            "structured_query": {
                "intent": "search",
                "topic": "prompt injection defense",
                "filters": {"venues": [], "years": [], "year_from": None, "year_to": None},
            },
            "retrieval_summary": {"intent_label": "direct_search", "query_variants": ["prompt injection defense"]},
        }
        stored_row = {
            "id": "review_123",
            "title": "prompt injection defense",
            "query": "prompt injection defense",
            "status": "prepared",
            "confirmed": False,
            "prepared_payload_json": {},
            "review_payload_json": {},
        }

        def _store_side_effect(*_, **kwargs):
            stored_row["prepared_payload_json"] = kwargs["prepared_payload"]
            return stored_row

        with (
            patch("backend.review_service.build_search_session_payload", return_value=search_payload),
            patch("backend.review_service.create_review_session", side_effect=_store_side_effect),
        ):
            detail = prepare_review_request(user_id="u1", query="prompt injection defense", preview_limit=10, candidate_limit=20)

        self.assertEqual(detail["session"]["id"], "review_123")
        self.assertEqual(detail["prepared"]["structured_query"]["topic"], "prompt injection defense")
        self.assertEqual(len(detail["prepared"]["candidate_papers"]), 1)
        self.assertIn("确认后", detail["prepared"]["confirmation_prompt"])
        self.assertEqual(detail["prepared"]["search_session_payload"]["query"], "prompt injection defense")

    def test_prepare_review_request_applies_score_prefilter(self) -> None:
        search_payload = {
            "query": "prompt injection defense",
            "results": [
                {
                    "score": 0.91,
                    "record": {"id": "p1", "title": "Paper One", "abstract": "A", "authors_text": "A", "paper_url": None, "source_pdf_url": None, "content_policy": None, "venue_code": "NDSS", "year": 2025},
                    "match_reasons": ["semantic match"],
                    "relevance": {"score": 0.91, "why_matched": ["semantic match"], "raw_signals": {}},
                },
                {
                    "score": 0.62,
                    "record": {"id": "p2", "title": "Paper Two", "abstract": "B", "authors_text": "B", "paper_url": None, "source_pdf_url": None, "content_policy": None, "venue_code": "NDSS", "year": 2024},
                    "match_reasons": ["semantic match"],
                    "relevance": {"score": 0.62, "why_matched": ["semantic match"], "raw_signals": {}},
                },
                {
                    "score": 0.18,
                    "record": {"id": "p3", "title": "Paper Three", "abstract": "C", "authors_text": "C", "paper_url": None, "source_pdf_url": None, "content_policy": None, "venue_code": "NDSS", "year": 2023},
                    "match_reasons": ["tail match"],
                    "relevance": {"score": 0.18, "why_matched": ["tail match"], "raw_signals": {}},
                },
            ],
            "structured_query": {
                "intent": "search",
                "topic": "prompt injection defense",
                "filters": {"venues": [], "years": [], "year_from": None, "year_to": None},
            },
            "retrieval_summary": {"intent_label": "direct_search", "query_variants": ["prompt injection defense"]},
        }
        stored_row = {
            "id": "review_124",
            "title": "prompt injection defense",
            "query": "prompt injection defense",
            "status": "prepared",
            "confirmed": False,
            "prepared_payload_json": {},
            "review_payload_json": {},
        }

        def _store_side_effect(*_, **kwargs):
            stored_row["prepared_payload_json"] = kwargs["prepared_payload"]
            return stored_row

        with (
            patch("backend.review_service.build_search_session_payload", return_value=search_payload),
            patch("backend.review_service.create_review_session", side_effect=_store_side_effect),
            patch("backend.review_service.REVIEW_SCORE_PREFILTER_MIN_KEEP", 1),
            patch("backend.review_service.REVIEW_SCORE_PREFILTER_MIN_RELATIVE_GAP", 0.18),
            patch("backend.review_service.REVIEW_SCORE_PREFILTER_MIN_ABSOLUTE_GAP", 0.08),
        ):
            detail = prepare_review_request(user_id="u1", query="prompt injection defense", preview_limit=10, candidate_limit=20)

        kept_ids = [item["paper_id"] for item in detail["prepared"]["candidate_papers"]]
        self.assertEqual(kept_ids, ["p1", "p2"])
        self.assertEqual(detail["prepared"]["retrieval_summary"]["review_score_prefilter"]["raw_candidate_count"], 3)
        self.assertEqual(detail["prepared"]["retrieval_summary"]["review_score_prefilter"]["kept_candidate_count"], 2)
        self.assertEqual(detail["prepared"]["retrieval_summary"]["review_score_prefilter"]["filter_mode"], "distribution_gap")
        self.assertEqual(detail["prepared"]["retrieval_summary"]["review_score_prefilter"]["selected_gap_after_rank"], 2)

    def test_generate_review_from_session_filters_then_synthesizes(self) -> None:
        row = {
            "id": "review_456",
            "title": "prompt injection defense",
            "query": "prompt injection defense",
            "status": "prepared",
            "confirmed": False,
            "prepared_payload_json": {
                "query": "prompt injection defense",
                "structured_query": {
                    "intent": "search",
                    "topic": "prompt injection defense",
                    "filters": {"venues": [], "years": [], "year_from": None, "year_to": None},
                },
                "retrieval_summary": {"intent_label": "direct_search"},
                "confirmation_prompt": "confirm",
                "preview_limit": 10,
                "candidate_limit": 20,
                "preview_results": [
                    {
                        "paper_id": "p1",
                        "title": "Paper One",
                        "abstract": "Defense for prompt injection.",
                        "venue_code": "NDSS",
                        "year": 2025,
                        "paper_url": "https://example.com/p1",
                        "score": 0.91,
                        "match_reasons": ["semantic match"],
                    }
                ],
                "candidate_papers": [
                    {
                        "paper_id": "p1",
                        "title": "Paper One",
                        "abstract": "Defense for prompt injection.",
                        "venue_code": "NDSS",
                        "year": 2025,
                        "paper_url": "https://example.com/p1",
                        "score": 0.91,
                        "match_reasons": ["semantic match"],
                    },
                    {
                        "paper_id": "p2",
                        "title": "Paper Two",
                        "abstract": "A paper about watermarking.",
                        "venue_code": "USENIX_SECURITY",
                        "year": 2024,
                        "paper_url": "https://example.com/p2",
                        "score": 0.65,
                        "match_reasons": ["lexical match"],
                    },
                ],
                "search_session_payload": {"query": "prompt injection defense"},
            },
            "review_payload_json": {},
        }

        updated_row = dict(row)

        def _update_side_effect(session_id, **kwargs):
            updated_row["status"] = kwargs.get("status", updated_row["status"])
            updated_row["confirmed"] = kwargs.get("confirmed", updated_row["confirmed"])
            if "review_payload" in kwargs and kwargs["review_payload"] is not None:
                updated_row["review_payload_json"] = kwargs["review_payload"]
            return updated_row

        with (
            patch("backend.review_service.get_review_session", return_value=row),
            patch("backend.review_service.update_review_session", side_effect=_update_side_effect),
            patch(
                "backend.review_service._call_gemini",
                side_effect=[
                    (
                        '{"decisions":[{"paper_id":"p1","decision":"include","reason":"核心防御论文"},{"paper_id":"p2","decision":"exclude","reason":"主题偏离"}]}',
                        "STOP",
                        {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    ),
                    (
                        '## 主题界定\n这是综述。\n\n## 分类框架\n分两类。\n\n## 研究脉络\n...\n\n## 方法路线\n...\n\n## 类内比较\n...\n\n## 跨类别比较\n...\n\n## 代表性工作\n- Paper One\n\n## 共识与分歧\n...\n\n## 局限与空白\n...\n\n## 参考论文清单\n- Paper One',
                        "STOP",
                        {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
                    ),
                ],
            ),
        ):
            detail = generate_review_from_session(user_id="u1", review_session_id="review_456", confirmed=True)

        self.assertEqual(detail["session"]["status"], "completed")
        self.assertEqual(detail["review"]["answer_summary"]["included_count"], 1)
        self.assertEqual(detail["review"]["answer_summary"]["excluded_count"], 1)
        self.assertEqual(detail["review"]["answer_summary"]["filter_fallback_batches"], 0)
        self.assertEqual(detail["review"]["included_papers"][0]["paper_id"], "p1")
        self.assertEqual(detail["review"]["excluded_papers"][0]["paper_id"], "p2")
        for section in REVIEW_REQUIRED_SECTIONS:
            self.assertIn(section, detail["review"]["review_markdown"])

    def test_generate_review_retries_filter_when_first_attempt_truncates(self) -> None:
        row = {
            "id": "review_789",
            "title": "llm security",
            "query": "llm security",
            "status": "prepared",
            "confirmed": False,
            "prepared_payload_json": {
                "query": "llm security",
                "structured_query": {
                    "intent": "search",
                    "topic": "llm security",
                    "filters": {"venues": [], "years": [], "year_from": None, "year_to": None},
                },
                "retrieval_summary": {"intent_label": "direct_search"},
                "confirmation_prompt": "confirm",
                "preview_limit": 10,
                "candidate_limit": 20,
                "preview_results": [],
                "candidate_papers": [
                    {
                        "paper_id": "p1",
                        "title": "Paper One",
                        "abstract": "Security paper.",
                        "venue_code": "NDSS",
                        "year": 2025,
                        "paper_url": "https://example.com/p1",
                        "score": 0.91,
                        "match_reasons": ["semantic match"],
                    }
                ],
                "search_session_payload": {"query": "llm security"},
            },
            "review_payload_json": {},
        }

        updated_row = dict(row)

        def _update_side_effect(session_id, **kwargs):
            updated_row["status"] = kwargs.get("status", updated_row["status"])
            updated_row["confirmed"] = kwargs.get("confirmed", updated_row["confirmed"])
            if "review_payload" in kwargs and kwargs["review_payload"] is not None:
                updated_row["review_payload_json"] = kwargs["review_payload"]
            return updated_row

        with (
            patch("backend.review_service.get_review_session", return_value=row),
            patch("backend.review_service.update_review_session", side_effect=_update_side_effect),
            patch(
                "backend.review_service._call_gemini",
                side_effect=[
                    ('{"decisions":[{"paper_id":"p1","decision":"include"', "MAX_TOKENS", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
                    ('{"decisions":[{"paper_id":"p1","decision":"include","reason":"相关"}]}', "STOP", {"prompt_tokens": 8, "completion_tokens": 6, "total_tokens": 14}),
                    ('## 主题界定\n综述正文\n\n## 分类框架\n一类。\n\n## 研究脉络\n...\n\n## 方法路线\n...\n\n## 类内比较\n...\n\n## 跨类别比较\n...\n\n## 代表性工作\n- Paper One\n\n## 共识与分歧\n...\n\n## 局限与空白\n...\n\n## 参考论文清单\n- Paper One', "STOP", {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}),
                ],
            ),
        ):
            detail = generate_review_from_session(user_id="u1", review_session_id="review_789", confirmed=True)

        self.assertEqual(detail["review"]["answer_summary"]["filter_retry_batches"], 1)
        self.assertEqual(detail["review"]["answer_summary"]["filter_fallback_batches"], 0)
        self.assertEqual(detail["review"]["included_papers"][0]["paper_id"], "p1")

    def test_generate_review_skips_retry_when_max_tokens_still_contains_complete_decisions(self) -> None:
        row = {
            "id": "review_max_tokens_complete",
            "title": "llm security",
            "query": "llm security",
            "status": "prepared",
            "confirmed": False,
            "prepared_payload_json": {
                "query": "llm security",
                "structured_query": {
                    "intent": "search",
                    "topic": "llm security",
                    "filters": {"venues": [], "years": [], "year_from": None, "year_to": None},
                },
                "retrieval_summary": {"intent_label": "direct_search"},
                "confirmation_prompt": "confirm",
                "preview_limit": 10,
                "candidate_limit": 20,
                "preview_results": [],
                "candidate_papers": [
                    {
                        "paper_id": "p1",
                        "title": "Paper One",
                        "abstract": "Security paper.",
                        "venue_code": "NDSS",
                        "year": 2025,
                        "paper_url": "https://example.com/p1",
                        "score": 0.91,
                        "match_reasons": ["semantic match"],
                    }
                ],
                "search_session_payload": {"query": "llm security"},
            },
            "review_payload_json": {},
        }

        updated_row = dict(row)

        def _update_side_effect(session_id, **kwargs):
            updated_row["status"] = kwargs.get("status", updated_row["status"])
            updated_row["confirmed"] = kwargs.get("confirmed", updated_row["confirmed"])
            if "review_payload" in kwargs and kwargs["review_payload"] is not None:
                updated_row["review_payload_json"] = kwargs["review_payload"]
            return updated_row

        with (
            patch("backend.review_service.get_review_session", return_value=row),
            patch("backend.review_service.update_review_session", side_effect=_update_side_effect),
            patch(
                "backend.review_service._call_gemini",
                side_effect=[
                    ('{"decisions":[{"paper_id":"p1","decision":"include","reason":"相关"}]}', "MAX_TOKENS", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
                    ('## 主题界定\n综述正文\n\n## 分类框架\n一类。\n\n## 研究脉络\n...\n\n## 方法路线\n...\n\n## 类内比较\n...\n\n## 跨类别比较\n...\n\n## 代表性工作\n- Paper One\n\n## 共识与分歧\n...\n\n## 局限与空白\n...\n\n## 参考论文清单\n- Paper One', "STOP", {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}),
                ],
            ),
        ):
            detail = generate_review_from_session(user_id="u1", review_session_id="review_max_tokens_complete", confirmed=True)

        self.assertEqual(detail["review"]["answer_summary"]["filter_retry_batches"], 0)
        self.assertEqual(detail["review"]["answer_summary"]["filter_fallback_batches"], 0)
        self.assertEqual(detail["review"]["included_papers"][0]["paper_id"], "p1")

    def test_generate_review_retries_synthesis_after_transient_failure(self) -> None:
        row = {
            "id": "review_synthesis_retry",
            "title": "llm security",
            "query": "llm security",
            "status": "prepared",
            "confirmed": False,
            "prepared_payload_json": {
                "query": "llm security",
                "structured_query": {
                    "intent": "search",
                    "topic": "llm security",
                    "filters": {"venues": [], "years": [], "year_from": None, "year_to": None},
                },
                "retrieval_summary": {"intent_label": "direct_search"},
                "confirmation_prompt": "confirm",
                "preview_limit": 10,
                "candidate_limit": 20,
                "preview_results": [],
                "candidate_papers": [
                    {
                        "paper_id": "p1",
                        "title": "Paper One",
                        "abstract": "Security paper.",
                        "venue_code": "NDSS",
                        "year": 2025,
                        "paper_url": "https://example.com/p1",
                        "score": 0.91,
                        "match_reasons": ["semantic match"],
                    }
                ],
                "search_session_payload": {"query": "llm security"},
            },
            "review_payload_json": {},
        }

        updated_row = dict(row)

        def _update_side_effect(session_id, **kwargs):
            updated_row["status"] = kwargs.get("status", updated_row["status"])
            updated_row["confirmed"] = kwargs.get("confirmed", updated_row["confirmed"])
            if "review_payload" in kwargs and kwargs["review_payload"] is not None:
                updated_row["review_payload_json"] = kwargs["review_payload"]
            return updated_row

        with (
            patch("backend.review_service.get_review_session", return_value=row),
            patch("backend.review_service.update_review_session", side_effect=_update_side_effect),
            patch("backend.review_service.time.sleep"),
            patch(
                "backend.review_service._call_gemini",
                side_effect=[
                    ('{"decisions":[{"paper_id":"p1","decision":"include","reason":"相关"}]}', "STOP", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "thoughts_tokens": 0}),
                    RuntimeError("transient synthesis error"),
                    ('## 主题界定\n综述正文\n\n## 分类框架\n一类。\n\n## 研究脉络\n...\n\n## 方法路线\n...\n\n## 类内比较\n...\n\n## 跨类别比较\n...\n\n## 代表性工作\n- Paper One\n\n## 共识与分歧\n...\n\n## 局限与空白\n...\n\n## 参考论文清单\n- Paper One', "STOP", {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30, "thoughts_tokens": 0}),
                ],
            ),
        ):
            detail = generate_review_from_session(user_id="u1", review_session_id="review_synthesis_retry", confirmed=True)

        self.assertEqual(detail["review"]["answer_summary"]["model_status"], "ok")
        self.assertEqual(detail["review"]["answer_summary"]["synthesis_retry_count"], 1)
        self.assertIn("自动重试 1 次后成功", " ".join(detail["review"]["answer_summary"]["limitations"]))

    def test_generate_review_parallel_batches_preserve_original_order(self) -> None:
        row = {
            "id": "review_parallel",
            "title": "llm security",
            "query": "llm security",
            "status": "prepared",
            "confirmed": False,
            "prepared_payload_json": {
                "query": "llm security",
                "structured_query": {
                    "intent": "search",
                    "topic": "llm security",
                    "filters": {"venues": [], "years": [], "year_from": None, "year_to": None},
                },
                "retrieval_summary": {"intent_label": "direct_search"},
                "confirmation_prompt": "confirm",
                "preview_limit": 10,
                "candidate_limit": 20,
                "preview_results": [],
                "candidate_papers": [
                    {
                        "paper_id": "p1",
                        "title": "Paper One",
                        "abstract": "Security paper one.",
                        "venue_code": "NDSS",
                        "year": 2025,
                        "paper_url": "https://example.com/p1",
                        "score": 0.91,
                        "match_reasons": ["semantic match"],
                    },
                    {
                        "paper_id": "p2",
                        "title": "Paper Two",
                        "abstract": "Security paper two.",
                        "venue_code": "USENIX_SECURITY",
                        "year": 2024,
                        "paper_url": "https://example.com/p2",
                        "score": 0.88,
                        "match_reasons": ["semantic match"],
                    },
                ],
                "search_session_payload": {"query": "llm security"},
            },
            "review_payload_json": {},
        }

        updated_row = dict(row)

        def _update_side_effect(session_id, **kwargs):
            updated_row["status"] = kwargs.get("status", updated_row["status"])
            updated_row["confirmed"] = kwargs.get("confirmed", updated_row["confirmed"])
            if "review_payload" in kwargs and kwargs["review_payload"] is not None:
                updated_row["review_payload_json"] = kwargs["review_payload"]
            return updated_row

        def _classify_side_effect(query, batch):
            paper_id = batch[0].paper_id
            if paper_id == "p1":
                time.sleep(0.03)
            else:
                time.sleep(0.005)
            return ({paper_id: {"decision": "include", "reason": "相关"}}, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, False)

        with (
            patch("backend.review_service.get_review_session", return_value=row),
            patch("backend.review_service.update_review_session", side_effect=_update_side_effect),
            patch("backend.review_service.REVIEW_BATCH_SIZE", 1),
            patch("backend.review_service.REVIEW_FILTER_PARALLELISM", 2),
            patch("backend.review_service._classify_batch_with_retry", side_effect=_classify_side_effect),
            patch(
                "backend.review_service._call_gemini",
                return_value=(
                    '## 主题界定\n综述正文\n\n## 分类框架\n两类。\n\n## 研究脉络\n...\n\n## 方法路线\n...\n\n## 类内比较\n...\n\n## 跨类别比较\n...\n\n## 代表性工作\n- Paper One\n- Paper Two\n\n## 共识与分歧\n...\n\n## 局限与空白\n...\n\n## 参考论文清单\n- Paper One\n- Paper Two',
                    "STOP",
                    {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
                ),
            ),
        ):
            detail = generate_review_from_session(user_id="u1", review_session_id="review_parallel", confirmed=True)

        self.assertEqual([item["paper_id"] for item in detail["review"]["included_papers"]], ["p1", "p2"])
        self.assertEqual(detail["review"]["answer_summary"]["included_count"], 2)
        self.assertEqual(detail["review"]["answer_summary"]["filter_parallel_batches"], 2)

    def test_generate_review_repairs_missing_required_sections_without_fallback(self) -> None:
        row = {
            "id": "review_repair",
            "title": "llm security",
            "query": "llm security",
            "status": "prepared",
            "confirmed": False,
            "prepared_payload_json": {
                "query": "llm security",
                "structured_query": {
                    "intent": "search",
                    "topic": "llm security",
                    "filters": {"venues": [], "years": [], "year_from": None, "year_to": None},
                },
                "retrieval_summary": {"intent_label": "direct_search"},
                "confirmation_prompt": "confirm",
                "preview_limit": 10,
                "candidate_limit": 20,
                "preview_results": [],
                "candidate_papers": [
                    {
                        "paper_id": "p1",
                        "title": "Paper One",
                        "abstract": "Security paper one.",
                        "venue_code": "NDSS",
                        "year": 2025,
                        "paper_url": "https://example.com/p1",
                        "score": 0.91,
                        "match_reasons": ["semantic match"],
                    }
                ],
                "search_session_payload": {"query": "llm security"},
            },
            "review_payload_json": {},
        }

        updated_row = dict(row)

        def _update_side_effect(session_id, **kwargs):
            updated_row["status"] = kwargs.get("status", updated_row["status"])
            updated_row["confirmed"] = kwargs.get("confirmed", updated_row["confirmed"])
            if "review_payload" in kwargs and kwargs["review_payload"] is not None:
                updated_row["review_payload_json"] = kwargs["review_payload"]
            return updated_row

        with (
            patch("backend.review_service.get_review_session", return_value=row),
            patch("backend.review_service.update_review_session", side_effect=_update_side_effect),
            patch(
                "backend.review_service._call_gemini",
                side_effect=[
                    (
                        '{"decisions":[{"paper_id":"p1","decision":"include","reason":"相关"}]}',
                        "STOP",
                        {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    ),
                    (
                        "## 主题界定\n综述正文\n\n## 分类框架\n两类。\n\n## 类内对比\n比较内容。\n\n## 代表性工作\n- Paper One",
                        "STOP",
                        {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
                    ),
                    (
                        "## 主题界定\n补充后仍不完整。\n\n## 分类框架\n两类。\n\n## 类内对比\n比较内容。\n\n## 代表性工作\n- Paper One",
                        "STOP",
                        {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                    ),
                ],
            ),
        ):
            detail = generate_review_from_session(user_id="u1", review_session_id="review_repair", confirmed=True)

        self.assertEqual(detail["review"]["answer_summary"]["model_status"], "ok_with_structure_repair")
        self.assertNotIn("fallback", detail["review"]["answer_summary"]["model_status"])
        for section in REVIEW_REQUIRED_SECTIONS:
            self.assertIn(section, detail["review"]["review_markdown"])
        self.assertTrue(detail["review"]["answer_summary"]["limitations"])


if __name__ == "__main__":
    unittest.main()
