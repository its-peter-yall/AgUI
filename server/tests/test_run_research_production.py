"""
============================================================================
FILE: test_run_research_production.py
LOCATION: server/tests/test_run_research_production.py
============================================================================
PURPOSE:
    Integration test for production run_research composition (C1).
ROLE IN PROJECT:
    Proves production path builds ProviderCoordinator + adapters and
    executes with MockTransport only (no fake research artifact writer).
KEY COMPONENTS:
    - ProductionRunResearchTests
DEPENDENCIES:
    - External: httpx, tempfile, unittest
    - Internal: server.services.research_runner, stores, schemas
USAGE:
    python -m unittest server.tests.test_run_research_production -v
============================================================================
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from server.database.generation_jobs import GenerationJobStore
from server.database.generation_migrations import initialize_generation_schema
from server.database.learning_persistence import LearningManager
from server.database.progress_events import ProgressEventStore
from server.database.research_store import ResearchStore
from server.schemas.llm import LLMContext
from server.schemas.research import (
    ResearchFinalization,
    ResearchIteration,
    ResearchPlan,
    ResearchStatus,
)
from server.schemas.search import SearchContext
from server.search.types import SearchProviderId
from server.services.research_runner import run_research


class ProductionRunResearchTests(unittest.IsolatedAsyncioTestCase):
    """C1: production run_research must use real coordinator path."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        LearningManager(self.db_path).init_learning_tables()
        initialize_generation_schema(self.db_path)
        self.jobs = GenerationJobStore(self.db_path)
        self.events = ProgressEventStore(self.db_path)
        self.research = ResearchStore(self.db_path)
        session, _ = self.jobs.create_session_shell_and_job(
            query="Current CSS layout",
            user_id=None,
            mode="lite",
            web_search_requested=True,
        )
        self.session_id = session["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_production_run_research_uses_coordinator_and_mock_http(
        self,
    ) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                request=request,
                json={
                    "results": [
                        {
                            "title": "MDN Flexbox",
                            "url": (
                                "https://developer.mozilla.org/en-US/docs/"
                                "Web/CSS/CSS_flexible_box_layout"
                            ),
                            "content": "Flexbox layout basics for modern CSS.",
                            "score": 0.95,
                            "published_date": "2026-07-01",
                        },
                        {
                            "title": "CSS Grid Guide",
                            "url": (
                                "https://css-tricks.com/snippets/css/"
                                "complete-guide-grid/"
                            ),
                            "content": "Grid is a two-dimensional layout system.",
                            "score": 0.9,
                            "published_date": "2026-06-15",
                        },
                        {
                            "title": "Web.dev Layout",
                            "url": "https://web.dev/learn/css/layout/",
                            "content": "Layout methods on the modern web.",
                            "score": 0.88,
                            "published_date": "2026-05-01",
                        },
                    ]
                },
            )

        agent = MagicMock()
        agent.analyze_query = AsyncMock(
            return_value=ResearchPlan(
                audience="Learner",
                provisional_concept_count=3,
                coverage=[],
                initial_queries=["current CSS layout"],
            )
        )
        agent.synthesize_iteration = AsyncMock(
            return_value=ResearchIteration(
                theme="Layout fundamentals",
                section_markdown="Layout uses flex and grid.",
                source_ids=[],
                conflicts=[],
                follow_up_queries=[],
                coverage_updates=[],
            )
        )
        agent.finalize_report = AsyncMock(
            return_value=ResearchFinalization(
                summary="Layout research summary.",
                limitations=[],
                freshness_note="Retrieved 2026-08-01.",
            )
        )

        llm = LLMContext(api_key="llm-test-key", model="test/model")
        search = SearchContext.from_plaintext_credentials(
            enabled=True,
            provider_ids=[SearchProviderId.TAVILY],
            credentials={SearchProviderId.TAVILY: "tvly-test-secret"},
        )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with (
                patch(
                    "server.database.storage_registry.generation_job_repository",
                    self.jobs,
                ),
                patch(
                    "server.database.storage_registry.progress_event_repository",
                    self.events,
                ),
                patch(
                    "server.database.storage_registry.research_repository",
                    self.research,
                ),
                patch(
                    "server.agents.researcher.researcher_agent",
                    agent,
                ),
            ):
                report_id, _is_degraded = await run_research(
                    session_id=self.session_id,
                    topic_query="Current CSS layout",
                    llm_context=llm,
                    search_context=search,
                    resolved_mode="full",
                    http_client=client,
                )

        self.assertTrue(report_id)
        self.assertGreaterEqual(len(requests), 1)
        auth = requests[0].headers.get("Authorization", "")
        self.assertIn("tvly-test-secret", auth)
        agent.analyze_query.assert_awaited()
        call_kwargs = agent.analyze_query.await_args.kwargs
        self.assertEqual(call_kwargs.get("resolved_mode"), "full")
        report = self.research.get_report(self.session_id)
        self.assertIsNotNone(report)
        status = report.status if hasattr(report, "status") else report["status"]
        self.assertIn(
            status,
            {
                ResearchStatus.COMPLETE,
                ResearchStatus.DEGRADED,
                "COMPLETE",
                "DEGRADED",
            },
        )


if __name__ == "__main__":
    unittest.main()
