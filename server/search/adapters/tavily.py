"""
============================================================================
FILE: tavily.py
LOCATION: server/search/adapters/tavily.py
============================================================================
PURPOSE:
    Tavily REST search adapter with request shaping and safe normalization.
ROLE IN PROJECT:
    One of four curated providers used by the search coordinator.
KEY COMPONENTS:
    - TavilySearchAdapter: Async SearchAdapter implementation
DEPENDENCIES:
    - External: httpx
    - Internal: server.search.adapters._common, http, source_safety, types
USAGE:
    adapter = TavilySearchAdapter(client=client)
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

TAVILY_ENDPOINT = "https://api.tavily.com/search"
DEFAULT_CONTENT_CAP = 4000


class TavilySearchAdapter:
    """Tavily Search API adapter."""

    provider_id = SearchProviderId.TAVILY

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
        """Execute a Tavily search and return normalized results."""
        body: dict = {
            "query": query.query,
            "max_results": query.max_results,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }
        if query.recency_days is not None:
            body["days"] = query.recency_days
        if query.include_domains:
            body["include_domains"] = list(query.include_domains)
        if query.exclude_domains:
            body["exclude_domains"] = list(query.exclude_domains)

        payload, response_bytes = await execute_search_request(
            self._client,
            provider_id=self.provider_id,
            method="POST",
            url=TAVILY_ENDPOINT,
            timeout_seconds=timeout_seconds,
            headers={"Authorization": f"Bearer {api_key}"},
            json_body=body,
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
        raw_results = payload.get("results")
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
            raw_url = item.get("url")
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
            content = sanitize_source_text(
                str(item.get("content") or ""),
                max_chars=self._content_cap,
            )
            snippet = sanitize_source_text(
                content,
                max_chars=2000,
            )
            score = item.get("score")
            raw_score = float(score) if isinstance(score, (int, float)) else None
            published_at = parse_provider_datetime(
                item.get("published_date") or item.get("published_at")
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
                    provider_rank=index,
                    raw_score=raw_score,
                )
            )
        return SearchResponse(results=results, response_bytes=response_bytes)
