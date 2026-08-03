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
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from server.config import Settings
from server.database.mongo_client import MongoUnavailableError
from server.database.storage_mode import DeploymentMode, StorageBackend
from server.main import start_cloud_runtime


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


class CloudStorageLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_cloud_connects_before_runtime_creation(self) -> None:
        storage = MagicMock()
        storage.mongo_connection.client = MagicMock()
        storage.connect.side_effect = lambda uri, db_name: setattr(
            storage,
            "active_backend",
            StorageBackend.MONGO,
        )
        app_state = SimpleNamespace()
        runtime_type = MagicMock()

        runtime = await start_cloud_runtime(
            app_state=app_state,
            storage=storage,
            uri="mongodb://host",
            db_name="a2ui",
            runtime_type=runtime_type,
        )

        storage.connect.assert_called_once_with(
            "mongodb://host",
            "a2ui",
        )
        self.assertEqual(storage.active_backend, StorageBackend.MONGO)
        runtime_type.assert_called_once_with(app_state=app_state)
        self.assertIs(runtime, runtime_type.return_value)

    async def test_cloud_startup_failure_does_not_create_runtime(self) -> None:
        storage = MagicMock()
        storage.connect.side_effect = MongoUnavailableError("down")
        runtime_type = MagicMock()
        with self.assertRaisesRegex(RuntimeError, "Cloud MongoDB startup failed"):
            await start_cloud_runtime(
                app_state=SimpleNamespace(),
                storage=storage,
                uri="mongodb://user:secret@host",
                db_name="a2ui",
                runtime_type=runtime_type,
            )
        runtime_type.assert_not_called()

    async def test_cloud_shutdown_orders_runtime_before_storage_close(
        self,
    ) -> None:
        events: list[str] = []
        storage = MagicMock()
        storage.connect.side_effect = lambda uri, db_name: setattr(
            storage,
            "active_backend",
            StorageBackend.MONGO,
        )
        storage.close.side_effect = lambda: events.append("close")
        runtime = MagicMock()
        runtime.shutdown = AsyncMock(side_effect=lambda: events.append("shutdown"))
        runtime_type = MagicMock(return_value=runtime)

        started = await start_cloud_runtime(
            app_state=SimpleNamespace(),
            storage=storage,
            uri="mongodb://host",
            db_name="a2ui",
            runtime_type=runtime_type,
        )
        await started.shutdown()
        storage.close()

        self.assertEqual(events, ["shutdown", "close"])


if __name__ == "__main__":
    unittest.main()
