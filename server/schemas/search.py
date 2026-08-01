"""
============================================================================
FILE: search.py
LOCATION: server/schemas/search.py
============================================================================
PURPOSE:
    Runtime-only search context carrying provider credentials as SecretStr.
ROLE IN PROJECT:
    Freezes the credential boundary: keys live only in memory, are excluded
    from dumps and repr, and never persist or log.
    - Exposes a plaintext-to-SecretStr factory for runtime wiring
    - Parses request headers into ephemeral SearchContext via dependency
KEY COMPONENTS:
    - SearchContext: Frozen runtime credential container
    - get_search_context: FastAPI header dependency
DEPENDENCIES:
    - External: fastapi, pydantic
    - Internal: server.search.types
USAGE:
    from server.schemas.search import SearchContext, get_search_context
============================================================================
"""

from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from server.search.types import SearchProviderId

_PROVIDER_KEY_HEADERS: dict[SearchProviderId, str] = {
    SearchProviderId.TAVILY: "X-Tavily-Key",
    SearchProviderId.EXA: "X-Exa-Key",
    SearchProviderId.BRAVE: "X-Brave-Key",
    SearchProviderId.SERPAPI: "X-SerpApi-Key",
}


class SearchContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    provider_ids: tuple[SearchProviderId, ...] = ()
    credentials: dict[SearchProviderId, SecretStr] = Field(
        default_factory=dict,
        exclude=True,
        repr=False,
    )

    @classmethod
    def from_plaintext_credentials(
        cls,
        *,
        enabled: bool,
        provider_ids: list[SearchProviderId],
        credentials: dict[SearchProviderId, str],
    ) -> "SearchContext":
        return cls(
            enabled=enabled,
            provider_ids=tuple(provider_ids),
            credentials={
                provider_id: SecretStr(value)
                for provider_id, value in credentials.items()
            },
        )

    def get_api_key(self, provider_id: SearchProviderId) -> str:
        credential = self.credentials.get(provider_id)
        if credential is None:
            raise KeyError(f"Missing search credential: {provider_id.value}")
        return credential.get_secret_value()


async def get_search_context(
    x_web_search: Optional[str] = Header(None, alias="X-Web-Search"),
    x_web_search_providers: Optional[str] = Header(
        None, alias="X-Web-Search-Providers"
    ),
    x_tavily_key: Optional[str] = Header(None, alias="X-Tavily-Key"),
    x_exa_key: Optional[str] = Header(None, alias="X-Exa-Key"),
    x_brave_key: Optional[str] = Header(None, alias="X-Brave-Key"),
    x_serpapi_key: Optional[str] = Header(None, alias="X-SerpApi-Key"),
) -> SearchContext:
    """Parse ephemeral web-search headers into a runtime SearchContext.

    Keys never appear in dumps, logs, or responses. Absent/false flags
    ignore any supplied key headers.
    """
    flag = (x_web_search or "false").strip().lower()
    if flag not in {"true", "false"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Web-Search must be true or false.",
        )
    if flag == "false":
        return SearchContext()

    raw_providers = (x_web_search_providers or "").strip()
    if not raw_providers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Web-Search-Providers header is required when search is on.",
        )

    key_by_provider: dict[SearchProviderId, Optional[str]] = {
        SearchProviderId.TAVILY: x_tavily_key,
        SearchProviderId.EXA: x_exa_key,
        SearchProviderId.BRAVE: x_brave_key,
        SearchProviderId.SERPAPI: x_serpapi_key,
    }

    provider_ids: list[SearchProviderId] = []
    seen: set[SearchProviderId] = set()
    for token in raw_providers.split(","):
        name = token.strip().lower()
        if not name:
            continue
        try:
            provider_id = SearchProviderId(name)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported web search provider: {name}",
            ) from exc
        if provider_id in seen:
            continue
        seen.add(provider_id)
        provider_ids.append(provider_id)

    if not provider_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Web-Search-Providers header is required when search is on.",
        )

    credentials: dict[SearchProviderId, str] = {}
    for provider_id in provider_ids:
        header_name = _PROVIDER_KEY_HEADERS[provider_id]
        raw_key = key_by_provider.get(provider_id)
        key = (raw_key or "").strip()
        if not key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"{header_name} header is missing.",
            )
        credentials[provider_id] = key

    return SearchContext.from_plaintext_credentials(
        enabled=True,
        provider_ids=provider_ids,
        credentials=credentials,
    )
