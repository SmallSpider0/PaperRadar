from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.chat_answer import _build_tool_context
from backend.chat_models import ChatAnswerResponse, ChatFilters, ChatSearchResponse, PaperToolResponse, RetrievalPaper, StructuredQuery
from backend.chat_orchestrator import _plan_tool_step, derive_route_mode, orchestrate_chat_turn
from backend.chat_parser import detect_intent, rules_parse_query


def _dummy_answer(intent: str) -> ChatAnswerResponse:
    return ChatAnswerResponse(
        query="q",
        answer="ok",
        answer_markdown="ok",
        citations=[],
        papers=[],
        structured_query=StructuredQuery(intent=intent, topic="q", filters=ChatFilters()),
        answer_summary={},
        used_papers=[],
        followup_suggestions=[],
    )


class ChatParserIntentTests(unittest.TestCase):
    def test_detect_greeting_as_chat(self) -> None:
        self.assertEqual(detect_intent("你好"), "chat")
        self.assertEqual(rules_parse_query("你好").intent, "chat")

    def test_detect_meta_and_help(self) -> None:
        self.assertEqual(detect_intent("你是谁"), "meta")
        self.assertEqual(detect_intent("这个页面怎么用"), "help")

    def test_detect_ambiguous_followup(self) -> None:
        self.assertEqual(detect_intent("继续"), "ask_clarification")


