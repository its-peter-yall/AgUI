"""
============================================================================
FILE: mongo_client.py
LOCATION: server/database/mongo_client.py
============================================================================
PURPOSE:
    Safe synchronous MongoDB client factory with ping validation and URI
    credential redaction for diagnostics.
ROLE IN PROJECT:
    Process-wide Mongo connection lifecycle for optional Atlas storage.
    - Creates one MongoClient, pings, returns selected database
    - Maps driver errors without leaking credentials
    - Closes client on configuration or network failure
DEPENDENCIES:
    - External: pymongo
    - Internal: None
USAGE:
    connection = connect_mongo(uri, "a2ui")
    safe = redact_mongo_uri(uri)
============================================================================
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import (
    ConfigurationError,
    ConnectionFailure,
    InvalidURI,
    OperationFailure,
    ServerSelectionTimeoutError,
)

_CREDENTIALS = re.compile(
    r"(mongodb(?:\+srv)?://)([^:/?#]+):([^@]+)@",
    re.IGNORECASE,
)


class MongoConfigurationError(ValueError):
    """Mongo connection request is malformed or rejected by auth."""


class MongoUnavailableError(ConnectionError):
    """Mongo target cannot be reached within configured timeout."""


@dataclass(frozen=True)
class MongoConnection:
    """Validated process-wide client and selected database."""

    client: MongoClient[Any]
    database: Database[Any]
    db_name: str


def redact_mongo_uri(uri: str) -> str:
    """Mask Mongo password while retaining target context for diagnostics."""

    return _CREDENTIALS.sub(r"\1\2:***@", uri)


def connect_mongo(
    uri: str,
    db_name: str,
    *,
    timeout_ms: int = 5000,
) -> MongoConnection:
    """Create one sync client, ping it, and return selected database."""

    try:
        client = MongoClient(
            uri,
            serverSelectionTimeoutMS=timeout_ms,
            maxPoolSize=50,
            minPoolSize=0,
            maxConnecting=2,
            retryWrites=True,
            w="majority",
        )
    except (ConfigurationError, InvalidURI) as exc:
        raise MongoConfigurationError("Invalid MongoDB connection") from exc
    try:
        client.admin.command("ping")
    except (ConfigurationError, InvalidURI, OperationFailure) as exc:
        client.close()
        raise MongoConfigurationError("MongoDB rejected connection") from exc
    except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
        client.close()
        raise MongoUnavailableError("MongoDB is unreachable") from exc
    return MongoConnection(client, client[db_name], db_name)
