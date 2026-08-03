"""
============================================================================
FILE: test_repository_facades.py
LOCATION: server/tests/test_repository_facades.py
============================================================================
PURPOSE:
    Tests late-bound repository facades and process storage registry identity.
ROLE IN PROJECT:
    Guards Phase 2B facade swap so consumers keep stable import identity while
    active repository bundles can change at runtime.
KEY COMPONENTS:
    - RepositoryFacadeTests: late binding, patch compatibility, registry identity
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.database.repositories.facade, storage_registry
USAGE:
    python -m unittest server.tests.test_repository_facades -v
============================================================================
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

from server.database.repositories.facade import RepositoryFacade


class RepositoryFacadeTests(unittest.TestCase):
    def test_resolves_current_target_for_every_attribute(self) -> None:
        first = MagicMock()
        second = MagicMock()
        first.read.return_value = "sqlite"
        second.read.return_value = "mongo"
        holder = SimpleNamespace(current=first)
        facade = RepositoryFacade(lambda: holder.current)

        self.assertEqual(facade.read(), "sqlite")
        holder.current = second
        self.assertEqual(facade.read(), "mongo")
        first.read.assert_called_once_with()
        second.read.assert_called_once_with()

    def test_patch_object_can_override_facade_method(self) -> None:
        target = MagicMock()
        facade = RepositoryFacade(lambda: target)
        facade.read = MagicMock(return_value="patched")

        self.assertEqual(facade.read(), "patched")

    def test_registry_facades_point_at_context_bundle(self) -> None:
        from server.database.storage_registry import (
            learning_repository,
            storage_context,
        )

        expected = MagicMock(return_value={"id": "s1"})
        original = storage_context._repositories
        fake = replace(original, learning=MagicMock())
        fake.learning.get_learning_session = expected
        try:
            storage_context._repositories = fake
            result = learning_repository.get_learning_session("s1")
        finally:
            storage_context._repositories = original

        self.assertEqual(result, {"id": "s1"})
        expected.assert_called_once_with("s1")

    def test_production_modules_import_repository_facades(self) -> None:
        from server.database.storage_registry import learning_repository
        from server.graph import nodes, regen, regen_stream, runner
        from server.routers import learning

        modules = (nodes, regen, regen_stream, runner, learning)
        for module in modules:
            with self.subTest(module=module.__name__):
                self.assertIs(module.learning_manager, learning_repository)


if __name__ == "__main__":
    unittest.main()
