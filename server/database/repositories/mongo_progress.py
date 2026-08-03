"""
============================================================================
FILE: mongo_progress.py
LOCATION: server/database/repositories/mongo_progress.py
============================================================================
PURPOSE:
    Synchronous Mongo implementation of ProgressEventRepository with a
    monotonic counter document and dedupe-key idempotency.
ROLE IN PROJECT:
    Phase 3B Atlas adapter for replayable generation progress events.
DEPENDENCIES:
    - External: pymongo, pydantic
    - Internal: server.database.progress_events (exceptions/constants),
                server.database.repositories.mongo_common,
                server.database.sqlite_utils,
                server.schemas.progress, server.schemas.generation
USAGE:
    repo = MongoProgressEventRepository(database)
    event = repo.append_once(...)
============================================================================
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from server.database.progress_events import (
    TERMINAL_EVENT_TYPES,
    TERMINAL_STAGES,
    ProgressEventConflict,
    ProgressEventPersistError,
)
from server.database.repositories.mongo_common import (
    model_payload,
    utc_iso,
)
from server.database.sqlite_utils import canonical_json, parse_iso_datetime
from server.schemas.generation import GenerationStage
from server.schemas.progress import (
    PAYLOAD_BY_EVENT_TYPE,
    ProgressEvent,
    ProgressEventType,
)

logger = logging.getLogger(__name__)


def _utc_now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


class MongoProgressEventRepository:
    """Mongo progress events with integer IDs via storage_counters."""

    def __init__(self, database: Any) -> None:
        self._db = database
        self._events = database["progress_events"]
        self._counters = database["storage_counters"]
        self._jobs = database["generation_jobs"]

    def _event(self, document: dict[str, Any]) -> ProgressEvent:
        event_type = ProgressEventType(document["event_type"])
        payload_cls = PAYLOAD_BY_EVENT_TYPE[event_type]
        return ProgressEvent(
            id=int(document["_id"]),
            session_id=document["session_id"],
            event_type=event_type,
            payload=payload_cls.model_validate(document["payload"]),
            created_at=parse_iso_datetime(document["created_at"]),
        )

    def append_once(
        self,
        *,
        session_id: str,
        event_type: ProgressEventType,
        payload: BaseModel,
        dedupe_key: str,
        now: Optional[datetime] = None,
    ) -> ProgressEvent:
        timestamp = _utc_now(now)
        payload_doc = model_payload(payload)
        payload_json = canonical_json(payload)
        try:
            counter = self._counters.find_one_and_update(
                {"_id": "progress_events"},
                {"$inc": {"value": 1}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            event_id = int(counter["value"])
            document = {
                "_id": event_id,
                "session_id": session_id,
                "event_type": event_type.value,
                "payload": payload_doc,
                "dedupe_key": dedupe_key,
                "created_at": timestamp.isoformat(),
            }
            try:
                self._events.insert_one(document)
            except DuplicateKeyError:
                existing_doc = self._events.find_one(
                    {
                        "session_id": session_id,
                        "dedupe_key": dedupe_key,
                    }
                )
                if existing_doc is None:
                    raise
                existing = self._event(existing_doc)
                if (
                    existing.event_type == event_type
                    and canonical_json(existing.payload) == payload_json
                ):
                    return existing
                raise ProgressEventConflict(
                    f"Dedupe key {dedupe_key!r} already exists for session"
                    f" {session_id} with a different event"
                )
            logger.debug(
                "Appended %s event %d for session %s",
                event_type.value,
                event_id,
                session_id,
            )
            return self._event(document)
        except ProgressEventConflict:
            raise
        except Exception as exc:
            raise ProgressEventPersistError(
                f"Failed to append progress event for session {session_id}"
            ) from exc

    def list_after(
        self,
        session_id: str,
        after_event_id: int,
        limit: int = 100,
    ) -> list[ProgressEvent]:
        if after_event_id < 0:
            raise ValueError("after_event_id must be non-negative")
        safe_limit = max(1, min(limit, 100))
        cursor = (
            self._events.find(
                {
                    "session_id": session_id,
                    "_id": {"$gt": after_event_id},
                }
            )
            .sort("_id", ASCENDING)
            .limit(safe_limit)
        )
        return [self._event(item) for item in cursor]

    def latest_id(self, session_id: str) -> int:
        document = self._events.find_one(
            {"session_id": session_id},
            sort=[("_id", DESCENDING)],
        )
        if document is None:
            return 0
        return int(document["_id"])

    def compact_completed(
        self,
        session_id: str,
        keep_last: int = 200,
    ) -> int:
        job = self._jobs.find_one(
            {"session_id": session_id},
            {"stage": 1},
        )
        if job is None:
            return 0
        if GenerationStage(job["stage"]) not in TERMINAL_STAGES:
            return 0
        newest = list(
            self._events.find(
                {"session_id": session_id},
                {"_id": 1},
            )
            .sort("_id", DESCENDING)
            .limit(keep_last)
        )
        keep_ids = [item["_id"] for item in newest]
        terminal_values = [t.value for t in TERMINAL_EVENT_TYPES]
        query: dict[str, Any] = {
            "session_id": session_id,
            "event_type": {"$nin": terminal_values},
        }
        if keep_ids:
            query["_id"] = {"$nin": keep_ids}
        result = self._events.delete_many(query)
        deleted = int(result.deleted_count)
        if deleted > 0:
            logger.info(
                "Compacted %d events for session %s",
                deleted,
                session_id,
            )
        return deleted
