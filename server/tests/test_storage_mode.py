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
from server.database.repositories.bundle import RepositoryBundle
from server.database.storage_mode import (
    DeploymentMode,
    StorageBackend,
    StorageContext,
)


def make_bundle(label: str) -> RepositoryBundle:
    return RepositoryBundle(
        learning=MagicMock(name=f"{label}-learning"),
        jobs=MagicMock(name=f"{label}-jobs"),
        artifacts=MagicMock(name=f"{label}-artifacts"),
        research=MagicMock(name=f"{label}-research"),
        progress=MagicMock(name=f"{label}-progress"),
        app_settings=MagicMock(name=f"{label}-app_settings"),
    )


def make_context(
    *,
    sqlite_path,
    mongo_factory,
    mongo_bundle_factory=None,
    mongo_indexer=None,
    sqlite_repositories=None,
    checkpointer_controller=None,
) -> StorageContext:
    kwargs = {
        "deployment_mode": DeploymentMode.LOCAL,
        "sqlite_path": sqlite_path,
        "mongo_factory": mongo_factory,
    }
    if sqlite_repositories is not None:
        kwargs["sqlite_repositories"] = sqlite_repositories
    if mongo_bundle_factory is not None:
        kwargs["mongo_bundle_factory"] = mongo_bundle_factory
    if mongo_indexer is not None:
        kwargs["mongo_indexer"] = mongo_indexer
    context = StorageContext(**kwargs)
    if checkpointer_controller is not None:
        context.set_checkpointer_controller(checkpointer_controller)
    return context


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
        self.sqlite_bundle = make_bundle("sqlite")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_connect_sets_validated_client_in_process_memory(self) -> None:
        factory = MagicMock(return_value=self.connection)
        context = make_context(
            sqlite_path=self.db_path,
            mongo_factory=factory,
            mongo_bundle_factory=MagicMock(return_value=make_bundle("mongo")),
            mongo_indexer=MagicMock(),
            sqlite_repositories=self.sqlite_bundle,
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
        context = make_context(
            sqlite_path=self.db_path,
            mongo_factory=factory,
            mongo_bundle_factory=MagicMock(return_value=make_bundle("mongo")),
            mongo_indexer=MagicMock(),
            sqlite_repositories=self.sqlite_bundle,
        )
        context.connect("mongodb://one", "atlas_db")
        with self.assertRaises(RuntimeError):
            context.connect("mongodb://two", "other")

        self.assertEqual(context.mongo_db_name, "atlas_db")
        self.client.close.assert_not_called()

    def test_disconnect_closes_client_and_reverts_to_sqlite(self) -> None:
        context = make_context(
            sqlite_path=self.db_path,
            mongo_factory=MagicMock(return_value=self.connection),
            mongo_bundle_factory=MagicMock(return_value=make_bundle("mongo")),
            mongo_indexer=MagicMock(),
            sqlite_repositories=self.sqlite_bundle,
        )
        context.connect("mongodb://host", "atlas_db")
        context.disconnect()

        self.client.close.assert_called_once_with()
        self.assertEqual(context.active_backend, StorageBackend.SQLITE)
        self.assertFalse(context.connected)
        self.assertIs(context.learning, self.sqlite_bundle.learning)

    def test_connect_publishes_complete_mongo_bundle_atomically(self) -> None:
        mongo_bundle = make_bundle("mongo")
        bundle_factory = MagicMock(return_value=mongo_bundle)
        indexer = MagicMock()
        context = make_context(
            sqlite_path=self.db_path,
            mongo_factory=MagicMock(return_value=self.connection),
            mongo_bundle_factory=bundle_factory,
            mongo_indexer=indexer,
            sqlite_repositories=self.sqlite_bundle,
        )

        context.connect("mongodb://host", "atlas")

        indexer.assert_called_once_with(self.connection.database)
        bundle_factory.assert_called_once_with(self.connection.database)
        self.assertIs(context.learning, mongo_bundle.learning)
        self.assertIs(context.jobs, mongo_bundle.jobs)
        self.assertEqual(context.active_backend, StorageBackend.MONGO)

    def test_bundle_build_failure_keeps_sqlite_and_closes_candidate(self) -> None:
        context = make_context(
            sqlite_path=self.db_path,
            mongo_factory=MagicMock(return_value=self.connection),
            mongo_bundle_factory=MagicMock(side_effect=RuntimeError("bad")),
            mongo_indexer=MagicMock(),
            sqlite_repositories=self.sqlite_bundle,
        )
        with self.assertRaises(RuntimeError):
            context.connect("mongodb://host", "atlas")
        self.connection.client.close.assert_called_once_with()
        self.assertEqual(context.active_backend, StorageBackend.SQLITE)
        self.assertIs(context.learning, context.sqlite_repositories.learning)

    def test_storage_connect_activates_prepared_saver_before_old_close(
        self,
    ) -> None:
        controller = MagicMock()
        mongo_saver = MagicMock()
        controller.prepare_mongo.return_value = mongo_saver
        context = make_context(
            sqlite_path=self.db_path,
            mongo_factory=MagicMock(return_value=self.connection),
            mongo_bundle_factory=MagicMock(return_value=make_bundle("mongo")),
            mongo_indexer=MagicMock(),
            sqlite_repositories=self.sqlite_bundle,
            checkpointer_controller=controller,
        )

        context.connect("mongodb://host", "atlas")

        controller.prepare_mongo.assert_called_once_with(
            self.connection.client,
            "atlas",
        )
        controller.activate.assert_called_once_with(mongo_saver)

    def test_storage_disconnect_restores_sqlite_graph(self) -> None:
        controller = MagicMock()
        context = make_context(
            sqlite_path=self.db_path,
            mongo_factory=MagicMock(return_value=self.connection),
            mongo_bundle_factory=MagicMock(return_value=make_bundle("mongo")),
            mongo_indexer=MagicMock(),
            sqlite_repositories=self.sqlite_bundle,
            checkpointer_controller=controller,
        )
        context.connect("mongodb://host", "atlas")
        controller.reset_mock()
        context.disconnect()
        controller.activate_sqlite.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
