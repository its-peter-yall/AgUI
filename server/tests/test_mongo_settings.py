"""
============================================================================
FILE: test_mongo_settings.py
LOCATION: server/tests/test_mongo_settings.py
============================================================================
PURPOSE:
    Unit tests for Mongo plaintext app settings repository.
ROLE IN PROJECT:
    Phase 3B coverage for mongo_settings without live Atlas.
KEY COMPONENTS:
    - MongoSettingsTests: fixed document IDs and payload-only reads
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.database.repositories.mongo_settings
USAGE:
    python -m unittest server.tests.test_mongo_settings -v
============================================================================
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from server.database.repositories.mongo_settings import (
    MongoAppSettingsRepository,
)


class MongoSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = MagicMock()
        self.database = MagicMock()
        self.database.__getitem__.side_effect = lambda name: {
            "app_settings": self.settings,
        }[name]
        self.repository = MongoAppSettingsRepository(self.database)

    def test_put_provider_settings_uses_fixed_document_id(self) -> None:
        payload = {"activeProvider": "openrouter", "providers": {}}
        self.repository.put_provider_settings(payload)
        args = self.settings.update_one.call_args.args
        self.assertEqual(args[0], {"_id": "provider_settings"})
        self.assertEqual(args[1]["$set"]["payload"], payload)

    def test_get_web_search_settings_returns_payload_only(self) -> None:
        self.settings.find_one.return_value = {
            "_id": "web_search_settings",
            "payload": {"masterEnabled": False, "providers": {}},
        }
        result = self.repository.get_web_search_settings()
        self.assertEqual(result["masterEnabled"], False)


if __name__ == "__main__":
    unittest.main()
