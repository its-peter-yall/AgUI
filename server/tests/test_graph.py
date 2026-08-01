"""
============================================================================
FILE: test_graph.py
LOCATION: server/tests/test_graph.py
============================================================================
PURPOSE:
    Tests LangGraph course generation contracts, state, and topology.
ROLE IN PROJECT:
    Guards staged LangGraph course generation contracts.
KEY COMPONENTS:
    - StagedStateTests: State schema, reducer, and secret safety checks
    - GraphBuildTests: Caching and factory tests
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.graph
USAGE:
    python -m unittest server.tests.test_graph -v
============================================================================
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from server.graph.build import build_graph, get_graph


class StagedStateTests(unittest.TestCase):
    """Tests staged graph state, reducers, and batch sizing."""

    def test_batches_are_three_then_ten_then_remainder(self) -> None:
        from server.graph.nodes import select_topic_batch

        cursor = 0
        batches: list[tuple[int, int]] = []
        while cursor < 30:
            batch = select_topic_batch(cursor, 30)
            batches.append((batch.start, batch.size))
            cursor = batch.start + batch.size
        self.assertEqual(
            batches,
            [(0, 3), (3, 10), (13, 10), (23, 7)],
        )

    def test_keyed_reducer_replaces_resumed_topic_result(self) -> None:
        from server.graph.state import merge_generator_results

        current = [
            {
                "batch_start": 0,
                "sequence_index": 1,
                "content_ready": False,
                "error_message": "first failure",
            }
        ]
        update = [
            {
                "batch_start": 0,
                "sequence_index": 1,
                "content_ready": True,
                "error_message": None,
            }
        ]
        merged = merge_generator_results(current, update)
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0]["content_ready"])

    def test_checkpoint_state_excludes_runtime_secrets_and_large_artifacts(
        self,
    ) -> None:
        from server.graph.state import CourseGraphContext, CourseState

        forbidden = {
            "api_key",
            "llm_context",
            "search_context",
            "search_credentials",
            "authorization",
            "session_ref",
            "cancel_event",
            "content_markdown",
            "source_excerpts",
            "generation_brief",
        }
        state_fields = {name.lower() for name in CourseState.__annotations__}
        context_fields = {
            name.lower() for name in CourseGraphContext.__annotations__
        }
        self.assertTrue(forbidden.isdisjoint(state_fields))
        self.assertIn("llm_context", context_fields)
        self.assertIn("search_context", context_fields)


class GraphBuildTests(unittest.IsolatedAsyncioTestCase):
    """Tests for compiled graph behavior."""

    async def test_get_graph_caches_on_app_state(self) -> None:
        app_state = SimpleNamespace()
        graph_one = get_graph(app_state)
        graph_two = get_graph(app_state)

        self.assertIs(graph_one, graph_two)


if __name__ == "__main__":
    unittest.main()
