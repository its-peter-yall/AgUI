"""
============================================================================
FILE: mongo_common.py
LOCATION: server/database/repositories/mongo_common.py
============================================================================
PURPOSE:
    Shared Mongo document codecs for ID mapping, timestamps, and Pydantic
    payload conversion to BSON-safe native dicts.
ROLE IN PROJECT:
    Foundation helpers for Phase 3 Mongo repository adapters.
    - Map Mongo `_id` to API `id` without mutating source documents
    - Produce timezone-aware ISO timestamps at API boundaries
    - Dump Pydantic models to native BSON shapes (not JSON strings)
DEPENDENCIES:
    - External: pydantic
    - Internal: None
USAGE:
    from server.database.repositories.mongo_common import (
        document_to_row,
        model_payload,
        utc_iso,
    )
============================================================================
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel


def utc_iso(now: Optional[datetime] = None) -> str:
    """Return stable timezone-aware ISO timestamp."""

    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def document_to_row(
    document: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Map Mongo `_id` to existing API/store `id` key."""

    if document is None:
        return None
    row = dict(document)
    identifier = row.pop("_id", None)
    if identifier is not None:
        row["id"] = identifier
    return row


def model_payload(value: BaseModel) -> dict[str, Any]:
    """Convert Pydantic value to BSON-safe native dict/list primitives."""

    return value.model_dump(mode="json", exclude_none=True)
