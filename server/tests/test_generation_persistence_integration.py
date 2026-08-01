"""
============================================================================
FILE: test_generation_persistence_integration.py
LOCATION: server/tests/test_generation_persistence_integration.py
============================================================================
PURPOSE:
    Tests atomic generation boundaries and explicit session cleanup cascades.
ROLE IN PROJECT:
    Verifies focused stores cooperate without adding methods to LearningManager.
KEY COMPONENTS:
    - GenerationPersistenceIntegrationTests: Transaction and cascade tests
DEPENDENCIES:
    - External: tempfile, unittest
    - Internal: server.database focused stores
USAGE:
    python -m unittest server.tests.test_generation_persistence_integration -v
============================================================================
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.database.generation_artifacts import GenerationArtifactStore
from server.database.generation_jobs import GenerationJobStore
from server.database.generation_migrations import initialize_generation_schema
from server.database.learning_persistence import LearningManager
from server.database.progress_events import ProgressEventStore
from server.database.sqlite_utils import connect_database, database_transaction
from server.schemas.generation import GenerationStage
from server.schemas.learning import CourseOutline, TopicNode
from server.schemas.progress import OutlineReadyPayload, ProgressEventType


class GenerationPersistenceIntegrationTests(unittest.TestCase):
    """Tests transaction sharing and cascade cleanup."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        self.learning = LearningManager(self.db_path)
        self.learning.init_learning_tables()
        initialize_generation_schema(self.db_path)
        self.jobs = GenerationJobStore(self.db_path)
        self.artifacts = GenerationArtifactStore(self.db_path)
        self.events = ProgressEventStore(self.db_path)
        self.session, _ = self.jobs.create_session_shell_and_job(
            query="Atomic boundaries",
            user_id=None,
            mode="lite",
            web_search_requested=False,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def outline(self) -> CourseOutline:
        return CourseOutline(
            course_title="Atomic Boundaries",
            topics=[
                TopicNode(
                    index=index,
                    title=f"Topic {index}",
                    summary_for_context=f"Summary {index}",
                    key_terms=["atomic", "transaction"],
                    complexity="Basic",
                    quiz_count=1,
                )
                for index in range(3)
            ],
        )

    def test_outline_and_event_roll_back_together(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "forced rollback"):
            with database_transaction(self.db_path) as conn:
                self.artifacts.persist_outline(
                    self.session["id"],
                    self.outline(),
                    conn=conn,
                )
                self.events.append_once(
                    session_id=self.session["id"],
                    event_type=ProgressEventType.OUTLINE_READY,
                    payload=OutlineReadyPayload(
                        course_title="Atomic Boundaries",
                        topic_count=3,
                    ),
                    dedupe_key="outline:ready",
                    conn=conn,
                )
                raise RuntimeError("forced rollback")
        self.assertEqual(self.learning.get_session_nodes(self.session["id"]), [])
        self.assertEqual(self.events.list_after(self.session["id"], 0), [])

    def test_explicit_session_delete_cascades_new_records(self) -> None:
        self.artifacts.persist_outline(self.session["id"], self.outline())
        self.assertTrue(self.learning.delete_learning_session(self.session["id"]))
        conn = connect_database(self.db_path)
        try:
            for table in (
                "generation_jobs",
                "research_reports",
                "generation_briefs",
                "progress_events",
            ):
                count = conn.execute(
                    f"SELECT COUNT(*) AS count FROM {table}"
                ).fetchone()["count"]
                self.assertEqual(count, 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
