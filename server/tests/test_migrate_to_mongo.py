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

import sqlite3
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from server.database.migrate_to_mongo import (
    MIGRATION_TABLES,
    bulk_upsert,
    iter_batches,
    migrate_to_mongo,
    row_to_document,
)


class FakeCollection:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.documents: dict[object, dict] = {}
        self.ordered_values: list[bool] = []
        self._fail_once = fail_once
        self._failed = False

    def bulk_write(self, operations, ordered=True):
        if self._fail_once and not self._failed:
            self._failed = True
            raise RuntimeError("simulated bulk failure")
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

    def find_one(self, filter=None, sort=None):
        if not self.documents:
            return None
        if sort:
            reverse = sort[0][1] < 0
            keys = sorted(self.documents.keys(), reverse=reverse)
            return dict(self.documents[keys[0]])
        if filter and "_id" in filter:
            document = self.documents.get(filter["_id"])
            return dict(document) if document is not None else None
        first_key = next(iter(self.documents))
        return dict(self.documents[first_key])

    def update_one(self, filter, update, upsert=False):
        identifier = filter.get("_id")
        document = dict(self.documents.get(identifier, {"_id": identifier}))
        if "$max" in update:
            for key, value in update["$max"].items():
                current = document.get(key)
                document[key] = (
                    value if current is None else max(current, value)
                )
        if "$set" in update:
            document.update(update["$set"])
        self.documents[identifier] = document
        return SimpleNamespace(matched_count=1, modified_count=1)


class FakeDatabase:
    def __init__(self, fail_table: str | None = None) -> None:
        self._collections: dict[str, FakeCollection] = {}
        self._fail_table = fail_table

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection(
                fail_once=name == self._fail_table,
            )
        return self._collections[name]


class FakeSqliteSaver:
    def __init__(self, tuples) -> None:
        self.tuples = tuples

    async def alist(self, config):
        for item in self.tuples:
            yield item


class FakeMongoSaver:
    def __init__(self) -> None:
        self.checkpoints: set[tuple[str, str, str]] = set()
        self.writes: set[tuple[str, str, str, str, int]] = set()

    async def aput(self, config, checkpoint, metadata, new_versions):
        values = config["configurable"]
        self.checkpoints.add(
            (
                values["thread_id"],
                values.get("checkpoint_ns", ""),
                checkpoint["id"],
            )
        )

    async def aput_writes(self, config, writes, task_id):
        values = config["configurable"]
        for index, _write in enumerate(writes):
            self.writes.add(
                (
                    values["thread_id"],
                    values.get("checkpoint_ns", ""),
                    values["checkpoint_id"],
                    task_id,
                    index,
                )
            )


def _make_checkpoint_tuple():
    return SimpleNamespace(
        config={
            "configurable": {
                "thread_id": "gen-s1",
                "checkpoint_ns": "",
                "checkpoint_id": "cp2",
            }
        },
        checkpoint={"id": "cp2", "v": 1},
        metadata={"step": 2},
        parent_config={
            "configurable": {
                "thread_id": "gen-s1",
                "checkpoint_ns": "",
                "checkpoint_id": "cp1",
            }
        },
        pending_writes=[
            ("task-a", "alpha", 1),
        ],
    )