class ChatOrchestratorTests(unittest.TestCase):
    def test_route_reuses_context_for_reference_query(self) -> None:
        structured_query = StructuredQuery(intent="qa", topic="prompt injection", filters=ChatFilters())
        mode = derive_route_mode(
            "这些论文里哪几篇更值得先读",
            structured_query,
            context_papers=[{"paper_id": "p1", "title": "Paper 1", "score": 0.9}],
        )
        self.assertEqual(mode, "answer_from_context")

    def test_orchestrator_direct_chat_skips_search(self) -> None:
        with (
            patch("backend.chat_orchestrator.parse_query", return_value=StructuredQuery(intent="chat", topic="你好", filters=ChatFilters())),
            patch("backend.chat_orchestrator.run_direct_chat_answer", return_value=_dummy_answer("chat")) as direct_mock,
            patch("backend.chat_orchestrator.run_chat_search") as search_mock,
        ):
            answer, mode, tool_calls = orchestrate_chat_turn("你好")
        self.assertEqual(mode, "chat")
        self.assertEqual(answer.structured_query.intent, "chat")
        self.assertEqual(tool_calls, [])
        direct_mock.assert_called_once()
        search_mock.assert_not_called()

    def test_orchestrator_search_query_runs_search_tool(self) -> None:
        structured_query = StructuredQuery(intent="search", topic="prompt injection", filters=ChatFilters())
        search_response = ChatSearchResponse(
            query="prompt injection",
            structured_query=structured_query,
            results=[],
            retrieval_summary={},
            paper_tool=PaperToolResponse(tool_name="search_papers", query_summary="prompt injection", applied_filters={}, results=[]),
        )
        with (
            patch("backend.chat_orchestrator.parse_query", return_value=structured_query),
            patch("backend.chat_orchestrator.run_chat_search", return_value=search_response) as search_mock,
            patch("backend.chat_orchestrator.run_grounded_chat_answer", return_value=_dummy_answer("search")) as grounded_mock,
        ):
            _, mode, tool_calls = orchestrate_chat_turn("帮我找 prompt injection 论文")
        self.assertEqual(mode, "search")
        self.assertTrue(tool_calls)
        self.assertEqual(tool_calls[0]["tool"], "search_papers")
        search_mock.assert_called_once()
        grounded_mock.assert_called_once()

    def test_planner_uses_llm_json_decision(self) -> None:
        structured_query = StructuredQuery(intent="qa", topic="prompt injection", filters=ChatFilters())
        with patch(
            "backend.chat_orchestrator._call_gemini",
            return_value=(
                '{"mode":"compare","tool":"compare_papers","tool_args":{"paper_ids":["p1","p2"]},"needs_more_tools":false,"final_response":"grounded","reason":"compare selected papers"}',
                None,
                {},
            ),
        ):
            decision = _plan_tool_step(
                "比较这两篇论文",
                structured_query=structured_query,
                heuristic_mode="compare",
                step=2,
                tool_history=[],
                current_candidates=[
                    RetrievalPaper(title="Paper 1", paper_id="p1", score=0.9),
                    RetrievalPaper(title="Paper 2", paper_id="p2", score=0.8),
                ],
            )
        self.assertEqual(decision["tool"], "compare_papers")
        self.assertEqual(decision["mode"], "compare")

    def test_orchestrator_can_chain_reuse_then_compare(self) -> None:
        structured_query = StructuredQuery(intent="qa", topic="prompt injection", filters=ChatFilters())
        session_papers = [{"paper_id": "p1", "title": "Paper 1", "score": 0.9}]
        reuse_response = ChatSearchResponse(
            query="这些论文有啥区别",
            structured_query=structured_query,
            results=[RetrievalPaper(title="Paper 1", paper_id="p1", score=0.9)],
            retrieval_summary={},
            paper_tool=PaperToolResponse(tool_name="reuse_session_papers", query_summary="prompt injection", applied_filters={}, results=[]),
        )
        with (
            patch("backend.chat_orchestrator.parse_query", return_value=structured_query),
            patch(
                "backend.chat_orchestrator._plan_tool_step",
                side_effect=[
                    {
                        "mode": "compare",
                        "tool": "reuse_session_papers",
                        "tool_args": {},
                        "needs_more_tools": True,
                        "final_response": "grounded",
                        "reason": "need session papers first",
                    },
                    {
                        "mode": "compare",
                        "tool": "compare_papers",
                        "tool_args": {"paper_ids": ["p1"]},
                        "needs_more_tools": False,
                        "final_response": "grounded",
                        "reason": "then compare",
                    },
                ],
            ),
            patch("backend.chat_orchestrator._build_search_response_from_context", return_value=reuse_response),
            patch(
                "backend.chat_orchestrator.compare_papers",
                return_value=type("CompareResult", (), {"model_dump": lambda self: {"paper_ids": ["p1"], "rows": [{"paper_id": "p1"}], "summary": "compared 1 paper"}})(),
            ),
            patch("backend.chat_orchestrator.run_grounded_chat_answer", return_value=_dummy_answer("compare")) as grounded_mock,
        ):
            answer, mode, tool_calls = orchestrate_chat_turn(
                "比较这些论文",
                context_papers=session_papers,
            )
        self.assertEqual(mode, "compare")
        self.assertEqual(len(tool_calls), 2)
        self.assertEqual(tool_calls[0]["tool"], "reuse_session_papers")
        self.assertEqual(tool_calls[1]["tool"], "compare_papers")
        grounded_mock.assert_called_once()
        grounded_kwargs = grounded_mock.call_args.kwargs
        self.assertEqual(grounded_kwargs["compare_result"]["summary"], "compared 1 paper")
        self.assertEqual(len(grounded_kwargs["tool_calls"]), 2)

    def test_build_tool_context_includes_compare_and_filter(self) -> None:
        rendered = _build_tool_context(
            tool_calls=[
                {
                    "tool": "search_papers",
                    "summary": "retrieved 5 papers",
                    "planner_reason": "need evidence",
                    "args": {"query": "prompt injection", "top_k": 5},
                }
            ],
            compare_result={
                "summary": "compared 2 papers",
                "rows": [{"title": "Paper A", "problem": "jailbreak", "approach": "classifier"}],
            },
            filter_result={
                "summary": "kept 2 of 5 candidates",
                "results": [{"title": "Paper A", "topic_tags": ["llm safety", "defense"]}],
            },
        )
        self.assertIn("[Tool Trace]", rendered)
        self.assertIn("compared 2 papers", rendered)
        self.assertIn("kept 2 of 5 candidates", rendered)


if __name__ == "__main__":
    unittest.main()
