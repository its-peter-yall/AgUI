"""
============================================================================
FILE: test_mongo_jobs.py
LOCATION: server/tests/test_mongo_jobs.py
============================================================================
PURPOSE:
    Unit tests for Mongo generation job repository locks and transitions.
ROLE IN PROJECT:
    Phase 3B coverage for mongo_jobs without live Atlas.
KEY COMPONENTS:
    - MongoJobTests: atomic lock and stage transition predicates
DEPENDENCIES:
    - External: unittest, unittest.mock, pymongo
    - Internal: server.database.repositories.mongo_jobs,
                server.schemas.generation
USAGE:
    python -m unittest server.tests.test_mongo_jobs -v
============================================================================
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from pymongo import ReturnDocument

from server.database.repositories.mongo_jobs import (
    MongoGenerationJobRepository,
)
from server.schemas.generation import (
    GenerationCounts,
    GenerationCursor,
    GenerationLock,
    GenerationStage,
    GroundingStatus,
)


def make_job_document(
    *,
    stage: str = "INITIALIZING",
    lock_owner: str | None = None,
    lock_version: int = 0,
    lock_expires_at: str | None = None,
) -> dict:
    now = "2026-08-03T00:00:00+00:00"
    return {
        "_id": "job1",
        "session_id": "s1",
        "thread_id": "gen-s1",
        "stage": stage,
        "resume_stage": None,
        "web_search_requested": False,
        "grounding_status": GroundingStatus.DISABLED.value,
        "cursor": GenerationCursor().model_dump(mode="json"),
        "counts": GenerationCounts().model_dump(mode="json"),
        "warnings": [],
        "cancel_requested": False,
        "lock_owner": lock_owner,
        "lock_version": lock_version,
        "lock_expires_at": lock_expires_at,
        "created_at": now,
        "updated_at": now,
    }


def make_lock(*, version: int = 1) -> GenerationLock:
    return GenerationLock(
        session_id="s1",
        owner="worker",
        version=version,
        expires_at=datetime(2026, 8, 3, 1, tzinfo=timezone.utc),
    )


class MongoJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = MagicMock()
        self.collections: dict[str, MagicMock] = {}

        def get_collection(name: str) -> MagicMock:
            if name not in self.collections:
                self.collections[name] = MagicMock(name=name)
            return self.collections[name]

        self.database.__getitem__.side_effect = get_collection
        self.repository = MongoGenerationJobRepository(self.database)

    def test_try_acquire_lock_uses_expiry_or_owner_predicate(self) -> None:
        jobs = self.database["generation_jobs"]
        jobs.find_one_and_update.return_value = make_job_document(
            lock_owner="worker",
            lock_version=2,
        )
        lock = self.repository.try_acquire_lock(
            session_id="s1",
            owner="worker",
            ttl_seconds=45,
            now=datetime(2026, 8, 3, tzinfo=timezone.utc),
        )
        query = jobs.find_one_and_update.call_args.args[0]
        self.assertIn("$or", query)
        self.assertEqual(
            jobs.find_one_and_update.call_args.kwargs["return_document"],
            ReturnDocument.AFTER,
        )
        self.assertIsNotNone(lock)
        self.assertEqual(lock.version, 2)

    def test_transition_requires_current_stage_and_lock_version(self) -> None:
        jobs = self.database["generation_jobs"]
        jobs.find_one.return_value = make_job_document(
            stage="INITIALIZING",
        )
        jobs.find_one_and_update.return_value = make_job_document(
            stage="OUTLINING",
        )
        lock = make_lock(version=3)
        self.repository.transition_stage(
            session_id="s1",
            target_stage=GenerationStage.OUTLINING,
            lock=lock,
        )
        query = jobs.find_one_and_update.call_args.args[0]
        self.assertEqual(query["stage"], "INITIALIZING")
        self.assertEqual(query["lock_version"], 3)

    def test_create_job_sets_session_status_in_progress(self) -> None:
        client = MagicMock()
        self.database.client = client
        session_ctx = MagicMock()
        client.start_session.return_value.__enter__.return_value = session_ctx
        session_ctx.start_transaction.return_value.__enter__.return_value = None

        jobs_col = self.database["generation_jobs"]
        jobs_col.find_one.return_value = make_job_document()

        session_row, job = self.repository.create_session_shell_and_job(
            user_id="u1",
            query="test query",
            mode="auto",
            web_search_requested=False,
        )

        sessions_col = self.database["learning_sessions"]
        session_doc = sessions_col.insert_one.call_args.kwargs.get(
            "session"
        )  # or args
        doc = sessions_col.insert_one.call_args.args[0]
        self.assertEqual(doc["status"], "in_progress")
        self.assertEqual(session_row["id"], doc["_id"])


if __name__ == "__main__":
    unittest.main()
