"""
============================================================================
FILE: generation_jobs.py
LOCATION: server/database/generation_jobs.py
============================================================================
PURPOSE:
    Durable generation session shells, stage transitions, cursors, counts,
    warnings, cancellation, and fenced per-session worker locks.
ROLE IN PROJECT:
    Owns the generation job lifecycle so workers can pause, cancel, and
    resume without touching LearningManager.
    - Enforces an explicit stage transition matrix
    - Fences workers with owner/version/expiry conditional updates
KEY COMPONENTS:
    - InvalidGenerationTransition: Illegal stage movement
    - GenerationLockConflict: Stale or fenced worker lock
    - GenerationJobStore: All job lifecycle persistence
DEPENDENCIES:
    - External: sqlite3, uuid, logging, pydantic
    - Internal: server.database.persistence, server.database.sqlite_utils,
                server.schemas.generation
USAGE:
    from server.database.generation_jobs import GenerationJobStore
    store = GenerationJobStore()
    session, job = store.create_session_shell_and_job(query="...", mode="auto")
============================================================================
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from server.database.persistence import DB_PATH
from server.database.sqlite_utils import (
    canonical_json,
    optional_transaction,
    parse_iso_datetime,
)
from server.schemas.generation import (
    GenerationCounts,
    GenerationCursor,
    GenerationJobRecord,
    GenerationLock,
    GenerationStage,
    GenerationWarning,
    GroundingStatus,
)

logger = logging.getLogger(__name__)

TERMINAL_STAGES = frozenset(
    {
        GenerationStage.COMPLETE,
        GenerationStage.COMPLETE_DEGRADED,
        GenerationStage.FAILED,
    }
)

ALLOWED_STAGE_TRANSITIONS: dict[GenerationStage, frozenset[GenerationStage]] = {
    GenerationStage.INITIALIZING: frozenset(
        {
            GenerationStage.RESEARCHING,
            GenerationStage.OUTLINING,
            GenerationStage.PLANNING_PREVIEW,
            GenerationStage.FAILED,
        }
    ),
    GenerationStage.RESEARCHING: frozenset(
        {
            GenerationStage.OUTLINING,
            GenerationStage.PLANNING_PREVIEW,
            GenerationStage.FAILED,
        }
    ),
    GenerationStage.OUTLINING: frozenset(
        {
            GenerationStage.PLANNING_PREVIEW,
            GenerationStage.GENERATING_PREVIEW,
            GenerationStage.FAILED,
        }
    ),
    GenerationStage.PLANNING_PREVIEW: frozenset(
        {
            GenerationStage.GENERATING_PREVIEW,
            GenerationStage.PLANNING_BATCH,
            GenerationStage.FAILED,
        }
    ),
    GenerationStage.GENERATING_PREVIEW: frozenset(
        {
            GenerationStage.PLANNING_BATCH,
            GenerationStage.COMPLETE,
            GenerationStage.COMPLETE_DEGRADED,
            GenerationStage.FAILED,
        }
    ),
    GenerationStage.PLANNING_BATCH: frozenset(
        {
            GenerationStage.GENERATING_BATCH,
            GenerationStage.FAILED,
        }
    ),
    GenerationStage.GENERATING_BATCH: frozenset(
        {
            GenerationStage.PLANNING_BATCH,
            GenerationStage.COMPLETE,
            GenerationStage.COMPLETE_DEGRADED,
            GenerationStage.FAILED,
        }
    ),
    GenerationStage.PAUSED: frozenset(),
    GenerationStage.CANCELLED: frozenset(),
    GenerationStage.COMPLETE: frozenset(),
    GenerationStage.COMPLETE_DEGRADED: frozenset(),
    GenerationStage.FAILED: frozenset(),
}

JOB_ROW_COLUMNS = (
    "id, session_id, thread_id, stage, resume_stage, web_search_requested,"
    " grounding_status, cursor_json, counts_json, warnings_json,"
    " cancel_requested, lock_owner, lock_version, lock_expires_at,"
    " created_at, updated_at"
)


class InvalidGenerationTransition(RuntimeError):
    """Raised when a stage change violates the transition matrix."""


class GenerationLockConflict(RuntimeError):
    """Raised when a worker mutation carries a stale or expired lock."""


class GenerationJobNotFound(LookupError):
    """Raised when a generation job row does not exist."""


def _utc_now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _row_to_record(row: sqlite3.Row) -> GenerationJobRecord:
    return GenerationJobRecord(
        id=row["id"],
        session_id=row["session_id"],
        thread_id=row["thread_id"],
        stage=GenerationStage(row["stage"]),
        resume_stage=(
            GenerationStage(row["resume_stage"])
            if row["resume_stage"] is not None
            else None
        ),
        web_search_requested=bool(row["web_search_requested"]),
        grounding_status=GroundingStatus(row["grounding_status"]),
        cursor=GenerationCursor.model_validate_json(row["cursor_json"]),
        counts=GenerationCounts.model_validate_json(row["counts_json"]),
        warnings=[
            GenerationWarning.model_validate(item)
            for item in json.loads(row["warnings_json"])
        ],
        cancel_requested=bool(row["cancel_requested"]),
        lock_owner=row["lock_owner"],
        lock_version=int(row["lock_version"]),
        lock_expires_at=parse_iso_datetime(row["lock_expires_at"]),
        created_at=parse_iso_datetime(row["created_at"]),
        updated_at=parse_iso_datetime(row["updated_at"]),
    )


class GenerationJobStore:
    """Persists generation shell and job lifecycle state."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DB_PATH

    def create_session_shell_and_job(
        self,
        *,
        query: str,
        user_id: Optional[str],
        mode: str,
        web_search_requested: bool,
        now: Optional[datetime] = None,
    ) -> tuple[dict[str, Any], GenerationJobRecord]:
        """Create a learning session shell and its job atomically.

        Never calls LearningManager; inserts rows directly so shell and job
        commit together.
        """
        timestamp = _utc_now(now)
        session_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        thread_id = f"gen-{session_id}"
        grounding_status = (
            GroundingStatus.PENDING if web_search_requested else GroundingStatus.DISABLED
        )
        now_iso = timestamp.isoformat()

        with optional_transaction(self.db_path, None) as conn:
            conn.execute(
                """
                INSERT INTO learning_sessions (
                    id, user_id, query, course_title, mode, resolved_mode,
                    title_finalized, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    query,
                    query.strip(),
                    mode,
                    None,
                    now_iso,
                    now_iso,
                ),
            )
            conn.execute(
                """
                INSERT INTO generation_jobs (
                    id, session_id, thread_id, stage, resume_stage,
                    web_search_requested, grounding_status, cursor_json,
                    counts_json, warnings_json, cancel_requested,
                    lock_owner, lock_version, lock_expires_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, '[]', 0, NULL, 0, NULL, ?, ?)
                """,
                (
                    job_id,
                    session_id,
                    thread_id,
                    GenerationStage.INITIALIZING.value,
                    int(web_search_requested),
                    grounding_status.value,
                    canonical_json(GenerationCursor()),
                    canonical_json(GenerationCounts()),
                    now_iso,
                    now_iso,
                ),
            )

        session: dict[str, Any] = {
            "id": session_id,
            "user_id": user_id,
            "query": query,
            "course_title": query.strip(),
            "mode": mode,
            "resolved_mode": None,
            "title_finalized": 0,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        job = self.get_by_session(session_id)
        if job is None:
            raise GenerationJobNotFound(session_id)
        logger.info("Created generation shell %s for session %s", job_id, session_id)
        return session, job

    def get_by_session(
        self, session_id: str, conn: Optional[sqlite3.Connection] = None
    ) -> Optional[GenerationJobRecord]:
        with optional_transaction(self.db_path, conn) as active_conn:
            row = active_conn.execute(
                f"SELECT {JOB_ROW_COLUMNS} FROM generation_jobs"
                " WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)

    def _load_stage(
        self, conn: sqlite3.Connection, session_id: str
    ) -> GenerationStage:
        row = conn.execute(
            "SELECT stage FROM generation_jobs WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise GenerationJobNotFound(session_id)
        return GenerationStage(row["stage"])

    def _check_lock_holds(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        lock: GenerationLock,
        now: datetime,
    ) -> bool:
        row = conn.execute(
            """
            SELECT lock_owner, lock_version, lock_expires_at
            FROM generation_jobs WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            raise GenerationJobNotFound(session_id)
        if row["lock_owner"] != lock.owner or int(row["lock_version"]) != lock.version:
            return False
        if row["lock_expires_at"] is None:
            return False
        return row["lock_expires_at"] > now.isoformat()

    def transition_stage(
        self,
        *,
        session_id: str,
        target_stage: GenerationStage,
        lock: GenerationLock,
        cursor: Optional[GenerationCursor] = None,
        counts: Optional[GenerationCounts] = None,
        warnings: Optional[list[GenerationWarning]] = None,
        grounding_status: Optional[GroundingStatus] = None,
        now: Optional[datetime] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> GenerationJobRecord:
        """Move a job to target_stage with an owned lock; same-stage is idempotent."""
        timestamp = _utc_now(now)
        with optional_transaction(self.db_path, conn) as active_conn:
            current = self._load_stage(active_conn, session_id)
            if target_stage != current:
                if target_stage not in ALLOWED_STAGE_TRANSITIONS[current]:
                    raise InvalidGenerationTransition(
                        f"Cannot transition from {current.value} to"
                        f" {target_stage.value}"
                    )
            if not self._check_lock_holds(active_conn, session_id, lock, timestamp):
                raise GenerationLockConflict(
                    f"Lock for session {session_id} is stale or fenced"
                )
            cursor_json = (
                canonical_json(cursor) if cursor is not None else None
            )
            counts_json = (
                canonical_json(counts) if counts is not None else None
            )
            warnings_json = (
                canonical_json(warnings) if warnings is not None else None
            )
            active_conn.execute(
                """
                UPDATE generation_jobs
                SET stage = ?,
                    cursor_json = COALESCE(?, cursor_json),
                    counts_json = COALESCE(?, counts_json),
                    warnings_json = COALESCE(?, warnings_json),
                    grounding_status = COALESCE(?, grounding_status),
                    updated_at = ?
                WHERE session_id = ?
                """,
                (
                    target_stage.value,
                    cursor_json,
                    counts_json,
                    warnings_json,
                    (
                        grounding_status.value
                        if grounding_status is not None
                        else None
                    ),
                    timestamp.isoformat(),
                    session_id,
                ),
            )
            return _row_to_record(
                active_conn.execute(
                    f"SELECT {JOB_ROW_COLUMNS} FROM generation_jobs"
                    " WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            )

    def update_cursor(
        self,
        *,
        session_id: str,
        lock: GenerationLock,
        cursor: Optional[GenerationCursor] = None,
        counts: Optional[GenerationCounts] = None,
        warnings: Optional[list[GenerationWarning]] = None,
        grounding_status: Optional[GroundingStatus] = None,
        now: Optional[datetime] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> GenerationJobRecord:
        """Persist cursor progress without changing the stage."""
        timestamp = _utc_now(now)
        with optional_transaction(self.db_path, conn) as active_conn:
            self._load_stage(active_conn, session_id)
            if not self._check_lock_holds(active_conn, session_id, lock, timestamp):
                raise GenerationLockConflict(
                    f"Lock for session {session_id} is stale or fenced"
                )
            active_conn.execute(
                """
                UPDATE generation_jobs
                SET cursor_json = COALESCE(?, cursor_json),
                    counts_json = COALESCE(?, counts_json),
                    warnings_json = COALESCE(?, warnings_json),
                    grounding_status = COALESCE(?, grounding_status),
                    updated_at = ?
                WHERE session_id = ?
                """,
                (
                    canonical_json(cursor) if cursor is not None else None,
                    canonical_json(counts) if counts is not None else None,
                    canonical_json(warnings) if warnings is not None else None,
                    (
                        grounding_status.value
                        if grounding_status is not None
                        else None
                    ),
                    timestamp.isoformat(),
                    session_id,
                ),
            )
            return _row_to_record(
                active_conn.execute(
                    f"SELECT {JOB_ROW_COLUMNS} FROM generation_jobs"
                    " WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            )

    def request_cancel(
        self,
        session_id: str,
        now: Optional[datetime] = None,
    ) -> GenerationJobRecord:
        """Set the cancel flag; requires no worker lock."""
        timestamp = _utc_now(now)
        with optional_transaction(self.db_path, None) as conn:
            self._load_stage(conn, session_id)
            conn.execute(
                """
                UPDATE generation_jobs
                SET cancel_requested = 1, updated_at = ?
                WHERE session_id = ?
                """,
                (timestamp.isoformat(), session_id),
            )
            return _row_to_record(
                conn.execute(
                    f"SELECT {JOB_ROW_COLUMNS} FROM generation_jobs"
                    " WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            )

    def is_cancel_requested(self, session_id: str) -> bool:
        with optional_transaction(self.db_path, None) as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM generation_jobs WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise GenerationJobNotFound(session_id)
        return bool(row["cancel_requested"])

    def mark_paused(
        self,
        *,
        session_id: str,
        lock: GenerationLock,
        now: Optional[datetime] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> GenerationJobRecord:
        """Pause an active job, saving its stage for later resume."""
        timestamp = _utc_now(now)
        with optional_transaction(self.db_path, conn) as active_conn:
            current = self._load_stage(active_conn, session_id)
            if current in TERMINAL_STAGES or current == GenerationStage.CANCELLED:
                raise InvalidGenerationTransition(
                    f"Cannot pause job in stage {current.value}"
                )
            if not self._check_lock_holds(active_conn, session_id, lock, timestamp):
                raise GenerationLockConflict(
                    f"Lock for session {session_id} is stale or fenced"
                )
            active_conn.execute(
                """
                UPDATE generation_jobs
                SET stage = ?,
                    resume_stage = CASE
                        WHEN stage = 'PAUSED' THEN resume_stage
                        ELSE stage
                    END,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (
                    GenerationStage.PAUSED.value,
                    timestamp.isoformat(),
                    session_id,
                ),
            )
            return _row_to_record(
                active_conn.execute(
                    f"SELECT {JOB_ROW_COLUMNS} FROM generation_jobs"
                    " WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            )

    def mark_cancelled(
        self,
        *,
        session_id: str,
        lock: GenerationLock,
        now: Optional[datetime] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> GenerationJobRecord:
        """Cancel an active job, retaining its stage for later resume."""
        timestamp = _utc_now(now)
        with optional_transaction(self.db_path, conn) as active_conn:
            current = self._load_stage(active_conn, session_id)
            if current in TERMINAL_STAGES:
                raise InvalidGenerationTransition(
                    f"Cannot cancel job in stage {current.value}"
                )
            if not self._check_lock_holds(active_conn, session_id, lock, timestamp):
                raise GenerationLockConflict(
                    f"Lock for session {session_id} is stale or fenced"
                )
            active_conn.execute(
                """
                UPDATE generation_jobs
                SET stage = ?,
                    resume_stage = CASE
                        WHEN stage = 'CANCELLED' THEN resume_stage
                        ELSE stage
                    END,
                    cancel_requested = 1,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (
                    GenerationStage.CANCELLED.value,
                    timestamp.isoformat(),
                    session_id,
                ),
            )
            return _row_to_record(
                active_conn.execute(
                    f"SELECT {JOB_ROW_COLUMNS} FROM generation_jobs"
                    " WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            )

    def prepare_resume(
        self,
        session_id: str,
        now: Optional[datetime] = None,
    ) -> GenerationJobRecord:
        """Restore a paused or cancelled job to its saved stage."""
        timestamp = _utc_now(now)
        with optional_transaction(self.db_path, None) as conn:
            row = conn.execute(
                "SELECT stage, resume_stage FROM generation_jobs"
                " WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise GenerationJobNotFound(session_id)
            current = GenerationStage(row["stage"])
            if current not in {
                GenerationStage.PAUSED,
                GenerationStage.CANCELLED,
            }:
                raise InvalidGenerationTransition(
                    f"Cannot resume job in stage {current.value}"
                )
            if row["resume_stage"] is None:
                raise InvalidGenerationTransition(
                    "Resume stage missing for job"
                )
            conn.execute(
                """
                UPDATE generation_jobs
                SET stage = ?, resume_stage = NULL, cancel_requested = 0,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (
                    row["resume_stage"],
                    timestamp.isoformat(),
                    session_id,
                ),
            )
            return _row_to_record(
                conn.execute(
                    f"SELECT {JOB_ROW_COLUMNS} FROM generation_jobs"
                    " WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            )

    def try_acquire_lock(
        self,
        *,
        session_id: str,
        owner: str,
        ttl_seconds: int,
        now: Optional[datetime] = None,
    ) -> Optional[GenerationLock]:
        """Acquire the per-session fence if no other live worker holds it."""
        timestamp = _utc_now(now)
        expires_at = timestamp + timedelta(seconds=ttl_seconds)
        with optional_transaction(self.db_path, None) as conn:
            row = conn.execute(
                """
                SELECT lock_owner, lock_version, lock_expires_at
                FROM generation_jobs WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            if (
                row["lock_owner"] is not None
                and row["lock_owner"] != owner
                and row["lock_expires_at"] is not None
                and row["lock_expires_at"] > timestamp.isoformat()
            ):
                return None
            new_version = int(row["lock_version"] or 0) + 1
            conn.execute(
                """
                UPDATE generation_jobs
                SET lock_owner = ?, lock_version = ?, lock_expires_at = ?,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (
                    owner,
                    new_version,
                    expires_at.isoformat(),
                    timestamp.isoformat(),
                    session_id,
                ),
            )
        return GenerationLock(
            session_id=session_id,
            owner=owner,
            version=new_version,
            expires_at=expires_at,
        )

    def renew_lock(
        self,
        *,
        lock: GenerationLock,
        ttl_seconds: int,
        now: Optional[datetime] = None,
    ) -> GenerationLock:
        """Extend a lock expiry; raises when the lock is fenced or expired."""
        timestamp = _utc_now(now)
        expires_at = timestamp + timedelta(seconds=ttl_seconds)
        with optional_transaction(self.db_path, None) as conn:
            cursor = conn.execute(
                """
                UPDATE generation_jobs
                SET lock_expires_at = ?, updated_at = ?
                WHERE session_id = ?
                  AND lock_owner = ? AND lock_version = ?
                  AND lock_expires_at > ?
                """,
                (
                    expires_at.isoformat(),
                    timestamp.isoformat(),
                    lock.session_id,
                    lock.owner,
                    lock.version,
                    timestamp.isoformat(),
                ),
            )
            if cursor.rowcount == 0:
                raise GenerationLockConflict(
                    f"Lock for owner {lock.owner} is stale or fenced"
                )
        return GenerationLock(
            session_id=lock.session_id,
            owner=lock.owner,
            version=lock.version,
            expires_at=expires_at,
        )

    def release_lock(
        self,
        *,
        lock: GenerationLock,
    ) -> None:
        """Release the fence; idempotent when the lock is already gone."""
        with optional_transaction(self.db_path, None) as conn:
            conn.execute(
                """
                UPDATE generation_jobs
                SET lock_owner = NULL, lock_expires_at = NULL
                WHERE session_id = ?
                  AND lock_owner = ? AND lock_version = ?
                """,
                (lock.session_id, lock.owner, lock.version),
            )

    def mark_orphaned_jobs_paused(
        self,
        now: Optional[datetime] = None,
    ) -> list[str]:
        """Pause jobs whose worker lock is absent or expired at startup."""
        timestamp = _utc_now(now)
        active_values = tuple(
            stage.value
            for stage in TERMINAL_STAGES
            | {GenerationStage.PAUSED, GenerationStage.CANCELLED}
        )
        placeholders = ",".join("?" for _ in active_values)
        with optional_transaction(self.db_path, None) as conn:
            rows = conn.execute(
                f"""
                SELECT id, session_id, stage FROM generation_jobs
                WHERE stage NOT IN ({placeholders})
                  AND (lock_owner IS NULL
                       OR lock_expires_at IS NULL
                       OR lock_expires_at <= ?)
                """,
                (*active_values, timestamp.isoformat()),
            ).fetchall()
            paused: list[str] = []
            for row in rows:
                conn.execute(
                    """
                    UPDATE generation_jobs
                    SET stage = 'PAUSED', resume_stage = ?,
                        cancel_requested = 0, lock_owner = NULL,
                        lock_expires_at = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (row["stage"], timestamp.isoformat(), row["id"]),
                )
                paused.append(row["session_id"])
        if paused:
            logger.info("Paused %d orphaned generation jobs", len(paused))
        return paused

    def update_stage(
        self,
        session_id: str,
        stage: GenerationStage,
    ) -> None:
        """Update job stage without requiring a worker lock."""
        with optional_transaction(self.db_path, None) as conn:
            conn.execute(
                """
                UPDATE generation_jobs
                SET stage = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (stage.value, _utc_now(None).isoformat(), session_id),
            )

    def update_progress(
        self,
        session_id: str,
        completed_topics: int,
    ) -> None:
        """Update cursor completed topics for session."""
        with optional_transaction(self.db_path, None) as conn:
            cursor_json = canonical_json(GenerationCursor(completed_topics=completed_topics))
            conn.execute(
                """
                UPDATE generation_jobs
                SET cursor_json = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (cursor_json, _utc_now(None).isoformat(), session_id),
            )


generation_job_store = GenerationJobStore()
