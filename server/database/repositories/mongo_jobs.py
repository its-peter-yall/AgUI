"""
============================================================================
FILE: mongo_jobs.py
LOCATION: server/database/repositories/mongo_jobs.py
============================================================================
PURPOSE:
    Synchronous Mongo implementation of GenerationJobRepository for job
    lifecycle, fenced locks, stages, cursors, counts, and cancellation.
ROLE IN PROJECT:
    Phase 3B Atlas adapter for generation job persistence. Mirrors
    GenerationJobStore public methods using atomic find_one_and_update.
DEPENDENCIES:
    - External: pymongo
    - Internal: server.database.generation_jobs (exceptions/transitions),
                server.database.repositories.mongo_common,
                server.database.sqlite_utils,
                server.schemas.generation
USAGE:
    repo = MongoGenerationJobRepository(database)
    lock = repo.try_acquire_lock(session_id="s1", owner="w", ttl_seconds=45)
============================================================================
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from server.database.generation_jobs import (
    ALLOWED_STAGE_TRANSITIONS,
    TERMINAL_STAGES,
    GenerationJobNotFound,
    GenerationLockConflict,
    InvalidGenerationTransition,
)
from server.database.repositories.mongo_common import (
    model_payload,
    utc_iso,
)
from server.database.sqlite_utils import parse_iso_datetime
from server.schemas.generation import (
    GenerationCounts,
    GenerationCursor,
    GenerationJobPublic,
    GenerationJobRecord,
    GenerationLock,
    GenerationStage,
    GenerationWarning,
    GroundingStatus,
)

logger = logging.getLogger(__name__)


def _utc_now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _record(document: dict[str, Any]) -> GenerationJobRecord:
    resume_raw = document.get("resume_stage")
    return GenerationJobRecord(
        id=document["_id"],
        session_id=document["session_id"],
        thread_id=document["thread_id"],
        stage=document["stage"],
        resume_stage=resume_raw,
        web_search_requested=bool(document["web_search_requested"]),
        grounding_status=document["grounding_status"],
        cursor=document["cursor"],
        counts=document["counts"],
        warnings=document.get("warnings") or [],
        cancel_requested=bool(document["cancel_requested"]),
        lock_owner=document.get("lock_owner"),
        lock_version=int(document["lock_version"]),
        lock_expires_at=parse_iso_datetime(
            document.get("lock_expires_at")
        ),
        created_at=parse_iso_datetime(document["created_at"]),
        updated_at=parse_iso_datetime(document["updated_at"]),
    )


class MongoGenerationJobRepository:
    """Mongo implementation of generation job lifecycle persistence."""

    def __init__(self, database: Any) -> None:
        self._db = database
        self._jobs = database["generation_jobs"]
        self._sessions = database["learning_sessions"]

    def create_session_shell_and_job(
        self,
        *,
        query: str,
        user_id: Optional[str],
        mode: str,
        web_search_requested: bool,
        now: Optional[datetime] = None,
    ) -> tuple[dict[str, Any], GenerationJobRecord]:
        timestamp = _utc_now(now)
        session_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        thread_id = f"gen-{session_id}"
        grounding_status = (
            GroundingStatus.PENDING
            if web_search_requested
            else GroundingStatus.DISABLED
        )
        now_iso = timestamp.isoformat()
        session_document = {
            "_id": session_id,
            "user_id": user_id,
            "query": query,
            "course_title": query.strip(),
            "mode": mode,
            "resolved_mode": None,
            "title_finalized": False,
            "status": "in_progress",
            "progress_percent": 0,
            "completed_at": None,
            "last_active_node_id": None,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        job_document = {
            "_id": job_id,
            "session_id": session_id,
            "thread_id": thread_id,
            "stage": GenerationStage.INITIALIZING.value,
            "resume_stage": None,
            "web_search_requested": bool(web_search_requested),
            "grounding_status": grounding_status.value,
            "cursor": model_payload(GenerationCursor()),
            "counts": model_payload(GenerationCounts()),
            "warnings": [],
            "cancel_requested": False,
            "lock_owner": None,
            "lock_version": 0,
            "lock_expires_at": None,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        try:
            with self._db.client.start_session() as session:
                with session.start_transaction():
                    self._sessions.insert_one(
                        session_document,
                        session=session,
                    )
                    self._jobs.insert_one(job_document, session=session)
        except DuplicateKeyError as exc:
            from server.database.generation_artifacts import (
                GenerationArtifactConflict,
            )

            raise GenerationArtifactConflict(
                "Session or job already exists"
            ) from exc
        session_row = {
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
        logger.info(
            "Created generation shell %s for session %s",
            job_id,
            session_id,
        )
        return session_row, job

    def get_by_session(
        self,
        session_id: str,
    ) -> Optional[GenerationJobRecord]:
        document = self._jobs.find_one({"session_id": session_id})
        if document is None:
            return None
        return _record(document)

    def to_public(
        self,
        job: GenerationJobRecord,
        *,
        last_event_id: Optional[int] = None,
    ) -> GenerationJobPublic:
        event_id = last_event_id
        if event_id is None:
            try:
                from server.database.storage_registry import (
                    progress_event_repository as progress_event_store,
                )

                event_id = progress_event_store.latest_id(job.session_id)
            except Exception:
                event_id = 0
        return GenerationJobPublic.from_job(
            job,
            last_event_id=event_id or 0,
        )

    def to_public_by_session(
        self,
        session_id: str,
    ) -> Optional[GenerationJobPublic]:
        job = self.get_by_session(session_id)
        if job is None:
            return None
        return self.to_public(job)

    def get_public_by_sessions(
        self,
        session_ids: list[str],
    ) -> dict[str, GenerationJobPublic]:
        if not session_ids:
            return {}
        unique_ids = list(dict.fromkeys(session_ids))
        documents = self._jobs.find({"session_id": {"$in": unique_ids}})
        result: dict[str, GenerationJobPublic] = {}
        for document in documents:
            job = _record(document)
            result[job.session_id] = self.to_public(job)
        return result

    def _require_job(self, session_id: str) -> dict[str, Any]:
        document = self._jobs.find_one({"session_id": session_id})
        if document is None:
            raise GenerationJobNotFound(session_id)
        return document

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
    ) -> GenerationJobRecord:
        timestamp = _utc_now(now)
        current_doc = self._require_job(session_id)
        current = GenerationStage(current_doc["stage"])
        if target_stage != current:
            if target_stage not in ALLOWED_STAGE_TRANSITIONS[current]:
                raise InvalidGenerationTransition(
                    f"Cannot transition from {current.value} to"
                    f" {target_stage.value}"
                )
        set_fields: dict[str, Any] = {
            "stage": target_stage.value,
            "updated_at": timestamp.isoformat(),
        }
        if cursor is not None:
            set_fields["cursor"] = model_payload(cursor)
        if counts is not None:
            set_fields["counts"] = model_payload(counts)
        if warnings is not None:
            set_fields["warnings"] = [
                model_payload(item) for item in warnings
            ]
        if grounding_status is not None:
            set_fields["grounding_status"] = grounding_status.value
        updated = self._jobs.find_one_and_update(
            {
                "session_id": session_id,
                "stage": current.value,
                "lock_owner": lock.owner,
                "lock_version": lock.version,
                "lock_expires_at": {"$gt": timestamp.isoformat()},
            },
            {"$set": set_fields},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise GenerationLockConflict(
                f"Lock for session {session_id} is stale or fenced"
            )
        return _record(updated)

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
    ) -> GenerationJobRecord:
        timestamp = _utc_now(now)
        self._require_job(session_id)
        set_fields: dict[str, Any] = {
            "updated_at": timestamp.isoformat(),
        }
        if cursor is not None:
            set_fields["cursor"] = model_payload(cursor)
        if counts is not None:
            set_fields["counts"] = model_payload(counts)
        if warnings is not None:
            set_fields["warnings"] = [
                model_payload(item) for item in warnings
            ]
        if grounding_status is not None:
            set_fields["grounding_status"] = grounding_status.value
        updated = self._jobs.find_one_and_update(
            {
                "session_id": session_id,
                "lock_owner": lock.owner,
                "lock_version": lock.version,
                "lock_expires_at": {"$gt": timestamp.isoformat()},
            },
            {"$set": set_fields},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise GenerationLockConflict(
                f"Lock for session {session_id} is stale or fenced"
            )
        return _record(updated)

    def request_cancel(
        self,
        session_id: str,
        now: Optional[datetime] = None,
    ) -> GenerationJobRecord:
        timestamp = _utc_now(now)
        self._require_job(session_id)
        updated = self._jobs.find_one_and_update(
            {"session_id": session_id},
            {
                "$set": {
                    "cancel_requested": True,
                    "updated_at": timestamp.isoformat(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise GenerationJobNotFound(session_id)
        return _record(updated)

    def is_cancel_requested(self, session_id: str) -> bool:
        document = self._require_job(session_id)
        return bool(document["cancel_requested"])

    def mark_paused(
        self,
        *,
        session_id: str,
        lock: GenerationLock,
        now: Optional[datetime] = None,
    ) -> GenerationJobRecord:
        timestamp = _utc_now(now)
        current_doc = self._require_job(session_id)
        current = GenerationStage(current_doc["stage"])
        if current in TERMINAL_STAGES or current == GenerationStage.CANCELLED:
            raise InvalidGenerationTransition(
                f"Cannot pause job in stage {current.value}"
            )
        resume_stage = (
            current_doc.get("resume_stage")
            if current == GenerationStage.PAUSED
            else current.value
        )
        updated = self._jobs.find_one_and_update(
            {
                "session_id": session_id,
                "lock_owner": lock.owner,
                "lock_version": lock.version,
                "lock_expires_at": {"$gt": timestamp.isoformat()},
            },
            {
                "$set": {
                    "stage": GenerationStage.PAUSED.value,
                    "resume_stage": resume_stage,
                    "updated_at": timestamp.isoformat(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise GenerationLockConflict(
                f"Lock for session {session_id} is stale or fenced"
            )
        return _record(updated)

    def mark_cancelled(
        self,
        *,
        session_id: str,
        lock: GenerationLock,
        now: Optional[datetime] = None,
    ) -> GenerationJobRecord:
        timestamp = _utc_now(now)
        current_doc = self._require_job(session_id)
        current = GenerationStage(current_doc["stage"])
        if current in TERMINAL_STAGES:
            raise InvalidGenerationTransition(
                f"Cannot cancel job in stage {current.value}"
            )
        resume_stage = (
            current_doc.get("resume_stage")
            if current == GenerationStage.CANCELLED
            else current.value
        )
        updated = self._jobs.find_one_and_update(
            {
                "session_id": session_id,
                "lock_owner": lock.owner,
                "lock_version": lock.version,
                "lock_expires_at": {"$gt": timestamp.isoformat()},
            },
            {
                "$set": {
                    "stage": GenerationStage.CANCELLED.value,
                    "resume_stage": resume_stage,
                    "cancel_requested": True,
                    "updated_at": timestamp.isoformat(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise GenerationLockConflict(
                f"Lock for session {session_id} is stale or fenced"
            )
        return _record(updated)

    def prepare_resume(
        self,
        session_id: str,
        now: Optional[datetime] = None,
    ) -> GenerationJobRecord:
        timestamp = _utc_now(now)
        document = self._require_job(session_id)
        current = GenerationStage(document["stage"])
        if current not in {
            GenerationStage.PAUSED,
            GenerationStage.CANCELLED,
        }:
            raise InvalidGenerationTransition(
                f"Cannot resume job in stage {current.value}"
            )
        resume_stage = document.get("resume_stage")
        if resume_stage is None:
            raise InvalidGenerationTransition(
                "Resume stage missing for job"
            )
        updated = self._jobs.find_one_and_update(
            {
                "session_id": session_id,
                "stage": {"$in": [
                    GenerationStage.PAUSED.value,
                    GenerationStage.CANCELLED.value,
                ]},
            },
            {
                "$set": {
                    "stage": resume_stage,
                    "resume_stage": None,
                    "cancel_requested": False,
                    "updated_at": timestamp.isoformat(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise GenerationJobNotFound(session_id)
        return _record(updated)

    def try_acquire_lock(
        self,
        *,
        session_id: str,
        owner: str,
        ttl_seconds: int,
        now: Optional[datetime] = None,
    ) -> Optional[GenerationLock]:
        timestamp = _utc_now(now)
        expires_at = timestamp + timedelta(seconds=ttl_seconds)
        updated = self._jobs.find_one_and_update(
            {
                "session_id": session_id,
                "$or": [
                    {"lock_owner": None},
                    {"lock_expires_at": {"$lte": timestamp.isoformat()}},
                    {"lock_owner": owner},
                ],
            },
            {
                "$set": {
                    "lock_owner": owner,
                    "lock_expires_at": expires_at.isoformat(),
                    "updated_at": timestamp.isoformat(),
                },
                "$inc": {"lock_version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            return None
        return GenerationLock(
            session_id=session_id,
            owner=owner,
            version=int(updated["lock_version"]),
            expires_at=expires_at,
        )

    def renew_lock(
        self,
        *,
        lock: GenerationLock,
        ttl_seconds: int,
        now: Optional[datetime] = None,
    ) -> GenerationLock:
        timestamp = _utc_now(now)
        expires_at = timestamp + timedelta(seconds=ttl_seconds)
        updated = self._jobs.find_one_and_update(
            {
                "session_id": lock.session_id,
                "lock_owner": lock.owner,
                "lock_version": lock.version,
                "lock_expires_at": {"$gt": timestamp.isoformat()},
            },
            {
                "$set": {
                    "lock_expires_at": expires_at.isoformat(),
                    "updated_at": timestamp.isoformat(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise GenerationLockConflict(
                f"Lock for owner {lock.owner} is stale or fenced"
            )
        return GenerationLock(
            session_id=lock.session_id,
            owner=lock.owner,
            version=lock.version,
            expires_at=expires_at,
        )

    def release_lock(self, *, lock: GenerationLock) -> None:
        updated = self._jobs.find_one_and_update(
            {
                "session_id": lock.session_id,
                "lock_owner": lock.owner,
                "lock_version": lock.version,
            },
            {
                "$set": {
                    "lock_owner": None,
                    "lock_expires_at": None,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise GenerationLockConflict(
                f"Lock for owner {lock.owner} is stale or fenced"
            )

    def mark_orphaned_jobs_paused(
        self,
        now: Optional[datetime] = None,
        *,
        pause_all_nonterminal: bool = False,
    ) -> list[str]:
        timestamp = _utc_now(now)
        terminal_values = [
            stage.value
            for stage in TERMINAL_STAGES
            | {GenerationStage.PAUSED, GenerationStage.CANCELLED}
        ]
        query: dict[str, Any] = {
            "stage": {"$nin": terminal_values},
        }
        if not pause_all_nonterminal:
            query["$or"] = [
                {"lock_owner": None},
                {"lock_expires_at": None},
                {"lock_expires_at": {"$lte": timestamp.isoformat()}},
            ]
        documents = list(self._jobs.find(query))
        paused: list[str] = []
        for document in documents:
            result = self._jobs.find_one_and_update(
                {"_id": document["_id"], "stage": document["stage"]},
                {
                    "$set": {
                        "stage": GenerationStage.PAUSED.value,
                        "resume_stage": document["stage"],
                        "cancel_requested": False,
                        "lock_owner": None,
                        "lock_expires_at": None,
                        "updated_at": timestamp.isoformat(),
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
            if result is not None:
                paused.append(document["session_id"])
        if paused:
            logger.info(
                "Paused %d orphaned generation jobs",
                len(paused),
            )
        return paused

    def update_stage(
        self,
        session_id: str,
        stage: GenerationStage,
        *,
        lock: Optional[GenerationLock] = None,
    ) -> None:
        timestamp = _utc_now(None)
        query: dict[str, Any] = {"session_id": session_id}
        if lock is not None:
            query["lock_owner"] = lock.owner
            query["lock_version"] = lock.version
            query["lock_expires_at"] = {"$gt": timestamp.isoformat()}
        updated = self._jobs.find_one_and_update(
            query,
            {
                "$set": {
                    "stage": stage.value,
                    "updated_at": timestamp.isoformat(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            if lock is not None:
                existing = self._jobs.find_one({"session_id": session_id})
                if existing is None:
                    raise GenerationJobNotFound(
                        f"Generation job for session {session_id} not found"
                    )
                raise GenerationLockConflict(
                    f"Lock for session {session_id} is stale or fenced"
                )
            raise GenerationJobNotFound(
                f"Generation job for session {session_id} not found"
            )

    def update_progress(
        self,
        session_id: str,
        completed_topics: int,
        *,
        lock: Optional[GenerationLock] = None,
        topics_ready: Optional[int] = None,
        topics_failed: Optional[int] = None,
    ) -> None:
        timestamp = _utc_now(None)
        document = self._require_job(session_id)
        if lock is not None:
            if (
                document.get("lock_owner") != lock.owner
                or int(document["lock_version"]) != lock.version
                or document.get("lock_expires_at") is None
                or document["lock_expires_at"] <= timestamp.isoformat()
            ):
                raise GenerationLockConflict(
                    f"Lock for session {session_id} is stale or fenced"
                )
        cursor = GenerationCursor.model_validate(document["cursor"])
        cursor = cursor.model_copy(
            update={"next_topic_index": completed_topics}
        )
        counts = GenerationCounts.model_validate(document["counts"])
        count_updates: dict[str, int] = {}
        if topics_ready is not None:
            count_updates["topics_ready"] = max(0, int(topics_ready))
        if topics_failed is not None:
            count_updates["topics_failed"] = max(0, int(topics_failed))
        if count_updates:
            counts = counts.model_copy(update=count_updates)
        query: dict[str, Any] = {"session_id": session_id}
        if lock is not None:
            query["lock_owner"] = lock.owner
            query["lock_version"] = lock.version
        updated = self._jobs.find_one_and_update(
            query,
            {
                "$set": {
                    "cursor": model_payload(cursor),
                    "counts": model_payload(counts),
                    "updated_at": timestamp.isoformat(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise GenerationJobNotFound(
                f"Generation job for session {session_id} not found"
            )

    def append_warning(
        self,
        session_id: str,
        warning: GenerationWarning,
    ) -> None:
        self._require_job(session_id)
        payload = model_payload(warning)
        self._jobs.update_one(
            {"session_id": session_id},
            {
                "$addToSet": {"warnings": payload},
                "$set": {"updated_at": utc_iso()},
            },
        )

    def bump_counts(
        self,
        session_id: str,
        **increments: int,
    ) -> GenerationCounts:
        allowed = set(GenerationCounts.model_fields)
        if set(increments) - allowed or any(
            value < 0 for value in increments.values()
        ):
            raise ValueError("Invalid generation count increment")
        self._require_job(session_id)
        inc_fields = {
            f"counts.{name}": value for name, value in increments.items()
        }
        updated = self._jobs.find_one_and_update(
            {"session_id": session_id},
            {
                "$inc": inc_fields,
                "$set": {"updated_at": utc_iso()},
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise GenerationJobNotFound(session_id)
        return GenerationCounts.model_validate(updated["counts"])

    def mark_failed(
        self,
        session_id: str,
        safe_message: str = "Generation failed",
    ) -> None:
        del safe_message
        try:
            self._jobs.update_one(
                {"session_id": session_id},
                {
                    "$set": {
                        "stage": GenerationStage.FAILED.value,
                        "lock_owner": None,
                        "lock_expires_at": None,
                        "updated_at": utc_iso(),
                    }
                },
            )
        except Exception:
            pass

    def set_grounding_status(
        self,
        session_id: str,
        grounding_status: GroundingStatus,
    ) -> None:
        self._require_job(session_id)
        updated = self._jobs.find_one_and_update(
            {"session_id": session_id},
            {
                "$set": {
                    "grounding_status": grounding_status.value,
                    "updated_at": utc_iso(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise GenerationJobNotFound(session_id)
