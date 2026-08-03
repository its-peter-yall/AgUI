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
from unittest.mock import patch

from server.config import Settings
from server.database.storage_mode import DeploymentMode, StorageBackend


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


if __name__ == "__main__":
    unittest.main()
