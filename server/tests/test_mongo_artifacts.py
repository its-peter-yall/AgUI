"""
============================================================================
FILE: test_mongo_artifacts.py
LOCATION: server/tests/test_mongo_artifacts.py
============================================================================
PURPOSE:
    Unit tests for Mongo generation artifact repository.
ROLE IN PROJECT:
    Phase 3B coverage for mongo_artifacts without live Atlas.
KEY COMPONENTS:
    - MongoArtifactTests: outline, brief, citation allowlist
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.database.repositories.mongo_artifacts,
                server.schemas.generation, server.schemas.learning
USAGE:
    python -m unittest server.tests.test_mongo_artifacts -v
============================================================================
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from server.database.generation_artifacts import UnsupportedCitationError
from server.database.repositories.mongo_artifacts import (
    MongoGenerationArtifactRepository,
)
from server.schemas.generation import (
    GenerationBrief,
    GenerationBriefBatch,
    GroundingStatus,
    SourceCitation,
)
from server.schemas.learning import CourseOutline, TopicNode


def make_outline() -> CourseOutline:
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
    return CourseOutline(
        course_title="Modern Python Packaging",
        topics=topics,
    )


def make_brief(topic_index: int = 0) -> GenerationBrief:
    return GenerationBrief(
        topic_index=topic_index,
        topic_scope="Standards-based build configuration.",
        learning_objectives=["Explain pyproject.toml build metadata."],
        prerequisites=["Python module structure."],
        assumed_knowledge=["Virtual environments."],
        current_facts=["PEP 517 build isolation is current."],
        methodologies=["Use a standards-based build frontend."],
        conventions=["Prefer pyproject.toml over setup.py."],
        deprecated_approaches=["Legacy setup.py-only packaging."],
        migration_notes=["Move metadata into pyproject.toml."],
        caveats=["Tooling versions matter."],
        required_examples=["Minimal pyproject.toml example."],
        common_misconceptions=["setup.py is still required."],
        failure_modes=["Missing build-system table."],
        pedagogical_guidance="Start from a minimal project file.",
        expected_depth="lite",
        boundaries_with_adjacent_topics="Do not cover packaging upload.",
        quiz_learning_targets=["Identify required build-system fields."],
        expected_learner_evidence=["Can write a minimal pyproject.toml."],
        grounding_status=GroundingStatus.DISABLED,
    )


def make_brief_batch() -> GenerationBriefBatch:
    return GenerationBriefBatch(start_index=0, briefs=[make_brief(0)])


class MongoArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.nodes = MagicMock()
        self.briefs = MagicMock()
        self.sessions = MagicMock()
        self.node_sources = MagicMock()
        self.research_sources = MagicMock()
        self.quizzes = MagicMock()
        self.database = MagicMock()
        self.database.__getitem__.side_effect = lambda name: {
            "concept_nodes": self.nodes,
            "generation_briefs": self.briefs,
            "learning_sessions": self.sessions,
            "node_sources": self.node_sources,
            "research_sources": self.research_sources,
            "quiz_data": self.quizzes,
        }[name]
        self.repository = MongoGenerationArtifactRepository(self.database)
        self.node_docs = [
            {
                "_id": "n0",
                "learning_session_id": "s1",
                "sequence_index": 0,
                "title": "Topic 0",
                "content_markdown": "",
                "status": "LOCKED",
                "error_message": None,
                "retry_available": False,
                "failed_step": None,
                "complexity": "Intermediate",
                "summary_for_context": "Summary 0",
                "key_terms": ["packaging", "standards"],
                "created_at": "2026-08-03T00:00:00+00:00",
                "updated_at": "2026-08-03T00:00:00+00:00",
                "generation_status": "SKELETON",
            },
            {
                "_id": "n1",
                "learning_session_id": "s1",
                "sequence_index": 1,
                "title": "Topic 1",
                "content_markdown": "",
                "status": "LOCKED",
                "error_message": None,
                "retry_available": False,
                "failed_step": None,
                "complexity": "Intermediate",
                "summary_for_context": "Summary 1",
                "key_terms": ["packaging", "standards"],
                "created_at": "2026-08-03T00:00:00+00:00",
                "updated_at": "2026-08-03T00:00:00+00:00",
                "generation_status": "SKELETON",
            },
        ]
        node_cursor = MagicMock()
        node_cursor.sort.return_value = self.node_docs
        self.nodes.find.return_value = node_cursor
        self.nodes.find_one.return_value = None
        brief_cursor = MagicMock()
        brief_cursor.sort.return_value = []
        self.briefs.find.return_value = brief_cursor

    def test_persist_outline_upserts_deterministic_nodes(self) -> None:
        outline = make_outline()
        rows = self.repository.persist_outline("s1", outline)
        operations = self.nodes.bulk_write.call_args.args[0]
        self.assertEqual(len(operations), len(outline.topics))
        self.assertEqual(rows[0]["sequence_index"], 0)

    def test_upsert_brief_stores_native_payload(self) -> None:
        batch = make_brief_batch()
        node_id = self.repository.node_id_for_topic("s1", 0)
        self.nodes.find_one.return_value = {
            "_id": node_id,
            "sequence_index": 0,
            "learning_session_id": "s1",
        }
        brief_docs = [
            {
                "payload": batch.briefs[0].model_dump(
                    mode="json",
                    exclude_none=True,
                )
            }
        ]
        cursor = MagicMock()
        cursor.sort.return_value = brief_docs
        self.briefs.find.return_value = cursor
        self.repository.upsert_brief_batch("s1", batch)
        operation = self.briefs.bulk_write.call_args.args[0][0]
        self.assertIsInstance(operation._doc["$set"]["payload"], dict)

    def test_replace_sources_rejects_unapproved_source(self) -> None:
        self.nodes.find_one.return_value = {
            "_id": "n1",
            "learning_session_id": "s1",
        }
        self.briefs.find_one.return_value = None
        self.research_sources.count_documents.return_value = 0
        empty_cursor = MagicMock()
        empty_cursor.sort.return_value = []
        self.research_sources.find.return_value = empty_cursor
        with self.assertRaises(UnsupportedCitationError):
            self.repository.replace_node_sources(
                "n1",
                [SourceCitation(source_id="missing", claim="claim")],
            )


if __name__ == "__main__":
    unittest.main()
