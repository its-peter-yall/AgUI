"""
============================================================================
FILE: test_search_context.py
LOCATION: server/tests/test_search_context.py
============================================================================
PURPOSE:
    Tests strict web-search header parsing and runtime secret exclusion.
ROLE IN PROJECT:
    Defines credential boundary used only by generate and resume endpoints.
KEY COMPONENTS:
    - SearchContextHeaderTests: Off, on, missing, unknown, duplicate tests
DEPENDENCIES:
    - External: fastapi, unittest
    - Internal: server.schemas.search
USAGE:
    python -m unittest server.tests.test_search_context -v
============================================================================
"""

from __future__ import annotations

import unittest
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from server.schemas.search import SearchContext, get_search_context
from server.search.types import SearchProviderId


app = FastAPI()


@app.get("/context")
async def read_context(
    context: Annotated[SearchContext, Depends(get_search_context)],
) -> dict[str, object]:
    return {
        "enabled": context.enabled,
        "provider_ids": [item.value for item in context.provider_ids],
        "dump": context.model_dump(mode="json"),
    }


class SearchContextHeaderTests(unittest.TestCase):
    """Tests request-scoped search header validation."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_default_and_explicit_off_return_no_credentials(self) -> None:
        for headers in ({}, {"X-Web-Search": "false", "X-Tavily-Key": "ignored"}):
            with self.subTest(headers=headers):
                response = self.client.get("/context", headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()["enabled"])
                self.assertEqual(response.json()["provider_ids"], [])
                self.assertNotIn("ignored", response.text)

    def test_enabled_context_deduplicates_and_excludes_keys(self) -> None:
        response = self.client.get(
            "/context",
            headers={
                "X-Web-Search": "true",
                "X-Web-Search-Providers": "tavily,exa,tavily",
                "X-Tavily-Key": "tvly-secret",
                "X-Exa-Key": "exa-secret",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["provider_ids"], ["tavily", "exa"])
        self.assertNotIn("tvly-secret", response.text)
        self.assertNotIn("exa-secret", response.text)
        self.assertNotIn("credentials", response.json()["dump"])

    def test_missing_selected_key_returns_safe_401(self) -> None:
        response = self.client.get(
            "/context",
            headers={
                "X-Web-Search": "true",
                "X-Web-Search-Providers": "brave",
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "X-Brave-Key header is missing.")

    def test_unknown_provider_and_invalid_flag_return_400(self) -> None:
        unknown = self.client.get(
            "/context",
            headers={
                "X-Web-Search": "true",
                "X-Web-Search-Providers": "unknown",
            },
        )
        invalid = self.client.get(
            "/context",
            headers={"X-Web-Search": "sometimes"},
        )
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(
            unknown.json()["detail"],
            "Unsupported web search provider: unknown",
        )
        self.assertEqual(invalid.status_code, 400)

    def test_context_returns_plain_key_only_through_explicit_method(self) -> None:
        context = SearchContext.from_plaintext_credentials(
            enabled=True,
            provider_ids=[SearchProviderId.SERPAPI],
            credentials={SearchProviderId.SERPAPI: "serp-secret"},
        )
        self.assertEqual(
            context.get_api_key(SearchProviderId.SERPAPI),
            "serp-secret",
        )


if __name__ == "__main__":
    unittest.main()
