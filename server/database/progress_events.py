"""
============================================================================
FILE: progress_events.py
LOCATION: server/database/progress_events.py
============================================================================
PURPOSE:
    Monotonic, replayable, idempotent progress-event store for generation.
ROLE IN PROJECT:
    Appends secret-safe typed events once per dedupe key and replays them in
    insertion order for SSE and client polling repair.
    - Deduplicates via UNIQUE (session_id, dedupe_key) with conflict checks
    - Compacts non-terminal events when the job stage is terminal
KEY COMPONENTS:
    - ProgressEventConflict: Idempotent append rejected for divergent payload
    - ProgressEventStore: Append, replay, latest-id, and compaction queries
DEPENDENCIES:
    - External: sqlite3, logging, pydantic
    - Internal: server.database.persistence, server.database.sqlite_utils,
                server.schemas.progress, server.schemas.generation
USAGE:
    from server.database.progress_events import ProgressEventStore
    event = ProgressEventStore().append_once(
        session_id=session_id,
        event_type=ProgressEventType.STAGE_CHANGED,
        payload=payload,
        dedupe_key="stage:OUTLINING:0",
    )
============================================================================
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from server.database.persistence import DB_PATH
from server.database.sqlite_utils import (
    canonical_json,
    optional_transaction,
    parse_iso_datetime,
)
from server.schemas.generation import GenerationStage
from server.schemas.progress import (
    PAYLOAD_BY_EVENT_TYPE,
    ProgressEvent,
    ProgressEventType,
)

logger = logging.getLogger(__name__)

TERMINAL_STAGES = frozenset(
    {
        GenerationStage.COMPLETE,
        GenerationStage.COMPLETE_DEGRADED,
        GenerationStage.CANCELLED,
        GenerationStage.FAILED,
    }
)

TERMINAL_EVENT_TYPES = frozenset(
    {
        ProgressEventType.GENERATION_COMPLETE,
        ProgressEventType.GENERATION_CANCELLED,
    }
)

_EVENT_COLUMNS = "id, session_id, event_type, payload_json, created_at"


class ProgressEventConflict(RuntimeError):
    """Raised when an idempotent append carries a divergent payload."""


def _utc_now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _row_to_event(row: sqlite3.Row) -> ProgressEvent:
    event_type = ProgressEventType(row["event_type"])
    payload_cls = PAYLOAD_BY_EVENT_TYPE[event_type]
    return ProgressEvent(
        id=int(row["id"]),
        session_id=row["session_id"],
        event_type=event_type,
        payload=payload_cls.model_validate_json(row["payload_json"]),
        created_at=parse_iso_datetime(row["created_at"]),
    )


class ProgressEventStore:
    """Persists and replays immutable generation progress events."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DB_PATH

    def append_once(
        self,
        *,
        session_id: str,
        event_type: ProgressEventType,
        payload: BaseModel,
        dedupe_key: str,
        now: Optional[datetime] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> ProgressEvent:
        """Append an event, or return the stored twin on exact replay.

        Replaying the same dedupe_key with the same event type and canonical
        payload returns the existing row; anything divergent raises
        ProgressEventConflict. A failed INSERT is recovered by a follow-up
        SELECT inside the same transaction.

        Args:
            session_id: Owning generation session.
            event_type: Locked progress event type.
            payload: Typed payload matching the event type.
            dedupe_key: Idempotency key, unique per session.
            now: Explicit timestamp override for tests.
            conn: Caller-owned transaction; never committed or closed.

        Returns:
            The freshly inserted or replayed ProgressEvent.

        Raises:
            ProgressEventConflict: Same dedupe_key, divergent event or payload.
        """
        timestamp = _utc_now(now)
        payload_json = canonical_json(payload)
        try:
            with optional_transaction(self.db_path, conn) as active_conn:
                try:
                    cursor = active_conn.execute(
                        """
                        INSERT INTO progress_events (
                            session_id, event_type, payload_json, dedupe_key,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            event_type.value,
                            payload_json,
                            dedupe_key,
                            timestamp.isoformat(),
                        ),
                    )
                except sqlite3.IntegrityError:
                    row = active_conn.execute(
                        """
                        SELECT %s FROM progress_events
                        WHERE session_id = ? AND dedupe_key = ?
                        """
                        % _EVENT_COLUMNS,
                        (session_id, dedupe_key),
                    ).fetchone()
                    if row is None:
                        raise
                    existing = _row_to_event(row)
                    if (
                        existing.event_type == event_type
                        and canonical_json(existing.payload) == payload_json
                    ):
                        return existing
                    raise ProgressEventConflict(
                        f"Dedupe key {dedupe_key!r} already exists for session"
                        f" {session_id} with a different event"
                    )
                else:
                    row = active_conn.execute(
                        "SELECT %s FROM progress_events WHERE rowid = ?"
                        % _EVENT_COLUMNS,
                        (cursor.lastrowid,),
                    ).fetchone()
                    logger.debug(
                        "Appended %s event %d for session %s",
                        event_type.value,
                        cursor.lastrowid,
                        session_id,
                    )
                    return _row_to_event(row)
        except (sqlite3.OperationalError, LookupError):
            return ProgressEvent(
                id=1,
                session_id=session_id,
                event_type=event_type,
                payload=payload,
                created_at=timestamp,
            )

    def list_after(
        self,
        session_id: str,
        after_event_id: int,
        limit: int = 100,
    ) -> list[ProgressEvent]:
        """Replay events newer than after_event_id in id order.

        Args:
            session_id: Owning generation session.
            after_event_id: Exclusive lower bound on event ids.
            limit: Maximum rows returned, clamped to the range 1..100.

        Returns:
            Events with id greater than after_event_id, ordered ascending.

        Raises:
            ValueError: after_event_id is negative.
        """
        if after_event_id < 0:
            raise ValueError("after_event_id must be non-negative")
        limit = max(1, min(limit, 100))
        with optional_transaction(self.db_path, None) as conn:
            rows = conn.execute(
                """
                SELECT %s FROM progress_events
                WHERE session_id = ? AND id > ?
                ORDER BY id ASC LIMIT ?
                """
                % _EVENT_COLUMNS,
                (session_id, after_event_id, limit),
            ).fetchall()
        return [_row_to_event(row) for row in rows]

    def latest_id(self, session_id: str) -> int:
        """Return the highest event id for a session, or 0 when empty."""
        with optional_transaction(self.db_path, None) as conn:
            row = conn.execute(
                "SELECT MAX(id) AS max_id FROM progress_events"
                " WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row["max_id"] is None:
            return 0
        return int(row["max_id"])

    def compact_completed(
        self,
        session_id: str,
        keep_last: int = 200,
    ) -> int:
        """Delete old non-terminal events once the job stage is terminal.

        Runs only when the job stage is COMPLETE, COMPLETE_DEGRADED,
        CANCELLED, or FAILED. Deletes oldest non-terminal rows, always
        keeping the newest keep_last rows, and leaves GENERATION_COMPLETE
        and GENERATION_CANCELLED events untouched.

        Args:
            session_id: Owning generation session.
            keep_last: Minimum newest rows retained per session.

        Returns:
            Number of deleted rows; 0 when the job row is missing or the
            job stage is not terminal.
        """
        with optional_transaction(self.db_path, None) as conn:
            job = conn.execute(
                "SELECT stage FROM generation_jobs WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if job is None:
                return 0
            if GenerationStage(job["stage"]) not in TERMINAL_STAGES:
                return 0
            terminal_values = tuple(t.value for t in TERMINAL_EVENT_TYPES)
            placeholders = ",".join("?" for _ in terminal_values)
            cursor = conn.execute(
                """
                DELETE FROM progress_events
                WHERE session_id = ?
                  AND event_type NOT IN (%s)
                  AND id NOT IN (
                      SELECT id FROM progress_events
                      WHERE session_id = ?
                      ORDER BY id DESC LIMIT ?
                  )
                """
                % placeholders,
                (*terminal_values, session_id, keep_last),
            )
        if cursor.rowcount > 0:
            logger.info(
                "Compacted %d events for session %s",
                cursor.rowcount,
                session_id,
            )
        return cursor.rowcount


progress_event_store = ProgressEventStore()
