"""
============================================================================
FILE: test_mongo_client.py
LOCATION: server/tests/test_mongo_client.py
============================================================================
PURPOSE:
    Unit tests for safe sync Mongo client lifecycle and URI redaction.
ROLE IN PROJECT:
    TDD guard for Phase 1 MongoDB Atlas storage client layer.
    - Password redaction for standard and SRV URIs
    - Ping-validated connect with cleanup on failure
    - Mapped errors without leaking credentials
DEPENDENCIES:
    - External: unittest, unittest.mock, pymongo
    - Internal: server.database.mongo_client
USAGE:
    python -m unittest server.tests.test_mongo_client -v
============================================================================
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pymongo.errors import (
    ConfigurationError,
    OperationFailure,
    ServerSelectionTimeoutError,
)

from server.database.mongo_client import (
    MongoConfigurationError,
    MongoUnavailableError,
    connect_mongo,
    redact_mongo_uri,
)


class MongoClientTests(unittest.TestCase):
    def test_redacts_standard_and_srv_passwords(self) -> None:
        cases = {
            "mongodb://alice:secret@host/db":
                "mongodb://alice:***@host/db",
            "mongodb+srv://bob:p%40ss@cluster/db":
                "mongodb+srv://bob:***@cluster/db",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(redact_mongo_uri(raw), expected)

    def test_returns_client_and_database_after_ping(self) -> None:
        client = MagicMock()
        database = client.__getitem__.return_value
        with patch(
            "server.database.mongo_client.MongoClient",
            return_value=client,
        ):
            connection = connect_mongo("mongodb://host", "a2ui")

        client.admin.command.assert_called_once_with("ping")
        self.assertIs(connection.client, client)
        self.assertIs(connection.database, database)
        self.assertEqual(connection.db_name, "a2ui")

    def test_closes_client_on_configuration_failure(self) -> None:
        client = MagicMock()
        client.admin.command.side_effect = ConfigurationError("bad URI")
        with patch(
            "server.database.mongo_client.MongoClient",
            return_value=client,
        ):
            with self.assertRaises(MongoConfigurationError):
                connect_mongo("mongodb://user:secret@host", "a2ui")
        client.close.assert_called_once_with()

    def test_maps_auth_failure_without_exposing_driver_detail(self) -> None:
        client = MagicMock()
        client.admin.command.side_effect = OperationFailure(
            "Authentication failed for user:secret"
        )
        with patch(
            "server.database.mongo_client.MongoClient",
            return_value=client,
        ):
            with self.assertRaises(MongoConfigurationError) as caught:
                connect_mongo("mongodb://user:secret@host", "a2ui")
        self.assertNotIn("secret", str(caught.exception))
        client.close.assert_called_once_with()

    def test_maps_timeout_without_leaking_uri(self) -> None:
        client = MagicMock()
        client.admin.command.side_effect = ServerSelectionTimeoutError(
            "mongodb://user:secret@host timed out"
        )
        with patch(
            "server.database.mongo_client.MongoClient",
            return_value=client,
        ):
            with self.assertRaises(MongoUnavailableError) as caught:
                connect_mongo("mongodb://user:secret@host", "a2ui")
        self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
