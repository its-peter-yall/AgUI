"""
============================================================================
FILE: test_storage_router.py
LOCATION: server/tests/test_storage_router.py
============================================================================
PURPOSE:
    API tests for storage status/connect/disconnect endpoints and guards.
ROLE IN PROJECT:
    TDD guard for Phase 1 storage lifecycle REST API.
    - Camel-case status contract
    - Connect credential handling and error mapping
    - Cloud mode 403 on mutable endpoints
DEPENDENCIES:
    - External: unittest, unittest.mock, fastapi
    - Internal: server.routers.storage, server.database.storage_mode
USAGE:
    python -m unittest server.tests.test_storage_router -v
============================================================================
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.database.mongo_client import (
    MongoConfigurationError,
    MongoUnavailableError,
)
from server.database.storage_mode import DeploymentMode, StorageBackend
from server.routers.storage import router


def make_storage(mode: DeploymentMode) -> SimpleNamespace:
    return SimpleNamespace(
        deployment_mode=mode,
        active_backend=StorageBackend.SQLITE,
        connected=False,
        mongo_db_name=None,
        connect=MagicMock(),
        disconnect=MagicMock(),
        local_data_present=MagicMock(return_value=True),
        app_settings=MagicMock(),
        mongo_connection=None,
        checkpointer_controller=None,
        sqlite_path=None,
    )


def make_connected_storage() -> SimpleNamespace:
    storage = make_storage(DeploymentMode.LOCAL)
    storage.connected = True
    storage.active_backend = StorageBackend.MONGO
    storage.mongo_db_name = "a2ui"
    storage.mongo_connection = SimpleNamespace(
        database=MagicMock(name="database"),
    )
    storage.checkpointer_controller = SimpleNamespace(
        active_saver=MagicMock(name="mongo-saver"),
    )
    storage.sqlite_path = MagicMock(name="sqlite-path")
    return storage


def make_client(
    storage: SimpleNamespace,
    *,
    active_session_ids: list[str] | None = None,
) -> TestClient:
    app = FastAPI()
    app.state.storage = storage
    app.state.generation_runtime = SimpleNamespace(
        active_session_ids=list(active_session_ids or []),
    )
    app.include_router(router)
    return TestClient(app)


class StorageRouterTests(unittest.TestCase):
    def test_status_uses_camel_case_contract(self) -> None:
        response = make_client(
            make_storage(DeploymentMode.LOCAL)
        ).get("/settings/storage/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["activeBackend"], "sqlite")
        self.assertTrue(response.json()["canConnect"])

    def test_connect_passes_credentials_once(self) -> None:
        storage = make_storage(DeploymentMode.LOCAL)

        def connect(uri: str, db_name: str) -> None:
            storage.connected = True
            storage.active_backend = StorageBackend.MONGO
            storage.mongo_db_name = db_name

        storage.connect.side_effect = connect
        response = make_client(storage).post(
            "/settings/storage/connect",
            json={"uri": "mongodb://host", "dbName": "a2ui"},
        )

        self.assertEqual(response.status_code, 200)
        storage.connect.assert_called_once_with("mongodb://host", "a2ui")
        self.assertNotIn("uri", response.json())

    def test_cloud_rejects_mutable_endpoints(self) -> None:
        client = make_client(make_storage(DeploymentMode.CLOUD))
        connect = client.post(
            "/settings/storage/connect",
            json={"uri": "mongodb://host", "dbName": "a2ui"},
        )
        disconnect = client.post("/settings/storage/disconnect")
        self.assertEqual(connect.status_code, 403)
        self.assertEqual(disconnect.status_code, 403)

    def test_connect_maps_configuration_and_network_errors(self) -> None:
        storage = make_storage(DeploymentMode.LOCAL)
        storage.connect.side_effect = MongoConfigurationError("bad")
        bad = make_client(storage).post(
            "/settings/storage/connect",
            json={"uri": "mongodb://host", "dbName": "a2ui"},
        )
        self.assertEqual(bad.status_code, 400)

        storage.connect.side_effect = MongoUnavailableError("down")
        down = make_client(storage).post(
            "/settings/storage/connect",
            json={"uri": "mongodb://host", "dbName": "a2ui"},
        )
        self.assertEqual(down.status_code, 503)

    def test_connect_returns_409_while_generation_is_active(self) -> None:
        storage = make_storage(DeploymentMode.LOCAL)
        client = make_client(storage, active_session_ids=["s1"])
        response = client.post(
            "/settings/storage/connect",
            json={"uri": "mongodb://host", "dbName": "a2ui"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["sessionIds"], ["s1"])
        storage.connect.assert_not_called()

    def test_migrate_requires_local_mode_connected_mongo(self) -> None:
        local = make_storage(DeploymentMode.LOCAL)
        local.active_backend = StorageBackend.SQLITE
        response = make_client(local).post(
            "/settings/storage/migrate",
            json={"providerSettings": {}, "webSearchSettings": {}},
        )
        self.assertEqual(response.status_code, 409)

    def test_cloud_migrate_is_forbidden(self) -> None:
        cloud = make_storage(DeploymentMode.CLOUD)
        response = make_client(cloud).post(
            "/settings/storage/migrate",
            json={"providerSettings": {}, "webSearchSettings": {}},
        )
        self.assertEqual(response.status_code, 403)

    def test_app_settings_require_mongo_and_round_trip(self) -> None:
        storage = make_connected_storage()
        storage.app_settings.get_provider_settings.return_value = {"a": 1}
        storage.app_settings.get_web_search_settings.return_value = {"b": 2}
        client = make_client(storage)
        response = client.get("/settings/storage/app-settings")
        self.assertEqual(response.json()["providerSettings"], {"a": 1})
        update = client.put(
            "/settings/storage/app-settings",
            json={
                "providerSettings": {"a": 3},
                "webSearchSettings": {"b": 4},
            },
        )
        self.assertEqual(update.status_code, 200)
        storage.app_settings.put_provider_settings.assert_called_once_with(
            {"a": 3}
        )
        storage.app_settings.put_web_search_settings.assert_called_once_with(
            {"b": 4}
        )

    def test_migrate_passes_browser_snapshots_once(self) -> None:
        storage = make_connected_storage()
        summary = SimpleNamespace(
            collections={
                "learning_sessions": SimpleNamespace(
                    rows=1,
                    matched=0,
                    upserted=1,
                    modified=0,
                )
            },
            checkpoints=2,
            checkpoint_writes=3,
            warnings=["w1"],
        )
        with patch(
            "server.routers.storage.migrate_to_mongo",
            new_callable=AsyncMock,
            return_value=summary,
        ) as migrate:
            response = make_client(storage).post(
                "/settings/storage/migrate",
                json={
                    "providerSettings": {"activeProvider": "openrouter"},
                    "webSearchSettings": {"masterEnabled": False},
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["checkpoints"], 2)
        self.assertEqual(payload["warnings"], ["w1"])
        migrate.assert_awaited_once()
        kwargs = migrate.await_args.kwargs
        self.assertEqual(
            kwargs["provider_settings"],
            {"activeProvider": "openrouter"},
        )
        self.assertEqual(
            kwargs["web_search_settings"],
            {"masterEnabled": False},
        )


if __name__ == "__main__":
    unittest.main()
