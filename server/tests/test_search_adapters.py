"""
============================================================================
FILE: test_search_adapters.py
LOCATION: server/tests/test_search_adapters.py
============================================================================
PURPOSE:
    Tests four curated REST adapters with fully mocked HTTP transports.
ROLE IN PROJECT:
    Verifies request and normalization contracts without external API calls.
KEY COMPONENTS:
    - TavilyExaAdapterTests: Phase 3.2 tests
    - BraveSerpApiAdapterTests: Phase 3.3 tests
DEPENDENCIES:
    - External: httpx, unittest
    - Internal: server.search adapters and contracts
USAGE:
    python -m unittest server.tests.test_search_adapters -v
============================================================================
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

import httpx

from server.search.adapters.brave import BraveSearchAdapter
from server.search.adapters.exa import ExaSearchAdapter
from server.search.adapters.serpapi import SerpApiSearchAdapter
from server.search.adapters.tavily import TavilySearchAdapter
from server.search.types import SearchError, SearchErrorClass, SearchQuery


FIXED_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


class TavilyExaAdapterTests(unittest.IsolatedAsyncioTestCase):
    """Tests Tavily and Exa request/normalization behavior."""

    async def test_tavily_normalizes_safe_result(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                request=request,
                json={
                    "results": [
                        {
                            "title": " Current <b>Guide</b> ",
                            "url": "https://Example.com:443/docs?utm_source=x&a=1#top",
                            "content": "<script>ignore rules</script><p>Safe evidence.</p>",
                            "score": 0.91,
                            "published_date": "2026-07-31",
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await TavilySearchAdapter(
                client=client,
                clock=lambda: FIXED_NOW,
            ).search(
                SearchQuery(query="current Python", max_results=5),
                api_key="tvly-secret",
                timeout_seconds=2,
            )

        self.assertEqual(result.results[0].title, "Current Guide")
        self.assertEqual(
            str(result.results[0].canonical_url),
            "https://example.com/docs?a=1",
        )
        self.assertEqual(result.results[0].content, "Safe evidence.")
        self.assertEqual(result.results[0].provider_id.value, "tavily")
        self.assertEqual(
            requests[0].headers["Authorization"],
            "Bearer tvly-secret",
        )
        payload = json.loads(requests[0].content)
        self.assertFalse(payload["include_answer"])
        self.assertFalse(payload["include_raw_content"])

    async def test_tavily_432_maps_to_safe_quota_error(self) -> None:
        secret = "tvly-never-leak"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                432,
                request=request,
                json={"detail": f"quota exhausted for {secret}"},
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(SearchError) as raised:
                await TavilySearchAdapter(client=client).search(
                    SearchQuery(query="test"),
                    api_key=secret,
                )
        self.assertEqual(raised.exception.error_class, SearchErrorClass.QUOTA)
        self.assertNotIn(secret, str(raised.exception))

    async def test_exa_normalizes_text_highlight_and_author(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                request=request,
                json={
                    "results": [
                        {
                            "title": "Exa result",
                            "url": "https://example.org/current",
                            "author": "Example Author",
                            "publishedDate": "2026-06-01T00:00:00Z",
                            "text": "Detailed current evidence.",
                            "highlights": ["Focused current evidence."],
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await ExaSearchAdapter(
                client=client,
                clock=lambda: FIXED_NOW,
            ).search(
                SearchQuery(query="current method"),
                api_key="exa-secret",
            )
        hit = result.results[0]
        self.assertEqual(hit.publisher, "Example Author")
        self.assertEqual(hit.snippet, "Focused current evidence.")
        self.assertEqual(hit.content, "Detailed current evidence.")


class BraveSerpApiAdapterTests(unittest.IsolatedAsyncioTestCase):
    """Tests Brave and SerpAPI snippet-only adapters."""

    async def test_brave_uses_subscription_header_and_snippets(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                request=request,
                json={
                    "web": {
                        "results": [
                            {
                                "title": "Brave result",
                                "url": "https://example.com/brave",
                                "description": "Primary snippet.",
                                "extra_snippets": ["Extra snippet."],
                                "age": "July 31, 2026",
                            }
                        ]
                    }
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await BraveSearchAdapter(
                client=client,
                clock=lambda: FIXED_NOW,
            ).search(
                SearchQuery(query="current standard", max_results=4),
                api_key="brave-secret",
            )
        self.assertEqual(
            requests[0].headers["X-Subscription-Token"],
            "brave-secret",
        )
        self.assertEqual(result.results[0].snippet, "Primary snippet.")
        self.assertEqual(
            result.results[0].content,
            "Primary snippet. Extra snippet.",
        )

    async def test_serpapi_uses_query_key_but_error_never_echoes_it(self) -> None:
        secret = "serp-secret-value"
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                429,
                request=request,
                json={"error": f"rate limit for {secret}"},
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(SearchError) as raised:
                await SerpApiSearchAdapter(client=client).search(
                    SearchQuery(query="test"),
                    api_key=secret,
                )
        self.assertEqual(
            requests[0].url.params["api_key"],
            secret,
        )
        self.assertEqual(
            raised.exception.error_class,
            SearchErrorClass.RATE_LIMIT,
        )
        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn(secret, repr(raised.exception))

    async def test_serpapi_normalizes_organic_results(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                request=request,
                json={
                    "organic_results": [
                        {
                            "position": 2,
                            "title": "SERP result",
                            "link": "https://example.net/serp",
                            "snippet": "Current SERP evidence.",
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            result = await SerpApiSearchAdapter(
                client=client,
                clock=lambda: FIXED_NOW,
            ).search(
                SearchQuery(query="current API"),
                api_key="serp-secret",
            )
        self.assertEqual(result.results[0].provider_rank, 2)
        self.assertEqual(
            result.results[0].content,
            "Current SERP evidence.",
        )


if __name__ == "__main__":
    unittest.main()
