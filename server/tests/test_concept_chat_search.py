"""
============================================================================
FILE: test_concept_chat_search.py
LOCATION: server/tests/test_concept_chat_search.py
============================================================================
PURPOSE:
    Unit tests for the concept-chat web_search tool schema, ChatSearchLedger,
    and one-shot ProviderCoordinator helper.
ROLE IN PROJECT:
    Locks Plan 3 contracts so Plan 4 can call one_shot_chat_search without
    live network or research-budget types.
    - Tool schema: query-only web_search
    - Ledger: 2x providers, 25s window, RuntimeError hard-stop
    - Helper: filter adapters, empty persisted_order, close httpx client
KEY COMPONENTS:
    - WebSearchToolSchemaTests: OpenAI function schema
    - ChatSearchLedgerTests: duck-typed budget stub
    - OneShotChatSearchTests: mocked coordinator wiring
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.services.concept_chat_search, search types/context
USAGE:
    python -m unittest server.tests.test_concept_chat_search
============================================================================
"""

from __future__ import annotations

import inspect
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from server.schemas.search import SearchContext
from server.search.budget import ResearchBudgetExceeded, ResearchBudgetLedger
from server.search.types import (
    AllProvidersUnavailable,
    SearchProviderId,
    SearchQuery,
    SearchResponse,
)
from server.services.concept_chat_search import (
    WEB_SEARCH_TOOL,
    ChatSearchLedger,
    one_shot_chat_search,
)


class WebSearchToolSchemaTests(unittest.TestCase):
    """Locks the OpenAI-compatible web_search tool exposed to the model."""

    def test_schema_is_web_search_with_query_only(self) -> None:
        self.assertEqual(WEB_SEARCH_TOOL["type"], "function")
        function = WEB_SEARCH_TOOL["function"]
        self.assertEqual(function["name"], "web_search")
        parameters = function["parameters"]
        self.assertEqual(parameters["type"], "object")
        self.assertEqual(list(parameters["properties"].keys()), ["query"])
        self.assertEqual(parameters["properties"]["query"]["type"], "string")
        self.assertEqual(parameters["required"], ["query"])
        self.assertNotIn("max_results", json.dumps(WEB_SEARCH_TOOL))

    def test_description_states_what_when_how_and_one_call(self) -> None:
        description = WEB_SEARCH_TOOL["function"]["description"]
        lowered = description.lower()
        self.assertIn("search the public web", lowered)
        self.assertIn("concept content", lowered)
        self.assertIn("prior messages", lowered)
        self.assertIn("lack the context", lowered)
        self.assertIn("prior web_search results already", lowered)
        self.assertIn("one search per turn", lowered)
        self.assertIn("meticulous query", lowered)
        self.assertIn("specific terms", lowered)
        self.assertIn("versions", lowered)
        self.assertIn("concept-title", lowered)
        self.assertIn("disambiguation", lowered)
        self.assertNotIn("max_results", lowered)


class ChatSearchLedgerTests(unittest.TestCase):
    """Duck-typed chat ledger: not ResearchBudgetLedger."""

    def test_is_not_research_budget_ledger(self) -> None:
        self.assertFalse(
            issubclass(ChatSearchLedger, ResearchBudgetLedger)
        )
        ledger = ChatSearchLedger(max_search_calls=2)
        self.assertIsInstance(ledger, ChatSearchLedger)
        self.assertNotIsInstance(ledger, ResearchBudgetLedger)

    def test_remaining_seconds_never_zero_at_start(self) -> None:
        ledger = ChatSearchLedger(max_search_calls=2)
        remaining = ledger.remaining_seconds()
        self.assertGreater(remaining, 24.0)
        self.assertLessEqual(remaining, 25.0)
        self.assertEqual(ledger.max_search_calls, 2)
        self.assertEqual(ledger.max_elapsed_seconds, 25.0)

    def test_remaining_seconds_uses_25s_monotonic_window(self) -> None:
        class FakeClock:
            def __init__(self) -> None:
                self.now = 1000.0

            def __call__(self) -> float:
                return self.now

        clock = FakeClock()
        ledger = ChatSearchLedger(max_search_calls=4, clock=clock)
        self.assertEqual(ledger.remaining_seconds(), 25.0)
        clock.now = 1010.0
        self.assertEqual(ledger.remaining_seconds(), 15.0)
        clock.now = 1025.0
        self.assertEqual(ledger.remaining_seconds(), 0.0)
        clock.now = 1040.0
        self.assertEqual(ledger.remaining_seconds(), 0.0)

    def test_reserve_search_call_hard_stops_after_cap(self) -> None:
        ledger = ChatSearchLedger(max_search_calls=2)
        ledger.reserve_search_call()
        ledger.reserve_search_call(1)
        with self.assertRaises(RuntimeError) as raised:
            ledger.reserve_search_call()
        self.assertNotIsInstance(
            raised.exception,
            ResearchBudgetExceeded,
        )


