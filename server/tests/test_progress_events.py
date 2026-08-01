"""
============================================================================
FILE: test_progress_events.py
LOCATION: server/tests/test_progress_events.py
============================================================================
PURPOSE:
    Tests monotonic, replayable, idempotent, secret-safe generation events.
ROLE IN PROJECT:
    Establishes durable event source used by Phase 5 SSE and client polling repair.
KEY COMPONENTS:
    - ProgressEventStoreTests: Append, replay, conflict, rollback tests
DEPENDENCIES:
    - External: tempfile, unittest
    - Internal: server.database stores and progress schemas
USAGE:
    python -m unittest server.tests.test_progress_events -v
============================================================================
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.database.generation_jobs import GenerationJobStore
from server.database.generation_migrations import initialize_generation_schema
from server.database.learning_persistence import LearningManager
from server.database.progress_events import (
    ProgressEventConflict,
    ProgressEventStore,
)
from server.database.sqlite_utils import database_transaction
from server.schemas.generation import GenerationStage
from server.schemas.progress import ProgressEventType, StageChangedPayload


class ProgressEventStoreTests(unittest.TestCase):
    """Tests durable progress event ordering and atomicity."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        LearningManager(self.db_path).init_learning_tables()
        initialize_generation_schema(self.db_path)
        session, _ = GenerationJobStore(
            self.db_path
        ).create_session_shell_and_job(
            query="Events",
            user_id=None,
            mode="lite",
            web_search_requested=False,
        )
        self.session_id = session["id"]
        self.store = ProgressEventStore(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_append_once_and_list_after_use_monotonic_ids(self) -> None:
        payload = StageChangedPayload(
            previous_stage=GenerationStage.INITIALIZING,
            stage=GenerationStage.OUTLINING,
        )
        first = self.store.append_once(
            session_id=self.session_id,
            event_type=ProgressEventType.STAGE_CHANGED,
            payload=payload,
            dedupe_key="stage:OUTLINING:0",
        )
        repeated = self.store.append_once(
            session_id=self.session_id,
            event_type=ProgressEventType.STAGE_CHANGED,
            payload=payload,
            dedupe_key="stage:OUTLINING:0",
        )
        second = self.store.append_once(
            session_id=self.session_id,
            event_type=ProgressEventType.STAGE_CHANGED,
            payload=StageChangedPayload(
                previous_stage=GenerationStage.OUTLINING,
                stage=GenerationStage.PLANNING_PREVIEW,
            ),
            dedupe_key="stage:PLANNING_PREVIEW:0",
        )
        self.assertEqual(first.id, repeated.id)
        self.assertGreater(second.id, first.id)
        self.assertEqual(
            [event.id for event in self.store.list_after(self.session_id, first.id)],
            [second.id],
        )

    def test_same_dedupe_key_with_changed_payload_conflicts(self) -> None:
        self.store.append_once(
            session_id=self.session_id,
            event_type=ProgressEventType.STAGE_CHANGED,
            payload=StageChangedPayload(
                previous_stage=GenerationStage.INITIALIZING,
                stage=GenerationStage.OUTLINING,
            ),
            dedupe_key="stage:one",
        )
        with self.assertRaises(ProgressEventConflict):
            self.store.append_once(
                session_id=self.session_id,
                event_type=ProgressEventType.STAGE_CHANGED,
                payload=StageChangedPayload(
                    previous_stage=GenerationStage.INITIALIZING,
                    stage=GenerationStage.RESEARCHING,
                ),
                dedupe_key="stage:one",
            )

    def test_caller_transaction_rolls_event_back(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "forced rollback"):
            with database_transaction(self.db_path) as conn:
                self.store.append_once(
                    session_id=self.session_id,
                    event_type=ProgressEventType.STAGE_CHANGED,
                    payload=StageChangedPayload(
                        previous_stage=GenerationStage.INITIALIZING,
                        stage=GenerationStage.OUTLINING,
                    ),
                    dedupe_key="rolled-back",
                    conn=conn,
                )
                raise RuntimeError("forced rollback")
        self.assertEqual(self.store.list_after(self.session_id, 0), [])


if __name__ == "__main__":
    unittest.main()
