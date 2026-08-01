"""
============================================================================
FILE: test_generation_jobs.py
LOCATION: server/tests/test_generation_jobs.py
============================================================================
PURPOSE:
    Tests durable generation job stages, cursors, cancellation, and locks.
ROLE IN PROJECT:
    Guards resumable single-worker generation lifecycle semantics.
KEY COMPONENTS:
    - GenerationJobStoreTests: Shell, transitions, lock fencing, cancel tests
DEPENDENCIES:
    - External: tempfile, unittest
    - Internal: server.database generation stores and schemas
USAGE:
    python -m unittest server.tests.test_generation_jobs -v
============================================================================
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from server.database.generation_jobs import (
    GenerationJobStore,
    GenerationLockConflict,
    InvalidGenerationTransition,
)
from server.database.generation_migrations import initialize_generation_schema
from server.database.learning_persistence import LearningManager
from server.schemas.generation import GenerationStage, GroundingStatus


class GenerationJobStoreTests(unittest.TestCase):
    """Tests durable generation job behavior."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        LearningManager(self.db_path).init_learning_tables()
        initialize_generation_schema(self.db_path)
        self.store = GenerationJobStore(self.db_path)
        self.now = datetime(2026, 8, 1, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_shell_and_job_are_created_atomically(self) -> None:
        session, job = self.store.create_session_shell_and_job(
            query="Modern Python packaging",
            user_id=None,
            mode="auto",
            web_search_requested=True,
            now=self.now,
        )
        self.assertEqual(session["course_title"], "Modern Python packaging")
        self.assertFalse(session["title_finalized"])
        self.assertIsNone(session["resolved_mode"])
        self.assertEqual(job.session_id, session["id"])
        self.assertEqual(job.thread_id, f"gen-{session['id']}")
        self.assertEqual(job.stage, GenerationStage.INITIALIZING)
        self.assertEqual(job.grounding_status, GroundingStatus.PENDING)

    def test_transition_matrix_rejects_skipped_stage(self) -> None:
        session, _ = self.store.create_session_shell_and_job(
            query="State machines",
            user_id=None,
            mode="lite",
            web_search_requested=False,
            now=self.now,
        )
        lock = self.store.try_acquire_lock(
            session_id=session["id"],
            owner="worker-a",
            ttl_seconds=120,
            now=self.now,
        )
        self.assertIsNotNone(lock)
        assert lock is not None
        with self.assertRaises(InvalidGenerationTransition):
            self.store.transition_stage(
                session_id=session["id"],
                target_stage=GenerationStage.COMPLETE,
                lock=lock,
                now=self.now,
            )

    def test_new_lock_fences_expired_worker(self) -> None:
        session, _ = self.store.create_session_shell_and_job(
            query="Fenced locks",
            user_id=None,
            mode="lite",
            web_search_requested=False,
            now=self.now,
        )
        first = self.store.try_acquire_lock(
            session_id=session["id"],
            owner="worker-a",
            ttl_seconds=60,
            now=self.now,
        )
        self.assertIsNotNone(first)
        second = self.store.try_acquire_lock(
            session_id=session["id"],
            owner="worker-b",
            ttl_seconds=60,
            now=self.now + timedelta(seconds=61),
        )
        self.assertIsNotNone(second)
        assert first is not None
        assert second is not None
        self.assertGreater(second.version, first.version)
        with self.assertRaises(GenerationLockConflict):
            self.store.transition_stage(
                session_id=session["id"],
                target_stage=GenerationStage.OUTLINING,
                lock=first,
                now=self.now + timedelta(seconds=62),
            )

    def test_cancel_retains_resume_stage_and_clears_on_resume(self) -> None:
        session, _ = self.store.create_session_shell_and_job(
            query="Cancellation",
            user_id=None,
            mode="full",
            web_search_requested=True,
            now=self.now,
        )
        lock = self.store.try_acquire_lock(
            session_id=session["id"],
            owner="worker-a",
            ttl_seconds=120,
            now=self.now,
        )
        assert lock is not None
        self.store.transition_stage(
            session_id=session["id"],
            target_stage=GenerationStage.RESEARCHING,
            lock=lock,
            now=self.now,
        )
        requested = self.store.request_cancel(session["id"], now=self.now)
        self.assertTrue(requested.cancel_requested)
        cancelled = self.store.mark_cancelled(
            session_id=session["id"],
            lock=lock,
            now=self.now,
        )
        self.assertEqual(cancelled.stage, GenerationStage.CANCELLED)
        self.assertEqual(cancelled.resume_stage, GenerationStage.RESEARCHING)
        resumed = self.store.prepare_resume(session["id"], now=self.now)
        self.assertEqual(resumed.stage, GenerationStage.RESEARCHING)
        self.assertFalse(resumed.cancel_requested)


if __name__ == "__main__":
    unittest.main()
