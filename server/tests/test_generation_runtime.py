"""
============================================================================
FILE: test_generation_runtime.py
LOCATION: server/tests/test_generation_runtime.py
============================================================================
PURPOSE:
    Tests detached generation task ownership and lifecycle reconciliation.
ROLE IN PROJECT:
    Ensures browser/SSE disconnect cannot own or cancel durable work.
KEY COMPONENTS:
    - GenerationRuntimeTests: Immediate start, task refs, shutdown tests
DEPENDENCIES:
    - External: asyncio, unittest, unittest.mock
    - Internal: server.services.generation_runtime
USAGE:
    python -m unittest server.tests.test_generation_runtime -v
============================================================================
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from server.schemas.llm import LLMContext
from server.schemas.search import SearchContext
from server.services.generation_runtime import GenerationRuntime


class GenerationRuntimeTests(unittest.IsolatedAsyncioTestCase):
    """Tests detached job ownership independent of HTTP connections."""

    async def test_start_returns_shell_while_runner_is_blocked(self) -> None:
        gate = asyncio.Event()

        async def blocked_runner(**kwargs):
            await gate.wait()

        jobs = MagicMock()
        jobs.create_session_shell_and_job.return_value = (
            {"id": "session-1", "nodes": []},
            SimpleNamespace(id="job-1", session_id="session-1"),
        )
        jobs.to_public.return_value = {"id": "job-1"}
        runtime = GenerationRuntime(
            app_state=SimpleNamespace(),
            job_store=jobs,
            runner=blocked_runner,
        )
        accepted = await runtime.start(
            request_body=SimpleNamespace(
                query="Topic",
                user_id=None,
                mode="auto",
            ),
            llm_context=LLMContext(api_key="llm-key", model="test/model"),
            search_context=SearchContext(),
        )
        self.assertEqual(accepted["session"]["id"], "session-1")
        self.assertEqual(len(runtime.active_tasks), 1)
        self.assertFalse(next(iter(runtime.active_tasks)).done())
        gate.set()
        await asyncio.gather(*runtime.active_tasks)

    async def test_shutdown_does_not_store_contexts_and_marks_jobs_paused(self) -> None:
        jobs = MagicMock()
        runtime = GenerationRuntime(
            app_state=SimpleNamespace(),
            job_store=jobs,
            runner=AsyncMock(),
        )
        await runtime.shutdown()
        jobs.mark_orphaned_jobs_paused.assert_called_once()
        self.assertNotIn("llm_context", runtime.__dict__)
        self.assertNotIn("search_context", runtime.__dict__)


if __name__ == "__main__":
    unittest.main()
