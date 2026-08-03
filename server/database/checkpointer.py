"""
============================================================================
FILE: checkpointer.py
LOCATION: server/database/checkpointer.py
============================================================================
PURPOSE:
    Prepare MongoDBSaver and atomically replace app-state graph bindings.
ROLE IN PROJECT:
    Phase 4 checkpointer controller for storage backend switches.
    - Builds MongoDBSaver on shared PyMongo client with fixed collections
    - Rebuilds course graph whenever active saver changes
KEY COMPONENTS:
    - CheckpointerController: prepare_mongo, activate, activate_sqlite
DEPENDENCIES:
    - External: langgraph-checkpoint-mongodb (MongoDBSaver)
    - Internal: None
USAGE:
    controller = CheckpointerController(
        app_state=app.state,
        sqlite_saver=checkpointer,
        graph_builder=lambda s: build_graph(checkpointer=s),
    )
============================================================================
"""
from __future__ import annotations

from typing import Any, Callable

from langgraph.checkpoint.mongodb import MongoDBSaver


class CheckpointerController:
    """Prepare savers and atomically replace app-state graph bindings."""

    def __init__(
        self,
        *,
        app_state: Any,
        sqlite_saver: Any,
        graph_builder: Callable[[Any], Any],
    ) -> None:
        self._app_state = app_state
        self.sqlite_saver = sqlite_saver
        self._graph_builder = graph_builder
        self.active_saver = sqlite_saver

    def prepare_mongo(self, client: Any, db_name: str) -> MongoDBSaver:
        return MongoDBSaver(
            client,
            db_name=db_name,
            checkpoint_collection_name="checkpoints",
            writes_collection_name="checkpoint_writes",
        )

    def activate(self, saver: Any) -> None:
        graph = self._graph_builder(saver)
        self._app_state.checkpointer = saver
        self._app_state.course_graph = graph
        self.active_saver = saver

    def activate_sqlite(self) -> None:
        self.activate(self.sqlite_saver)
