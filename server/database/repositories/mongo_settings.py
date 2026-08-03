"""
============================================================================
FILE: mongo_settings.py
LOCATION: server/database/repositories/mongo_settings.py
============================================================================
PURPOSE:
    Synchronous Mongo AppSettingsRepository storing provider and web-search
    settings as two fixed-ID plaintext JSON documents.
ROLE IN PROJECT:
    Phase 3B Atlas adapter for roaming credentials when cloud mode active.
    Never logs payloads (API keys plaintext by product decision).
DEPENDENCIES:
    - External: None (duck-typed Database)
    - Internal: server.database.repositories.mongo_common
USAGE:
    repo = MongoAppSettingsRepository(database)
    repo.put_provider_settings(payload)
============================================================================
"""
from __future__ import annotations

from typing import Any, Optional

from server.database.repositories.mongo_common import utc_iso


class MongoAppSettingsRepository:
    """Store roaming provider/search settings as plaintext JSON documents."""

    def __init__(self, database: Any) -> None:
        self._settings = database["app_settings"]

    def _get(self, identifier: str) -> Optional[dict[str, Any]]:
        document = self._settings.find_one({"_id": identifier})
        return dict(document["payload"]) if document is not None else None

    def _put(self, identifier: str, payload: dict[str, Any]) -> None:
        self._settings.update_one(
            {"_id": identifier},
            {"$set": {"payload": payload, "updated_at": utc_iso()}},
            upsert=True,
        )

    def get_provider_settings(self) -> Optional[dict[str, Any]]:
        return self._get("provider_settings")

    def put_provider_settings(self, payload: dict[str, Any]) -> None:
        self._put("provider_settings", payload)

    def get_web_search_settings(self) -> Optional[dict[str, Any]]:
        return self._get("web_search_settings")

    def put_web_search_settings(self, payload: dict[str, Any]) -> None:
        self._put("web_search_settings", payload)
