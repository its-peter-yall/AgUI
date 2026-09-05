"""
============================================================================
FILE: concept_chat_search.py
LOCATION: server/services/concept_chat_search.py
============================================================================
PURPOSE:
    One-shot web search helper and OpenAI tool schema for concept chat.
ROLE IN PROJECT:
    Gives the concept-chat assistant a web_search tool backed by the same
    adapters and ProviderCoordinator as Researcher, without research jobs.
    - Exposes a stable tool definition (constraints in the description)
    - Caps coordinator retries with a tiny duck-typed ledger
    - Runs a single SearchQuery and always closes the httpx client
KEY COMPONENTS:
    - WEB_SEARCH_TOOL: OpenAI function schema (query only)
    - ChatSearchLedger: 2x-provider call cap and 25s monotonic window
    - one_shot_chat_search: Filter adapters and run ProviderCoordinator
DEPENDENCIES:
    - External: httpx
    - Internal: server.schemas.search, server.search adapters/coordinator/types
USAGE:
    from server.services.concept_chat_search import (
        WEB_SEARCH_TOOL,
        one_shot_chat_search,
    )
    response = await one_shot_chat_search(search_context, query)
============================================================================
"""

from __future__ import annotations

import time
from typing import Callable, Optional

import httpx

from server.schemas.search import SearchContext
from server.search.adapters import build_search_adapters
from server.search.coordinator import ProviderCoordinator
from server.search.types import SearchQuery, SearchResponse

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the public web for current facts, versions, APIs, or "
            "news that the concept card does not cover. Use only when the "
            "concept content and prior messages lack the context needed to "
            "answer. Do not search if prior web_search results already "
            "cover the question. One search per turn. Write one meticulous "
            "query using specific terms, versions, and concept-title "
            "disambiguation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Single meticulous search query. Include specific "
                        "terms, versions, and the concept title when needed "
                        "to disambiguate."
                    ),
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


class ChatSearchLedger:
    """In-process search call/time cap for one concept-chat tool round.

    Duck-typed for ProviderCoordinator. Not a ResearchBudgetLedger.
    """

    def __init__(
        self,
        max_search_calls: int,
        *,
        max_elapsed_seconds: float = 25.0,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        """Store call cap and start the monotonic window.

        Args:
            max_search_calls: Hard cap (use 2 * provider count).
            max_elapsed_seconds: Wall window; default 25 so remaining
                is never 0 at start (coordinator clamps 0 to 10ms).
            clock: Optional monotonic clock for tests.
        """
        self.max_search_calls = max_search_calls
        self.max_elapsed_seconds = max_elapsed_seconds
        self._clock = clock or time.monotonic
        self._started_at = self._clock()
        self._search_calls = 0

    def remaining_seconds(self) -> float:
        """Seconds left in the 25s window, floored at 0."""
        elapsed = self._clock() - self._started_at
        return max(0.0, self.max_elapsed_seconds - elapsed)

    def reserve_search_call(self, amount: int = 1) -> None:
        """Reserve search attempts or raise RuntimeError.

        Args:
            amount: Calls to reserve (coordinator uses default 1).

        Raises:
            RuntimeError: When the call cap would be exceeded.
        """
        if self._search_calls + amount > self.max_search_calls:
            raise RuntimeError("Chat search call budget exceeded")
        self._search_calls += amount


async def one_shot_chat_search(
    search_context: SearchContext,
    query: str,
    *,
    max_results: int = 5,
    timeout_seconds: float = 20.0,
) -> SearchResponse:
    """Run one ProviderCoordinator search for concept chat.

    Args:
        search_context: Runtime context with selected provider keys.
        query: Model query; truncated to SearchQuery max (500 chars).
        max_results: Server-chosen hit cap (default 5). Not a tool arg.
        timeout_seconds: Coordinator timeout (default 20).

    Returns:
        SearchResponse from the first successful provider.

    Raises:
        ValueError: Empty adapter set or mismatched credentials.
        SearchError: Non-rotatable provider failure.
        AllProvidersUnavailable: Every configured provider failed.
    """
    client = httpx.AsyncClient()
    try:
        all_adapters = build_search_adapters(client)
        selected = set(search_context.provider_ids)
        adapters = {
            provider_id: adapter
            for provider_id, adapter in all_adapters.items()
            if provider_id in selected
        }
        credentials = {
            provider_id: search_context.get_api_key(provider_id)
            for provider_id in adapters
        }
        ledger = ChatSearchLedger(
            max_search_calls=2 * len(adapters),
        )
        coordinator = ProviderCoordinator.create(
            adapters=adapters,
            credentials=credentials,
            persisted_order=[],
            ledger=ledger,
        )
        search_query = SearchQuery(
            query=query[:500],
            max_results=max_results,
        )
        return await coordinator.search(
            search_query,
            timeout_seconds=timeout_seconds,
        )
    finally:
        await client.aclose()
