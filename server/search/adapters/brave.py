"""
============================================================================
FILE: brave.py
LOCATION: server/search/adapters/brave.py
============================================================================
PURPOSE:
    Brave Search REST adapter using snippet-only web results.
ROLE IN PROJECT:
    One of four curated providers used by the search coordinator.
    Does not call Brave LLM Context or fetch result pages.
KEY COMPONENTS:
    - BraveSearchAdapter: Async SearchAdapter implementation
DEPENDENCIES:
    - External: httpx
    - Internal: server.search.adapters._common, source_safety, types
USAGE:
    adapter = BraveSearchAdapter(client=client)
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

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_CONTENT_CAP = 4000


class BraveSearchAdapter:
    """Brave Web Search API adapter (snippets only)."""

    provider_id = SearchProviderId.BRAVE

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
        """Execute a Brave web search and return normalized snippets."""
        params: dict = {
            "q": query.query,
            "count": query.max_results,
            "safesearch": "strict",
            "extra_snippets": "true",
        }
        payload, response_bytes = await execute_search_request(
            self._client,
            provider_id=self.provider_id,
            method="GET",
            url=BRAVE_ENDPOINT,
            timeout_seconds=timeout_seconds,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
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
        web = payload.get("web")
        if not isinstance(web, dict):
            raise SearchError(
                provider_id=self.provider_id,
                error_class=SearchErrorClass.INVALID_RESPONSE,
                status_code=200,
            )
        raw_results = web.get("results")
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
            description = sanitize_source_text(
                str(item.get("description") or ""),
                max_chars=2000,
            )
            extra_parts: list[str] = []
            extras = item.get("extra_snippets") or []
            if isinstance(extras, list):
                for extra in extras:
                    cleaned = sanitize_source_text(
                        str(extra or ""), max_chars=2000
                    )
                    if cleaned:
                        extra_parts.append(cleaned)
            content_parts = [part for part in [description, *extra_parts] if part]
            content = sanitize_source_text(
                " ".join(content_parts),
                max_chars=self._content_cap,
            )
            snippet = description or sanitize_source_text(
                content, max_chars=2000
            )
            published_at = parse_provider_datetime(
                item.get("age") or item.get("page_age")
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
                    raw_score=None,
                )
            )
        return SearchResponse(results=results, response_bytes=response_bytes)
