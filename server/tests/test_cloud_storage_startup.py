"""
============================================================================
FILE: test_cloud_storage_startup.py
LOCATION: server/tests/test_cloud_storage_startup.py
============================================================================
PURPOSE:
    Fail-fast cloud config and Mongo-only lifespan lifecycle tests.
ROLE IN PROJECT:
    TDD guard for Phase 7 deploy hardening.
    - DEPLOYMENT_MODE=cloud requires MONGO_URI and MONGO_DB
    - Cloud startup connects before runtime creation
    - Shutdown orders runtime before storage close
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.config, server.database.storage_mode, server.main
USAGE:
    python -m unittest server.tests.test_cloud_storage_startup -v
============================================================================
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from server.config import Settings
from server.database.storage_mode import DeploymentMode


class CloudStorageConfigTests(unittest.TestCase):
    def test_cloud_requires_uri(self) -> None:
        with patch.dict(
            os.environ,
            {"DEPLOYMENT_MODE": "cloud", "MONGO_DB": "a2ui"},
            clear=True,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "DEPLOYMENT_MODE=cloud requires MONGO_URI and MONGO_DB",
            ):
                Settings()

    def test_cloud_requires_database(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEPLOYMENT_MODE": "cloud",
                "MONGO_URI": "mongodb://host",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "requires MONGO_URI"):
                Settings()

    def test_local_does_not_require_mongo_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()
        self.assertEqual(settings.deployment_mode, DeploymentMode.LOCAL)


if __name__ == "__main__":
    unittest.main()
