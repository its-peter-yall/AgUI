"""
============================================================================
FILE: test_storage_schemas.py
LOCATION: server/tests/test_storage_schemas.py
============================================================================
PURPOSE:
    Contract tests for storage REST request/response Pydantic schemas.
ROLE IN PROJECT:
    TDD guard for camel-case API contracts used by storage endpoints.
    - StorageStatusResponse alias serialization
    - StorageConnectRequest camel-case input and URI validation
DEPENDENCIES:
    - External: unittest, pydantic
    - Internal: server.schemas.storage
USAGE:
    python -m unittest server.tests.test_storage_schemas -v
============================================================================
"""
from __future__ import annotations

import unittest

from pydantic import ValidationError

from server.schemas.storage import (
    AppSettingsResponse,
    StorageConnectRequest,
    StorageMigrateRequest,
    StorageStatusResponse,
)


class StorageSchemaTests(unittest.TestCase):
    def test_status_serializes_camel_case_contract(self) -> None:
        status = StorageStatusResponse(
            deployment_mode="local",
            active_backend="sqlite",
            connected=False,
            mongo_db_name=None,
            can_connect=True,
            can_disconnect=False,
            can_migrate=False,
            local_data_present=True,
        )
        payload = status.model_dump(mode="json", by_alias=True)
        self.assertEqual(payload["deploymentMode"], "local")
        self.assertEqual(payload["activeBackend"], "sqlite")
        self.assertTrue(payload["localDataPresent"])

    def test_connect_accepts_camel_case_database_name(self) -> None:
        request = StorageConnectRequest.model_validate(
            {"uri": "mongodb://host", "dbName": "a2ui"}
        )
        self.assertEqual(request.db_name, "a2ui")

    def test_connect_rejects_non_mongo_uri(self) -> None:
        with self.assertRaises(ValidationError):
            StorageConnectRequest.model_validate(
                {"uri": "https://host", "dbName": "a2ui"}
            )

    def test_migrate_request_accepts_browser_snapshots(self) -> None:
        request = StorageMigrateRequest.model_validate(
            {
                "providerSettings": {"activeProvider": "openrouter"},
                "webSearchSettings": {"masterEnabled": False},
            }
        )
        self.assertEqual(
            request.provider_settings["activeProvider"],
            "openrouter",
        )

    def test_app_settings_response_keeps_camel_case(self) -> None:
        response = AppSettingsResponse(
            provider_settings={},
            web_search_settings={},
        )
        payload = response.model_dump(mode="json", by_alias=True)
        self.assertIn("providerSettings", payload)
        self.assertIn("webSearchSettings", payload)


if __name__ == "__main__":
    unittest.main()
