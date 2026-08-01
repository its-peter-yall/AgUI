"""
============================================================================
FILE: test_majors_m1_m8.py
LOCATION: server/tests/test_majors_m1_m8.py
============================================================================
PURPOSE:
    Regression tests for review majors M1-M8 (budget, coverage, HTTP, depth).
ROLE IN PROJECT:
    Locks shared durable budget, grounded completion, domain/freshness rules,
    streamed byte caps, and depth_router resolution.
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.search.*, server.services.research_runner
USAGE:
    python -m unittest server.tests.test_majors_m1_m8 -v
============================================================================
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from server.schemas.generation import ResearchCursor
from server.schemas.research import (
    CoverageItem,
    CoverageTheme,
    ResearchFinalization,
    ResearchIteration,
    ResearchPlan,
    ResearchSource,
    ResearchStatus,
)
from server.search.budget import (
    ResearchBudgetExceeded,
    ResearchBudgetLedger,
    resolve_research_budget,
)
from server.search.http import read_capped_json
from server.search.types import (
    SearchError,
    SearchErrorClass,
    SearchProviderId,
    SearchResponse,
)
from server.services.research_runner import (
    ResearchRunner,
    coverage_is_complete,
    registrable_domain,
)


class M1BudgetLedgerTests(unittest.TestCase):
    """M1: shared durable budget with elapsed restore."""

    def test_to_cursor_persists_sources_context_and_elapsed(self) -> None:
        clock = [100.0]
        ledger = ResearchBudgetLedger(
            resolve_research_budget("lite", 3),
            clock=lambda: clock[0],
        )
        ledger.reserve_search_call()
        ledger.reserve_sources(2)
        ledger.reserve_context_chars(50)
        clock[0] = 112.5
        cursor = ledger.to_cursor(iteration=1)
        self.assertEqual(cursor.sources, 2)
        self.assertEqual(cursor.context_chars, 50)
        self.assertAlmostEqual(cursor.elapsed_seconds, 12.5, places=2)
        self.assertEqual(cursor.search_calls, 1)

    def test_from_cursor_restores_usage_and_elapsed_hard_stop(self) -> None:
        clock = [500.0]
        cursor = ResearchCursor(
            search_calls=5,
            llm_turns=3,
            results_examined=10,
            provider_bytes=1000,
            excerpt_chars=200,
            sources=4,
            context_chars=300,
            elapsed_seconds=44.0,
        )
        ledger = ResearchBudgetLedger.from_cursor(
            resolve_research_budget("lite", 3),
            cursor,
            clock=lambda: clock[0],
        )
        snap = ledger.usage_snapshot()
        self.assertEqual(snap.sources, 4)
        self.assertEqual(snap.context_chars, 300)
        self.assertEqual(snap.search_calls, 5)
        clock[0] = 501.5  # total elapsed 45.5 > 45
        with self.assertRaises(ResearchBudgetExceeded) as raised:
            ledger.check_time()
        self.assertEqual(raised.exception.limit_name, "elapsed_seconds")

    def test_remaining_seconds_caps_timeout(self) -> None:
        clock = [0.0]
        ledger = ResearchBudgetLedger(
            resolve_research_budget("lite", 3),
            clock=lambda: clock[0],
        )
        clock[0] = 40.0
        self.assertAlmostEqual(ledger.remaining_seconds(), 5.0, places=2)


class M2M3CoverageTests(unittest.TestCase):
    """M2/M3: grounded completion and evidence integrity."""

    def _source(
        self,
        source_id: str,
        url: str,
        *,
        days_ago: int = 1,
    ) -> ResearchSource:
        now = datetime.now(timezone.utc)
        return ResearchSource(
            id=source_id,
            title=f"T {source_id}",
            url=url,
            publisher="Pub",
            published_at=now - timedelta(days=days_ago),
            retrieved_at=now,
            provider_id=SearchProviderId.TAVILY,
            snippet="s",
            excerpt="e",
        )

    def test_registrable_domain_collapses_subdomains(self) -> None:
        self.assertEqual(
            registrable_domain("https://a.blog.example.com/x"),
            "example.com",
        )
        self.assertEqual(
            registrable_domain("https://b.blog.example.com/y"),
            "example.com",
        )

    def test_subdomains_do_not_fake_domain_diversity(self) -> None:
        sources = [
            self._source("s1", "https://a.example.com/1"),
            self._source("s2", "https://b.example.com/2"),
            self._source("s3", "https://c.example.com/3"),
        ]
        coverage = [
            CoverageItem(
                theme=CoverageTheme.FUNDAMENTALS,
                required=True,
                covered=True,
                explicit_unknown=False,
                source_ids=["s1", "s2", "s3"],
            )
        ]
        self.assertFalse(coverage_is_complete(coverage, sources))

    def test_three_registrable_domains_can_complete(self) -> None:
        sources = [
            self._source("s1", "https://a.example.com/1"),
            self._source("s2", "https://news.org/2"),
            self._source("s3", "https://docs.io/3"),
        ]
        coverage = [
            CoverageItem(
                theme=CoverageTheme.FUNDAMENTALS,
                required=True,
                covered=True,
                explicit_unknown=False,
                source_ids=["s1", "s2", "s3"],
            )
        ]
        self.assertTrue(
            coverage_is_complete(coverage, sources, recency_days=None)
        )

    def test_freshness_uses_publication_date(self) -> None:
        sources = [
            self._source("s1", "https://a.example.com/1", days_ago=400),
            self._source("s2", "https://b.org/2", days_ago=400),
            self._source("s3", "https://c.io/3", days_ago=400),
        ]
        coverage = [
            CoverageItem(
                theme=CoverageTheme.CURRENT_VERSIONS,
                required=True,
                covered=True,
                explicit_unknown=False,
                freshness_sensitive=True,
                source_ids=["s1"],
            )
        ]
        self.assertFalse(
            coverage_is_complete(coverage, sources, recency_days=365)
        )


class M2IncompleteResearchRunnerTests(unittest.IsolatedAsyncioTestCase):
    """M2: incomplete/empty research must finalize DEGRADED with warning."""

    def _runner(self) -> tuple[ResearchRunner, MagicMock, MagicMock]:
        agent = MagicMock()
        agent.analyze_query = AsyncMock(
            return_value=ResearchPlan(
                audience="Learner",
                provisional_concept_count=3,
                coverage=[
                    CoverageItem(
                        theme=CoverageTheme.FUNDAMENTALS,
                        required=True,
                        covered=False,
                        explicit_unknown=False,
                    )
                ],
                initial_queries=["q1"],
            )
        )
        agent.synthesize_iteration = AsyncMock(
            return_value=ResearchIteration(
                theme="Need evidence",
                section_markdown="No real evidence [src:fake].",
                source_ids=[],
                conflicts=[],
                follow_up_queries=[],
                coverage_updates=[],
            )
        )
        agent.finalize_report = AsyncMock(
            return_value=ResearchFinalization(
                summary="Done?",
                limitations=[],
                freshness_note="n/a",
            )
        )
        stores = MagicMock()
        stores.research.create_report.return_value.id = "report-1"
        stores.jobs.is_cancel_requested.return_value = False
        stores.research.upsert_section.return_value = MagicMock(id="sec-1")
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

    async def test_empty_research_is_degraded_not_grounded_complete(self) -> None:
        runner, coordinator, stores = self._runner()
        outcome = await runner.run(
            job_id="job-1",
            session_id="session-1",
            query="topic",
            resolved_mode="lite",
            coordinator=coordinator,
            llm_context=MagicMock(),
        )
        self.assertEqual(outcome.status, ResearchStatus.DEGRADED)
        from server.schemas.generation import GroundingStatus

        self.assertEqual(outcome.grounding_status, GroundingStatus.DEGRADED)
        self.assertTrue(outcome.warnings)
        stores.research.finalize_report.assert_called()
        call_kw = stores.research.finalize_report.call_args.kwargs
        self.assertEqual(call_kw.get("status"), ResearchStatus.DEGRADED)


class M7DepthResolutionTests(unittest.IsolatedAsyncioTestCase):
    """M7: auto depth resolved via depth_router in init."""

    async def test_initialize_resolves_auto_via_depth_router(self) -> None:
        from server.graph.nodes import initialize_generation_node

        with (
            patch(
                "server.graph.nodes.resolve_depth_mode",
                new_callable=AsyncMock,
                return_value="lite",
            ) as resolve_mock,
            patch("server.graph.nodes.raise_if_cancel_requested"),
            patch("server.graph.nodes._fenced_update_stage"),
            patch("server.graph.nodes.progress_event_store") as events,
        ):
            events.append_once = MagicMock()
            state = {
                "session_id": "s1",
                "query": "what is gravity",
                "mode": "auto",
                "web_search_enabled": False,
            }
            runtime = {
                "llm_context": MagicMock(),
                "search_context": MagicMock(enabled=False),
            }
            result = await initialize_generation_node(state, runtime)
            resolve_mock.assert_awaited()
            self.assertEqual(result["resolved_mode"], "lite")


class M8StreamedHttpTests(unittest.IsolatedAsyncioTestCase):
    """M8: stream body and count actual bytes."""

    async def test_read_capped_json_rejects_oversized_chunked_body(self) -> None:
        chunks = [b'{"a":"', b"x" * 100, b'"}']

        async def fake_aiter_bytes():
            for chunk in chunks:
                yield chunk

        response = MagicMock()
        response.status_code = 200
        response.aiter_bytes = fake_aiter_bytes
        with self.assertRaises(SearchError) as raised:
            await read_capped_json(
                response,
                max_bytes=50,
                provider_id=SearchProviderId.TAVILY,
            )
        self.assertEqual(
            raised.exception.error_class,
            SearchErrorClass.INVALID_RESPONSE,
        )

    async def test_provider_request_uses_stream_and_actual_bytes(self) -> None:
        from server.search.adapters._common import execute_search_request

        body = json.dumps({"ok": True}).encode("utf-8")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=body,
                headers={"Content-Length": "1"},  # under-report
                request=request,
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            payload, nbytes = await execute_search_request(
                client,
                provider_id=SearchProviderId.TAVILY,
                method="GET",
                url="https://example.test/search",
                timeout_seconds=5.0,
                max_bytes=10_000,
            )
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(nbytes, len(body))
        self.assertNotEqual(nbytes, 1)


if __name__ == "__main__":
    unittest.main()
