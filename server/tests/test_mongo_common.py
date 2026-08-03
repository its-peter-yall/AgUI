"""
============================================================================
FILE: test_mongo_common.py
LOCATION: server/tests/test_mongo_common.py
============================================================================
PURPOSE:
    Unit tests for Mongo document codecs and learning collection indexes.
ROLE IN PROJECT:
    Phase 3A coverage for mongo_common / mongo_indexes without live Atlas.
KEY COMPONENTS:
    - MongoCommonTests: codec mapping and ensure_learning_indexes calls
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.database.repositories.mongo_common,
                server.database.repositories.mongo_indexes,
                server.schemas.generation
USAGE:
    python -m unittest server.tests.test_mongo_common -v
============================================================================
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, call

from server.database.repositories.mongo_common import (
    document_to_row,
    model_payload,
    utc_iso,
)
from server.database.repositories.mongo_indexes import (
    ensure_learning_indexes,
    ensure_operational_indexes,
)
from server.schemas.generation import GenerationCounts


class MongoCommonTests(unittest.TestCase):
    def test_document_to_row_maps_id_without_mutating_source(self) -> None:
        source = {"_id": "s1", "query": "q"}
        self.assertEqual(
            document_to_row(source),
            {"id": "s1", "query": "q"},
        )
        self.assertEqual(source, {"_id": "s1", "query": "q"})

    def test_model_payload_returns_native_bson_shape(self) -> None:
        counts = GenerationCounts(sources=2)
        self.assertEqual(model_payload(counts)["sources"], 2)

    def test_utc_iso_is_timezone_aware(self) -> None:
        value = utc_iso(datetime(2026, 8, 3, tzinfo=timezone.utc))
        self.assertEqual(value, "2026-08-03T00:00:00+00:00")

    def test_learning_indexes_match_sqlite_constraints(self) -> None:
        database = MagicMock()
        ensure_learning_indexes(database)

        database["concept_nodes"].create_index.assert_has_calls(
            [
                call([("learning_session_id", 1)]),
                call(
                    [
                        ("learning_session_id", 1),
                        ("sequence_index", 1),
                    ],
                    unique=True,
                ),
            ]
        )
        database["quiz_data"].create_index.assert_any_call(
            [("node_id", 1)],
            unique=True,
        )
        database["revision_node_progress"].create_index.assert_any_call(
            [("revision_session_id", 1), ("node_id", 1)],
            unique=True,
        )

    def test_operational_indexes_match_sqlite_uniques(self) -> None:
        database = MagicMock()
        ensure_operational_indexes(database)

        database["generation_jobs"].create_index.assert_has_calls(
            [
                call([("session_id", 1)], unique=True),
                call([("thread_id", 1)], unique=True),
            ]
        )
        database["research_sources"].create_index.assert_any_call(
            [("session_id", 1), ("canonical_url", 1)],
            unique=True,
        )
        database["progress_events"].create_index.assert_any_call(
            [("session_id", 1), ("dedupe_key", 1)],
            unique=True,
        )


if __name__ == "__main__":
    unittest.main()
