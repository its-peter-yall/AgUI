"""
============================================================================
FILE: serpapi.py
LOCATION: server/search/adapters/serpapi.py
============================================================================
PURPOSE:
    SerpAPI Google organic-results adapter with query-key protection.
ROLE IN PROJECT:
    One of four curated providers used by the search coordinator.
    Uses api_key query param but never echoes it in errors or local logs.
KEY COMPONENTS:
    - SerpApiSearchAdapter: Async SearchAdapter implementation
DEPENDENCIES:
    - External: httpx
    - Internal: server.search.adapters._common, http, source_safety, types
USAGE:
    adapter = SerpApiSearchAdapter(client=client)
    response = await adapter.search(query, api_key=key)
============================================================================
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

import httpx

from server.search.adapters._common import (
    execute_search_request,
    parse_provider_datetime,
    publisher_from_host,
)
from server.search.http import install_search_log_redaction
from server.search.source_safety import (
    UnsafeSourceUrl,
    canonicalize_source_url,
    sanitize_source_text,
)
from server.search.types import (
    NormalizedSearchResult,
    SearchError,
    SearchErrorClass,
    SearchProviderId,
    SearchQuery,
    SearchResponse,
)

Clock = Callable[[], datetime]

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
DEFAULT_CONTENT_CAP = 4000


class SerpApiSearchAdapter:
    """SerpAPI Google Search adapter (organic snippets only)."""

    provider_id = SearchProviderId.SERPAPI

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        clock: Optional[Clock] = None,
        content_cap: int = DEFAULT_CONTENT_CAP,
    ) -> None:
        self._client = client
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._content_cap = content_cap

    async def search(
        self,
        query: SearchQuery,
        *,
        api_key: str,
        timeout_seconds: float = 20.0,
    ) -> SearchResponse:
        """Execute a SerpAPI search and return normalized organic results."""
        install_search_log_redaction()
        params: dict = {
            "q": query.query,
            "api_key": api_key,
            "engine": "google",
            "safe": "active",
            "num": query.max_results,
        }
        payload, response_bytes = await execute_search_request(
            self._client,
            provider_id=self.provider_id,
            method="GET",
            url=SERPAPI_ENDPOINT,
            timeout_seconds=timeout_seconds,
            params=params,
        )
        return self._normalize(payload, response_bytes=response_bytes)

    def _normalize(
        self,
        payload: object,
        *,
        response_bytes: int,
    ) -> SearchResponse:
        if not isinstance(payload, dict):
            raise SearchError(
                provider_id=self.provider_id,
                error_class=SearchErrorClass.INVALID_RESPONSE,
                status_code=200,
            )
        raw_results = payload.get("organic_results")
        if not isinstance(raw_results, list):
            raise SearchError(
                provider_id=self.provider_id,
                error_class=SearchErrorClass.INVALID_RESPONSE,
                status_code=200,
            )

        retrieved_at = self._clock()
        results: list[NormalizedSearchResult] = []
        for index, item in enumerate(raw_results, start=1):
            if not isinstance(item, dict):
                continue
            raw_url = item.get("link") or item.get("url")
            if not isinstance(raw_url, str) or not raw_url.strip():
                continue
            try:
                canonical = canonicalize_source_url(raw_url)
            except UnsafeSourceUrl:
                continue
            title = sanitize_source_text(
                str(item.get("title") or canonical),
                max_chars=500,
            )
            if not title:
                title = canonical
            snippet = sanitize_source_text(
                str(item.get("snippet") or ""),
                max_chars=2000,
            )
            content = sanitize_source_text(
                snippet,
                max_chars=self._content_cap,
            )
            position = item.get("position")
            if isinstance(position, int) and position >= 1:
                rank = position
            else:
                rank = index
            published_at = parse_provider_datetime(
                item.get("date") or item.get("published_at")
            )
            results.append(
                NormalizedSearchResult(
                    title=title,
                    url=canonical,
                    canonical_url=canonical,
                    snippet=snippet,
                    content=content,
                    publisher=publisher_from_host(canonical),
                    published_at=published_at,
                    retrieved_at=retrieved_at,
                    provider_id=self.provider_id,
                    provider_rank=rank,
                    raw_score=None,
                )
            )
        return SearchResponse(results=results, response_bytes=response_bytes)
