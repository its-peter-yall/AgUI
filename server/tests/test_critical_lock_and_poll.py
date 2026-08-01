"""
============================================================================
FILE: test_critical_lock_and_poll.py
LOCATION: server/tests/test_critical_lock_and_poll.py
============================================================================
PURPOSE:
    Critical fixes C2/C3/C5: lock fencing, real poll columns, no synthetic events.
ROLE IN PROJECT:
    Regression guards for execution fence and progressive polling integrity.
KEY COMPONENTS:
    - CriticalLockPollTests
DEPENDENCIES:
    - External: tempfile, unittest
    - Internal: generation stores, learning router
USAGE:
    python -m unittest server.tests.test_critical_lock_and_poll -v
============================================================================
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from server.database.generation_artifacts import GenerationArtifactStore
from server.database.generation_jobs import (
    GenerationJobNotFound,
    GenerationJobStore,
    GenerationLockConflict,
)
from server.database.generation_migrations import initialize_generation_schema
from server.database.learning_persistence import LearningManager
from server.database.progress_events import (
    ProgressEventPersistError,
    ProgressEventStore,
)
from server.routers.learning import get_learning_session
from server.schemas.generation import GenerationLock, GenerationStage
from server.schemas.learning import CourseOutline, TopicNode
from server.schemas.progress import ProgressEventType, StageChangedPayload


class CriticalLockPollTests(unittest.TestCase):
    """C2/C3/C5 regression tests against real temp SQLite."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        self.learning = LearningManager(self.db_path)
        self.learning.init_learning_tables()
        initialize_generation_schema(self.db_path)
        self.jobs = GenerationJobStore(self.db_path)
        self.events = ProgressEventStore(self.db_path)
        self.artifacts = GenerationArtifactStore(self.db_path)
        self.now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        session, _ = self.jobs.create_session_shell_and_job(
            query="Lock fence topic",
            user_id=None,
            mode="lite",
            web_search_requested=False,
            now=self.now,
        )
        self.session_id = session["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_c2_live_lock_refuses_same_owner_reacquire(self) -> None:
        first = self.jobs.try_acquire_lock(
            session_id=self.session_id,
            owner="worker-same",
            ttl_seconds=120,
            now=self.now,
        )
        self.assertIsNotNone(first)
        second = self.jobs.try_acquire_lock(
            session_id=self.session_id,
            owner="worker-same",
            ttl_seconds=120,
            now=self.now + timedelta(seconds=1),
        )
        self.assertIsNone(second)
        assert first is not None
        # Fenced mutation still works for first lock
        self.jobs.transition_stage(
            session_id=self.session_id,
            target_stage=GenerationStage.OUTLINING,
            lock=first,
            now=self.now + timedelta(seconds=2),
        )

    def test_c2_stale_lock_cannot_update_stage_or_progress(self) -> None:
        first = self.jobs.try_acquire_lock(
            session_id=self.session_id,
            owner="worker-a",
            ttl_seconds=30,
            now=self.now,
        )
        assert first is not None
        second = self.jobs.try_acquire_lock(
            session_id=self.session_id,
            owner="worker-b",
            ttl_seconds=30,
            now=self.now + timedelta(seconds=31),
        )
        self.assertIsNotNone(second)
        with self.assertRaises(GenerationLockConflict):
            self.jobs.update_stage(
                self.session_id,
                GenerationStage.OUTLINING,
                lock=first,
            )
        with self.assertRaises(GenerationLockConflict):
            self.jobs.update_progress(
                self.session_id,
                3,
                lock=first,
            )

    def test_c3_real_db_poll_returns_title_and_module_status(self) -> None:
        # Shell: title not finalized
        shell = self.learning.get_learning_session(self.session_id)
        assert shell is not None
        self.assertIn("title_finalized", shell)
        self.assertFalse(shell["title_finalized"])

        outline = CourseOutline(
            course_title="Real Poll Course",
            topics=[
                TopicNode(
                    index=0,
                    title="Topic Zero",
                    complexity="Basic",
                    summary_for_context="s0",
                    key_terms=["alpha", "beta"],
                ),
                TopicNode(
                    index=1,
                    title="Topic One",
                    complexity="Basic",
                    summary_for_context="s1",
                    key_terms=["gamma", "delta"],
                ),
                TopicNode(
                    index=2,
                    title="Topic Two",
                    complexity="Basic",
                    summary_for_context="s2",
                    key_terms=["epsilon", "zeta"],
                ),
            ],
        )
        self.artifacts.persist_outline(self.session_id, outline)
        nodes = self.learning.get_session_nodes(self.session_id)
        self.assertEqual(len(nodes), 3)
        self.assertEqual(nodes[0]["generation_status"], "SKELETON")
        self.assertEqual(nodes[1]["generation_status"], "SKELETON")

        # Mark first GENERATING, second READY via direct SQL
        import sqlite3

        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "UPDATE concept_nodes SET generation_status = ? "
                "WHERE learning_session_id = ? AND sequence_index = 0",
                ("GENERATING", self.session_id),
            )
            conn.execute(
                "UPDATE concept_nodes SET generation_status = ?, "
                "content_markdown = ? "
                "WHERE learning_session_id = ? AND sequence_index = 1",
                ("READY", "# Ready body", self.session_id),
            )
            conn.execute(
                "UPDATE learning_sessions SET title_finalized = 1, "
                "course_title = ? WHERE id = ?",
                ("Real Poll Course", self.session_id),
            )
            conn.commit()
        finally:
            conn.close()

        with (
            patch("server.routers.learning.learning_manager", self.learning),
            patch("server.routers.learning.generation_job_store", self.jobs),
            patch(
                "server.routers.learning.research_store",
                type(
                    "R",
                    (),
                    {
                        "get_citations_by_session": staticmethod(
                            lambda _s: {}
                        )
                    },
                )(),
            ),
        ):
            response = get_learning_session(self.session_id)
        payload = response.model_dump(mode="json")
        self.assertTrue(payload["title_finalized"])
        self.assertEqual(payload["nodes"][0]["module_status"], "GENERATING")
        self.assertEqual(payload["nodes"][0]["content_markdown"], "")
        self.assertEqual(payload["nodes"][1]["module_status"], "READY")

    def test_c5_append_once_does_not_return_synthetic_id_on_error(self) -> None:
        # Point store at missing path to force OperationalError
        bad = ProgressEventStore(Path(self.temp_dir.name) / "missing" / "no.db")
        with self.assertRaises(ProgressEventPersistError):
            bad.append_once(
                session_id=self.session_id,
                event_type=ProgressEventType.STAGE_CHANGED,
                payload=StageChangedPayload(
                    previous_stage=GenerationStage.INITIALIZING,
                    stage=GenerationStage.OUTLINING,
                ),
                dedupe_key="should-fail",
            )

    def test_c5_update_stage_raises_when_session_missing(self) -> None:
        with self.assertRaises(GenerationJobNotFound):
            self.jobs.update_stage(
                "missing-session",
                GenerationStage.FAILED,
            )

    def test_c4_startup_pauses_live_lock_nonterminal(self) -> None:
        lock = self.jobs.try_acquire_lock(
            session_id=self.session_id,
            owner="dead-process-worker",
            ttl_seconds=3600,
            now=self.now,
        )
        assert lock is not None
        self.jobs.transition_stage(
            session_id=self.session_id,
            target_stage=GenerationStage.RESEARCHING,
            lock=lock,
            now=self.now,
        )
        paused = self.jobs.mark_orphaned_jobs_paused(
            now=self.now + timedelta(seconds=5),
            pause_all_nonterminal=True,
        )
        self.assertIn(self.session_id, paused)
        job = self.jobs.get_by_session(self.session_id)
        assert job is not None
        self.assertEqual(job.stage, GenerationStage.PAUSED)
        self.assertIsNone(job.lock_owner)


if __name__ == "__main__":
    unittest.main()
