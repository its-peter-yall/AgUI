"""
============================================================================
FILE: test_mongo_research.py
LOCATION: server/tests/test_mongo_research.py
============================================================================
PURPOSE:
    Unit tests for Mongo research repository relationships and conflicts.
ROLE IN PROJECT:
    Phase 3B coverage for mongo_research without live Atlas.
KEY COMPONENTS:
    - MongoResearchTests: report idempotency and section junction replace
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.database.repositories.mongo_research
USAGE:
    python -m unittest server.tests.test_mongo_research -v
============================================================================
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from server.database.repositories.mongo_research import (
    MongoResearchRepository,
)
from server.schemas.research import ResearchStatus


def make_report_document() -> dict:
    now = "2026-08-03T00:00:00+00:00"
    return {
        "_id": "r1",
        "session_id": "s1",
        "status": ResearchStatus.PENDING.value,
        "summary": None,
        "limitations": [],
        "freshness_note": None,
        "warnings": [],
        "created_at": now,
        "updated_at": now,
    }


class MongoResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reports = MagicMock()
        self.sources = MagicMock()
        self.sections = MagicMock()
        self.section_sources = MagicMock()
        self.providers = MagicMock()
        self.nodes = MagicMock()
        self.node_sources = MagicMock()
        self.database = MagicMock()
        self.database.__getitem__.side_effect = lambda name: {
            "research_reports": self.reports,
            "research_sources": self.sources,
            "research_sections": self.sections,
            "research_section_sources": self.section_sources,
            "research_provider_statuses": self.providers,
            "concept_nodes": self.nodes,
            "node_sources": self.node_sources,
        }[name]
        self.repository = MongoResearchRepository(self.database)

    def test_create_report_is_idempotent_by_session(self) -> None:
        doc = make_report_document()
        self.reports.find_one_and_update.return_value = doc
        self.reports.find_one.return_value = doc
        self.sections.find.return_value = MagicMock(
            sort=MagicMock(return_value=[])
        )
        self.sources.find.return_value = []
        self.providers.find.return_value = []
        first = self.repository.create_report("s1")
        query = self.reports.find_one_and_update.call_args.args[0]
        self.assertEqual(query, {"session_id": "s1"})
        self.assertEqual(first.session_id, "s1")

    def test_upsert_section_replaces_junction_documents(self) -> None:
        self.reports.find_one.return_value = {
            "_id": "r1",
            "session_id": "s1",
        }
        self.sources.count_documents.return_value = 2
        section_doc = {
            "_id": "section-id",
            "report_id": "r1",
            "sequence_index": 0,
            "theme": "Theme",
            "markdown": "Body",
            "created_at": "2026-08-03T00:00:00+00:00",
            "updated_at": "2026-08-03T00:00:00+00:00",
        }
        self.sections.find_one_and_update.return_value = section_doc
        self.sections.find_one.return_value = section_doc
        self.section_sources.find.return_value = MagicMock(
            sort=MagicMock(
                return_value=[
                    {"source_id": "src1"},
                    {"source_id": "src2"},
                ]
            )
        )
        self.repository.upsert_section(
            report_id="r1",
            sequence_index=0,
            theme="Theme",
            markdown="Body",
            source_ids=["src1", "src2"],
        )
        self.section_sources.delete_many.assert_called_once()
        links = self.section_sources.insert_many.call_args.args[0]
        self.assertEqual(
            {link["_id"] for link in links},
            {"section-id::src1", "section-id::src2"},
        )


if __name__ == "__main__":
    unittest.main()
