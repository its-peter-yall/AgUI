"""
============================================================================
FILE: test_generation_artifacts.py
LOCATION: server/tests/test_generation_artifacts.py
============================================================================
PURPOSE:
    Tests idempotent TOC, private brief, module, and citation persistence.
ROLE IN PROJECT:
    Guards Planner-to-Generator durable artifacts without growing LearningManager.
KEY COMPONENTS:
    - GenerationArtifactStoreTests: Outline, brief, content, citation tests
DEPENDENCIES:
    - External: tempfile, unittest
    - Internal: server.database stores and learning schemas
USAGE:
    python -m unittest server.tests.test_generation_artifacts -v
============================================================================
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from server.database.generation_artifacts import (
    GenerationArtifactStore,
    UnsupportedCitationError,
)
from server.database.generation_jobs import GenerationJobStore
from server.database.generation_migrations import initialize_generation_schema
from server.database.learning_persistence import LearningManager
from server.database.research_store import ResearchStore
from server.schemas.generation import (
    BriefSourceExcerpt,
    GenerationBrief,
    GenerationBriefBatch,
    GroundingStatus,
    SourceCitation,
)
from server.schemas.learning import CourseOutline, TopicNode
from server.schemas.research import ResearchSource
from server.search.types import SearchProviderId


class GenerationArtifactStoreTests(unittest.TestCase):
    """Tests durable generation artifacts and citation allowlists."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        self.learning = LearningManager(self.db_path)
        self.learning.init_learning_tables()
        initialize_generation_schema(self.db_path)
        session, _ = GenerationJobStore(
            self.db_path
        ).create_session_shell_and_job(
            query="Modern packaging",
            user_id=None,
            mode="lite",
            web_search_requested=True,
        )
        self.session_id = session["id"]
        self.store = GenerationArtifactStore(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_outline_brief_and_citations_are_idempotent_and_private(self) -> None:
        topics = [
            TopicNode(
                index=index,
                title=f"Topic {index}",
                summary_for_context=f"Summary {index}",
                key_terms=["packaging", "standards"],
                complexity="Intermediate",
                quiz_count=2,
            )
            for index in range(3)
        ]
        outline = CourseOutline(
            course_title="Modern Python Packaging",
            topics=topics,
        )
        first_nodes = self.store.persist_outline(self.session_id, outline)
        second_nodes = self.store.persist_outline(self.session_id, outline)
        self.assertEqual(
            [node["id"] for node in first_nodes],
            [node["id"] for node in second_nodes],
        )
        self.assertTrue(all(node["generation_status"] == "SKELETON" for node in first_nodes))

        research = ResearchStore(self.db_path)
        research.create_report(self.session_id)
        source = research.upsert_source(
            session_id=self.session_id,
            source=ResearchSource(
                id="input-id",
                title="Python Packaging User Guide",
                url="https://packaging.python.org/en/latest/",
                publisher="Python Packaging Authority",
                published_at=None,
                retrieved_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                provider_id=SearchProviderId.EXA,
                snippet="Current packaging guidance.",
                excerpt="Use pyproject.toml for build configuration.",
                relevance_score=0.95,
            ),
            canonical_url="https://packaging.python.org/en/latest/",
            content_hash="b" * 64,
        )
        brief = GenerationBrief(
            topic_index=0,
            topic_scope="Standards-based build configuration.",
            learning_objectives=["Explain pyproject.toml build metadata."],
            prerequisites=["Python module structure."],
            assumed_knowledge=["Virtual environments."],
            current_facts=["PEP 517 build isolation is current."],
            methodologies=["Use a standards-based build frontend."],
            conventions=["Store metadata in pyproject.toml."],
            deprecated_approaches=["Direct setup.py invocation."],
            migration_notes=["Move legacy metadata incrementally."],
            caveats=["Backend-specific options differ."],
            research_report_id=research.get_report(self.session_id).id,
            source_excerpts=[
                BriefSourceExcerpt(
                    source_id=source.id,
                    excerpt="Use pyproject.toml for build configuration.",
                )
            ],
            required_examples=["Build a wheel with python -m build."],
            common_misconceptions=["pip is not a build backend."],
            failure_modes=["Missing build-system requirements."],
            pedagogical_guidance="Contrast frontend and backend roles.",
            expected_depth="lite",
            boundaries_with_adjacent_topics="Lock files belong later.",
            quiz_learning_targets=["Identify valid build configuration."],
            expected_learner_evidence=["Choose a standards-based command."],
            grounding_status=GroundingStatus.GROUNDED,
        )
        batch = GenerationBriefBatch(start_index=0, briefs=[brief])
        self.store.upsert_brief_batch(self.session_id, batch)
        self.store.upsert_brief_batch(self.session_id, batch)
        self.assertEqual(self.store.get_brief(first_nodes[0]["id"]), brief)

        links = self.store.replace_node_sources(
            node_id=first_nodes[0]["id"],
            citations=[
                SourceCitation(
                    source_id=source.id,
                    claim="pyproject.toml stores build configuration.",
                )
            ],
        )
        self.assertEqual([link["source_id"] for link in links], [source.id])

        public_node = self.learning.get_concept_node(first_nodes[0]["id"])
        self.assertNotIn("brief", public_node)
        self.assertNotIn("source_excerpts", public_node)

    def test_unsupported_citation_preserves_existing_links(self) -> None:
        topics = [
            TopicNode(
                index=index,
                title=f"Topic {index}",
                summary_for_context=f"Summary {index}",
                key_terms=["term-a", "term-b"],
                complexity="Basic",
                quiz_count=1,
            )
            for index in range(3)
        ]
        node = self.store.persist_outline(
            self.session_id,
            CourseOutline(course_title="Course", topics=topics),
        )[0]
        with self.assertRaises(UnsupportedCitationError):
            self.store.replace_node_sources(
                node_id=node["id"],
                citations=[
                    SourceCitation(
                        source_id="fabricated-source",
                        claim="Fabricated claim.",
                    )
                ],
            )
        self.assertEqual(self.store.list_node_sources(node["id"]), [])


if __name__ == "__main__":
    unittest.main()
