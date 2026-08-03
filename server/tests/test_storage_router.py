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
from unittest.mock import MagicMock

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
    )


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


if __name__ == "__main__":
    unittest.main()
