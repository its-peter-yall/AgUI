"""
============================================================================
FILE: test_sqlite_repositories.py
LOCATION: server/tests/test_sqlite_repositories.py
============================================================================
PURPOSE:
    Delegation tests for thin SQLite repository adapters and local app
    settings unavailability contract.
ROLE IN PROJECT:
    TDD guard for Phase 2A SQLite repository wrappers.
    - Ensures adapters forward public calls to wrapped stores
    - Ensures local app settings stay browser-owned on SQLite backend
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.database.repositories
USAGE:
    python -m unittest server.tests.test_sqlite_repositories -v
============================================================================
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from server.database.repositories.errors import (
    RepositoryUnavailableError,
)
from server.database.repositories.sqlite import (
    LocalAppSettingsRepository,
    SqliteGenerationArtifactRepository,
    SqliteGenerationJobRepository,
    SqliteLearningRepository,
    SqliteProgressEventRepository,
    SqliteResearchRepository,
)


class SqliteRepositoryTests(unittest.TestCase):
    def test_each_adapter_delegates_to_wrapped_store(self) -> None:
        cases = (
            (SqliteLearningRepository, "get_learning_session", ("s1",)),
            (SqliteGenerationJobRepository, "get_by_session", ("s1",)),
            (SqliteGenerationArtifactRepository, "get_brief", ("n1",)),
            (SqliteResearchRepository, "get_report", ("s1",)),
            (SqliteProgressEventRepository, "latest_id", ("s1",)),
        )
        for adapter_type, method_name, args in cases:
            store = MagicMock()
            getattr(store, method_name).return_value = "sentinel"
            adapter = adapter_type(store)
            with self.subTest(adapter=adapter_type.__name__):
                result = getattr(adapter, method_name)(*args)
                self.assertEqual(result, "sentinel")
                getattr(store, method_name).assert_called_once_with(*args)

    def test_local_app_settings_is_explicitly_unavailable(self) -> None:
        repository = LocalAppSettingsRepository()
        with self.assertRaises(RepositoryUnavailableError):
            repository.get_provider_settings()


if __name__ == "__main__":
    unittest.main()
