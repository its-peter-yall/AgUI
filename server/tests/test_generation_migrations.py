"""
============================================================================
FILE: test_generation_migrations.py
LOCATION: server/tests/test_generation_migrations.py
============================================================================
PURPOSE:
    Tests generation-schema creation and safe evolution of existing databases.
ROLE IN PROJECT:
    Guards startup migrations before focused generation stores use new tables.
KEY COMPONENTS:
    - GenerationMigrationTests: Fresh, existing, idempotent, and rollback tests
DEPENDENCIES:
    - External: sqlite3, tempfile, unittest
    - Internal: server.database generation migration and learning manager
USAGE:
    python -m unittest server.tests.test_generation_migrations -v
============================================================================
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.database import generation_migrations as migration_module
from server.database.generation_migrations import (
    GenerationMigrationError,
    initialize_generation_schema,
)
from server.database.learning_persistence import LearningManager
from server.database.sqlite_utils import connect_database


EXPECTED_TABLES = {
    "generation_schema_migrations",
    "generation_jobs",
    "research_reports",
    "research_sources",
    "research_sections",
    "research_section_sources",
    "research_provider_statuses",
    "generation_briefs",
    "node_sources",
    "progress_events",
}


class GenerationMigrationTests(unittest.TestCase):
    """Tests fresh and existing SQLite generation schema migration."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        self.manager = LearningManager(db_path=self.db_path)
        self.manager.init_learning_tables()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_fresh_database_gets_all_tables_columns_and_indexes(self) -> None:
        initialize_generation_schema(self.db_path)
        conn = connect_database(self.db_path)
        try:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertTrue(EXPECTED_TABLES.issubset(tables))
            session_columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(learning_sessions)"
                ).fetchall()
            }
            node_columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(concept_nodes)"
                ).fetchall()
            }
            self.assertIn("title_finalized", session_columns)
            self.assertIn("generation_status", node_columns)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            conn.close()

    def test_existing_data_survives_idempotent_migration(self) -> None:
        session = self.manager.create_learning_session(
            query="Existing course",
            course_title="Existing Course",
        )
        initialize_generation_schema(self.db_path)
        initialize_generation_schema(self.db_path)

        loaded = self.manager.get_learning_session(session["id"])
        self.assertIsNotNone(loaded)
        conn = connect_database(self.db_path)
        try:
            versions = conn.execute(
                "SELECT version FROM generation_schema_migrations"
            ).fetchall()
            self.assertEqual([row["version"] for row in versions], [1])
        finally:
            conn.close()

    def test_duplicate_existing_sequence_stops_before_unique_index(self) -> None:
        session = self.manager.create_learning_session(
            query="Duplicate test",
            course_title="Duplicate Test",
        )
        conn = self.manager._get_connection()
        try:
            for node_id in ("node-a", "node-b"):
                conn.execute(
                    """
                    INSERT INTO concept_nodes (
                        id, learning_session_id, sequence_index, title,
                        content_markdown, status
                    ) VALUES (?, ?, 0, 'Topic', '', 'LOCKED')
                    """,
                    (node_id, session["id"]),
                )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(GenerationMigrationError):
            initialize_generation_schema(self.db_path)

    def test_failed_statement_rolls_back_migration_version(self) -> None:
        original_execute = migration_module._execute_ddl

        def fail_on_jobs(connection, sql, parameters=()):
            if "CREATE TABLE generation_jobs" in sql:
                raise sqlite3.OperationalError("forced migration failure")
            return original_execute(connection, sql, parameters)

        with patch.object(migration_module, "_execute_ddl", fail_on_jobs):
            with self.assertRaises(sqlite3.OperationalError):
                initialize_generation_schema(self.db_path)

        conn = connect_database(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name = 'generation_schema_migrations'
                """
            ).fetchone()
            if row is not None:
                versions = conn.execute(
                    "SELECT version FROM generation_schema_migrations"
                ).fetchall()
                self.assertEqual(versions, [])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
