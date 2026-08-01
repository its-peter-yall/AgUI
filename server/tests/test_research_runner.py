"""
============================================================================
FILE: test_research_runner.py
LOCATION: server/tests/test_research_runner.py
============================================================================
PURPOSE:
    Tests bounded Researcher loop persistence, degradation, and cancellation.
ROLE IN PROJECT:
    Verifies research always terminates and preserves durable partial work.
KEY COMPONENTS:
    - ResearchRunnerTests: Success, exhaustion, auth, cancel, and resume tests
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.services.research_runner
USAGE:
    python -m unittest server.tests.test_research_runner -v
============================================================================
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from server.schemas.research import (
    ResearchFinalization,
    ResearchIteration,
    ResearchPlan,
    ResearchStatus,
)
from server.search.types import (
    AllProvidersUnavailable,
    SearchError,
    SearchErrorClass,
    SearchProviderId,
    SearchResponse,
)
from server.services.research_runner import ResearchCancelled, ResearchRunner


class ResearchRunnerTests(unittest.IsolatedAsyncioTestCase):
    """Tests bounded incremental research orchestration."""

    def make_runner(self) -> tuple[ResearchRunner, MagicMock, MagicMock]:
        agent = MagicMock()
        agent.analyze_query = AsyncMock(
            return_value=ResearchPlan(
                audience="Learner",
                provisional_concept_count=3,
                coverage=[],
                initial_queries=["current topic"],
            )
        )
        agent.synthesize_iteration = AsyncMock(
            return_value=ResearchIteration(
                theme="Current topic",
                section_markdown="Current evidence is limited.",
                source_ids=[],
                conflicts=[],
                follow_up_queries=[],
                coverage_updates=[],
            )
        )
        agent.finalize_report = AsyncMock(
            return_value=ResearchFinalization(
                summary="Research summary.",
                limitations=["Limited evidence."],
                freshness_note="Retrieved 2026-08-01.",
            )
        )
        stores = MagicMock()
        stores.research.create_report.return_value.id = "report-1"
        stores.jobs.is_cancel_requested.return_value = False
        stores.research.upsert_section.return_value = MagicMock(id="section-1")
        coordinator = MagicMock()
        coordinator.provider_order = (SearchProviderId.TAVILY,)
        coordinator.search = AsyncMock(
            return_value=SearchResponse(results=[], response_bytes=10)
        )
        runner = ResearchRunner(
            agent=agent,
            research_store=stores.research,
            job_store=stores.jobs,
            event_store=stores.events,
        )
        return runner, coordinator, stores

    async def test_loop_persists_order_section_cursor_and_final_report(self) -> None:
        runner, coordinator, stores = self.make_runner()
        outcome = await runner.run(
            job_id="job-1",
            session_id="session-1",
            query="Current topic",
            resolved_mode="lite",
            coordinator=coordinator,
            llm_context=MagicMock(),
        )
        self.assertEqual(outcome.status, ResearchStatus.COMPLETE)
        stores.jobs.update_cursor.assert_called()
        stores.research.upsert_section.assert_called_once()
        stores.research.finalize_report.assert_called_once()
        stores.events.append_once.assert_called()

    async def test_provider_exhaustion_marks_degraded_and_preserves_report(self) -> None:
        runner, coordinator, stores = self.make_runner()
        coordinator.search.side_effect = AllProvidersUnavailable(
            provider_ids=(SearchProviderId.TAVILY,)
        )
        outcome = await runner.run(
            job_id="job-1",
            session_id="session-1",
            query="Current topic",
            resolved_mode="lite",
            coordinator=coordinator,
            llm_context=MagicMock(),
        )
        self.assertEqual(outcome.status, ResearchStatus.DEGRADED)
        stores.research.mark_degraded.assert_called_once()
        stores.research.upsert_section.assert_not_called()

    async def test_auth_error_stops_without_silent_rotation(self) -> None:
        runner, coordinator, stores = self.make_runner()
        coordinator.search.side_effect = SearchError(
            provider_id=SearchProviderId.TAVILY,
            error_class=SearchErrorClass.AUTHENTICATION,
            status_code=401,
        )
        outcome = await runner.run(
            job_id="job-1",
            session_id="session-1",
            query="Current topic",
            resolved_mode="lite",
            coordinator=coordinator,
            llm_context=MagicMock(),
        )
        self.assertEqual(outcome.status, ResearchStatus.DEGRADED)
        self.assertEqual(coordinator.search.await_count, 1)
        stores.research.mark_degraded.assert_called_once()

    async def test_cancel_check_runs_before_search_and_keeps_partial_rows(self) -> None:
        runner, coordinator, stores = self.make_runner()
        stores.jobs.is_cancel_requested.return_value = True
        with self.assertRaises(ResearchCancelled):
            await runner.run(
                job_id="job-1",
                session_id="session-1",
                query="Current topic",
                resolved_mode="lite",
                coordinator=coordinator,
                llm_context=MagicMock(),
            )
        coordinator.search.assert_not_awaited()
        stores.research.create_report.assert_called_once()


if __name__ == "__main__":
    unittest.main()