def _seed_sqlite(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        for table in MIGRATION_TABLES:
            if table == "node_sources":
                connection.execute(
                    "CREATE TABLE node_sources ("
                    "node_id TEXT, source_id TEXT)"
                )
                connection.execute(
                    "INSERT INTO node_sources VALUES ('n1', 'src1')"
                )
            elif table == "research_section_sources":
                connection.execute(
                    "CREATE TABLE research_section_sources ("
                    "section_id TEXT, source_id TEXT)"
                )
                connection.execute(
                    "INSERT INTO research_section_sources "
                    "VALUES ('sec1', 'src1')"
                )
            elif table == "research_provider_statuses":
                connection.execute(
                    "CREATE TABLE research_provider_statuses ("
                    "report_id TEXT, provider_id TEXT)"
                )
                connection.execute(
                    "INSERT INTO research_provider_statuses "
                    "VALUES ('r1', 'p1')"
                )
            elif table == "progress_events":
                connection.execute(
                    "CREATE TABLE progress_events ("
                    "id INTEGER PRIMARY KEY, payload_json TEXT)"
                )
                connection.execute(
                    "INSERT INTO progress_events VALUES "
                    "(7, '{\"ok\": true}')"
                )
            elif table == "generation_jobs":
                connection.execute(
                    "CREATE TABLE generation_jobs ("
                    "id TEXT PRIMARY KEY, cursor_json TEXT, "
                    "counts_json TEXT, warnings_json TEXT, "
                    "cancel_requested INTEGER)"
                )
                connection.execute(
                    "INSERT INTO generation_jobs VALUES "
                    "('j1', '{}', '{}', '[]', 0)"
                )
            else:
                connection.execute(
                    f"CREATE TABLE {table} (id TEXT PRIMARY KEY, name TEXT)"
                )
                connection.execute(
                    f"INSERT INTO {table} VALUES (?, ?)",
                    (f"{table}-1", "row"),
                )
        connection.commit()
    finally:
        connection.close()


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


class MigrationOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmpdir.name)
        self.sqlite_path = root / "a2ui.db"
        self.checkpoint_path = root / "checkpoints.db"
        self.checkpoint_path.write_bytes(b"")
        _seed_sqlite(self.sqlite_path)
        self.mongo_database = FakeDatabase()
        self.mongo_saver = FakeMongoSaver()
        self.settings_repository = MagicMock()
        self._checkpoint_tuple = _make_checkpoint_tuple()

        @asynccontextmanager
        async def sqlite_saver_factory(path: str):
            yield FakeSqliteSaver([self._checkpoint_tuple])

        self.sqlite_saver_factory = sqlite_saver_factory

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    async def test_migrate_all_copies_tables_settings_and_checkpoints(
        self,
    ) -> None:
        summary = await migrate_to_mongo(
            sqlite_path=self.sqlite_path,
            checkpoint_path=self.checkpoint_path,
            database=self.mongo_database,
            mongo_checkpointer=self.mongo_saver,
            app_settings=self.settings_repository,
            provider_settings={"activeProvider": "openrouter"},
            web_search_settings={"masterEnabled": False},
            sqlite_saver_factory=self.sqlite_saver_factory,
        )
        self.assertEqual(
            set(summary.collections),
            set(MIGRATION_TABLES),
        )
        self.assertEqual(summary.checkpoints, 1)
        self.settings_repository.put_provider_settings.assert_called_once()
        self.settings_repository.put_web_search_settings.assert_called_once()
        self.assertTrue(self.sqlite_path.exists())
        self.assertTrue(self.checkpoint_path.exists())
        counter = self.mongo_database["storage_counters"].documents[
            "progress_events"
        ]
        self.assertEqual(counter["value"], 7)

    async def test_retry_after_partial_failure_is_idempotent(self) -> None:
        failing_db = FakeDatabase(fail_table="quiz_data")
        with self.assertRaises(Exception):
            await migrate_to_mongo(
                sqlite_path=self.sqlite_path,
                checkpoint_path=self.checkpoint_path,
                database=failing_db,
                mongo_checkpointer=self.mongo_saver,
                app_settings=self.settings_repository,
                provider_settings={"activeProvider": "openrouter"},
                web_search_settings={"masterEnabled": False},
                sqlite_saver_factory=self.sqlite_saver_factory,
            )
        self.settings_repository.put_provider_settings.assert_not_called()

        retry_db = FakeDatabase()
        for name, collection in failing_db._collections.items():
            if name == "quiz_data":
                continue
            retry_db._collections[name] = collection

        summary = await migrate_to_mongo(
            sqlite_path=self.sqlite_path,
            checkpoint_path=self.checkpoint_path,
            database=retry_db,
            mongo_checkpointer=self.mongo_saver,
            app_settings=self.settings_repository,
            provider_settings={"activeProvider": "openrouter"},
            web_search_settings={"masterEnabled": False},
            sqlite_saver_factory=self.sqlite_saver_factory,
        )
        for table in MIGRATION_TABLES:
            self.assertEqual(len(retry_db[table].documents), 1)
        self.assertEqual(summary.checkpoints, 1)
        self.assertEqual(len(self.mongo_saver.checkpoints), 1)
        self.settings_repository.put_provider_settings.assert_called_once()
        self.settings_repository.put_web_search_settings.assert_called_once()


if __name__ == "__main__":
    unittest.main()
