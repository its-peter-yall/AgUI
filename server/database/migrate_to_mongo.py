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


@dataclass(frozen=True)
class CollectionMigrationSummary:
    collection: str
    rows: int
    matched: int
    upserted: int
    modified: int


class MigrationError(RuntimeError):
    def __init__(self, collection: str) -> None:
        super().__init__(f"Migration failed for {collection}")
        self.collection = collection


class _EmptyBulkResult:
    matched_count = 0
    upserted_count = 0
    modified_count = 0


def iter_batches(
    values: Iterable[Any],
    size: int = MIGRATION_BATCH_SIZE,
) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def bulk_upsert(collection: Any, documents: list[dict[str, Any]]) -> Any:
    operations = [
        ReplaceOne({"_id": item["_id"]}, item, upsert=True)
        for item in documents
    ]
    if not operations:
        return _EmptyBulkResult()
    return collection.bulk_write(operations, ordered=False)


def migrate_table(
    connection: sqlite3.Connection,
    collection: Any,
    table: str,
    warnings: list[str],
) -> CollectionMigrationSummary:
    matched = 0
    upserted = 0
    modified = 0
    rows = 0
    try:
        cursor = connection.execute(f"SELECT * FROM {table}")
        while True:
            batch_rows = cursor.fetchmany(MIGRATION_BATCH_SIZE)
            if not batch_rows:
                break
            documents = [
                row_to_document(
                    table,
                    dict(row),
                    warnings=warnings,
                )
                for row in batch_rows
            ]
            result = bulk_upsert(collection, documents)
            matched += int(getattr(result, "matched_count", 0) or 0)
            upserted += int(getattr(result, "upserted_count", 0) or 0)
            modified += int(getattr(result, "modified_count", 0) or 0)
            rows += len(documents)
    except MigrationError:
        raise
    except Exception as exc:
        raise MigrationError(table) from exc
    return CollectionMigrationSummary(
        collection=table,
        rows=rows,
        matched=matched,
        upserted=upserted,
        modified=modified,
    )
