"""
============================================================================
FILE: mongo_indexes.py
LOCATION: server/database/repositories/mongo_indexes.py
============================================================================
PURPOSE:
    Idempotent application-level Mongo indexes for learning collections.
ROLE IN PROJECT:
    Ensures lookup and uniqueness constraints equivalent to SQLite indexes
    when Atlas mode is active. Called after successful connect/migrate.
DEPENDENCIES:
    - External: None (duck-typed Database)
    - Internal: None
USAGE:
    from server.database.repositories.mongo_indexes import (
        ensure_learning_indexes,
    )
    ensure_learning_indexes(database)
============================================================================
"""
from __future__ import annotations

from typing import Any


def ensure_learning_indexes(database: Any) -> None:
    """Create learning collection indexes; safe to call repeatedly."""

    database["learning_sessions"].create_index([("user_id", 1)])
    database["learning_sessions"].create_index([("updated_at", -1)])
    database["concept_nodes"].create_index(
        [("learning_session_id", 1)]
    )
    database["concept_nodes"].create_index(
        [("learning_session_id", 1), ("sequence_index", 1)],
        unique=True,
    )
    database["quiz_data"].create_index([("node_id", 1)])
    database["quiz_attempts"].create_index([("node_id", 1)])
    database["quiz_attempts"].create_index(
        [("node_id", 1), ("attempt_number", 1)]
    )
    database["quiz_attempts"].create_index(
        [("revision_session_id", 1)]
    )
    database["revision_sessions"].create_index(
        [("original_session_id", 1)]
    )
    database["revision_node_progress"].create_index(
        [("revision_session_id", 1)]
    )
    database["revision_node_progress"].create_index(
        [("revision_session_id", 1), ("node_id", 1)],
        unique=True,
    )
