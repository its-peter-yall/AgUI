"""
============================================================================
FILE: test_search_coordinator.py
LOCATION: server/tests/test_search_coordinator.py
============================================================================
PURPOSE:
    Tests one-time provider order, explicit retries, and approved rotation.
ROLE IN PROJECT:
    Enforces locked provider failure policy using deterministic test doubles.
KEY COMPONENTS:
    - ProviderCoordinatorTests: Shuffle, retry, rotate, stop, exhaustion tests
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.search coordinator and contracts
USAGE:
    python -m unittest server.tests.test_search_coordinator -v
============================================================================
"""

from __future__ import annotations

import random
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from server.search.coordinator import ProviderCoordinator
from server.search.types import (
    AllProvidersUnavailable,
    NormalizedSearchResult,
    SearchError,
    SearchErrorClass,
    SearchProviderId,
    SearchQuery,
    SearchResponse,
)


def _response(provider_id: SearchProviderId) -> SearchResponse:
    return SearchResponse(
        results=[
            NormalizedSearchResult(
                title="Result",
                url="https://example.com/result",
                canonical_url="https://example.com/result",
                snippet="Evidence",
                content="Evidence",
                publisher="example.com",
                published_at=None,
                retrieved_at=datetime.now(timezone.utc),
                provider_id=provider_id,
                provider_rank=1,
                raw_score=None,
            )
        ],
        response_bytes=100,
    )


class ProviderCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    """Tests job-local search provider coordination."""

    async def test_new_order_is_shuffled_once_and_reused(self) -> None:
        adapters = {
            provider_id: SimpleNamespace(
                provider_id=provider_id,
                search=AsyncMock(return_value=_response(provider_id)),
            )
            for provider_id in (SearchProviderId.TAVILY, SearchProviderId.EXA)
        }
        coordinator = ProviderCoordinator.create(
            adapters=adapters,
            credentials={
                SearchProviderId.TAVILY: "tavily-key",
                SearchProviderId.EXA: "exa-key",
            },
            persisted_order=[],
            ledger=MagicMock(),
            rng=random.Random(7),
            sleep=AsyncMock(),
            jitter=lambda delay: delay,
        )
        order = list(coordinator.provider_order)
        await coordinator.search(SearchQuery(query="one"))
        await coordinator.search(SearchQuery(query="two"))
        self.assertEqual(list(coordinator.provider_order), order)

    async def test_rate_limit_retries_then_rotates(self) -> None:
        first = SimpleNamespace(
            provider_id=SearchProviderId.TAVILY,
            search=AsyncMock(
                side_effect=[
                    SearchError(
                        provider_id=SearchProviderId.TAVILY,
                        error_class=SearchErrorClass.RATE_LIMIT,
                        status_code=429,
                        retry_after_seconds=0.1,
                    ),
                    SearchError(
                        provider_id=SearchProviderId.TAVILY,
                        error_class=SearchErrorClass.RATE_LIMIT,
                        status_code=429,
                        retry_after_seconds=0.1,
                    ),
                ]
            ),
        )
        second = SimpleNamespace(
            provider_id=SearchProviderId.EXA,
            search=AsyncMock(return_value=_response(SearchProviderId.EXA)),
        )
        ledger = MagicMock()
        coordinator = ProviderCoordinator.create(
            adapters={
                SearchProviderId.TAVILY: first,
                SearchProviderId.EXA: second,
            },
            credentials={
                SearchProviderId.TAVILY: "tavily-key",
                SearchProviderId.EXA: "exa-key",
            },
            persisted_order=[SearchProviderId.TAVILY, SearchProviderId.EXA],
            ledger=ledger,
            rng=random.Random(1),
            sleep=AsyncMock(),
            jitter=lambda delay: delay,
        )
        result = await coordinator.search(SearchQuery(query="test"))
        self.assertEqual(result.results[0].provider_id, SearchProviderId.EXA)
        self.assertEqual(first.search.await_count, 2)
        second.search.assert_awaited_once()
        self.assertEqual(ledger.reserve_search_call.call_count, 3)

    async def test_authentication_error_does_not_retry_or_rotate(self) -> None:
        first = SimpleNamespace(
            provider_id=SearchProviderId.TAVILY,
            search=AsyncMock(
                side_effect=SearchError(
                    provider_id=SearchProviderId.TAVILY,
                    error_class=SearchErrorClass.AUTHENTICATION,
                    status_code=401,
                )
            ),
        )
        second = SimpleNamespace(
            provider_id=SearchProviderId.EXA,
            search=AsyncMock(),
        )
        coordinator = ProviderCoordinator.create(
            adapters={
                SearchProviderId.TAVILY: first,
                SearchProviderId.EXA: second,
            },
            credentials={
                SearchProviderId.TAVILY: "bad-key",
                SearchProviderId.EXA: "good-key",
            },
            persisted_order=[SearchProviderId.TAVILY, SearchProviderId.EXA],
            ledger=MagicMock(),
            rng=random.Random(1),
            sleep=AsyncMock(),
            jitter=lambda delay: delay,
        )
        with self.assertRaises(SearchError) as raised:
            await coordinator.search(SearchQuery(query="test"))
        self.assertEqual(
            raised.exception.error_class,
            SearchErrorClass.AUTHENTICATION,
        )
        first.search.assert_awaited_once()
        second.search.assert_not_awaited()

    async def test_all_rotatable_failures_raise_exhaustion(self) -> None:
        adapters = {}
        credentials = {}
        order = [SearchProviderId.TAVILY, SearchProviderId.EXA]
        for provider_id in order:
            adapters[provider_id] = SimpleNamespace(
                provider_id=provider_id,
                search=AsyncMock(
                    side_effect=SearchError(
                        provider_id=provider_id,
                        error_class=SearchErrorClass.QUOTA,
                        status_code=402,
                    )
                ),
            )
            credentials[provider_id] = f"{provider_id.value}-key"
        coordinator = ProviderCoordinator.create(
            adapters=adapters,
            credentials=credentials,
            persisted_order=order,
            ledger=MagicMock(),
            rng=random.Random(1),
            sleep=AsyncMock(),
            jitter=lambda delay: delay,
        )
        with self.assertRaises(AllProvidersUnavailable):
            await coordinator.search(SearchQuery(query="test"))


if __name__ == "__main__":
    unittest.main()
