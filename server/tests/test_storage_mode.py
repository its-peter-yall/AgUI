"""
============================================================================
FILE: test_storage_mode.py
LOCATION: server/tests/test_storage_mode.py
============================================================================
PURPOSE:
    Unit tests for deployment mode config parsing and StorageContext.
ROLE IN PROJECT:
    TDD guard for storage mode foundation (Phase 1 MongoDB Atlas storage).
    - DEPLOYMENT_MODE / MONGO_URI / MONGO_DB environment parsing
    - StorageBackend enum API values
    - StorageContext connect/disconnect lifecycle
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.config, server.database.storage_mode
USAGE:
    python -m unittest server.tests.test_storage_mode -v
============================================================================
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from server.config import Settings
from server.database.mongo_client import MongoConnection
from server.database.storage_mode import (
    DeploymentMode,
    StorageBackend,
    StorageContext,
)


class StorageModeConfigTests(unittest.TestCase):
    def test_defaults_to_local_without_mongo_config(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()

        self.assertEqual(settings.deployment_mode, DeploymentMode.LOCAL)
        self.assertIsNone(settings.mongo_uri)
        self.assertIsNone(settings.mongo_db)

    def test_reads_cloud_environment(self) -> None:
        env = {
            "DEPLOYMENT_MODE": "cloud",
            "MONGO_URI": "mongodb://user:secret@db.example/a2ui",
            "MONGO_DB": "a2ui",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()

        self.assertEqual(settings.deployment_mode, DeploymentMode.CLOUD)
        self.assertEqual(settings.mongo_uri, env["MONGO_URI"])
        self.assertEqual(settings.mongo_db, "a2ui")

    def test_rejects_unknown_deployment_mode(self) -> None:
        with patch.dict(
            os.environ,
            {"DEPLOYMENT_MODE": "shared"},
            clear=True,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "DEPLOYMENT_MODE must be local or cloud",
            ):
                Settings()

    def test_storage_backend_values_match_api(self) -> None:
        self.assertEqual(StorageBackend.SQLITE.value, "sqlite")
        self.assertEqual(StorageBackend.MONGO.value, "mongo")


class StorageContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        self.client = MagicMock()
        self.connection = MongoConnection(
            client=self.client,
            database=MagicMock(),
            db_name="atlas_db",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_connect_sets_validated_client_in_process_memory(self) -> None:
        factory = MagicMock(return_value=self.connection)
        context = StorageContext(
            deployment_mode=DeploymentMode.LOCAL,
            sqlite_path=self.db_path,
            mongo_factory=factory,
        )
        context.connect("mongodb://host", "atlas_db")

        self.assertEqual(context.active_backend, StorageBackend.MONGO)
        self.assertTrue(context.connected)
        self.assertEqual(context.mongo_db_name, "atlas_db")
        factory.assert_called_once_with("mongodb://host", "atlas_db")

    def test_failed_reconnect_keeps_previous_connection(self) -> None:
        factory = MagicMock(
            side_effect=[self.connection, RuntimeError("failed")]
        )
        context = StorageContext(
            deployment_mode=DeploymentMode.LOCAL,
            sqlite_path=self.db_path,
            mongo_factory=factory,
        )
        context.connect("mongodb://one", "atlas_db")
        with self.assertRaises(RuntimeError):
            context.connect("mongodb://two", "other")

        self.assertEqual(context.mongo_db_name, "atlas_db")
        self.client.close.assert_not_called()

    def test_disconnect_closes_client_and_reverts_to_sqlite(self) -> None:
        context = StorageContext(
            deployment_mode=DeploymentMode.LOCAL,
            sqlite_path=self.db_path,
            mongo_factory=MagicMock(return_value=self.connection),
        )
        context.connect("mongodb://host", "atlas_db")
        context.disconnect()

        self.client.close.assert_called_once_with()
        self.assertEqual(context.active_backend, StorageBackend.SQLITE)
        self.assertFalse(context.connected)


if __name__ == "__main__":
    unittest.main()
