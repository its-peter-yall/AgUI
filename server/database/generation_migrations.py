"""
============================================================================
FILE: generation_migrations.py
LOCATION: server/database/generation_migrations.py
============================================================================
PURPOSE:
    Versioned startup migration creating generation, research, brief,
    citation, and progress-event schema on fresh and existing databases.
ROLE IN PROJECT:
    Single entry point that evolves legacy learning tables and adds focused
    generation tables before any focused store runs.
    - Adds title_finalized and generation_status columns
    - Adds a unique per-session node sequence index
    - Runs inside one transaction so failures leave no partial schema
KEY COMPONENTS:
    - GenerationMigrationError: Raised for unsafe or failed migrations
    - initialize_generation_schema: Idempotent versioned migration
DEPENDENCIES:
    - External: sqlite3, logging
    - Internal: server.database.persistence, server.database.sqlite_utils
USAGE:
    from server.database.generation_migrations import initialize_generation_schema
    initialize_generation_schema()
============================================================================
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.database.persistence import DB_PATH
from server.database.sqlite_utils import connect_database, database_transaction

logger = logging.getLogger(__name__)

CURRENT_GENERATION_SCHEMA_VERSION = 1

GENERATION_JOBS_COLUMNS = """
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE,
    thread_id TEXT NOT NULL UNIQUE,
    stage TEXT NOT NULL,
    resume_stage TEXT,
    web_search_requested INTEGER NOT NULL DEFAULT 0,
    grounding_status TEXT NOT NULL DEFAULT 'DISABLED',
    cursor_json TEXT NOT NULL,
    counts_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    lock_owner TEXT,
    lock_version INTEGER NOT NULL DEFAULT 0,
    lock_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES learning_sessions(id)
        ON DELETE CASCADE
"""

GENERATION_DDL: tuple[tuple[str, str], ...] = (
    ("generation_jobs", GENERATION_JOBS_COLUMNS),
    (
        "research_reports",
        """
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,
        summary TEXT,
        limitations_json TEXT NOT NULL DEFAULT '[]',
        freshness_note TEXT,
        warnings_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES learning_sessions(id)
            ON DELETE CASCADE
        """,
    ),
    (
        "research_sources",
        """
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        canonical_url TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        publisher TEXT,
        published_at TEXT,
        retrieved_at TEXT NOT NULL,
        provider_id TEXT NOT NULL,
        snippet TEXT NOT NULL DEFAULT '',
        excerpt TEXT NOT NULL DEFAULT '',
        relevance_score REAL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (session_id, canonical_url),
        UNIQUE (session_id, content_hash),
        FOREIGN KEY (session_id) REFERENCES learning_sessions(id)
            ON DELETE CASCADE
        """,
    ),
    (
        "research_sections",
        """
        id TEXT PRIMARY KEY,
        report_id TEXT NOT NULL,
        sequence_index INTEGER NOT NULL,
        theme TEXT NOT NULL,
        markdown TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (report_id, sequence_index),
        FOREIGN KEY (report_id) REFERENCES research_reports(id)
            ON DELETE CASCADE
        """,
    ),
    (
        "research_section_sources",
        """
        section_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        PRIMARY KEY (section_id, source_id),
        FOREIGN KEY (section_id) REFERENCES research_sections(id)
            ON DELETE CASCADE,
        FOREIGN KEY (source_id) REFERENCES research_sources(id)
            ON DELETE CASCADE
        """,
    ),
    (
        "research_provider_statuses",
        """
        report_id TEXT NOT NULL,
        provider_id TEXT NOT NULL,
        state TEXT NOT NULL,
        search_calls INTEGER NOT NULL,
        result_count INTEGER NOT NULL,
        error_class TEXT,
        PRIMARY KEY (report_id, provider_id),
        FOREIGN KEY (report_id) REFERENCES research_reports(id)
            ON DELETE CASCADE
        """,
    ),
    (
        "generation_briefs",
        """
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        node_id TEXT NOT NULL UNIQUE,
        topic_index INTEGER NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (session_id, topic_index),
        FOREIGN KEY (session_id) REFERENCES learning_sessions(id)
            ON DELETE CASCADE,
        FOREIGN KEY (node_id) REFERENCES concept_nodes(id)
            ON DELETE CASCADE
        """,
    ),
    (
        "node_sources",
        """
        node_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        citation_order INTEGER NOT NULL,
        claim TEXT NOT NULL,
        PRIMARY KEY (node_id, source_id),
        UNIQUE (node_id, citation_order),
        FOREIGN KEY (node_id) REFERENCES concept_nodes(id)
            ON DELETE CASCADE,
        FOREIGN KEY (source_id) REFERENCES research_sources(id)
            ON DELETE CASCADE
        """,
    ),
    (
        "progress_events",
        """
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        dedupe_key TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (session_id, dedupe_key),
        FOREIGN KEY (session_id) REFERENCES learning_sessions(id)
            ON DELETE CASCADE
        """,
    ),
)


class GenerationMigrationError(RuntimeError):
    """Raised when the generation schema cannot be applied safely."""


def _execute_ddl(
    conn: sqlite3.Connection,
    sql: str,
    parameters: tuple[Any, ...] = (),
) -> Any:
    """Execute one DDL statement; kept as a seam for failure injection."""
    return conn.execute(sql, parameters)


def _column_names(
    conn: sqlite3.Connection, table_name: str
) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table_name: str,
    column_sql: str,
    column_name: str,
) -> None:
    if column_name not in _column_names(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def initialize_generation_schema(db_path: Path = DB_PATH) -> None:
    """Create generation schema and evolve legacy tables inside one transaction.

    Args:
        db_path: Path to the SQLite database file.

    Raises:
        GenerationMigrationError: Duplicate node sequence rows block the
            unique index, or a foreign-key violation survives migration.
        sqlite3.Error: Any statement-level failure rolls the migration back.
    """
    logger.info("Initializing generation schema at %s", db_path)
    with database_transaction(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS generation_schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        existing = conn.execute(
            "SELECT version FROM generation_schema_migrations"
        ).fetchall()
        if any(
            row["version"] == CURRENT_GENERATION_SCHEMA_VERSION for row in existing
        ):
            logger.info("Generation schema already at version %d", 1)
            return

        duplicate_rows = conn.execute(
            """
            SELECT learning_session_id, sequence_index
            FROM concept_nodes
            GROUP BY learning_session_id, sequence_index
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        ).fetchall()
        if duplicate_rows:
            raise GenerationMigrationError(
                "Duplicate concept-node sequence rows block generation migration"
            )

        _add_column_if_missing(
            conn,
            "learning_sessions",
            "title_finalized INTEGER NOT NULL DEFAULT 1",
            "title_finalized",
        )
        _add_column_if_missing(
            conn,
            "concept_nodes",
            "generation_status TEXT NOT NULL DEFAULT 'READY'",
            "generation_status",
        )

        for table_name, columns in GENERATION_DDL:
            _execute_ddl(
                conn,
                f"CREATE TABLE {table_name} ({columns})",
            )

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                uq_concept_nodes_session_sequence
            ON concept_nodes(learning_session_id, sequence_index)
            """
        )

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise GenerationMigrationError(
                "Foreign-key violations block generation migration"
            )

        applied_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO generation_schema_migrations (version, applied_at)"
            " VALUES (?, ?)",
            (CURRENT_GENERATION_SCHEMA_VERSION, applied_at),
        )
    logger.info("Generation schema migration %d applied", 1)
