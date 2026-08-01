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
    - Provides safe key lookup for adapter calls
KEY COMPONENTS:
    - SearchContext: Frozen runtime credential container
DEPENDENCIES:
    - External: pydantic
    - Internal: server.search.types
USAGE:
    from server.schemas.search import SearchContext
============================================================================
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from server.search.types import SearchProviderId


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
