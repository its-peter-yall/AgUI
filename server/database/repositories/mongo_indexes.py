"""
============================================================================
FILE: mongo_indexes.py
LOCATION: server/database/repositories/mongo_indexes.py
============================================================================
PURPOSE:
    Idempotent application-level Mongo indexes for learning and operational
    collections.
ROLE IN PROJECT:
    Ensures lookup and uniqueness constraints equivalent to SQLite indexes
    when Atlas mode is active. Called after successful connect/migrate.
DEPENDENCIES:
    - External: None (duck-typed Database)
    - Internal: None
USAGE:
    from server.database.repositories.mongo_indexes import (
        ensure_all_indexes,
    )
    ensure_all_indexes(database)
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
    database["quiz_data"].create_index(
        [("node_id", 1)],
        unique=True,
    )
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


def ensure_operational_indexes(database: Any) -> None:
    """Create generation/research/progress indexes; safe to call repeatedly."""

    database["generation_jobs"].create_index(
        [("session_id", 1)], unique=True
    )
    database["generation_jobs"].create_index(
        [("thread_id", 1)], unique=True
    )
    database["generation_briefs"].create_index(
        [("node_id", 1)], unique=True
    )
    database["generation_briefs"].create_index(
        [("session_id", 1), ("topic_index", 1)], unique=True
    )
    database["node_sources"].create_index(
        [("node_id", 1), ("source_id", 1)], unique=True
    )
    database["node_sources"].create_index(
        [("node_id", 1), ("citation_order", 1)], unique=True
    )
    database["research_reports"].create_index(
        [("session_id", 1)], unique=True
    )
    database["research_sources"].create_index(
        [("session_id", 1), ("canonical_url", 1)], unique=True
    )
    database["research_sources"].create_index(
        [("session_id", 1), ("content_hash", 1)], unique=True
    )
    database["research_sections"].create_index(
        [("report_id", 1), ("sequence_index", 1)], unique=True
    )
    database["research_section_sources"].create_index(
        [("section_id", 1), ("source_id", 1)], unique=True
    )
    database["research_provider_statuses"].create_index(
        [("report_id", 1), ("provider_id", 1)], unique=True
    )
    database["progress_events"].create_index(
        [("session_id", 1), ("dedupe_key", 1)], unique=True
    )
    database["progress_events"].create_index(
        [("session_id", 1), ("_id", 1)]
    )


def ensure_all_indexes(database: Any) -> None:
    """Create every application collection index; safe to call repeatedly."""

    ensure_learning_indexes(database)
    ensure_operational_indexes(database)
