"""
============================================================================
FILE: __init__.py
LOCATION: server/search/__init__.py
============================================================================
PURPOSE:
    Public API surface for the server search package.
ROLE IN PROJECT:
    Aggregates adapter-neutral types, registry, safety helpers, budget,
    coordinator, and adapter factory into one importable namespace.
KEY COMPONENTS:
    - Search types: IDs, errors, queries, normalized results, adapters
    - Registry: SEARCH_PROVIDER_REGISTRY metadata mapping
    - Safety, HTTP, budget, coordinator, adapter factory exports
DEPENDENCIES:
    - External: None
    - Internal: server.search.*
USAGE:
    from server.search import SearchProviderId, ProviderCoordinator
============================================================================
"""

from server.search.adapters import (
    BraveSearchAdapter,
    ExaSearchAdapter,
    SerpApiSearchAdapter,
    TavilySearchAdapter,
    build_search_adapters,
)
from server.search.budget import (
    ResearchBudget,
    ResearchBudgetExceeded,
    ResearchBudgetLedger,
    ResearchBudgetUsage,
    resolve_research_budget,
)
from server.search.coordinator import ProviderCoordinator
from server.search.http import (
    SearchSecretRedactionFilter,
    install_search_log_redaction,
    map_http_status_to_error_class,
    parse_retry_after,
    read_capped_json,
)
from server.search.registry import SEARCH_PROVIDER_REGISTRY, SearchProviderMetadata
from server.search.source_safety import (
    UnsafeSourceUrl,
    canonicalize_source_url,
    content_identity,
    deduplicate_results,
    format_untrusted_sources,
    sanitize_source_text,
)
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
    "BraveSearchAdapter",
    "ExaSearchAdapter",
    "NormalizedSearchResult",
    "ProviderCoordinator",
    "ROTATABLE_SEARCH_ERRORS",
    "ResearchBudget",
    "ResearchBudgetExceeded",
    "ResearchBudgetLedger",
    "ResearchBudgetUsage",
    "SEARCH_PROVIDER_REGISTRY",
    "SearchAdapter",
    "SearchError",
    "SearchErrorClass",
    "SearchProviderId",
    "SearchProviderMetadata",
    "SearchQuery",
    "SearchResponse",
    "SearchSecretRedactionFilter",
    "SerpApiSearchAdapter",
    "TavilySearchAdapter",
    "UnsafeSourceUrl",
    "build_search_adapters",
    "canonicalize_source_url",
    "content_identity",
    "deduplicate_results",
    "format_untrusted_sources",
    "install_search_log_redaction",
    "map_http_status_to_error_class",
    "parse_retry_after",
    "read_capped_json",
    "resolve_research_budget",
    "sanitize_source_text",
]
