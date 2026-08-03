"""
============================================================================
FILE: migrate_to_mongo.py
LOCATION: server/database/migrate_to_mongo.py
============================================================================
PURPOSE:
    One-way idempotent SQLite-to-Mongo migration for app tables and
    LangGraph checkpoints, plus app-settings snapshot writes.
ROLE IN PROJECT:
    Phase 5 migrate service used by storage REST API.
    - Converts rows (JSON text → BSON, IDs → _id, booleans)
    - Batched unordered ReplaceOne upserts
    - Copies checkpoints via public saver APIs
KEY COMPONENTS:
    - MIGRATION_TABLES / row_to_document: mapping metadata and conversion
    - bulk_upsert / migrate_table: batch idempotent collection copy
    - migrate_to_mongo: full orchestration entry point
DEPENDENCIES:
    - External: pymongo, sqlite3
    - Internal: server.database.checkpoint_migration
USAGE:
    summary = await migrate_to_mongo(...)
============================================================================
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from pymongo import ReplaceOne

MIGRATION_BATCH_SIZE = 500
MIGRATION_TABLES = (
    "learning_sessions",
    "concept_nodes",
    "quiz_data",
    "quiz_attempts",
    "revision_sessions",
    "revision_node_progress",
    "generation_jobs",
    "generation_briefs",
    "node_sources",
    "research_reports",
    "research_sources",
    "research_sections",
    "research_section_sources",
    "research_provider_statuses",
    "progress_events",
)

JSON_COLUMNS = {
    "concept_nodes": {"key_terms": "key_terms"},
    "quiz_data": {"payload": "payload"},
    "generation_jobs": {
        "cursor_json": "cursor",
        "counts_json": "counts",
        "warnings_json": "warnings",
    },
    "generation_briefs": {"payload_json": "payload"},
    "research_reports": {
        "limitations_json": "limitations",
        "warnings_json": "warnings",
    },
    "progress_events": {"payload_json": "payload"},
}

BOOLEAN_COLUMNS = {
    "learning_sessions": {"title_finalized"},
    "concept_nodes": {"retry_available"},
    "generation_jobs": {
        "web_search_requested",
        "cancel_requested",
    },
    "quiz_attempts": {"is_correct"},
}


def row_to_document(
    table: str,
    row: dict[str, Any],
    *,
    warnings: Optional[list[str]] = None,
) -> dict[str, Any]:
    document = dict(row)
    identifier = document.pop("id", None)
    if identifier is not None:
        document["_id"] = identifier
    elif table == "node_sources":
        document["_id"] = (
            f"{document['node_id']}::{document['source_id']}"
        )
    elif table == "research_section_sources":
        document["_id"] = (
            f"{document['section_id']}::{document['source_id']}"
        )
    elif table == "research_provider_statuses":
        document["_id"] = (
            f"{document['report_id']}::{document['provider_id']}"
        )
    else:
        raise ValueError(f"No migration key for table {table}")

    for source, target in JSON_COLUMNS.get(table, {}).items():
        raw = document.pop(source, None)
        if isinstance(raw, str):
            try:
                document[target] = json.loads(raw)
            except json.JSONDecodeError:
                document[target] = raw
                if warnings is not None:
                    warnings.append(
                        f"{table}.{source} kept as invalid JSON string"
                    )
        else:
            document[target] = raw
    if table == "quiz_attempts":
        selected = document.get("selected_option_id")
        if isinstance(selected, str) and selected.startswith("["):
            try:
                document["selected_option_id"] = json.loads(selected)
            except json.JSONDecodeError:
                pass
    for column in BOOLEAN_COLUMNS.get(table, set()):
        if document.get(column) is not None:
            document[column] = bool(document[column])
    return document
