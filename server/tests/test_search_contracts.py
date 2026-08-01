"""
============================================================================
FILE: test_search_contracts.py
LOCATION: server/tests/test_search_contracts.py
============================================================================
PURPOSE:
    Verifies search provider metadata, normalized result limits, typed errors,
    and runtime-only credential serialization.
ROLE IN PROJECT:
    Freezes Phase 1 search contracts before adapters and API wiring exist.
KEY COMPONENTS:
    - SearchContractTests: Provider, error, result, and secret-boundary tests
DEPENDENCIES:
    - External: pydantic, unittest
    - Internal: server.schemas.search, server.search.registry, server.search.types
USAGE:
    python -m unittest server.tests.test_search_contracts -v
============================================================================
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from server.schemas.search import SearchContext
from server.search.registry import SEARCH_PROVIDER_REGISTRY
from server.search.types import (
    ROTATABLE_SEARCH_ERRORS,
    NormalizedSearchResult,
    SearchError,
    SearchErrorClass,
    SearchProviderId,
)


class SearchContractTests(unittest.TestCase):
    """Tests frozen search-provider and runtime-secret contracts."""

    def test_registry_contains_exact_locked_provider_order(self) -> None:
        self.assertEqual(
            list(SEARCH_PROVIDER_REGISTRY),
            [
                SearchProviderId.TAVILY,
                SearchProviderId.EXA,
                SearchProviderId.BRAVE,
                SearchProviderId.SERPAPI,
            ],
        )
        brave = SEARCH_PROVIDER_REGISTRY[SearchProviderId.BRAVE]
        self.assertTrue(brave.requires_payment_method)
        self.assertTrue(brave.attribution_required)
        self.assertEqual(brave.verified_at, "2026-08-01")
        self.assertEqual(
            SEARCH_PROVIDER_REGISTRY[SearchProviderId.TAVILY].key_header,
            "X-Tavily-Key",
        )
        self.assertEqual(
            SEARCH_PROVIDER_REGISTRY[SearchProviderId.SERPAPI].key_header,
            "X-SerpApi-Key",
        )

    def test_only_availability_errors_are_rotatable(self) -> None:
        self.assertEqual(
            ROTATABLE_SEARCH_ERRORS,
            frozenset(
                {
                    SearchErrorClass.RATE_LIMIT,
                    SearchErrorClass.QUOTA,
                    SearchErrorClass.TIMEOUT,
                    SearchErrorClass.AVAILABILITY,
                }
            ),
        )
        self.assertNotIn(
            SearchErrorClass.AUTHENTICATION,
            ROTATABLE_SEARCH_ERRORS,
        )
        self.assertNotIn(
            SearchErrorClass.INVALID_REQUEST,
            ROTATABLE_SEARCH_ERRORS,
        )
        self.assertNotIn(SearchErrorClass.POLICY, ROTATABLE_SEARCH_ERRORS)

    def test_search_error_uses_safe_generated_message(self) -> None:
        secret = "tvly-secret-never-render"
        error = SearchError(
            provider_id=SearchProviderId.TAVILY,
            error_class=SearchErrorClass.QUOTA,
            status_code=432,
            retry_after_seconds=1.5,
        )
        rendered = repr(error) + str(error) + secret[:0]
        self.assertIn("tavily", rendered)
        self.assertIn("quota", rendered)
        self.assertNotIn(secret, rendered)

    def test_normalized_result_rejects_unsafe_url(self) -> None:
        with self.assertRaises(ValidationError):
            NormalizedSearchResult(
                title="Unsafe",
                url="https://user:password@example.com/docs",
                canonical_url="https://example.com/docs",
                snippet="Unsafe URL",
                content="Evidence",
                publisher="Example",
                published_at=None,
                retrieved_at=datetime.now(timezone.utc),
                provider_id=SearchProviderId.EXA,
                provider_rank=1,
                raw_score=None,
            )

    def test_normalized_result_enforces_content_caps(self) -> None:
        with self.assertRaises(ValidationError):
            NormalizedSearchResult(
                title="Oversized",
                url="https://example.com/docs",
                canonical_url="https://example.com/docs",
                snippet="s" * 2001,
                content="c" * 8001,
                publisher=None,
                published_at=None,
                retrieved_at=datetime.now(timezone.utc),
                provider_id=SearchProviderId.BRAVE,
                provider_rank=1,
                raw_score=None,
            )

    def test_search_context_excludes_credentials_from_dumps_and_repr(
        self,
    ) -> None:
        secret = "exa-runtime-secret"
        context = SearchContext.from_plaintext_credentials(
            enabled=True,
            provider_ids=[SearchProviderId.EXA],
            credentials={SearchProviderId.EXA: secret},
        )
        self.assertEqual(context.get_api_key(SearchProviderId.EXA), secret)
        self.assertNotIn(secret, repr(context))
        self.assertNotIn(secret, context.model_dump_json())
        self.assertNotIn("credentials", context.model_dump())


if __name__ == "__main__":
    unittest.main()
