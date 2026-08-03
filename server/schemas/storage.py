"""
============================================================================
FILE: storage.py
LOCATION: server/schemas/storage.py
============================================================================
PURPOSE:
    Pydantic v2 request/response contracts for storage lifecycle REST API.
ROLE IN PROJECT:
    Defines camel-case JSON / snake-case Python contracts for status,
    connect, and disconnect endpoints under /settings/storage.
DEPENDENCIES:
    - External: pydantic
    - Internal: server.database.storage_mode
USAGE:
    from server.schemas.storage import StorageStatusResponse
============================================================================
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from server.database.storage_mode import DeploymentMode, StorageBackend


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.title() for part in tail)


class StorageSchema(BaseModel):
    """Base contract using camel-case JSON and snake-case Python."""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
    )


class StorageConnectRequest(StorageSchema):
    uri: str = Field(min_length=10, max_length=2048, repr=False)
    db_name: str = Field(min_length=1, max_length=63)

    @field_validator("uri")
    @classmethod
    def validate_uri_scheme(cls, value: str) -> str:
        if not value.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError("URI must use mongodb or mongodb+srv")
        return value

    @field_validator("db_name")
    @classmethod
    def validate_database_name(cls, value: str) -> str:
        forbidden = set('/\\."$\x00')
        if any(character in forbidden for character in value):
            raise ValueError("Mongo database name contains invalid characters")
        return value


class StorageStatusResponse(StorageSchema):
    deployment_mode: DeploymentMode
    active_backend: StorageBackend
    connected: bool
    mongo_db_name: Optional[str] = None
    can_connect: bool
    can_disconnect: bool
    can_migrate: bool
    local_data_present: bool