def _enabled_context() -> SearchContext:
    return SearchContext.from_plaintext_credentials(
        enabled=True,
        provider_ids=[SearchProviderId.TAVILY, SearchProviderId.EXA],
        credentials={
            SearchProviderId.TAVILY: "tvly-test-key",
            SearchProviderId.EXA: "exa-test-key",
        },
    )


def _all_adapters() -> dict[SearchProviderId, object]:
    return {
        SearchProviderId.TAVILY: object(),
        SearchProviderId.EXA: object(),
        SearchProviderId.BRAVE: object(),
        SearchProviderId.SERPAPI: object(),
    }


class OneShotChatSearchTests(unittest.IsolatedAsyncioTestCase):
    """one_shot_chat_search wiring; mocks only, no live network."""

    async def test_filters_adapters_builds_query_and_closes_client(
        self,
    ) -> None:
        adapters = _all_adapters()
        expected = SearchResponse(results=[], response_bytes=0)
        fake_client = MagicMock()
        fake_client.aclose = AsyncMock()
        captured: dict = {}

        def fake_create(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            coordinator = MagicMock()
            coordinator.search = AsyncMock(return_value=expected)
            captured["_coordinator"] = coordinator
            return coordinator

        with patch(
            "server.services.concept_chat_search.httpx.AsyncClient",
            return_value=fake_client,
        ), patch(
            "server.services.concept_chat_search.build_search_adapters",
            return_value=adapters,
        ) as build, patch(
            "server.services.concept_chat_search.ProviderCoordinator.create",
            side_effect=fake_create,
        ):
            result = await one_shot_chat_search(
                _enabled_context(),
                "LangChain BaseTool documentation",
            )

        self.assertIs(result, expected)
        build.assert_called_once_with(fake_client)
        self.assertEqual(
            set(captured["adapters"].keys()),
            {SearchProviderId.TAVILY, SearchProviderId.EXA},
        )
        self.assertIs(
            captured["adapters"][SearchProviderId.TAVILY],
            adapters[SearchProviderId.TAVILY],
        )
        self.assertIs(
            captured["adapters"][SearchProviderId.EXA],
            adapters[SearchProviderId.EXA],
        )
        self.assertEqual(
            captured["credentials"],
            {
                SearchProviderId.TAVILY: "tvly-test-key",
                SearchProviderId.EXA: "exa-test-key",
            },
        )
        self.assertEqual(captured["persisted_order"], [])
        ledger = captured["ledger"]
        self.assertIsInstance(ledger, ChatSearchLedger)
        self.assertNotIsInstance(ledger, ResearchBudgetLedger)
        self.assertEqual(ledger.max_search_calls, 4)

        search = captured["_coordinator"].search
        search.assert_awaited_once()
        called_query = search.await_args.args[0]
        self.assertIsInstance(called_query, SearchQuery)
        self.assertEqual(
            called_query.query,
            "LangChain BaseTool documentation",
        )
        self.assertEqual(called_query.max_results, 5)
        self.assertEqual(
            search.await_args.kwargs["timeout_seconds"],
            20.0,
        )
        fake_client.aclose.assert_awaited_once()

    async def test_truncates_query_to_500_and_closes_on_error(self) -> None:
        adapters = {
            SearchProviderId.TAVILY: object(),
        }
        fake_client = MagicMock()
        fake_client.aclose = AsyncMock()
        captured: dict = {}
        boom = AllProvidersUnavailable(
            provider_ids=(SearchProviderId.TAVILY,),
        )

        def fake_create(**kwargs: object) -> MagicMock:
            coordinator = MagicMock()
            coordinator.search = AsyncMock(side_effect=boom)
            captured["coordinator"] = coordinator
            captured["ledger"] = kwargs["ledger"]
            return coordinator

        long_query = "x" * 600
        context = SearchContext.from_plaintext_credentials(
            enabled=True,
            provider_ids=[SearchProviderId.TAVILY],
            credentials={SearchProviderId.TAVILY: "tvly-test-key"},
        )

        with patch(
            "server.services.concept_chat_search.httpx.AsyncClient",
            return_value=fake_client,
        ), patch(
            "server.services.concept_chat_search.build_search_adapters",
            return_value=adapters,
        ), patch(
            "server.services.concept_chat_search.ProviderCoordinator.create",
            side_effect=fake_create,
        ):
            with self.assertRaises(AllProvidersUnavailable):
                await one_shot_chat_search(context, long_query)

        search = captured["coordinator"].search
        search.assert_awaited_once()
        called_query = search.await_args.args[0]
        self.assertEqual(len(called_query.query), 500)
        self.assertEqual(called_query.query, "x" * 500)
        self.assertEqual(called_query.max_results, 5)
        self.assertEqual(captured["ledger"].max_search_calls, 2)
        fake_client.aclose.assert_awaited_once()

    def test_module_does_not_use_research_budget_or_formatter(self) -> None:
        import server.services.concept_chat_search as module

        source = inspect.getsource(module)
        self.assertNotIn("server.search.budget", source)
        self.assertNotIn("chat_format", source)
        self.assertNotIn("stream_concept_chat", source)
        self.assertNotIn("ResearchRunner", source)
