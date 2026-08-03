"""
============================================================================
FILE: test_migrate_to_mongo.py
LOCATION: server/tests/test_migrate_to_mongo.py
============================================================================
PURPOSE:
    Unit tests for SQLite-to-Mongo row mapping, batching, and migration.
ROLE IN PROJECT:
    TDD guard for Phase 5 one-way idempotent migrate service.
    - Table list and deterministic _id / JSON / boolean conversion
    - Unordered bulk upsert batching and retry safety
    - Full orchestration including checkpoints and app settings
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.database.migrate_to_mongo
USAGE:
    python -m unittest server.tests.test_migrate_to_mongo -v
============================================================================
"""
from __future__ import annotations

import unittest

from types import SimpleNamespace

from server.database.migrate_to_mongo import (
    MIGRATION_TABLES,
    bulk_upsert,
    iter_batches,
    row_to_document,
)


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[object, dict] = {}
        self.ordered_values: list[bool] = []

    def bulk_write(self, operations, ordered=True):
        self.ordered_values.append(ordered)
        matched = 0
        upserted = 0
        modified = 0
        for operation in operations:
            document = dict(operation._doc)
            identifier = document["_id"]
            if identifier in self.documents:
                matched += 1
                if self.documents[identifier] != document:
                    modified += 1
                self.documents[identifier] = document
            else:
                upserted += 1
                self.documents[identifier] = document
        return SimpleNamespace(
            matched_count=matched,
            upserted_count=upserted,
            modified_count=modified,
        )


class MigrationMappingTests(unittest.TestCase):
    def test_table_list_covers_all_application_data(self) -> None:
        self.assertEqual(
            set(MIGRATION_TABLES),
            {
                "learning_sessions",
                "concept_nodes",
                "quiz_data",
                "quiz_attempts",
                "revision_sessions",
                "revision_node_progress",
                "generation_jobs",
                "generation_briefs",
                "node_sources",
                "research_reports",
                "research_sources",
                "research_sections",
                "research_section_sources",
                "research_provider_statuses",
                "progress_events",
            },
        )

    def test_maps_id_and_json_columns_to_native_values(self) -> None:
        document = row_to_document(
            "generation_jobs",
            {
                "id": "j1",
                "cursor_json": '{"next_topic_index": 2}',
                "counts_json": '{"topics_total": 3}',
                "warnings_json": "[]",
                "cancel_requested": 1,
            },
        )
        self.assertEqual(document["_id"], "j1")
        self.assertEqual(document["cursor"]["next_topic_index"], 2)
        self.assertEqual(document["counts"]["topics_total"], 3)
        self.assertEqual(document["warnings"], [])
        self.assertIs(document["cancel_requested"], True)

    def test_maps_composite_join_id_deterministically(self) -> None:
        document = row_to_document(
            "research_section_sources",
            {"section_id": "sec", "source_id": "src"},
        )
        self.assertEqual(document["_id"], "sec::src")

    def test_preserves_invalid_json_as_string_and_warning(self) -> None:
        warnings: list[str] = []
        document = row_to_document(
            "concept_nodes",
            {"id": "n1", "key_terms": "not-json"},
            warnings=warnings,
        )
        self.assertEqual(document["key_terms"], "not-json")
        self.assertEqual(len(warnings), 1)


class MigrationBatchTests(unittest.TestCase):
    def test_bulk_upsert_is_unordered_and_retry_safe(self) -> None:
        collection = FakeCollection()
        documents = [
            {"_id": "s1", "query": "one"},
            {"_id": "s2", "query": "two"},
        ]
        first = bulk_upsert(collection, documents)
        second = bulk_upsert(collection, documents)

        self.assertEqual(len(collection.documents), 2)
        self.assertEqual(first.upserted_count, 2)
        self.assertEqual(second.matched_count, 2)
        self.assertFalse(collection.ordered_values[0])

    def test_iter_batches_uses_500_row_limit(self) -> None:
        batches = list(iter_batches(range(1001)))
        self.assertEqual([len(batch) for batch in batches], [500, 500, 1])


if __name__ == "__main__":
    unittest.main()
