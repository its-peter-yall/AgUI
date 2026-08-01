"""
============================================================================
FILE: test_graph.py
LOCATION: server/tests/test_graph.py
============================================================================
PURPOSE:
    Tests LangGraph course generation contract.
ROLE IN PROJECT:
    Guards LangGraph course generation contract.
    - Verifies node wrappers call existing agents and persistence methods
    - Verifies graph fan-out, response shape, metrics, and secret safety
KEY COMPONENTS:
    - GraphNodeTests: Unit tests for individual graph nodes
    - GraphBuildTests: Integration tests for compiled graph execution
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.graph, server.schemas
USAGE:
    python -m unittest server.tests.test_graph -v
============================================================================
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langgraph.types import Send

from langgraph.errors import NodeError

from server.agents.generator import GeneratedContent
from server.graph.build import build_graph, get_graph
from server.graph.nodes import (
    build_response_node,
    fan_out_generators,
    fan_out_quizzers,
    generator_error_handler,
    generator_node,
    planner_node,
    quizzer_error_handler,
    quizzer_node,
)
from server.graph.state import CourseState, GeneratorResult, TopicResult
from server.schemas.learning import (
    CourseOutline,
    NodeStatus,
    QuizCard,
    QuizOption,
    QuizSet,
    TopicNode,
)
from server.schemas.llm import LLMContext


def _llm_context() -> LLMContext:
    return LLMContext(api_key="test-key", model="test/model")


def _config(session_ref: dict[str, str] | None = None) -> dict[str, object]:
    return {
        "configurable": {
            "thread_id": "test-thread",
            "llm_context": _llm_context(),
            "session_ref": session_ref if session_ref is not None else {},
        }
    }


def _runtime_config(
    session_ref: dict[str, str] | None = None,
) -> dict[str, object]:
    return _config(session_ref)


def _runtime_context(
    session_ref: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "llm_context": _llm_context(),
        "session_ref": session_ref if session_ref is not None else {},
    }


def _topics(count: int = 5) -> list[TopicNode]:
    return [
        TopicNode(
            index=index,
            title=f"Topic {index}",
            summary_for_context=f"Summary {index}",
            key_terms=["term-a", "term-b"],
            complexity="Basic" if index == 0 else "Intermediate",
            quiz_count=1 if index == 0 else 2,
        )
        for index in range(count)
    ]


def _outline() -> CourseOutline:
    return CourseOutline(course_title="Test Course", topics=_topics())


def _quiz_set() -> QuizSet:
    options = [
        QuizOption(
            option_id=f"option-{index}",
            display_label=label,
            text=f"Option {label}",
            is_correct=label == "A",
            explanation="Explanation",
        )
        for index, label in enumerate(["A", "B", "C", "D"])
    ]
    return QuizSet(
        quizzes=[
            QuizCard(
                question_text="Question?",
                options=options,
                difficulty="medium",
            )
        ],
        current_index=0,
    )


def _session() -> dict[str, object]:
    return {
        "id": "session-1",
        "user_id": "user-1",
        "query": "test query",
        "course_title": "Test Course",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "total_nodes": 0,
        "completed_nodes": 0,
    }


def _node(index: int, status: NodeStatus = NodeStatus.LOCKED) -> dict[str, object]:
    return {
        "id": f"node-{index}",
        "learning_session_id": "session-1",
        "sequence_index": index,
        "title": f"Topic {index}",
        "content_markdown": "Content",
        "status": status.value,
        "error_message": None,
        "retry_available": False,
        "complexity": "Intermediate",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "quiz": _quiz_set().model_dump(),
    }


class GraphNodeTests(unittest.IsolatedAsyncioTestCase):
    """Tests for graph node behavior."""

    async def test_planner_node_creates_session_and_records_ref(self) -> None:
        session_ref: dict[str, str] = {}
        manager = MagicMock()
        manager.create_learning_session.return_value = _session()

        with (
            patch("server.graph.nodes.planner_agent.plan", new=AsyncMock())
            as mock_plan,
            patch("server.graph.nodes.learning_manager", manager),
        ):
            mock_plan.return_value = _outline()
            result = await planner_node(
                {
                    "query": "test query",
                    "user_id": "user-1",
                    "mode": "auto",
                    "resolved_mode": "lite",
                },
                _runtime_context(session_ref),
            )

        self.assertEqual(result["session"]["id"], "session-1")
        self.assertEqual(session_ref["session_id"], "session-1")
        self.assertEqual(result["topic_results"], [])
        self.assertIn("planner_ms", result)
        mock_plan.assert_awaited_once()
        self.assertEqual(mock_plan.await_args.kwargs["mode"], "lite")
        create_kwargs = manager.create_learning_session.call_args.kwargs
        self.assertEqual(create_kwargs["mode"], "auto")
        self.assertEqual(create_kwargs["resolved_mode"], "lite")

    def test_build_response_node_sorts_and_computes_metrics(self) -> None:
        state = {
            "session": _session(),
            "planner_ms": 10.0,
            "parallel_start_time": 100.0,
            "total_start_time": 99.0,
            "topic_results": [
                {"node": _node(2), "generation_ms": 30.0, "error_message": None},
                {"node": _node(0), "generation_ms": 20.0, "error_message": None},
            ],
        }

        with patch("server.graph.nodes.time.perf_counter", return_value=101.0):
            result = build_response_node(state)

        self.assertEqual([node["sequence_index"] for node in result["nodes"]], [0, 2])
        self.assertEqual(result["metrics"]["planner_ms"], 10.0)
        self.assertEqual(result["metrics"]["serial_estimate_ms"], 50.0)
        self.assertIn("latency_savings_ms", result["metrics"])

    def test_build_response_node_clamps_negative_latency_savings(self) -> None:
        state = {
            "session": _session(),
            "planner_ms": 5.0,
            "parallel_start_time": 100.0,
            "total_start_time": 99.0,
            "topic_results": [
                {"node": _node(0), "generation_ms": 1.0, "error_message": None},
            ],
        }

        with patch("server.graph.nodes.time.perf_counter", return_value=110.0):
            result = build_response_node(state)

        self.assertEqual(result["metrics"]["parallel_ms"], 10000.0)
        self.assertEqual(result["metrics"]["serial_estimate_ms"], 1.0)
        self.assertEqual(result["metrics"]["latency_savings_ms"], 0.0)

    def test_build_response_node_metrics_omit_api_key(self) -> None:
        state = {
            "session": _session(),
            "planner_ms": 10.0,
            "parallel_start_time": 100.0,
            "total_start_time": 99.0,
            "topic_results": [
                {"node": _node(0), "generation_ms": 20.0, "error_message": None},
            ],
        }

        with patch("server.graph.nodes.time.perf_counter", return_value=101.0):
            result = build_response_node(state)

        metrics_text = repr(result["metrics"])
        self.assertNotIn("test-key", metrics_text)
        self.assertNotIn("llm_context", metrics_text)
        self.assertNotIn("api_key", metrics_text)

    def test_build_response_node_mixed_failures(self) -> None:
        state = {
            "session": _session(),
            "planner_ms": 10.0,
            "parallel_start_time": 100.0,
            "total_start_time": 99.0,
            "topic_results": [
                {
                    "node": _node(0),
                    "generation_ms": 20.0,
                    "error_message": None,
                },
                {
                    "node": {
                        **_node(1, NodeStatus.ERROR),
                        "error_message": "boom",
                    },
                    "generation_ms": 5.0,
                    "error_message": "boom",
                },
                {
                    "node": {
                        **_node(2, NodeStatus.ERROR),
                        "error_message": "err",
                    },
                    "generation_ms": 3.0,
                    "error_message": "err",
                },
            ],
        }

        with patch("server.graph.nodes.time.perf_counter", return_value=101.0):
            result = build_response_node(state)

        self.assertEqual(len(result["nodes"]), 3)
        self.assertEqual(result["metrics"]["cards_success"], 1)
        self.assertEqual(result["metrics"]["cards_failed"], 2)

    async def test_planner_node_calls_complexity_validation(self) -> None:
        session_ref: dict[str, str] = {}
        manager = MagicMock()
        manager.create_learning_session.return_value = _session()

        with (
            patch("server.graph.nodes.planner_agent.plan", new=AsyncMock())
            as mock_plan,
            patch("server.graph.nodes.validate_complexity_distribution")
            as mock_validate,
            patch("server.graph.nodes.learning_manager", manager),
            patch("server.graph.nodes.logger") as mock_logger,
        ):
            mock_plan.return_value = _outline()
            mock_validate.return_value = {
                "valid": False,
                "errors": ["no basic topics"],
                "warnings": [],
                "distribution": {},
            }
            await planner_node(
                {"query": "test query", "user_id": "user-1"},
                _runtime_context(session_ref),
            )

        mock_validate.assert_called_once_with(mock_plan.return_value)
        mock_logger.warning.assert_called_once()


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


class GeneratorNodeTests(unittest.IsolatedAsyncioTestCase):
    """Tests for generator_node pure content generation."""

    async def test_generator_node_returns_content(self) -> None:
        state = {
            "topic_data": _topics()[0].model_dump(),
            "prev_summary": "Start",
            "next_summary": "Summary 1",
            "session_id": "session-1",
            "sequence_index": 0,
        }

        with (
            patch("server.graph.nodes.generator_agent.generate_explanation")
            as mock_generate,
        ):
            mock_generate.return_value = GeneratedContent(
                content_markdown="Generated content" * 30,
                key_takeaways=["a", "b", "c"],
            )
            result = await generator_node(state, _runtime_context())

        self.assertEqual(len(result["generator_results"]), 1)
        gen_result = result["generator_results"][0]
        self.assertEqual(
            gen_result["content_markdown"], "Generated content" * 30,
        )
        self.assertIsNone(gen_result["error_message"])
        self.assertEqual(gen_result["sequence_index"], 0)
        mock_generate.assert_called_once()

    async def test_generator_node_no_db_writes(self) -> None:
        topic = _topics()[0]
        state = {
            "topic_data": topic.model_dump(),
            "prev_summary": "Start",
            "next_summary": "Summary 1",
            "session_id": "session-1",
            "sequence_index": 0,
        }

        with (
            patch("server.graph.nodes.generator_agent.generate_explanation")
            as mock_generate,
        ):
            mock_generate.return_value = GeneratedContent(
                content_markdown="content" * 50,
                key_takeaways=["a", "b", "c"],
            )
            result = await generator_node(state, _runtime_context())

        mock_generate.assert_called_once_with(
            topic=topic,
            prev_summary=None,
            next_summary="Summary 1",
            llm_context=_llm_context(),
        )
        gen_result = result["generator_results"][0]
        self.assertNotIn("node", gen_result)

    async def test_generator_node_re_raises_cancelled_error(self) -> None:
        state = {
            "topic_data": _topics()[0].model_dump(),
            "prev_summary": "Start",
            "next_summary": "End",
            "session_id": "session-1",
            "sequence_index": 0,
        }

        with (
            patch("server.graph.nodes.generator_agent.generate_explanation")
            as mock_generate,
        ):
            mock_generate.side_effect = asyncio.CancelledError()
            with self.assertRaises(asyncio.CancelledError):
                await generator_node(state, _runtime_context())


class QuizzerNodeTests(unittest.IsolatedAsyncioTestCase):
    """Tests for quizzer_node — quiz generation + DB persistence."""

    async def test_quizzer_node_creates_success_node(self) -> None:
        manager = MagicMock()
        manager.create_concept_node.return_value = _node(
            0, NodeStatus.VIEWING_EXPLANATION,
        )
        state = {
            "topic_data": _topics()[0].model_dump(),
            "content_markdown": "Generated content",
            "sequence_index": 0,
            "session_id": "session-1",
            "error_message": None,
        }

        with (
            patch("server.graph.nodes.quizzer_agent.generate_quiz_set")
            as mock_quiz,
            patch("server.graph.nodes.learning_manager", manager),
        ):
            mock_quiz.return_value = _quiz_set()
            result = await quizzer_node(state, _runtime_context())

        self.assertEqual(len(result["topic_results"]), 1)
        self.assertEqual(
            result["topic_results"][0]["node"]["status"],
            NodeStatus.VIEWING_EXPLANATION.value,
        )
        manager.create_concept_node.assert_called_once()

    async def test_quizzer_node_skips_quiz_on_generator_error(self) -> None:
        manager = MagicMock()
        error_node = _node(0, NodeStatus.ERROR)
        error_node["error_message"] = "generator failed"
        error_node["retry_available"] = True
        manager.create_concept_node.return_value = error_node
        state = {
            "topic_data": _topics()[0].model_dump(),
            "content_markdown": "Content generation failed. Retry is available.",
            "sequence_index": 0,
            "session_id": "session-1",
            "error_message": "generator failed",
        }

        with (
            patch("server.graph.nodes.quizzer_agent.generate_quiz_set")
            as mock_quiz,
            patch("server.graph.nodes.learning_manager", manager),
        ):
            result = await quizzer_node(state, _runtime_context())

        mock_quiz.assert_not_called()
        self.assertEqual(
            result["topic_results"][0]["node"]["status"],
            NodeStatus.ERROR.value,
        )

    async def test_quizzer_node_preserves_content_on_quiz_failure(self) -> None:
        manager = MagicMock()
        error_node = _node(1, NodeStatus.ERROR)
        error_node["error_message"] = "quiz boom"
        manager.create_concept_node.return_value = error_node
        state = {
            "topic_data": _topics()[1].model_dump(),
            "content_markdown": "Real content here",
            "sequence_index": 1,
            "session_id": "session-1",
            "error_message": None,
        }

        with (
            patch("server.graph.nodes.quizzer_agent.generate_quiz_set")
            as mock_quiz,
            patch("server.graph.nodes.learning_manager", manager),
        ):
            mock_quiz.side_effect = RuntimeError("quiz boom")
            result = await quizzer_node(state, _runtime_context())

        call_kwargs = manager.create_concept_node.call_args.kwargs
        self.assertEqual(call_kwargs["content_markdown"], "Real content here")
        self.assertEqual(call_kwargs["failed_step"].value, "QUIZZER")

    async def test_quizzer_node_passes_quiz_count(self) -> None:
        manager = MagicMock()
        manager.create_concept_node.return_value = _node(1, NodeStatus.LOCKED)
        topics = _topics(3)
        state = {
            "topic_data": topics[1].model_dump(),
            "content_markdown": "Generated content",
            "sequence_index": 1,
            "session_id": "session-1",
            "error_message": None,
        }

        with (
            patch("server.graph.nodes.quizzer_agent.generate_quiz_set")
            as mock_quiz,
            patch("server.graph.nodes.learning_manager", manager),
        ):
            mock_quiz.return_value = _quiz_set()
            await quizzer_node(state, _runtime_context())

        self.assertEqual(mock_quiz.await_args.kwargs["quiz_count"], 2)


class ErrorHandlerTests(unittest.IsolatedAsyncioTestCase):
    """Tests for error handler nodes (catch after retries exhausted)."""

    async def test_generator_error_handler_returns_error_result(self) -> None:
        state = {
            "topic_data": _topics()[0].model_dump(),
            "sequence_index": 0,
            "session_id": "session-1",
        }
        error = NodeError(node="generator_node", error=RuntimeError("LLM timeout"))

        result = await generator_error_handler(
            state, error,
        )

        self.assertEqual(len(result["generator_results"]), 1)
        gen_result = result["generator_results"][0]
        self.assertEqual(gen_result["error_message"], "LLM timeout")
        self.assertIn("failed", gen_result["content_markdown"].lower())
        self.assertEqual(gen_result["sequence_index"], 0)

    async def test_quizzer_error_handler_persists_error_node(self) -> None:
        manager = MagicMock()
        error_node = _node(1, NodeStatus.ERROR)
        manager.create_concept_node.return_value = error_node
        state = {
            "topic_data": _topics()[1].model_dump(),
            "content_markdown": "Real content",
            "sequence_index": 1,
            "session_id": "session-1",
        }
        error = NodeError(node="quizzer_node", error=RuntimeError("quiz API down"))

        with patch("server.graph.nodes.learning_manager", manager):
            result = await quizzer_error_handler(
                state, error,
            )

        call_kwargs = manager.create_concept_node.call_args.kwargs
        self.assertEqual(call_kwargs["status"], NodeStatus.ERROR)
        self.assertEqual(call_kwargs["failed_step"].value, "QUIZZER")
        self.assertEqual(call_kwargs["content_markdown"], "Real content")
        self.assertTrue(call_kwargs["retry_available"])


class GraphBuildTests(unittest.IsolatedAsyncioTestCase):
    """Tests for compiled graph behavior."""

    async def test_get_graph_caches_on_app_state(self) -> None:
        app_state = SimpleNamespace()
        graph_one = get_graph(app_state)
        graph_two = get_graph(app_state)

        self.assertIs(graph_one, graph_two)


class FanOutTests(unittest.IsolatedAsyncioTestCase):
    def test_fan_out_generators_creates_send_per_topic(self) -> None:
        state = {
            "outline": _outline().model_dump(),
            "session": _session(),
        }

        sends = fan_out_generators(state)

        self.assertEqual(len(sends), 3)
        self.assertTrue(all(isinstance(s, Send) for s in sends))
        self.assertTrue(all(s.node == "generator_node" for s in sends))

    def test_fan_out_generators_excludes_api_key(self) -> None:
        state = {
            "outline": _outline().model_dump(),
            "session": _session(),
        }

        sends = fan_out_generators(state)
        payload_text = repr(sends)

        self.assertNotIn("test-key", payload_text)
        self.assertNotIn("llm_context", payload_text)

    def test_fan_out_generators_sets_prev_next_summaries(self) -> None:
        topics = _topics()
        state = {
            "outline": _outline().model_dump(),
            "session": _session(),
        }

        sends = fan_out_generators(state)

        self.assertEqual(sends[0].arg["prev_summary"], "Start")
        self.assertEqual(sends[0].arg["next_summary"], topics[1].summary_for_context)
        self.assertEqual(sends[2].arg["prev_summary"], topics[1].summary_for_context)
        self.assertEqual(sends[2].arg["next_summary"], topics[3].summary_for_context)

    def test_fan_out_quizzers_creates_send_per_result(self) -> None:
        generator_results = [
            {
                "topic_data": _topics()[i].model_dump(),
                "content_markdown": f"Content {i}",
                "generation_ms": 100.0,
                "error_message": None,
                "sequence_index": i,
                "session_id": "session-1",
            }
            for i in range(3)
        ]
        state = {"generator_results": generator_results}

        sends = fan_out_quizzers(state)

        self.assertEqual(len(sends), 3)
        self.assertTrue(all(s.node == "quizzer_node" for s in sends))

    def test_fan_out_quizzers_passes_error_message(self) -> None:
        generator_results = [
            {
                "topic_data": _topics()[0].model_dump(),
                "content_markdown": "Content",
                "generation_ms": 100.0,
                "error_message": "LLM failed",
                "sequence_index": 0,
                "session_id": "session-1",
            }
        ]
        state = {"generator_results": generator_results}

        sends = fan_out_quizzers(state)

        self.assertEqual(sends[0].arg["error_message"], "LLM failed")


class NewGraphBuildTests(unittest.IsolatedAsyncioTestCase):
    """Tests for the rewired graph with split generator/quizzer nodes."""

    async def test_full_graph_with_split_nodes(self) -> None:
        manager = MagicMock()
        manager.create_learning_session.return_value = _session()
        
        nodes_created = [
            _node(0, NodeStatus.VIEWING_EXPLANATION),
            _node(1),
            _node(2),
            _node(3),
            _node(4),
        ]
        manager.create_concept_node.side_effect = nodes_created
        manager.get_session_nodes.return_value = nodes_created
        manager.update_node_content.side_effect = [
            _node(0, NodeStatus.VIEWING_EXPLANATION),
            _node(1, NodeStatus.LOCKED),
            _node(2, NodeStatus.LOCKED),
        ]
        
        graph = build_graph()

        with (
            patch("server.graph.nodes.planner_agent.plan", new=AsyncMock())
            as mock_plan,
            patch("server.graph.nodes.generator_agent.generate_explanation")
            as mock_generate,
            patch("server.graph.nodes.quizzer_agent.generate_quiz_set")
            as mock_quiz,
            patch("server.graph.nodes.learning_manager", manager),
        ):
            mock_plan.return_value = _outline()
            mock_generate.return_value = GeneratedContent(
                content_markdown="Content" * 100,
                key_takeaways=["a", "b", "c"],
            )
            mock_quiz.return_value = _quiz_set()
            result = await graph.ainvoke(
                {
                    "query": "test query",
                    "user_id": "user-1",
                    "topic_results": [],
                    "generator_results": [],
                },
                context=_runtime_context(),
            )

        self.assertIn("session", result)
        self.assertIn("nodes", result)
        self.assertIn("metrics", result)
        self.assertEqual(len(result["nodes"]), 3)
        self.assertEqual(result["session"]["total_nodes"], 3)

    async def test_generator_failure_produces_error_result(self) -> None:
        """Generator error handler produces ERROR result for quizzer consumption."""
        state = {
            "topic_data": _topics()[0].model_dump(),
            "prev_summary": "Start",
            "next_summary": "Summary 1",
            "session_id": "session-1",
            "sequence_index": 0,
        }
        node_error = NodeError(
            node="generator_node",
            error=RuntimeError("LLM timeout"),
        )

        result = await generator_error_handler(state, node_error)

        gen_results = result["generator_results"]
        self.assertEqual(len(gen_results), 1)
        self.assertEqual(gen_results[0]["error_message"], "LLM timeout")
        self.assertIn("failed", gen_results[0]["content_markdown"].lower())
        self.assertEqual(gen_results[0]["sequence_index"], 0)
        self.assertEqual(gen_results[0]["session_id"], "session-1")
        self.assertIsNotNone(gen_results[0]["topic_data"])


if __name__ == "__main__":
    unittest.main()
