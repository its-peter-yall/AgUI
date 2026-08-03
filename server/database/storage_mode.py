"""
============================================================================
FILE: storage_mode.py
LOCATION: server/database/storage_mode.py
============================================================================
PURPOSE:
    Deployment and storage backend enums plus process-wide StorageContext.
ROLE IN PROJECT:
    Foundation for optional MongoDB Atlas storage (Approach A repository swap).
    - DeploymentMode controls mutable storage endpoints (local vs cloud)
    - StorageBackend tracks active persistence (sqlite vs mongo)
    - StorageContext owns Mongo connection lifecycle in process memory
DEPENDENCIES:
    - External: None (stdlib only for enums; context adds sqlite3/threading)
    - Internal: server.database.mongo_client (when StorageContext is used)
USAGE:
    from server.database.storage_mode import DeploymentMode, StorageBackend
============================================================================
"""
from __future__ import annotations

from enum import Enum


class DeploymentMode(str, Enum):
    """Server deployment policy controlling mutable storage endpoints."""

    LOCAL = "local"
    CLOUD = "cloud"


class StorageBackend(str, Enum):
    """Active application persistence backend."""

    SQLITE = "sqlite"
    MONGO = "mongo"
