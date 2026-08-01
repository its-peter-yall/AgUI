"""
============================================================================
FILE: test_staged_graph.py
LOCATION: server/tests/test_staged_graph.py
============================================================================
PURPOSE:
    Tests optional research, TOC-first persistence, exact batches, and barriers.
ROLE IN PROJECT:
    Guards permanent staged LangGraph topology and preview priority.
KEY COMPONENTS:
    - StagedGraphTests: Web routing, batch order, fan-out barrier tests
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.graph build and nodes
USAGE:
    python -m unittest server.tests.test_staged_graph -v
============================================================================
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from server.graph.build import build_graph
from server.graph.nodes import fan_out_generators, select_topic_batch
from server.schemas.generation import GenerationStage
from server.schemas.llm import LLMContext
from server.schemas.search import SearchContext


class StagedGraphTests(unittest.IsolatedAsyncioTestCase):
    """Tests staged graph route and batch orchestration."""

    async def test_web_off_skips_research_and_runs_three_then_ten(self) -> None:
        calls: list[str] = []
        jobs = MagicMock()
        jobs.is_cancel_requested.return_value = False
        artifacts = MagicMock()
        artifacts.count_topics.return_value = 13

        async def initialize(state, runtime):
            calls.append("initialize")
            return {"resolved_mode": "full", "web_search_enabled": False}

        async def outline(state, runtime):
            calls.append("outline")
            return {"topic_count": 13, "next_topic_index": 0}

        async def plan_batch(state, runtime):
            batch = select_topic_batch(state["next_topic_index"], 13)
            calls.append(f"plan:{batch.start}:{batch.size}")
            return {
                "active_batch_start": batch.start,
                "active_batch_size": batch.size,
            }

        async def generator(state, runtime):
            return {
                "generator_results": [
                    {
                        "batch_start": state["batch_start"],
                        "sequence_index": state["sequence_index"],
                        "content_ready": True,
                        "error_message": None,
                    }
                ]
            }

        async def quizzer(state, runtime):
            return {
                "topic_results": [
                    {
                        "batch_start": state["batch_start"],
                        "sequence_index": state["sequence_index"],
                        "terminal_status": "READY",
                        "error_message": None,
                    }
                ]
            }

        async def advance(state, runtime):
            start = state["active_batch_start"]
            size = state["active_batch_size"]
            calls.append(f"advance:{start}:{size}")
            return {"next_topic_index": start + size}

        graph = build_graph(
            node_overrides={
                "initialize_generation_node": initialize,
                "outline_planner_node": outline,
                "plan_brief_batch_node": plan_batch,
                "generator_node": generator,
                "quizzer_node": quizzer,
                "advance_batch_node": advance,
            }
        )
        with patch("server.graph.nodes.generation_artifact_store", artifacts):
            result = await graph.ainvoke(
                {
                    "job_id": "job-1",
                    "session_id": "session-1",
                    "query": "Topic",
                    "user_id": None,
                    "mode": "full",
                    "next_topic_index": 0,
                    "generator_results": [],
                    "topic_results": [],
                    "degraded": False,
                },
                config={"max_concurrency": 3},
                context={
                    "llm_context": LLMContext(
                        api_key="llm-key",
                        model="test/model",
                    ),
                    "search_context": SearchContext(),
                    "worker_id": "worker-1",
                },
            )
        self.assertEqual(result["next_topic_index"], 13)
        self.assertNotIn("research", calls)
        self.assertEqual(
            [call for call in calls if call.startswith("plan:")],
            ["plan:0:3", "plan:3:10"],
        )
        self.assertEqual(
            [call for call in calls if call.startswith("advance:")],
            ["advance:0:3", "advance:3:10"],
        )

    def test_generator_send_payload_contains_only_artifact_references(self) -> None:
        state = {
            "job_id": "job-1",
            "session_id": "session-1",
            "active_batch_start": 3,
            "active_batch_size": 2,
        }
        sends = fan_out_generators(state)
        self.assertEqual(len(sends), 2)
        self.assertEqual(
            set(sends[0].arg.keys()),
            {"job_id", "session_id", "batch_start", "sequence_index"},
        )
        self.assertNotIn("content_markdown", repr(sends))
        self.assertNotIn("source_excerpts", repr(sends))

    async def test_web_on_runs_research_before_outline(self) -> None:
        calls: list[str] = []
        graph = build_graph()
        with (
            patch(
                "server.graph.nodes.run_research",
                new=AsyncMock(side_effect=lambda **kwargs: calls.append("research")),
            ),
            patch(
                "server.graph.nodes.run_outline",
                new=AsyncMock(side_effect=lambda **kwargs: calls.append("outline")),
            ),
        ):
            await graph.ainvoke(
                {
                    "job_id": "job-1",
                    "session_id": "session-1",
                    "query": "Topic",
                    "user_id": None,
                    "mode": "lite",
                    "web_search_enabled": True,
                    "next_topic_index": 0,
                    "generator_results": [],
                    "topic_results": [],
                    "degraded": False,
                },
                context={
                    "llm_context": LLMContext(
                        api_key="llm-key",
                        model="test/model",
                    ),
                    "search_context": SearchContext(),
                    "worker_id": "worker-1",
                },
            )
        self.assertLess(calls.index("research"), calls.index("outline"))


if __name__ == "__main__":
    unittest.main()
