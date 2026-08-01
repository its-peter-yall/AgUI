"""
============================================================================
FILE: __init__.py
LOCATION: server/search/adapters/__init__.py
============================================================================
PURPOSE:
    Adapter exports and registry factory for curated search providers.
ROLE IN PROJECT:
    Builds injected httpx adapters keyed by SearchProviderId for the
    coordinator without performing network calls at import time.
KEY COMPONENTS:
    - build_search_adapters: Factory returning configured adapters
    - Adapter class re-exports
DEPENDENCIES:
    - External: httpx
    - Internal: server.search.adapters.*, server.search.types
USAGE:
    from server.search.adapters import build_search_adapters
============================================================================
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

import httpx

from server.search.adapters.exa import ExaSearchAdapter
from server.search.adapters.tavily import TavilySearchAdapter
from server.search.types import SearchAdapter, SearchProviderId

Clock = Callable[[], datetime]


def build_search_adapters(
    client: httpx.AsyncClient,
    clock: Optional[Clock] = None,
) -> dict[SearchProviderId, SearchAdapter]:
    """Return available adapters keyed by provider ID in registry order.

    Args:
        client: Shared AsyncClient (caller owns lifecycle).
        clock: Optional clock for retrieved_at timestamps.

    Returns:
        Mapping of SearchProviderId to adapter instances.
    """
    active_clock = clock or (lambda: datetime.now(timezone.utc))
    return {
        SearchProviderId.TAVILY: TavilySearchAdapter(
            client=client, clock=active_clock
        ),
        SearchProviderId.EXA: ExaSearchAdapter(
            client=client, clock=active_clock
        ),
    }


__all__ = [
    "ExaSearchAdapter",
    "TavilySearchAdapter",
    "build_search_adapters",
]
