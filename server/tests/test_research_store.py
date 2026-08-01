"""
============================================================================
FILE: test_research_store.py
LOCATION: server/tests/test_research_store.py
============================================================================
PURPOSE:
    Tests incremental reports, source deduplication, sections, and providers.
ROLE IN PROJECT:
    Guards durable Researcher output before live search is implemented.
KEY COMPONENTS:
    - ResearchStoreTests: Report aggregate persistence tests
DEPENDENCIES:
    - External: tempfile, unittest
    - Internal: server.database research store and schemas
USAGE:
    python -m unittest server.tests.test_research_store -v
============================================================================
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from server.database.generation_jobs import GenerationJobStore
from server.database.generation_migrations import initialize_generation_schema
from server.database.learning_persistence import LearningManager
from server.database.research_store import ResearchSourceConflict, ResearchStore
from server.schemas.research import (
    ResearchProviderState,
    ResearchSource,
    ResearchStatus,
)
from server.search.types import SearchErrorClass, SearchProviderId


class ResearchStoreTests(unittest.TestCase):
    """Tests idempotent research aggregate writes."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        LearningManager(self.db_path).init_learning_tables()
        initialize_generation_schema(self.db_path)
        session, _ = GenerationJobStore(
            self.db_path
        ).create_session_shell_and_job(
            query="React 19",
            user_id=None,
            mode="full",
            web_search_requested=True,
        )
        self.session_id = session["id"]
        self.store = ResearchStore(self.db_path)
        self.report = self.store.create_report(self.session_id)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def make_source(self, content_hash: str = "a" * 64) -> ResearchSource:
        return ResearchSource(
            id="source-input-id",
            title="React v19",
            url="https://react.dev/blog/2024/12/05/react-19",
            publisher="React",
            published_at=datetime(2024, 12, 5, tzinfo=timezone.utc),
            retrieved_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            provider_id=SearchProviderId.TAVILY,
            snippet="React 19 release summary.",
            excerpt="React 19 is stable.",
            relevance_score=0.98,
        ).model_copy(update={"id": content_hash})

    def test_source_and_section_upserts_are_idempotent(self) -> None:
        first = self.store.upsert_source(
            session_id=self.session_id,
            source=self.make_source(),
            canonical_url="https://react.dev/blog/2024/12/05/react-19",
            content_hash="a" * 64,
        )
        second = self.store.upsert_source(
            session_id=self.session_id,
            source=self.make_source(),
            canonical_url="https://react.dev/blog/2024/12/05/react-19",
            content_hash="a" * 64,
        )
        self.assertEqual(first.id, second.id)

        section = self.store.upsert_section(
            report_id=self.report.id,
            sequence_index=0,
            theme="Current versions",
            markdown="React 19 is stable.",
            source_ids=[first.id],
        )
        updated = self.store.upsert_section(
            report_id=self.report.id,
            sequence_index=0,
            theme="Current versions",
            markdown="React 19 is stable and documents Actions.",
            source_ids=[first.id],
        )
        self.assertEqual(section.id, updated.id)
        self.assertIn("Actions", updated.markdown)

    def test_content_hash_collision_with_different_url_is_rejected(self) -> None:
        self.store.upsert_source(
            session_id=self.session_id,
            source=self.make_source(),
            canonical_url="https://react.dev/react-19",
            content_hash="a" * 64,
        )
        with self.assertRaises(ResearchSourceConflict):
            self.store.upsert_source(
                session_id=self.session_id,
                source=self.make_source(),
                canonical_url="https://example.com/copied-react-19",
                content_hash="a" * 64,
            )

    def test_provider_state_and_final_report_expose_safe_data(self) -> None:
        self.store.set_provider_status(
            report_id=self.report.id,
            provider_id=SearchProviderId.EXA,
            state=ResearchProviderState.AUTH_FAILED,
            search_calls=1,
            result_count=0,
            error_class=SearchErrorClass.AUTHENTICATION,
        )
        final = self.store.finalize_report(
            session_id=self.session_id,
            status=ResearchStatus.DEGRADED,
            summary="Research stopped after provider authentication failed.",
            limitations=["Current web evidence is incomplete."],
            freshness_note="Retrieved 2026-08-01.",
        )
        rendered = final.model_dump_json()
        self.assertIn("AUTH_FAILED", rendered)
        self.assertNotIn("api_key", rendered)
        self.assertNotIn("authorization", rendered.lower())


if __name__ == "__main__":
    unittest.main()
