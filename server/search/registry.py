"""
============================================================================
FILE: registry.py
LOCATION: server/search/registry.py
============================================================================
PURPOSE:
    Metadata-only curated registry for Tavily, Exa, Brave, and SerpAPI.
ROLE IN PROJECT:
    Supplies exact provider metadata for Settings display, header
    construction, and future adapter wiring without making network calls.
    - Freezes insertion-ordered provider rows verified 2026-08-01
    - Stores no credentials and imports no HTTP adapter
KEY COMPONENTS:
    - SearchProviderMetadata: Frozen provider row contract
    - SEARCH_PROVIDER_REGISTRY: Ordered metadata mapping
DEPENDENCIES:
    - External: pydantic
    - Internal: server.search.types
USAGE:
    from server.search.registry import SEARCH_PROVIDER_REGISTRY
============================================================================
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from server.search.types import SearchProviderId


class SearchProviderMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: SearchProviderId
    display_name: str
    free_tier_summary: str
    signup_url: str
    docs_url: str
    endpoint: str
    key_header: str
    requires_payment_method: bool
    attribution_required: bool
    recommended: bool
    verified_at: str


SEARCH_PROVIDER_REGISTRY: dict[SearchProviderId, SearchProviderMetadata] = {
    SearchProviderId.TAVILY: SearchProviderMetadata(
        id=SearchProviderId.TAVILY,
        display_name="Tavily",
        free_tier_summary="1,000 API credits each month; no card required.",
        signup_url="https://app.tavily.com",
        docs_url=(
            "https://docs.tavily.com/documentation/api-reference/"
            "endpoint/search"
        ),
        endpoint="https://api.tavily.com/search",
        key_header="X-Tavily-Key",
        requires_payment_method=False,
        attribution_required=False,
        recommended=True,
        verified_at="2026-08-01",
    ),
    SearchProviderId.EXA: SearchProviderMetadata(
        id=SearchProviderId.EXA,
        display_name="Exa",
        free_tier_summary=(
            "$10 monthly free credits plus signup credits; no card required."
        ),
        signup_url="https://dashboard.exa.ai/api-keys",
        docs_url="https://exa.ai/docs/reference/search",
        endpoint="https://api.exa.ai/search",
        key_header="X-Exa-Key",
        requires_payment_method=False,
        attribution_required=False,
        recommended=False,
        verified_at="2026-08-01",
    ),
    SearchProviderId.BRAVE: SearchProviderMetadata(
        id=SearchProviderId.BRAVE,
        display_name="Brave Search",
        free_tier_summary=(
            "$5 monthly credits, about 1,000 searches; card required."
        ),
        signup_url="https://api-dashboard.search.brave.com/register",
        docs_url=(
            "https://api-dashboard.search.brave.com/documentation/"
            "quickstart"
        ),
        endpoint="https://api.search.brave.com/res/v1/web/search",
        key_header="X-Brave-Key",
        requires_payment_method=True,
        attribution_required=True,
        recommended=False,
        verified_at="2026-08-01",
    ),
    SearchProviderId.SERPAPI: SearchProviderMetadata(
        id=SearchProviderId.SERPAPI,
        display_name="SerpAPI",
        free_tier_summary="250 searches each month on recurring free plan.",
        signup_url="https://serpapi.com/users/sign_up",
        docs_url="https://serpapi.com/search-api",
        endpoint="https://serpapi.com/search.json",
        key_header="X-SerpApi-Key",
        requires_payment_method=False,
        attribution_required=False,
        recommended=False,
        verified_at="2026-08-01",
    ),
}
