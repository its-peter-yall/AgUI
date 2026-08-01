"""
============================================================================
FILE: test_generation_recovery.py
LOCATION: server/tests/test_generation_recovery.py
============================================================================
PURPOSE:
    Tests stable threads, execution locks, cancellation, pause, and resume.
ROLE IN PROJECT:
    Protects durable generation against duplicate workers and lost credentials.
KEY COMPONENTS:
    - GenerationRunnerTests: New/resume invoke and secret-boundary tests
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.graph.runner and runtime schemas
USAGE:
    python -m unittest server.tests.test_generation_recovery -v
============================================================================
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from server.graph.runner import (
    GenerationAlreadyRunning,
    GenerationCancelled,
    ResumableGenerationError,
    run_generation_job,
)
from server.schemas.generation import GenerationStage
from server.schemas.llm import LLMContext
from server.schemas.search import SearchContext
from server.search.types import SearchProviderId


class GenerationRunnerTests(unittest.IsolatedAsyncioTestCase):
    """Tests graph runner lock and resume behavior."""

    async def test_resume_uses_none_input_same_thread_and_fresh_context(self) -> None:
        graph = AsyncMock()
        graph.ainvoke.return_value = {"session_id": "session-1"}
        jobs = MagicMock()
        jobs.get_by_session.return_value = SimpleNamespace(
            id="job-1",
            session_id="session-1",
            thread_id="gen-session-1",
            stage=GenerationStage.PAUSED,
            query="test query",
            user_id=None,
            mode="full",
            resolved_mode="full",
            research_report_id=None,
        )
        jobs.try_acquire_lock.return_value = SimpleNamespace(
            owner="worker-1",
            version=2,
        )
        jobs.renew_lock.return_value = jobs.try_acquire_lock.return_value
        llm = LLMContext(api_key="llm-secret", model="test/model")
        search = SearchContext.from_plaintext_credentials(
            enabled=True,
            provider_ids=[SearchProviderId.TAVILY],
            credentials={SearchProviderId.TAVILY: "search-secret"},
        )
        await run_generation_job(
            app_state=SimpleNamespace(course_graph=graph),
            session_id="session-1",
            llm_context=llm,
            search_context=search,
            resume=True,
            worker_id="worker-1",
            job_store=jobs,
            event_store=MagicMock(),
        )
        call = graph.ainvoke.await_args
        self.assertIsNone(call.args[0])
        self.assertEqual(
            call.kwargs["config"]["configurable"]["thread_id"],
            "gen-session-1",
        )
        self.assertEqual(call.kwargs["context"]["llm_context"], llm)
        self.assertEqual(call.kwargs["context"]["search_context"], search)
        persisted_calls = repr(jobs.method_calls)
        self.assertNotIn("llm-secret", persisted_calls)
        self.assertNotIn("search-secret", persisted_calls)

    async def test_second_worker_is_rejected(self) -> None:
        jobs = MagicMock()
        jobs.get_by_session.return_value = SimpleNamespace(
            id="job-1",
            session_id="session-1",
            thread_id="gen-session-1",
            stage=GenerationStage.OUTLINING,
        )
        jobs.try_acquire_lock.return_value = None
        with self.assertRaises(GenerationAlreadyRunning):
            await run_generation_job(
                app_state=SimpleNamespace(course_graph=AsyncMock()),
                session_id="session-1",
                llm_context=LLMContext(
                    api_key="llm-key",
                    model="test/model",
                ),
                search_context=SearchContext(),
                resume=False,
                worker_id="worker-2",
                job_store=jobs,
                event_store=MagicMock(),
            )

    async def test_cancel_marks_retained_cancelled_state(self) -> None:
        graph = AsyncMock()
        graph.ainvoke.side_effect = GenerationCancelled("session-1")
        jobs = MagicMock()
        jobs.get_by_session.return_value = SimpleNamespace(
            id="job-1",
            session_id="session-1",
            thread_id="gen-session-1",
            stage=GenerationStage.GENERATING_PREVIEW,
            query="test query",
            user_id=None,
            mode="full",
            resolved_mode="full",
            research_report_id=None,
        )
        lock = SimpleNamespace(owner="worker-1", version=1)
        jobs.try_acquire_lock.return_value = lock
        jobs.renew_lock.return_value = lock
        events = MagicMock()
        await run_generation_job(
            app_state=SimpleNamespace(course_graph=graph),
            session_id="session-1",
            llm_context=LLMContext(api_key="llm-key", model="test/model"),
            search_context=SearchContext(),
            resume=False,
            worker_id="worker-1",
            job_store=jobs,
            event_store=events,
        )
        jobs.mark_cancelled.assert_called_once()
        events.append_once.assert_called_once()
        jobs.release_lock.assert_called_once()

    async def test_resumable_error_marks_paused_not_failed(self) -> None:
        graph = AsyncMock()
        graph.ainvoke.side_effect = ResumableGenerationError(
            "Planner brief validation failed"
        )
        jobs = MagicMock()
        jobs.get_by_session.return_value = SimpleNamespace(
            id="job-1",
            session_id="session-1",
            thread_id="gen-session-1",
            stage=GenerationStage.PLANNING_BATCH,
            query="test query",
            user_id=None,
            mode="full",
            resolved_mode="full",
            research_report_id=None,
        )
        lock = SimpleNamespace(owner="worker-1", version=1)
        jobs.try_acquire_lock.return_value = lock
        jobs.renew_lock.return_value = lock
        await run_generation_job(
            app_state=SimpleNamespace(course_graph=graph),
            session_id="session-1",
            llm_context=LLMContext(api_key="llm-key", model="test/model"),
            search_context=SearchContext(),
            resume=False,
            worker_id="worker-1",
            job_store=jobs,
            event_store=MagicMock(),
        )
        jobs.mark_paused.assert_called_once()
        jobs.mark_failed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
