"""
============================================================================
FILE: test_learning_graph_router.py
LOCATION: server/tests/test_learning_graph_router.py
============================================================================
PURPOSE:
    Tests graph-only learning router behavior after LangGraph cutover.
ROLE IN PROJECT:
    Verifies Phase 3 removes fallback routing while preserving HTTP contract.
    - Ensures course generation always invokes LangGraph
    - Ensures cancellation cleanup remains intact
    - Ensures single node regeneration logic works
KEY COMPONENTS:
    - LearningGraphRouterTests: Router-level tests for /learning/generate
DEPENDENCIES:
    - External: asyncio, unittest, fastapi
    - Internal: server.routers.learning, server.schemas.llm
USAGE:
    python -m unittest server.tests.test_learning_graph_router -v
============================================================================
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.agents.planner import OutlineTopicCountError
from server.routers.learning import (
    GenerateCourseRequest,
    QuizSubmitRequest,
    _generate_course_with_graph,
    router,
    submit_quiz,
)
from server.schemas.learning import (
    QuizCard,
    QuizOption,
    QuizSet,
)
from server.schemas.llm import LLMContext, get_llm_context


def _result() -> dict[str, object]:
    session = {
        "id": "session-1",
        "user_id": None,
        "query": "test query",
        "course_title": "Test Course",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "total_nodes": 1,
        "completed_nodes": 0,
        "mode": "auto",
        "resolved_mode": "lite",
    }
    node = {
        "id": "node-1",
        "learning_session_id": "session-1",
        "sequence_index": 0,
        "title": "Topic 0",
        "content_markdown": "Content",
        "status": "VIEWING_EXPLANATION",
        "error_message": None,
        "retry_available": False,
        "complexity": "Basic",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "quiz": None,
    }
    return {"session": session, "nodes": [node], "metrics": {}}


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_llm_context] = lambda: LLMContext(
        api_key="test-key",
        model="test/model",
    )
    return TestClient(app)


class LearningGraphRouterTests(unittest.IsolatedAsyncioTestCase):
    """Tests for graph-only router behavior."""

    @patch("server.routers.learning.learning_manager.get_session_nodes")
    @patch("server.routers.learning.learning_manager.get_learning_session")
    @patch("server.routers.learning.run_generation_job", new_callable=AsyncMock)
    @patch("server.routers.learning.generation_job_store.create_session_shell_and_job")
    def test_generate_always_uses_graph(
        self,
        mock_shell: MagicMock,
        mock_run: AsyncMock,
        mock_get_session: MagicMock,
        mock_get_nodes: MagicMock,
    ) -> None:
        res = _result()
        mock_shell.return_value = (res["session"], SimpleNamespace(id="job-1"))
        mock_get_session.return_value = res["session"]
        mock_get_nodes.return_value = res["nodes"]
        client = _client()

        response = client.post(
            "/learning/generate",
            json={"query": "test query"},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["id"], "session-1")
        self.assertEqual(
            response.json()["nodes"][0]["status"],
            "VIEWING_EXPLANATION",
        )
        mock_run.assert_awaited_once()

    @patch("server.routers.learning.learning_manager.get_session_nodes")
    @patch("server.routers.learning.learning_manager.get_learning_session")
    @patch("server.routers.learning.run_generation_job", new_callable=AsyncMock)
    @patch("server.routers.learning.generation_job_store.create_session_shell_and_job")
    def test_generate_response_shape(
        self,
        mock_shell: MagicMock,
        mock_run: AsyncMock,
        mock_get_session: MagicMock,
        mock_get_nodes: MagicMock,
    ) -> None:
        res = _result()
        mock_shell.return_value = (res["session"], SimpleNamespace(id="job-1"))
        mock_get_session.return_value = res["session"]
        mock_get_nodes.return_value = res["nodes"]
        client = _client()

        response = client.post(
            "/learning/generate",
            json={"query": "test query"},
        )

        body = response.json()
        self.assertIn("id", body)
        self.assertIn("nodes", body)
        self.assertIn("query", body)
        self.assertIn("course_title", body)
        self.assertIsInstance(body["nodes"], list)
        self.assertGreater(len(body["nodes"]), 0)

    def test_generate_invalid_mode_returns_422(self) -> None:
        client = _client()

        response = client.post(
            "/learning/generate",
            json={"query": "test query", "mode": "turbo"},
        )

        self.assertEqual(response.status_code, 422)

    @patch("server.routers.learning.learning_manager.get_concept_node")
    @patch("server.routers.learning.regenerate_failed_node")
    def test_regenerate_calls_regen_function(
        self, mock_regen: AsyncMock, mock_get: MagicMock,
    ) -> None:
        mock_get.return_value = {
            "id": "node-1",
            "learning_session_id": "session-1",
            "sequence_index": 0,
            "title": "Topic 0",
            "status": "ERROR",
            "error_message": "fail",
            "retry_available": True,
            "failed_step": None,
            "complexity": "Basic",
            "content_markdown": "",
            "summary_for_context": None,
            "key_terms": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "quiz": None,
        }
        mock_regen.return_value = {
            "id": "node-1",
            "learning_session_id": "session-1",
            "sequence_index": 0,
            "title": "Topic 0",
            "content_markdown": "Regenerated",
            "status": "VIEWING_EXPLANATION",
            "error_message": None,
            "retry_available": False,
            "complexity": "Basic",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "quiz": None,
        }
        client = _client()

        response = client.post(
            "/learning/nodes/node-1/regenerate",
        )

        self.assertEqual(response.status_code, 200)
        mock_regen.assert_awaited_once()

    @patch("server.routers.learning.learning_manager.get_concept_node")
    @patch("server.routers.learning.regenerate_failed_node", new_callable=AsyncMock)
    def test_regenerate_endpoint_passes_step_query(
        self, mock_regen: AsyncMock, mock_get: MagicMock,
    ) -> None:
        mock_get.return_value = {
            "id": "n1",
            "learning_session_id": "s1",
            "sequence_index": 0,
            "title": "t",
            "status": "ERROR",
            "error_message": "fail",
            "retry_available": True,
            "failed_step": None,
            "complexity": "Intermediate",
            "summary_for_context": "sum",
            "key_terms": ["a", "b"],
            "content_markdown": "c",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "quiz": None,
        }
        mock_regen.return_value = {
            "id": "n1",
            "learning_session_id": "s1",
            "sequence_index": 0,
            "title": "t",
            "content_markdown": "c",
            "status": "VIEWING_EXPLANATION",
            "error_message": None,
            "retry_available": False,
            "complexity": "Intermediate",
            "summary_for_context": "sum",
            "key_terms": ["a", "b"],
            "failed_step": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "quiz": None,
        }
        client = _client()

        response = client.post(
            "/learning/nodes/n1/regenerate?step=QUIZZER",
        )

        self.assertEqual(response.status_code, 200)
        mock_regen.assert_awaited_once()
        kwargs = mock_regen.call_args.kwargs
        self.assertEqual(kwargs["regen_step"], "QUIZZER")

    @patch("server.routers.learning.learning_manager.get_concept_node")
    @patch("server.routers.learning.regenerate_failed_node", new_callable=AsyncMock)
    def test_regenerate_endpoint_invalid_step_returns_400(
        self, mock_regen: AsyncMock, mock_get: MagicMock,
    ) -> None:
        mock_get.return_value = {
            "id": "n1",
            "learning_session_id": "s1",
            "sequence_index": 0,
            "title": "t",
            "status": "ERROR",
            "content_markdown": "c",
            "quiz": None,
        }
        client = _client()

        response = client.post(
            "/learning/nodes/n1/regenerate?step=NONSENSE",
        )

        self.assertEqual(response.status_code, 400)
        mock_regen.assert_not_awaited()

class StagedCompatibilityRouterTests(unittest.IsolatedAsyncioTestCase):
    """Tests temporary Phase 4 HTTP wrapper over complete staged graph."""

    async def test_disconnect_check_never_cancels_or_deletes_session(self) -> None:
        class RequestStub:
            def __init__(self) -> None:
                self.app = SimpleNamespace(state=SimpleNamespace())
                self.disconnect_checks = 0

            async def is_disconnected(self) -> bool:
                self.disconnect_checks += 1
                return True

        request = RequestStub()
        completed = {
            "id": "session-1",
            "user_id": None,
            "query": "test query",
            "course_title": "Test Course",
            "mode": "lite",
            "resolved_mode": "lite",
            "created_at": "2026-08-01T00:00:00+00:00",
            "updated_at": "2026-08-01T00:00:00+00:00",
            "total_nodes": 3,
            "completed_nodes": 0,
            "last_active_node_id": None,
        }
        with (
            patch(
                "server.routers.learning.generation_job_store"
                ".create_session_shell_and_job",
                return_value=(completed, SimpleNamespace(id="job-1")),
            ),
            patch(
                "server.routers.learning.run_generation_job",
                new=AsyncMock(),
            ) as run,
            patch(
                "server.routers.learning.learning_manager"
                ".get_learning_session",
                return_value=completed,
            ),
            patch(
                "server.routers.learning.learning_manager.get_session_nodes",
                return_value=[],
            ),
            patch(
                "server.routers.learning.learning_manager"
                ".delete_learning_session"
            ) as delete,
        ):
            await _generate_course_with_graph(
                GenerateCourseRequest(query="test query", mode="lite"),
                request,  # type: ignore[arg-type]
                LLMContext(api_key="llm-key", model="test/model"),
            )
        run.assert_awaited_once()
        delete.assert_not_called()
        self.assertEqual(request.disconnect_checks, 0)

    def test_old_background_helpers_are_removed(self) -> None:
        from server.routers import learning

        self.assertFalse(hasattr(learning, "_generate_single_node_bg"))
        self.assertFalse(hasattr(learning, "_generate_remaining_nodes_bg"))


def _quiz_option(label: str, correct: bool) -> QuizOption:
    return QuizOption(
        option_id=f"opt-{label}",
        display_label=label,
        text=f"Option {label}",
        is_correct=correct,
        explanation=f"Explanation {label}",
    )


def _quiz_set_with_count(count: int) -> QuizSet:
    options = [_quiz_option("A", True), _quiz_option("B", False),
               _quiz_option("C", False), _quiz_option("D", False)]
    return QuizSet(quizzes=[
        QuizCard(
            question_text=f"Question {i + 1}",
            options=options,
            difficulty="medium",
        )
        for i in range(count)
    ], current_index=0)


def _attempt_dict(
    quiz_index: int,
    is_correct: bool,
    attempt_number: int = 1,
    is_mastered: bool = False,
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": f"attempt-{attempt_number}",
        "node_id": "node-1",
        "attempt_number": attempt_number,
        "quiz_index": quiz_index,
        "selected_option_ids": ["opt-A"],
        "is_correct": is_correct,
        "score_percent": 100 if is_correct else 0,
        "correct_option_ids": ["opt-A"] if is_correct else [],
        "explanation": "Correct" if is_correct else "Incorrect",
        "is_mastered": is_mastered,
        "created_at": now,
        "updated_at": now,
    }


def _fake_learning_manager() -> MagicMock:
    fm = MagicMock()
    fm.get_concept_node.return_value = {
        "id": "node-1",
        "learning_session_id": "session-1",
        "sequence_index": 0,
    }
    fm.get_next_node.return_value = None
    fm.update_node_status.return_value = None
    fm.update_quiz_set_progress.return_value = None
    return fm


class MultiQuizMasteryTests(unittest.TestCase):
    """Tests for multi-quiz mastery and sequential progression."""

    def test_mastery_requires_all_quizzes_passed(self) -> None:
        from server.database.learning_persistence import learning_manager

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.side_effect = [
            [{"quiz_index": 0}, {"quiz_index": 1}],
            [{"quiz_index": 0}, {"quiz_index": 1}, {"quiz_index": 2}],
        ]

        with (
            patch.object(learning_manager, "_get_connection",
                         return_value=conn),
            patch.object(learning_manager, "get_quiz_set_for_node",
                         return_value={"quiz_set": _quiz_set_with_count(3)}),
        ):
            first_check = learning_manager.check_mastery("node-1")
            second_check = learning_manager.check_mastery("node-1")

        conn.close.assert_called()
        self.assertFalse(first_check)
        self.assertTrue(second_check)

    def test_sequential_enforcement_via_current_index(self) -> None:
        fm = _fake_learning_manager()
        fm.create_quiz_attempt.side_effect = [
            _attempt_dict(quiz_index=0, is_correct=True, attempt_number=1),
            _attempt_dict(quiz_index=1, is_correct=False, attempt_number=2),
        ]
        fm.get_quiz_set_for_node.return_value = {
            "quiz_set": _quiz_set_with_count(3),
        }

        with patch("server.routers.learning.learning_manager", fm):
            submit_quiz(
                "node-1",
                QuizSubmitRequest(
                    selected_option_ids=["opt-A"], quiz_index=0,
                ),
            )
            submit_quiz(
                "node-1",
                QuizSubmitRequest(
                    selected_option_ids=["opt-B"], quiz_index=1,
                ),
            )

        fm.update_quiz_set_progress.assert_called_once_with(
            node_id="node-1", current_index=1,
        )

    def test_retry_targets_only_failed_quiz(self) -> None:
        fm = _fake_learning_manager()
        fm.create_quiz_attempt.side_effect = [
            _attempt_dict(quiz_index=1, is_correct=False,
                          attempt_number=2),
            _attempt_dict(quiz_index=1, is_correct=True,
                          attempt_number=3),
        ]
        fm.get_quiz_set_for_node.return_value = {
            "quiz_set": _quiz_set_with_count(3),
        }

        with patch("server.routers.learning.learning_manager", fm):
            submit_quiz(
                "node-1",
                QuizSubmitRequest(
                    selected_option_ids=["opt-W"], quiz_index=1,
                ),
            )
            submit_quiz(
                "node-1",
                QuizSubmitRequest(
                    selected_option_ids=["opt-A"], quiz_index=1,
                ),
            )

        fm.update_quiz_set_progress.assert_called_once_with(
            node_id="node-1", current_index=2,
        )


if __name__ == "__main__":
    unittest.main()
