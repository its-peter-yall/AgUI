"""
============================================================================
FILE: sqlite_utils.py
LOCATION: server/database/sqlite_utils.py
============================================================================
PURPOSE:
    Shared SQLite connection factory and transactional context managers for
    the focused generation persistence stores.
ROLE IN PROJECT:
    Provides the resource behavior every focused store relies on.
    - Opens connections with foreign keys, busy timeout, and autocommit off
    - Wraps caller-owned or self-owned transactions uniformly
KEY COMPONENTS:
    - connect_database: Connection factory with Row factory
    - database_transaction: Owned BEGIN IMMEDIATE transaction context
    - optional_transaction: Adapter for caller-owned connections
    - canonical_json: Deterministic compact JSON serialization
DEPENDENCIES:
    - External: sqlite3, json
    - Internal: server.database.persistence
USAGE:
    with optional_transaction(self.db_path, conn) as active_conn:
        active_conn.execute(...)
============================================================================
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional, Union

from pydantic import BaseModel

from server.database.persistence import DB_PATH


def connect_database(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(db_path),
        timeout=5.0,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def database_transaction(
    db_path: Path = DB_PATH,
) -> Iterator[sqlite3.Connection]:
    conn = connect_database(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def optional_transaction(
    db_path: Path,
    conn: Optional[sqlite3.Connection],
) -> Iterator[sqlite3.Connection]:
    if conn is not None:
        yield conn
        return
    with database_transaction(db_path) as owned_conn:
        yield owned_conn


def canonical_json(value: Union[BaseModel, dict[str, Any], list[Any]]) -> str:
    """Serialize a Pydantic model or JSON-ready value deterministically.

    Produces compact, key-sorted JSON so identical payloads round-trip to
    the same string for deduplication comparisons.
    """
    if isinstance(value, BaseModel):
        data = value.model_dump(mode="json")
    else:
        data = value
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse a stored ISO-8601 timestamp, tolerating absent values."""
    if value is None:
        return None
    return datetime.fromisoformat(value)
