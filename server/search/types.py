"""
============================================================================
FILE: types.py
LOCATION: server/search/types.py
============================================================================
PURPOSE:
    Adapter-neutral search provider IDs, queries, normalized results, and
    safe typed errors shared by every search adapter.
ROLE IN PROJECT:
    Freezes the search contract boundary so adapters, the registry, and the
    API layer evolve without renaming shared types.
    - Defines provider/error enums and the rotatable error set
    - Normalizes raw provider responses into one result shape
KEY COMPONENTS:
    - SearchProviderId, SearchErrorClass: Enum contracts
    - SearchError, AllProvidersUnavailable: Typed exception hierarchy
    - SearchQuery, NormalizedSearchResult, SearchResponse: Pydantic models
    - SearchAdapter: Async adapter protocol
DEPENDENCIES:
    - External: pydantic
    - Internal: None
USAGE:
    from server.search.types import SearchProviderId, SearchQuery
============================================================================
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, Protocol

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator


class SearchProviderId(str, Enum):
    TAVILY = "tavily"
    EXA = "exa"
    BRAVE = "brave"
    SERPAPI = "serpapi"


class SearchErrorClass(str, Enum):
    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    POLICY = "policy"
    RATE_LIMIT = "rate_limit"
    QUOTA = "quota"
    TIMEOUT = "timeout"
    AVAILABILITY = "availability"
    INVALID_RESPONSE = "invalid_response"


ROTATABLE_SEARCH_ERRORS = frozenset(
    {
        SearchErrorClass.RATE_LIMIT,
        SearchErrorClass.QUOTA,
        SearchErrorClass.TIMEOUT,
        SearchErrorClass.AVAILABILITY,
    }
)


class SearchError(Exception):
    def __init__(
        self,
        *,
        provider_id: SearchProviderId,
        error_class: SearchErrorClass,
        status_code: Optional[int] = None,
        retry_after_seconds: Optional[float] = None,
    ) -> None:
        self.provider_id = provider_id
        self.error_class = error_class
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"{provider_id.value} search failed: {error_class.value}"
        )


class AllProvidersUnavailable(RuntimeError):
    """Raised after every configured provider has an approved outage."""

    def __init__(
        self,
        *,
        provider_ids: tuple[SearchProviderId, ...],
    ) -> None:
        self.provider_ids = provider_ids
        super().__init__("All configured search providers are unavailable.")


class SearchQuery(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=8, ge=1, le=20)
    recency_days: Optional[int] = Field(default=None, ge=1, le=3650)
    include_domains: list[str] = Field(default_factory=list, max_length=20)
    exclude_domains: list[str] = Field(default_factory=list, max_length=20)


class NormalizedSearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str = Field(min_length=1, max_length=500)
    url: AnyHttpUrl
    canonical_url: AnyHttpUrl
    snippet: str = Field(default="", max_length=2000)
    content: str = Field(default="", max_length=8000)
    publisher: Optional[str] = Field(default=None, max_length=300)
    published_at: Optional[datetime] = None
    retrieved_at: datetime
    provider_id: SearchProviderId
    provider_rank: int = Field(ge=1)
    raw_score: Optional[float] = None

    @field_validator("url", "canonical_url")
    @classmethod
    def reject_url_credentials(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username or value.password:
            raise ValueError("Source URLs cannot contain credentials")
        return value


class SearchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    results: list[NormalizedSearchResult]
    response_bytes: int = Field(ge=0)


class SearchAdapter(Protocol):
    provider_id: SearchProviderId

    async def search(
        self,
        query: SearchQuery,
        *,
        api_key: str,
        timeout_seconds: float = 20.0,
    ) -> SearchResponse:
        """Return normalized results or raise SearchError."""
        ...
