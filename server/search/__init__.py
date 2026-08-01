"""
============================================================================
FILE: __init__.py
LOCATION: server/search/__init__.py
============================================================================
PURPOSE:
    Public API surface for the server search package.
ROLE IN PROJECT:
    Aggregates adapter-neutral types and the curated provider registry into
    a single importable namespace.
KEY COMPONENTS:
    - Search types: IDs, errors, queries, normalized results, adapters
    - Registry: SEARCH_PROVIDER_REGISTRY metadata mapping
DEPENDENCIES:
    - External: None
    - Internal: server.search.registry, server.search.types
USAGE:
    from server.search import SearchProviderId, SEARCH_PROVIDER_REGISTRY
============================================================================
"""

from server.search.registry import SEARCH_PROVIDER_REGISTRY, SearchProviderMetadata
from server.search.types import (
    ROTATABLE_SEARCH_ERRORS,
    AllProvidersUnavailable,
    NormalizedSearchResult,
    SearchAdapter,
    SearchError,
    SearchErrorClass,
    SearchProviderId,
    SearchQuery,
    SearchResponse,
)

__all__ = [
    "AllProvidersUnavailable",
    "NormalizedSearchResult",
    "ROTATABLE_SEARCH_ERRORS",
    "SEARCH_PROVIDER_REGISTRY",
    "SearchAdapter",
    "SearchError",
    "SearchErrorClass",
    "SearchProviderId",
    "SearchProviderMetadata",
    "SearchQuery",
    "SearchResponse",
]
