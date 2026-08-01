"""
============================================================================
FILE: test_partial_failure.py
LOCATION: server/tests/test_partial_failure.py
============================================================================
PURPOSE:
    Verifies quizzer_node persists partial content and tagged failed_step
    when quiz generation fails or generator error is present in state.
USAGE:
    python -m unittest server.tests.test_partial_failure -v
============================================================================
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

from server.database.learning_persistence import LearningManager, learning_manager
from server.graph.nodes import quizzer_node
from server.schemas.learning import (
    CourseOutline,
    FailedStep,
    NodeStatus,
    QuizCard,
    QuizOption,
    QuizSet,
    TopicNode,
)
from server.schemas.llm import LLMContext


def _qs() -> QuizSet:
    return QuizSet(
        quizzes=[
            QuizCard(
                question_text="q",
                options=[
                    QuizOption(option_id="a", display_label="A", text="t", is_correct=True, explanation="e"),
                    QuizOption(option_id="b", display_label="B", text="t", is_correct=False, explanation="e"),
                    QuizOption(option_id="c", display_label="C", text="t", is_correct=False, explanation="e"),
                    QuizOption(option_id="d", display_label="D", text="t", is_correct=False, explanation="e"),
                ],
            )
        ]
    )


def _outline() -> CourseOutline:
    return CourseOutline(
        course_title="Test",
        topics=[
            TopicNode(
                index=i,
                title=f"Topic {i}",
                summary_for_context=f"summary{i}",
                key_terms=["t1", "t2"],
                complexity="Basic" if i == 0 else "Intermediate",
                quiz_count=1,
            )
            for i in range(5)
        ],
    )


def _make_state(
    session_id: str,
    topic: TopicNode,
    content_markdown: str = "",
    error_message: str | None = None,
) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "session_id": session_id,
        "sequence_index": 0,
        "topic_data": topic.model_dump(),
        "outline": _outline().model_dump(),
        "content_markdown": content_markdown,
    }
    if error_message is not None:
        state["error_message"] = error_message
    return state


class QuizzerNodePartialFailureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.manager = LearningManager(db_path=Path(self.tmp.name) / "t.db")
        self.manager.init_learning_tables()
        self.patcher = patch(
            "server.graph.nodes.learning_manager",
            self.manager,
        )
        self.patcher.start()
        self.session = self.manager.create_learning_session(
            query="q", course_title="c"
        )
        self.runtime = {"llm_context": LLMContext(api_key="test", model="test/m")}

    def tearDown(self) -> None:
        self.patcher.stop()
        self.tmp.cleanup()

    @patch("server.graph.nodes.quizzer_agent.generate_quiz_set", new_callable=AsyncMock)
    async def test_quizzer_failure_keeps_real_content(
        self, mock_quiz: AsyncMock
    ) -> None:
        mock_quiz.side_effect = RuntimeError("quiz fail")
        content = "# Real content\n" + ("x " * 200)
        state = _make_state(self.session["id"], _outline().topics[0], content_markdown=content)
        await quizzer_node(state, self.runtime)
        nodes = learning_manager.get_session_nodes(self.session["id"])
        node = nodes[0]
        self.assertEqual(node["status"], NodeStatus.ERROR.value)
        self.assertEqual(node["failed_step"], FailedStep.QUIZZER.value)
        self.assertTrue(node["retry_available"])
        self.assertIn("Real content", node["content_markdown"])
        mock_quiz.assert_awaited_once()

    async def test_generator_error_uses_placeholder(self) -> None:
        state = _make_state(
            self.session["id"],
            _outline().topics[0],
            content_markdown="Content generation failed.",
            error_message="gen fail",
        )
        await quizzer_node(state, self.runtime)
        nodes = learning_manager.get_session_nodes(self.session["id"])
        node = nodes[0]
        self.assertEqual(node["status"], NodeStatus.ERROR.value)
        self.assertEqual(node["failed_step"], FailedStep.GENERATOR.value)
        self.assertTrue(node["retry_available"])

    async def test_generator_error_skips_quizzer(self) -> None:
        state = _make_state(
            self.session["id"],
            _outline().topics[0],
            content_markdown="Content generation failed.",
            error_message="gen fail",
        )
        with patch("server.graph.nodes.quizzer_agent.generate_quiz_set", new_callable=AsyncMock) as mock_quiz:
            await quizzer_node(state, self.runtime)
            mock_quiz.assert_not_awaited()

    @patch("server.graph.nodes.quizzer_agent.generate_quiz_set", new_callable=AsyncMock)
    async def test_success_no_failed_step(
        self, mock_quiz: AsyncMock
    ) -> None:
        mock_quiz.return_value = _qs()
        state = _make_state(self.session["id"], _outline().topics[0], content_markdown="# Content")
        await quizzer_node(state, self.runtime)
        nodes = learning_manager.get_session_nodes(self.session["id"])
        node = nodes[0]
        self.assertEqual(node["status"], NodeStatus.VIEWING_EXPLANATION.value)
        self.assertIsNone(node["failed_step"])
        self.assertFalse(node["retry_available"])


if __name__ == "__main__":
    unittest.main()
