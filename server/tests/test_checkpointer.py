"""
============================================================================
FILE: test_checkpointer.py
LOCATION: server/tests/test_checkpointer.py
============================================================================
PURPOSE:
    Unit tests for CheckpointerController and MongoDBSaver wiring.
ROLE IN PROJECT:
    TDD guard for Phase 4 Mongo checkpointer and graph switch.
    - Shared client + fixed collection names for MongoDBSaver
    - Graph rebuild on activate / activate_sqlite
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.database.checkpointer
USAGE:
    python -m unittest server.tests.test_checkpointer -v
============================================================================
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from server.database.checkpointer import CheckpointerController


class CheckpointerControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sqlite_saver = MagicMock()
        self.app_state = SimpleNamespace()
        self.builder = MagicMock(side_effect=lambda checkpointer: (
            "graph",
            checkpointer,
        ))
        self.controller = CheckpointerController(
            app_state=self.app_state,
            sqlite_saver=self.sqlite_saver,
            graph_builder=self.builder,
        )

    @patch("server.database.checkpointer.MongoDBSaver")
    def test_prepare_mongo_uses_shared_client_and_fixed_collections(
        self,
        saver_type,
    ) -> None:
        client = MagicMock()
        saver = MagicMock()
        saver_type.return_value = saver
        prepared = self.controller.prepare_mongo(client, "a2ui")

        saver_type.assert_called_once_with(
            client,
            db_name="a2ui",
            checkpoint_collection_name="checkpoints",
            writes_collection_name="checkpoint_writes",
        )
        self.assertIs(prepared, saver)

    def test_activate_rebuilds_graph_and_updates_app_state(self) -> None:
        saver = MagicMock()
        self.controller.activate(saver)
        self.assertIs(self.app_state.checkpointer, saver)
        self.assertEqual(self.app_state.course_graph, ("graph", saver))

    def test_activate_sqlite_restores_original_saver(self) -> None:
        self.controller.activate(MagicMock())
        self.controller.activate_sqlite()
        self.assertIs(self.app_state.checkpointer, self.sqlite_saver)


if __name__ == "__main__":
    unittest.main()
