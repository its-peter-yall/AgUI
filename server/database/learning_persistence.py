"""
============================================================================
FILE: learning_persistence.py
LOCATION: server/database/learning_persistence.py
============================================================================
PURPOSE:
    SQLite persistence layer for the adaptive learning system. Manages
    storage for learning sessions, concept nodes, quizzes, and mastery
    tracking with enforced state transitions.
ROLE IN PROJECT:
    Core data layer for the learning feature, consumed by the LangGraph
    course graph and learning router.
    - Enforces sequential node progression through a state machine
    - Provides quiz attempt tracking for mastery evaluation
KEY COMPONENTS:
    - LearningManager: Main class handling all database operations
    - learning_manager: Module-level singleton instance
DEPENDENCIES:
    - External: sqlite3, uuid, json, pydantic
    - Internal: server.database.persistence.DB_PATH,
                server.schemas.learning
USAGE:
    ```python
    from server.database.learning_persistence import learning_manager

    session = learning_manager.create_learning_session(
        query="Learn Python basics",
        course_title="Python Fundamentals"
    )
    node = learning_manager.create_concept_node(
        session_id=session["id"],
        sequence_index=0,
        title="Variables and Data Types",
        content_markdown="# Variables\n...",
        status=NodeStatus.VIEWING_EXPLANATION
    )
    ```
============================================================================
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from server.database.persistence import DB_PATH
from server.schemas.learning import (
    FailedStep,
    NodeStatus,
    QuizCard,
    QuizSet,
    convert_legacy_to_quiz_set,
)

logger = logging.getLogger(__name__)


class LearningManager:
    """Manages SQLite persistence for learning sessions and concept nodes."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_learning_tables(self) -> None:
        """Create learning tables if they do not exist."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    query TEXT NOT NULL,
                    course_title TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'auto',
                    resolved_mode TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS concept_nodes (
                    id TEXT PRIMARY KEY,
                    learning_session_id TEXT NOT NULL,
                    sequence_index INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    content_markdown TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    retry_available INTEGER DEFAULT 0,
                    failed_step TEXT,
                    summary_for_context TEXT,
                    key_terms TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (learning_session_id)
                        REFERENCES learning_sessions(id)
                        ON DELETE CASCADE
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS quiz_data (
                    id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    format_version INTEGER,
                    shuffle_seed TEXT,
                    current_index INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (node_id)
                        REFERENCES concept_nodes(id)
                        ON DELETE CASCADE
                )
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_learning_sessions_user_id
                ON learning_sessions(user_id)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_concept_nodes_session_id
                ON concept_nodes(learning_session_id)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_concept_nodes_sequence
                ON concept_nodes(learning_session_id, sequence_index)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_quiz_data_node_id
                ON quiz_data(node_id)
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS revision_sessions (
                    id TEXT PRIMARY KEY,
                    original_session_id TEXT NOT NULL,
                    revision_number INTEGER NOT NULL DEFAULT 1,
                    mode TEXT NOT NULL DEFAULT 'full_review',
                    status TEXT NOT NULL DEFAULT 'in_progress',
                    progress_percent INTEGER NOT NULL DEFAULT 0,
                    total_quiz_score_percent INTEGER,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    FOREIGN KEY (original_session_id)
                        REFERENCES learning_sessions(id)
                        ON DELETE CASCADE
                )
                """
            )
            # Quiz attempts table for mastery tracking
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS quiz_attempts (
                    id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    quiz_index INTEGER DEFAULT 0,
                    revision_session_id TEXT,
                    selected_option_id TEXT NOT NULL,
                    is_correct INTEGER NOT NULL,
                    score_percent INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (node_id)
                        REFERENCES concept_nodes(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (revision_session_id)
                        REFERENCES revision_sessions(id)
                        ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS revision_node_progress (
                    id TEXT PRIMARY KEY,
                    revision_session_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reviewed_at TIMESTAMP,
                    FOREIGN KEY (revision_session_id)
                        REFERENCES revision_sessions(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (node_id)
                        REFERENCES concept_nodes(id)
                        ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_quiz_attempts_node_id
                ON quiz_attempts(node_id)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_quiz_attempts_node_attempt
                ON quiz_attempts(node_id, attempt_number)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_revision_original_session_id
                ON revision_sessions(original_session_id)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_revision_node_progress_session_id
                ON revision_node_progress(revision_session_id)
                """
            )

            self._ensure_concept_node_columns(conn)
            self._ensure_session_progress_columns(conn)
            self._ensure_node_timestamp_columns(conn)
            self._ensure_quiz_data_columns(conn)
            self._ensure_quiz_attempts_columns(conn)
            self._ensure_quiz_attempts_revision_column(conn)

            conn.commit()
            logger.info("Learning tables initialized successfully")
        except sqlite3.Error as e:
            logger.error(f"Error initializing learning tables: {e}")
            raise
        finally:
            conn.close()

    def create_learning_session(
        self,
        query: str,
        course_title: str,
        user_id: Optional[str] = None,
        mode: str = "auto",
        resolved_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        conn = self._get_connection()
        try:
            session_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO learning_sessions (
                    id, user_id, query, course_title, mode, resolved_mode,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    query,
                    course_title,
                    mode,
                    resolved_mode,
                    now,
                    now,
                ),
            )
            conn.commit()
            logger.info(f"Created learning session: {session_id}")
            return {
                "id": session_id,
                "user_id": user_id,
                "query": query,
                "course_title": course_title,
                "mode": mode,
                "resolved_mode": resolved_mode,
                "created_at": now,
                "updated_at": now,
                "total_nodes": 0,
                "completed_nodes": 0,
            }
        except sqlite3.Error as e:
            logger.error(f"Error creating learning session: {e}")
            raise
        finally:
            conn.close()

    def get_learning_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    ls.id,
                    ls.user_id,
                    ls.query,
                    ls.course_title,
                    ls.title_finalized,
                    ls.mode,
                    ls.resolved_mode,
                    ls.last_active_node_id,
                    ls.created_at,
                    ls.updated_at,
                    COUNT(cn.id) AS total_nodes,
                    SUM(CASE WHEN cn.status = ? THEN 1 ELSE 0 END) AS completed_nodes
                FROM learning_sessions ls
                LEFT JOIN concept_nodes cn ON ls.id = cn.learning_session_id
                WHERE ls.id = ?
                GROUP BY ls.id
                """,
                (NodeStatus.COMPLETED.value, session_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            title_finalized = row["title_finalized"]
            if title_finalized is None:
                title_finalized = 1
            return {
                "id": row["id"],
                "user_id": row["user_id"],
                "query": row["query"],
                "course_title": row["course_title"],
                "title_finalized": bool(title_finalized),
                "mode": row["mode"],
                "resolved_mode": row["resolved_mode"],
                "last_active_node_id": row["last_active_node_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "total_nodes": row["total_nodes"],
                "completed_nodes": row["completed_nodes"] or 0,
            }
        except sqlite3.Error as e:
            logger.error(f"Error getting learning session: {e}")
            raise
        finally:
            conn.close()

    def get_session_progress(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get progress summary for a single learning session."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                WITH node_counts AS (
                    SELECT
                        learning_session_id,
                        COUNT(*) AS total_nodes,
                        SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS completed_nodes
                    FROM concept_nodes
                    WHERE learning_session_id = ?
                    GROUP BY learning_session_id
                )
                SELECT
                    ls.status,
                    COALESCE(nc.completed_nodes, 0) AS completed_nodes,
                    COALESCE(nc.total_nodes, 0) AS total_nodes,
                    ls.last_active_node_id,
                    cn.title AS last_active_node_title
                FROM learning_sessions ls
                LEFT JOIN node_counts nc ON ls.id = nc.learning_session_id
                LEFT JOIN concept_nodes cn ON ls.last_active_node_id = cn.id
                WHERE ls.id = ?
                """,
                (NodeStatus.COMPLETED.value, session_id, session_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            total = int(row["total_nodes"] or 0)
            completed = int(row["completed_nodes"] or 0)
            progress = self._calculate_progress_percent(completed, total)
            return {
                "progress_percent": progress,
                "status": row["status"] or "in_progress",
                "completed_nodes": completed,
                "total_nodes": total,
                "last_active_node_id": row["last_active_node_id"],
                "last_active_node_title": row["last_active_node_title"],
            }
        except sqlite3.Error as e:
            logger.error(f"Error getting session progress: {e}")
            raise
        finally:
            conn.close()

    def get_sessions_list(
        self,
        user_id: Optional[str] = None,
        status: str = "all",
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[List[Dict[str, Any]], int]:
        """Get paginated learning sessions with progress and revision data."""
        conn = self._get_connection()
        try:
            normalized_status = status.lower()
            if normalized_status not in {"all", "in_progress", "completed"}:
                normalized_status = "all"

            sort_columns = {
                "updated_at": "ss.updated_at",
                "created_at": "ss.created_at",
                "progress_percent": "ss.progress_percent",
            }
            order_column = sort_columns.get(sort_by, "ss.updated_at")
            order_direction = "ASC" if sort_order.lower() == "asc" else "DESC"

            safe_limit = max(limit, 0)
            safe_offset = max(offset, 0)

            cursor = conn.cursor()
            cursor.execute(
                """
                WITH node_counts AS (
                    SELECT
                        learning_session_id,
                        COUNT(*) AS total_nodes,
                        SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS completed_nodes
                    FROM concept_nodes
                    GROUP BY learning_session_id
                ),
                session_status AS (
                    SELECT
                        ls.id,
                        ls.user_id,
                        CASE
                            WHEN COALESCE(nc.total_nodes, 0) = 0 THEN 'in_progress'
                            WHEN COALESCE(nc.completed_nodes, 0) * 100
                                / nc.total_nodes = 100
                            THEN 'completed'
                            ELSE 'in_progress'
                        END AS computed_status
                    FROM learning_sessions ls
                    LEFT JOIN node_counts nc
                        ON ls.id = nc.learning_session_id
                )
                SELECT COUNT(*) AS total_count
                FROM session_status ss
                WHERE (? IS NULL OR ss.user_id = ?)
                    AND (? = 'all' OR ss.computed_status = ?)
                """,
                (
                    NodeStatus.COMPLETED.value,
                    user_id,
                    user_id,
                    normalized_status,
                    normalized_status,
                ),
            )
            total_row = cursor.fetchone()
            total_count = int(total_row["total_count"]) if total_row else 0

            cursor.execute(
                f"""
                WITH node_counts AS (
                    SELECT
                        learning_session_id,
                        COUNT(*) AS total_nodes,
                        SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS completed_nodes
                    FROM concept_nodes
                    GROUP BY learning_session_id
                ),
                session_status AS (
                    SELECT
                        ls.id,
                        ls.query,
                        ls.course_title,
                        ls.user_id,
                        ls.created_at,
                        ls.updated_at,
                        ls.completed_at,
                        ls.last_active_node_id,
                        COALESCE(nc.total_nodes, 0) AS total_nodes,
                        COALESCE(nc.completed_nodes, 0) AS completed_nodes,
                        CASE
                            WHEN COALESCE(nc.total_nodes, 0) = 0 THEN 0
                            ELSE (COALESCE(nc.completed_nodes, 0) * 100)
                                / nc.total_nodes
                        END AS progress_percent,
                        CASE
                            WHEN COALESCE(nc.total_nodes, 0) = 0 THEN 'in_progress'
                            WHEN COALESCE(nc.completed_nodes, 0) * 100
                                / nc.total_nodes = 100
                            THEN 'completed'
                            ELSE 'in_progress'
                        END AS computed_status
                    FROM learning_sessions ls
                    LEFT JOIN node_counts nc
                        ON ls.id = nc.learning_session_id
                ),
                revision_counts AS (
                    SELECT
                        original_session_id,
                        COUNT(*) AS revision_count
                    FROM revision_sessions
                    GROUP BY original_session_id
                )
                SELECT
                    ss.id,
                    ss.query,
                    ss.course_title,
                    ss.progress_percent,
                    ss.computed_status AS status,
                    ss.total_nodes,
                    ss.completed_nodes,
                    cn2.title AS last_active_node_title,
                    ss.created_at,
                    ss.updated_at,
                    ss.completed_at,
                    COALESCE(rc.revision_count, 0) AS revision_count
                FROM session_status ss
                LEFT JOIN concept_nodes cn2
                    ON ss.last_active_node_id = cn2.id
                LEFT JOIN revision_counts rc
                    ON ss.id = rc.original_session_id
                WHERE (? IS NULL OR ss.user_id = ?)
                    AND (? = 'all' OR ss.computed_status = ?)
                ORDER BY {order_column} {order_direction}
                LIMIT ? OFFSET ?
                """,
                (
                    NodeStatus.COMPLETED.value,
                    user_id,
                    user_id,
                    normalized_status,
                    normalized_status,
                    safe_limit,
                    safe_offset,
                ),
            )
            rows = cursor.fetchall()
            sessions = [
                {
                    "id": row["id"],
                    "query": row["query"],
                    "course_title": row["course_title"],
                    "status": row["status"],
                    "progress_percent": int(row["progress_percent"] or 0),
                    "total_nodes": int(row["total_nodes"] or 0),
                    "completed_nodes": int(row["completed_nodes"] or 0),
                    "last_active_node_title": row["last_active_node_title"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "completed_at": row["completed_at"],
                    "revision_count": int(row["revision_count"] or 0),
                }
                for row in rows
            ]
            return sessions, total_count
        except sqlite3.Error as e:
            logger.error(f"Error listing learning sessions: {e}")
            raise
        finally:
            conn.close()

    def update_session_resolved_mode(
        self, session_id: str, resolved_mode: str
    ) -> None:
        """Persist resolved depth mode (lite|full) on learning session."""
        if resolved_mode not in ("lite", "full"):
            raise ValueError(f"Invalid resolved_mode: {resolved_mode}")
        conn = self._get_connection()
        try:
            conn.execute(
                """
                UPDATE learning_sessions
                SET resolved_mode = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (resolved_mode, session_id),
            )
            conn.commit()
        finally:
            conn.close()

    def create_revision_session(
        self,
        original_session_id: str,
        mode: str,
    ) -> Dict[str, Any]:
        """Create a revision session for a completed learning session.

        Args:
            original_session_id: Identifier of the completed session to revise.
            mode: Revision mode, either 'full_review' or 'quiz_only'.

        Returns:
            Revision session payload with created node progress rows.

        Raises:
            LookupError: If the original learning session does not exist.
            ValueError: If mode is invalid or session is not completed.
        """
        allowed_modes = {"full_review", "quiz_only"}
        if mode not in allowed_modes:
            raise ValueError(f"Invalid revision mode: {mode}")

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    ls.id,
                    ls.course_title,
                    COUNT(cn.id) AS total_nodes,
                    SUM(CASE WHEN cn.status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed_nodes
                FROM learning_sessions ls
                LEFT JOIN concept_nodes cn ON cn.learning_session_id = ls.id
                WHERE ls.id = ?
                GROUP BY ls.id
                """,
                (original_session_id,),
            )
            session_row = cursor.fetchone()
            if session_row is None:
                raise LookupError(f"Learning session not found: {original_session_id}")
            # Calculate derived status from actual node completion
            total_nodes = session_row["total_nodes"] or 0
            completed_nodes = session_row["completed_nodes"] or 0
            is_completed = total_nodes > 0 and completed_nodes == total_nodes
            if not is_completed:
                raise ValueError(
                    "Revision sessions can only be created for completed sessions"
                )

            revision_id = str(uuid.uuid4())
            revision_number = self._get_next_revision_number(
                original_session_id=original_session_id,
                conn=conn,
            )
            now = datetime.now(timezone.utc).isoformat()

            cursor.execute(
                """
                INSERT INTO revision_sessions (
                    id, original_session_id, revision_number, mode, status,
                    progress_percent, total_quiz_score_percent, started_at,
                    completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    original_session_id,
                    revision_number,
                    mode,
                    "in_progress",
                    0,
                    None,
                    now,
                    None,
                ),
            )

            cursor.execute(
                """
                SELECT id, title, sequence_index
                FROM concept_nodes
                WHERE learning_session_id = ?
                ORDER BY sequence_index ASC
                """,
                (original_session_id,),
            )

            progress_rows: List[Dict[str, Any]] = []
            for node_row in cursor.fetchall():
                progress_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO revision_node_progress (
                        id, revision_session_id, node_id, status, reviewed_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        progress_id,
                        revision_id,
                        node_row["id"],
                        "pending",
                        None,
                    ),
                )
                progress_rows.append(
                    {
                        "id": progress_id,
                        "revision_session_id": revision_id,
                        "node_id": node_row["id"],
                        "node_title": node_row["title"],
                        "sequence_index": int(node_row["sequence_index"]),
                        "status": "pending",
                        "reviewed_at": None,
                    }
                )

            conn.commit()
            return {
                "id": revision_id,
                "original_session_id": original_session_id,
                "revision_number": revision_number,
                "mode": mode,
                "status": "in_progress",
                "progress_percent": 0,
                "total_quiz_score_percent": None,
                "started_at": now,
                "completed_at": None,
                "nodes": progress_rows,
            }
        except sqlite3.Error as e:
            logger.error(f"Error creating revision session: {e}")
            raise
        finally:
            conn.close()

    def get_revisions_for_session(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[List[Dict[str, Any]], int]:
        """List revision sessions for an original learning session."""
        conn = self._get_connection()
        try:
            safe_limit = max(limit, 0)
            safe_offset = max(offset, 0)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) AS total_count
                FROM revision_sessions
                WHERE original_session_id = ?
                """,
                (session_id,),
            )
            count_row = cursor.fetchone()
            total_count = int(count_row["total_count"]) if count_row else 0

            cursor.execute(
                """
                SELECT
                    id,
                    original_session_id,
                    revision_number,
                    mode,
                    status,
                    progress_percent,
                    total_quiz_score_percent,
                    started_at,
                    completed_at
                FROM revision_sessions
                WHERE original_session_id = ?
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
                """,
                (session_id, safe_limit, safe_offset),
            )
            revisions = [
                {
                    "id": row["id"],
                    "original_session_id": row["original_session_id"],
                    "revision_number": int(row["revision_number"]),
                    "mode": row["mode"],
                    "status": row["status"],
                    "progress_percent": int(row["progress_percent"] or 0),
                    "total_quiz_score_percent": row["total_quiz_score_percent"],
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"],
                }
                for row in cursor.fetchall()
            ]
            return revisions, total_count
        except sqlite3.Error as e:
            logger.error(f"Error listing revision sessions: {e}")
            raise
        finally:
            conn.close()

    def get_revision_session(self, revision_id: str) -> Optional[Dict[str, Any]]:
        """Get a revision session with node-level progress details."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    id,
                    original_session_id,
                    revision_number,
                    mode,
                    status,
                    progress_percent,
                    total_quiz_score_percent,
                    started_at,
                    completed_at
                FROM revision_sessions
                WHERE id = ?
                """,
                (revision_id,),
            )
            revision_row = cursor.fetchone()
            if revision_row is None:
                return None

            cursor.execute(
                """
                SELECT
                    rnp.id,
                    rnp.revision_session_id,
                    rnp.node_id,
                    rnp.status,
                    rnp.reviewed_at,
                    cn.title AS node_title,
                    cn.sequence_index AS sequence_index
                FROM revision_node_progress rnp
                INNER JOIN concept_nodes cn
                    ON cn.id = rnp.node_id
                WHERE rnp.revision_session_id = ?
                ORDER BY cn.sequence_index ASC
                """,
                (revision_id,),
            )
            progress_rows = [
                {
                    "id": row["id"],
                    "revision_session_id": row["revision_session_id"],
                    "node_id": row["node_id"],
                    "node_title": row["node_title"],
                    "sequence_index": int(row["sequence_index"]),
                    "status": row["status"],
                    "reviewed_at": row["reviewed_at"],
                }
                for row in cursor.fetchall()
            ]

            return {
                "id": revision_row["id"],
                "original_session_id": revision_row["original_session_id"],
                "revision_number": int(revision_row["revision_number"]),
                "mode": revision_row["mode"],
                "status": revision_row["status"],
                "progress_percent": int(revision_row["progress_percent"] or 0),
                "total_quiz_score_percent": revision_row["total_quiz_score_percent"],
                "started_at": revision_row["started_at"],
                "completed_at": revision_row["completed_at"],
                "nodes": progress_rows,
            }
        except sqlite3.Error as e:
            logger.error(f"Error getting revision session: {e}")
            raise
        finally:
            conn.close()

    def delete_revision_session(self, revision_id: str) -> bool:
        """Delete a revision session by ID.

        Returns:
            True if a revision session was deleted, otherwise False.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM quiz_attempts
                WHERE revision_session_id = ?
                """,
                (revision_id,),
            )
            cursor.execute(
                """
                DELETE FROM revision_sessions
                WHERE id = ?
                """,
                (revision_id,),
            )
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
        except sqlite3.Error as e:
            logger.error(f"Error deleting revision session: {e}")
            raise
        finally:
            conn.close()

    def delete_learning_session(self, session_id: str) -> bool:
        """Delete a learning session and all related data.

        Cascades to delete:
        - Quiz attempts for concept nodes in the session
        - Concept nodes belonging to the session
        - Revision sessions (and their quiz attempts) for the session
        - The learning session itself

        Args:
            session_id: ID of the learning session to delete.

        Returns:
            True if a learning session was deleted, otherwise False.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Get all concept node IDs for this session
            cursor.execute(
                """
                SELECT id FROM concept_nodes
                WHERE learning_session_id = ?
                """,
                (session_id,),
            )
            node_ids = [row["id"] for row in cursor.fetchall()]

            # Delete quiz attempts for all concept nodes
            if node_ids:
                placeholders = ",".join("?" for _ in node_ids)
                cursor.execute(
                    f"""
                    DELETE FROM quiz_attempts
                    WHERE node_id IN ({placeholders})
                    """,
                    tuple(node_ids),
                )

            # Delete concept nodes
            cursor.execute(
                """
                DELETE FROM concept_nodes
                WHERE learning_session_id = ?
                """,
                (session_id,),
            )

            # Get all revision session IDs for this session
            cursor.execute(
                """
                SELECT id FROM revision_sessions
                WHERE original_session_id = ?
                """,
                (session_id,),
            )
            revision_ids = [row["id"] for row in cursor.fetchall()]

            # Delete quiz attempts for all revision sessions
            if revision_ids:
                placeholders = ",".join("?" for _ in revision_ids)
                cursor.execute(
                    f"""
                    DELETE FROM quiz_attempts
                    WHERE revision_session_id IN ({placeholders})
                    """,
                    tuple(revision_ids),
                )

            # Delete revision sessions
            cursor.execute(
                """
                DELETE FROM revision_sessions
                WHERE original_session_id = ?
                """,
                (session_id,),
            )

            # Delete the learning session
            cursor.execute(
                """
                DELETE FROM learning_sessions
                WHERE id = ?
                """,
                (session_id,),
            )
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
        except sqlite3.Error as e:
            logger.error(f"Error deleting learning session: {e}")
            raise
        finally:
            conn.close()

    def mark_revision_node_reviewed(
        self,
        revision_id: str,
        node_id: str,
    ) -> Dict[str, Any]:
        """Mark a revision node as reviewed for full-review sessions."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, mode
                FROM revision_sessions
                WHERE id = ?
                """,
                (revision_id,),
            )
            revision_row = cursor.fetchone()
            if revision_row is None:
                raise LookupError(f"Revision session not found: {revision_id}")
            if revision_row["mode"] != "full_review":
                raise ValueError(
                    "mark-reviewed is only allowed for full_review revisions"
                )

            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                UPDATE revision_node_progress
                SET status = 'reviewed', reviewed_at = ?
                WHERE revision_session_id = ? AND node_id = ?
                """,
                (now, revision_id, node_id),
            )
            if cursor.rowcount == 0:
                raise LookupError(
                    f"Revision node not found for revision {revision_id}: {node_id}"
                )

            self._update_revision_progress(revision_id, conn)
            cursor.execute(
                """
                SELECT id, revision_session_id, node_id, status, reviewed_at
                FROM revision_node_progress
                WHERE revision_session_id = ? AND node_id = ?
                """,
                (revision_id, node_id),
            )
            row = cursor.fetchone()
            conn.commit()
            if row is None:
                raise LookupError(
                    f"Revision node not found for revision {revision_id}: {node_id}"
                )

            return {
                "id": row["id"],
                "revision_session_id": row["revision_session_id"],
                "node_id": row["node_id"],
                "status": row["status"],
                "reviewed_at": row["reviewed_at"],
            }
        except sqlite3.Error as e:
            logger.error(f"Error marking revision node reviewed: {e}")
            raise
        finally:
            conn.close()

    def submit_revision_quiz(
        self,
        revision_id: str,
        node_id: str,
        selected_option_ids: List[str],
        quiz_index: int = 0,
    ) -> Dict[str, Any]:
        """Submit quiz answer for a revision node and track progress."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id
                FROM revision_sessions
                WHERE id = ?
                """,
                (revision_id,),
            )
            if cursor.fetchone() is None:
                raise LookupError(f"Revision session not found: {revision_id}")

            cursor.execute(
                """
                SELECT status
                FROM revision_node_progress
                WHERE revision_session_id = ? AND node_id = ?
                """,
                (revision_id, node_id),
            )
            progress_row = cursor.fetchone()
            if progress_row is None:
                raise LookupError(
                    f"Revision node not found for revision {revision_id}: {node_id}"
                )

            quiz_result = self.create_quiz_attempt(
                node_id=node_id,
                selected_option_ids=selected_option_ids,
                quiz_index=quiz_index,
                revision_session_id=revision_id,
                conn=conn,
            )

            next_status = "quiz_passed" if quiz_result["is_correct"] else "quiz_failed"
            if progress_row["status"] == "quiz_passed":
                next_status = "quiz_passed"

            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                UPDATE revision_node_progress
                SET status = ?,
                    reviewed_at = CASE
                        WHEN ? = 'quiz_passed'
                            THEN COALESCE(reviewed_at, ?)
                        ELSE reviewed_at
                    END
                WHERE revision_session_id = ? AND node_id = ?
                """,
                (next_status, next_status, now, revision_id, node_id),
            )

            self._update_revision_progress(revision_id, conn)
            conn.commit()
            return {
                "is_correct": bool(quiz_result["is_correct"]),
                "correct_option_ids": quiz_result.get("correct_option_ids", []),
                "explanation": quiz_result.get("explanation"),
                "selected_explanation": quiz_result.get("selected_explanation"),
                "revision_node_status": next_status,
            }
        except sqlite3.Error as e:
            logger.error(f"Error submitting revision quiz: {e}")
            raise
        finally:
            conn.close()

    def _update_revision_progress(
        self,
        revision_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Dict[str, Any]:
        """Recalculate and persist revision-level progress metadata."""
        owns_connection = conn is None
        active_conn = conn or self._get_connection()
        try:
            cursor = active_conn.cursor()
            cursor.execute(
                """
                SELECT id
                FROM revision_sessions
                WHERE id = ?
                """,
                (revision_id,),
            )
            if cursor.fetchone() is None:
                raise LookupError(f"Revision session not found: {revision_id}")

            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total_nodes,
                    SUM(CASE WHEN status != 'pending' THEN 1 ELSE 0 END)
                        AS completed_nodes,
                    SUM(CASE WHEN status = 'quiz_passed' THEN 1 ELSE 0 END)
                        AS quizzes_passed,
                    SUM(CASE WHEN status = 'quiz_failed' THEN 1 ELSE 0 END)
                        AS quizzes_failed
                FROM revision_node_progress
                WHERE revision_session_id = ?
                """,
                (revision_id,),
            )
            row = cursor.fetchone()
            total_nodes = int(row["total_nodes"] or 0) if row else 0
            completed_nodes = int(row["completed_nodes"] or 0) if row else 0
            quizzes_passed = int(row["quizzes_passed"] or 0) if row else 0
            quizzes_failed = int(row["quizzes_failed"] or 0) if row else 0

            progress_percent = self._calculate_progress_percent(
                completed_nodes=completed_nodes,
                total_nodes=total_nodes,
            )
            quiz_attempted = quizzes_passed + quizzes_failed
            total_quiz_score_percent = (
                (quizzes_passed * 100) // quiz_attempted if quiz_attempted > 0 else None
            )
            revision_status = (
                "completed"
                if total_nodes > 0 and completed_nodes >= total_nodes
                else "in_progress"
            )
            now = datetime.now(timezone.utc).isoformat()

            cursor.execute(
                """
                UPDATE revision_sessions
                SET status = ?,
                    progress_percent = ?,
                    total_quiz_score_percent = ?,
                    completed_at = CASE
                        WHEN ? = 'completed'
                            THEN COALESCE(completed_at, ?)
                        ELSE completed_at
                    END
                WHERE id = ?
                """,
                (
                    revision_status,
                    progress_percent,
                    total_quiz_score_percent,
                    revision_status,
                    now,
                    revision_id,
                ),
            )

            if owns_connection:
                active_conn.commit()

            return {
                "revision_id": revision_id,
                "status": revision_status,
                "progress_percent": progress_percent,
                "total_quiz_score_percent": total_quiz_score_percent,
            }
        finally:
            if owns_connection:
                active_conn.close()

    def get_revision_summary(self, revision_id: str) -> Dict[str, Any]:
        """Return summary metrics for a revision session."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    id,
                    mode,
                    progress_percent,
                    total_quiz_score_percent,
                    started_at,
                    completed_at
                FROM revision_sessions
                WHERE id = ?
                """,
                (revision_id,),
            )
            revision_row = cursor.fetchone()
            if revision_row is None:
                raise LookupError(f"Revision session not found: {revision_id}")

            cursor.execute(
                """
                SELECT
                    COUNT(*) AS nodes_total,
                    SUM(CASE WHEN status != 'pending' THEN 1 ELSE 0 END)
                        AS nodes_reviewed
                FROM revision_node_progress
                WHERE revision_session_id = ?
                """,
                (revision_id,),
            )
            nodes_row = cursor.fetchone()
            nodes_total = int(nodes_row["nodes_total"] or 0) if nodes_row else 0
            nodes_reviewed = int(nodes_row["nodes_reviewed"] or 0) if nodes_row else 0

            cursor.execute(
                """
                SELECT
                    COUNT(*) AS quizzes_total,
                    SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END)
                        AS quizzes_passed
                FROM quiz_attempts
                WHERE revision_session_id = ?
                """,
                (revision_id,),
            )
            revision_attempts_row = cursor.fetchone()
            quizzes_total = (
                int(revision_attempts_row["quizzes_total"] or 0)
                if revision_attempts_row
                else 0
            )
            quizzes_passed = (
                int(revision_attempts_row["quizzes_passed"] or 0)
                if revision_attempts_row
                else 0
            )
            quizzes_failed = max(quizzes_total - quizzes_passed, 0)

            revision_quiz_score_percent = (
                (quizzes_passed * 100) // quizzes_total if quizzes_total > 0 else None
            )
            total_quiz_score_percent = (
                revision_quiz_score_percent
                if revision_quiz_score_percent is not None
                else revision_row["total_quiz_score_percent"]
            )

            cursor.execute(
                """
                SELECT node_id
                FROM revision_node_progress
                WHERE revision_session_id = ?
                """,
                (revision_id,),
            )
            node_ids = [row["node_id"] for row in cursor.fetchall()]

            comparison = None
            if quizzes_total > 0 and node_ids:
                placeholders = ",".join("?" for _ in node_ids)
                cursor.execute(
                    f"""
                    SELECT
                        COUNT(*) AS quizzes_total,
                        SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END)
                            AS quizzes_passed
                    FROM quiz_attempts
                    WHERE revision_session_id IS NULL
                      AND node_id IN ({placeholders})
                    """,
                    tuple(node_ids),
                )
                original_row = cursor.fetchone()
                original_total = int(original_row["quizzes_total"] or 0)
                if original_total > 0 and revision_quiz_score_percent is not None:
                    original_passed = int(original_row["quizzes_passed"] or 0)
                    original_score = (original_passed * 100) // original_total
                    comparison = {
                        "original_quiz_score_percent": original_score,
                        "improvement_percent": (
                            revision_quiz_score_percent - original_score
                        ),
                    }

            started_at = revision_row["started_at"]
            completed_at = revision_row["completed_at"]
            time_spent_seconds = None
            if started_at and completed_at:
                try:
                    started_dt = datetime.fromisoformat(str(started_at))
                    completed_dt = datetime.fromisoformat(str(completed_at))
                    delta_seconds = int((completed_dt - started_dt).total_seconds())
                    time_spent_seconds = max(delta_seconds, 0)
                except ValueError:
                    time_spent_seconds = None

            return {
                "revision_id": revision_row["id"],
                "mode": revision_row["mode"],
                "progress_percent": int(revision_row["progress_percent"] or 0),
                "total_quiz_score_percent": total_quiz_score_percent,
                "nodes_reviewed": nodes_reviewed,
                "nodes_total": nodes_total,
                "quizzes_passed": quizzes_passed,
                "quizzes_failed": quizzes_failed,
                "quizzes_total": quizzes_total,
                "time_spent_seconds": time_spent_seconds,
                "comparison": comparison,
            }
        except sqlite3.Error as e:
            logger.error(f"Error getting revision summary: {e}")
            raise
        finally:
            conn.close()

    def create_concept_node(
        self,
        session_id: str,
        sequence_index: int,
        title: str,
        content_markdown: str,
        status: NodeStatus,
        quiz: Optional[QuizCard] = None,
        quiz_set: Optional[QuizSet] = None,
        error_message: Optional[str] = None,
        retry_available: bool = False,
        complexity: Optional[str] = "Intermediate",
        summary_for_context: Optional[str] = None,
        key_terms: Optional[List[str]] = None,
        failed_step: Optional["FailedStep"] = None,
    ) -> Dict[str, Any]:
        """Create a new concept node for a learning session.

        Callers must provide the correct initial status:
        - NodeStatus.VIEWING_EXPLANATION for the first node (sequence_index=0)
        - NodeStatus.LOCKED for subsequent nodes (sequence_index>0)

        Supports both single QuizCard and QuizSet for multiple quizzes.
        If both quiz and quiz_set are provided, quiz_set takes precedence.
        """
        conn = self._get_connection()
        try:
            node_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.cursor()
            if not self._learning_session_exists(session_id, conn):
                raise ValueError(f"Learning session not found: {session_id}")
            cursor.execute(
                """
                INSERT INTO concept_nodes (
                    id, learning_session_id, sequence_index, title, content_markdown,
                    status, error_message, retry_available, failed_step, complexity,
                    summary_for_context, key_terms, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node_id,
                    session_id,
                    sequence_index,
                    title,
                    content_markdown,
                    status.value,
                    error_message,
                    int(retry_available),
                    failed_step.value if failed_step is not None else None,
                    complexity,
                    summary_for_context,
                    json.dumps(key_terms) if key_terms is not None else None,
                    now,
                    now,
                ),
            )

            quiz_payload = None
            if quiz_set is not None:
                # Store as QuizSet (format_version=1)
                cursor.execute(
                    """
                    INSERT INTO quiz_data (
                        id, node_id, payload, format_version,
                        shuffle_seed, current_index, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        node_id,
                        json.dumps(quiz_set.model_dump()),
                        1,  # format_version for QuizSet
                        quiz_set.shuffle_seed,
                        quiz_set.current_index,
                        now,
                        now,
                    ),
                )
                quiz_payload = quiz_set.model_dump()
            elif quiz is not None:
                # Store as legacy single quiz (format_version=0)
                quiz_payload = quiz.model_dump()
                cursor.execute(
                    """
                    INSERT INTO quiz_data (
                        id, node_id, payload, format_version, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        node_id,
                        json.dumps(quiz_payload),
                        0,  # format_version 0 = legacy single quiz
                        now,
                        now,
                    ),
                )

            conn.commit()
            logger.info(f"Created concept node: {node_id}")
            return {
                "id": node_id,
                "learning_session_id": session_id,
                "sequence_index": sequence_index,
                "title": title,
                "content_markdown": content_markdown,
                "status": status.value,
                "error_message": error_message,
                "retry_available": retry_available,
                "failed_step": failed_step.value if failed_step is not None else None,
                "complexity": complexity,
                "summary_for_context": summary_for_context,
                "key_terms": key_terms,
                "created_at": now,
                "updated_at": now,
                "quiz": quiz_payload,
            }
        except sqlite3.Error as e:
            logger.error(f"Error creating concept node: {e}")
            raise
        finally:
            conn.close()

    def _learning_session_exists(
        self, session_id: str, conn: sqlite3.Connection
    ) -> bool:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id FROM learning_sessions WHERE id = ?
            """,
            (session_id,),
        )
        return cursor.fetchone() is not None

    def get_session_nodes(self, session_id: str) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    cn.id,
                    cn.learning_session_id,
                    cn.sequence_index,
                    cn.title,
                    cn.content_markdown,
                    cn.status,
                    cn.generation_status,
                    cn.error_message,
                    cn.retry_available,
                    cn.failed_step,
                    cn.complexity,
                    cn.summary_for_context,
                    cn.key_terms,
                    cn.created_at,
                    cn.updated_at,
                    qd.payload AS quiz_payload
                FROM concept_nodes cn
                LEFT JOIN quiz_data qd ON cn.id = qd.node_id
                WHERE cn.learning_session_id = ?
                ORDER BY cn.sequence_index ASC
                """,
                (session_id,),
            )
            nodes = []
            for row in cursor.fetchall():
                quiz_payload = (
                    json.loads(row["quiz_payload"]) if row["quiz_payload"] else None
                )
                key_terms_raw = row["key_terms"]
                key_terms = json.loads(key_terms_raw) if key_terms_raw else None
                generation_status = row["generation_status"]
                if generation_status is None:
                    generation_status = "READY"
                nodes.append(
                    {
                        "id": row["id"],
                        "learning_session_id": row["learning_session_id"],
                        "sequence_index": row["sequence_index"],
                        "title": row["title"],
                        "content_markdown": row["content_markdown"],
                        "status": row["status"],
                        "generation_status": generation_status,
                        "error_message": row["error_message"],
                        "retry_available": bool(row["retry_available"])
                        if row["retry_available"] is not None
                        else False,
                        "failed_step": row["failed_step"],
                        "complexity": row["complexity"],
                        "summary_for_context": row["summary_for_context"],
                        "key_terms": key_terms,
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "quiz": quiz_payload,
                    }
                )
            return nodes
        except sqlite3.Error as e:
            logger.error(f"Error getting session nodes: {e}")
            raise
        finally:
            conn.close()

    def update_node_status(
        self, node_id: str, status: NodeStatus
    ) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT status, learning_session_id
                FROM concept_nodes
                WHERE id = ?
                """,
                (node_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            current_status = NodeStatus(row["status"])
            session_id = row["learning_session_id"]
            logger.info(
                f"Transition attempt: {current_status.value} -> {status.value} for node {node_id}"
            )
            if not self._is_valid_transition(current_status, status):
                logger.error(
                    f"Invalid transition: {current_status.value} -> {status.value}"
                )
                raise ValueError(
                    "Invalid status transition from "
                    f"{current_status.value} to {status.value}"
                )
            cursor.execute(
                """
                UPDATE concept_nodes
                SET status = ?, updated_at = ?,
                    started_at = CASE
                        WHEN ? = ? AND started_at IS NULL THEN ?
                        ELSE started_at
                    END,
                    completed_at = CASE
                        WHEN ? = ? THEN ?
                        ELSE completed_at
                    END
                WHERE id = ? AND status = ?
                """,
                (
                    status.value,
                    now,
                    status.value,
                    NodeStatus.VIEWING_EXPLANATION.value,
                    now,
                    status.value,
                    NodeStatus.COMPLETED.value,
                    now,
                    node_id,
                    current_status.value,
                ),
            )
            if cursor.rowcount == 0:
                node = self._get_node_by_id(node_id, conn)
                if node is None:
                    return None
                raise ValueError("Node status changed during update; retry")
            self._update_session_progress(
                session_id=session_id,
                conn=conn,
            )
            if status == NodeStatus.VIEWING_EXPLANATION:
                self._update_last_active_node_internal(
                    session_id=session_id,
                    node_id=node_id,
                    conn=conn,
                )
            conn.commit()
            return self._get_node_by_id(node_id, conn)
        except sqlite3.Error as e:
            logger.error(f"Error updating node status: {e}")
            raise
        finally:
            conn.close()

    def update_node_content(
        self,
        node_id: str,
        content_markdown: str,
        status: NodeStatus,
        quiz: Optional[QuizCard] = None,
        quiz_set: Optional[QuizSet] = None,
        error_message: Optional[str] = None,
        retry_available: bool = False,
        failed_step: Optional["FailedStep"] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update node content, quiz data, and status.

        Supports both single QuizCard and QuizSet for multiple quizzes.
        If both quiz and quiz_set are provided, quiz_set takes precedence.
        If both are None, any existing quiz data is deleted.
        """
        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT status
                FROM concept_nodes
                WHERE id = ?
                """,
                (node_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            current_status = NodeStatus(row["status"])
            if not self._is_valid_transition(current_status, status):
                raise ValueError(
                    "Invalid status transition from "
                    f"{current_status.value} to {status.value}"
                )
            cursor.execute(
                """
                UPDATE concept_nodes
                SET content_markdown = ?, status = ?, error_message = ?,
                    retry_available = ?, failed_step = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    content_markdown,
                    status.value,
                    error_message,
                    int(retry_available),
                    failed_step.value if failed_step is not None else None,
                    now,
                    node_id,
                    current_status.value,
                ),
            )
            if cursor.rowcount == 0:
                node = self._get_node_by_id(node_id, conn)
                if node is None:
                    return None
                raise ValueError("Node status changed during update; retry")

            # Handle quiz data: quiz_set takes precedence over quiz
            if quiz_set is not None:
                # Store as QuizSet (format_version=1)
                quiz_payload = json.dumps(quiz_set.model_dump())
                cursor.execute(
                    """
                    SELECT id FROM quiz_data WHERE node_id = ?
                    """,
                    (node_id,),
                )
                quiz_row = cursor.fetchone()
                if quiz_row:
                    cursor.execute(
                        """
                        UPDATE quiz_data
                        SET payload = ?, format_version = 1,
                            shuffle_seed = ?, current_index = ?,
                            updated_at = ?
                        WHERE node_id = ?
                        """,
                        (
                            quiz_payload,
                            quiz_set.shuffle_seed,
                            quiz_set.current_index,
                            now,
                            node_id,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO quiz_data (
                            id, node_id, payload, format_version,
                            shuffle_seed, current_index, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            node_id,
                            quiz_payload,
                            1,  # format_version for QuizSet
                            quiz_set.shuffle_seed,
                            quiz_set.current_index,
                            now,
                            now,
                        ),
                    )
            elif quiz is not None:
                # Store as legacy single quiz
                quiz_payload = json.dumps(quiz.model_dump())
                cursor.execute(
                    """
                    SELECT id FROM quiz_data WHERE node_id = ?
                    """,
                    (node_id,),
                )
                quiz_row = cursor.fetchone()
                if quiz_row:
                    cursor.execute(
                        """
                        UPDATE quiz_data
                        SET payload = ?, format_version = 0,
                            shuffle_seed = NULL, current_index = 0,
                            updated_at = ?
                        WHERE node_id = ?
                        """,
                        (quiz_payload, now, node_id),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO quiz_data (id, node_id, payload, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (str(uuid.uuid4()), node_id, quiz_payload, now),
                    )
            else:
                # Delete existing quiz data if any
                cursor.execute(
                    """
                    DELETE FROM quiz_data
                    WHERE node_id = ?
                    """,
                    (node_id,),
                )

            conn.commit()
            return self._get_node_by_id(node_id, conn)
        except sqlite3.Error as e:
            logger.error(f"Error updating node content: {e}")
            raise
        finally:
            conn.close()

    def replace_node_content(
        self,
        node_id: str,
        content_markdown: str,
        status: NodeStatus,
        quiz_set: Optional[QuizSet] = None,
    ) -> Optional[Dict[str, Any]]:
        """Replace node content atomically without state-machine validation.

        Used by manual topic regeneration where IN_QUIZ / SHOWING_FEEDBACK /
        COMPLETED nodes must reset to VIEWING_EXPLANATION. Clears error
        state fields.

        Args:
            node_id: Target concept node.
            content_markdown: New explanation content.
            status: Target status (typically VIEWING_EXPLANATION or LOCKED).
            quiz_set: New quiz set. None deletes existing quiz data.

        Returns:
            Updated node dict, or None if node does not exist.
        """
        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM concept_nodes WHERE id = ?",
                (node_id,),
            )
            if not cursor.fetchone():
                return None

            cursor.execute(
                """
                UPDATE concept_nodes
                SET content_markdown = ?, status = ?,
                    error_message = NULL, retry_available = 0,
                    failed_step = NULL, updated_at = ?
                WHERE id = ?
                """,
                (content_markdown, status.value, now, node_id),
            )

            # Handle quiz data
            if quiz_set is not None:
                quiz_payload = json.dumps(quiz_set.model_dump())
                cursor.execute(
                    "SELECT id FROM quiz_data WHERE node_id = ?",
                    (node_id,),
                )
                quiz_row = cursor.fetchone()
                if quiz_row:
                    cursor.execute(
                        """
                        UPDATE quiz_data
                        SET payload = ?, format_version = 1,
                            shuffle_seed = ?, current_index = ?,
                            updated_at = ?
                        WHERE node_id = ?
                        """,
                        (
                            quiz_payload,
                            quiz_set.shuffle_seed,
                            quiz_set.current_index,
                            now,
                            node_id,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO quiz_data (
                            id, node_id, payload, format_version,
                            shuffle_seed, current_index, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            node_id,
                            quiz_payload,
                            1,
                            quiz_set.shuffle_seed,
                            quiz_set.current_index,
                            now,
                            now,
                        ),
                    )
            else:
                cursor.execute(
                    "DELETE FROM quiz_data WHERE node_id = ?",
                    (node_id,),
                )

            conn.commit()
            return self._get_node_by_id(node_id, conn)
        except sqlite3.Error as e:
            logger.error(f"Error replacing node content: {e}")
            raise
        finally:
            conn.close()

    @staticmethod
    def _is_valid_transition(
        current_status: NodeStatus, next_status: NodeStatus
    ) -> bool:
        """Validate state transitions for the sequential learning flow.

        Valid transitions:
            LOCKED → VIEWING_EXPLANATION (unlock when previous completed)
            VIEWING_EXPLANATION → IN_QUIZ (user clicks "proceed to quiz")
            VIEWING_EXPLANATION → ERROR (generation failed)
            IN_QUIZ → SHOWING_FEEDBACK (quiz submitted)
            SHOWING_FEEDBACK → IN_QUIZ (retry quiz, score < 100%)
            SHOWING_FEEDBACK → COMPLETED (score = 100%)
            ERROR → LOCKED (reset for retry)
            ERROR → VIEWING_EXPLANATION (regeneration succeeded)

        Note: First node starts as VIEWING_EXPLANATION (not LOCKED).
        """
        if current_status == next_status:
            return True
        allowed = {
            NodeStatus.LOCKED: {
                NodeStatus.VIEWING_EXPLANATION,  # Unlocked by previous completion
                NodeStatus.ERROR,
            },
            NodeStatus.VIEWING_EXPLANATION: {
                NodeStatus.IN_QUIZ,  # User clicks "proceed to quiz"
                NodeStatus.ERROR,
            },
            NodeStatus.IN_QUIZ: {
                NodeStatus.SHOWING_FEEDBACK,  # Quiz submitted
                NodeStatus.ERROR,
            },
            NodeStatus.SHOWING_FEEDBACK: {
                NodeStatus.IN_QUIZ,  # Retry (score < 100%)
                NodeStatus.COMPLETED,  # Mastered (score = 100%)
            },
            NodeStatus.COMPLETED: set(),  # Terminal state
            NodeStatus.ERROR: {
                NodeStatus.LOCKED,  # Reset
                NodeStatus.VIEWING_EXPLANATION,  # Regeneration succeeded
            },
        }
        return next_status in allowed[current_status]

    def get_next_node(
        self, session_id: str, sequence_index: int
    ) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    cn.id,
                    cn.learning_session_id,
                    cn.sequence_index,
                    cn.title,
                    cn.content_markdown,
                    cn.status,
                    cn.error_message,
                    cn.retry_available,
                    cn.failed_step,
                    cn.created_at,
                    cn.updated_at,
                    qd.payload AS quiz_payload
                FROM concept_nodes cn
                LEFT JOIN quiz_data qd ON cn.id = qd.node_id
                WHERE cn.learning_session_id = ?
                  AND cn.sequence_index = ?
                """,
                (session_id, sequence_index + 1),
            )
            row = cursor.fetchone()
            if not row:
                return None
            quiz_payload = (
                json.loads(row["quiz_payload"]) if row["quiz_payload"] else None
            )
            return {
                "id": row["id"],
                "learning_session_id": row["learning_session_id"],
                "sequence_index": row["sequence_index"],
                "title": row["title"],
                "content_markdown": row["content_markdown"],
                "status": row["status"],
                "error_message": row["error_message"],
                "retry_available": bool(row["retry_available"])
                if row["retry_available"] is not None
                else False,
                "failed_step": row["failed_step"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "quiz": quiz_payload,
            }
        except sqlite3.Error as e:
            logger.error(f"Error getting next node: {e}")
            raise
        finally:
            conn.close()

    def get_quiz_for_node(self, node_id: str) -> Optional[QuizCard]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT payload, format_version, current_index
                FROM quiz_data
                WHERE node_id = ?
                """,
                (node_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            payload = json.loads(row["payload"])
            format_version = row["format_version"]
            current_index = row["current_index"]

            # Handle legacy format (single QuizCard) stored without format_version
            if format_version is None or format_version < 1:
                # Legacy: payload is a QuizCard, return converted
                from server.schemas.learning import convert_legacy_quiz_card
                return convert_legacy_quiz_card(payload)

            # New format: payload is a QuizSet. Fall back to legacy parsing
            # if format_version was incorrectly set during prior migrations.
            try:
                quiz_set = QuizSet.model_validate(payload)
            except ValidationError:
                logger.warning(
                    "Detected stale format_version for legacy quiz row: "
                    "node_id=%s. Falling back to legacy parsing.",
                    node_id,
                )
                from server.schemas.learning import convert_legacy_quiz_card
                return convert_legacy_quiz_card(payload)
            if quiz_set.quizzes:
                # Use current_index from database column, not from payload
                idx = (
                    current_index
                    if current_index is not None
                    else quiz_set.current_index
                )
                return quiz_set.quizzes[idx]
            return None
        except sqlite3.Error as e:
            logger.error(f"Error getting quiz for node: {e}")
            raise
        finally:
            conn.close()

    def create_quiz_set(
        self,
        node_id: str,
        quiz_set: QuizSet,
        shuffle_seed: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store a QuizSet for a concept node.

        Args:
            node_id: The concept node identifier
            quiz_set: QuizSet containing 1-5 quizzes
            shuffle_seed: Optional seed for deterministic shuffling

        Returns:
            Dict with quiz_set_id, node_id, format_version, and shuffle_seed

        Raises:
            ValueError: If node_id not found
            sqlite3.Error: On database errors
        """
        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.cursor()

            # Verify node exists
            cursor.execute(
                "SELECT id FROM concept_nodes WHERE id = ?",
                (node_id,),
            )
            if cursor.fetchone() is None:
                raise ValueError(f"Concept node not found: {node_id}")

            # Delete any existing quiz data for this node
            cursor.execute(
                "DELETE FROM quiz_data WHERE node_id = ?",
                (node_id,),
            )

            # Insert new QuizSet
            quiz_set_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO quiz_data (
                    id, node_id, payload, format_version,
                    shuffle_seed, current_index, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    quiz_set_id,
                    node_id,
                    json.dumps(quiz_set.model_dump()),
                    1,  # format_version for QuizSet
                    shuffle_seed,
                    quiz_set.current_index,
                    now,
                    now,
                ),
            )
            conn.commit()

            logger.info(
                f"Created QuizSet for node {node_id}: "
                f"{len(quiz_set.quizzes)} quizzes, seed={shuffle_seed}"
            )

            return {
                "id": quiz_set_id,
                "node_id": node_id,
                "format_version": 1,
                "shuffle_seed": shuffle_seed,
                "current_index": quiz_set.current_index,
                "total_quizzes": len(quiz_set.quizzes),
                "created_at": now,
                "updated_at": now,
            }
        except sqlite3.Error as e:
            logger.error(f"Error creating QuizSet: {e}")
            raise
        finally:
            conn.close()

    def get_quiz_set_for_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve QuizSet data for a concept node.

        Args:
            node_id: The concept node identifier

        Returns:
            Dict with quiz_set, shuffle_seed, current_index, format_version,
            or None if no quiz data exists

        Raises:
            sqlite3.Error: On database errors
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    payload, format_version, shuffle_seed,
                    current_index, created_at, updated_at
                FROM quiz_data
                WHERE node_id = ?
                """,
                (node_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            payload = json.loads(row["payload"])
            format_version = row["format_version"]

            # Handle legacy format - wrap single quiz in QuizSet
            if format_version is None or format_version < 1:
                # Legacy: payload is a QuizCard, convert and wrap in QuizSet
                quiz_set = convert_legacy_to_quiz_set(payload)
                shuffle_seed = row["shuffle_seed"]
                current_index = row["current_index"] or 0
            else:
                try:
                    quiz_set = QuizSet.model_validate(payload)
                    shuffle_seed = row["shuffle_seed"]
                    current_index = row["current_index"]
                except ValidationError:
                    logger.warning(
                        "Detected stale format_version for legacy quiz row: "
                        "node_id=%s. Falling back to wrapped legacy quiz.",
                        node_id,
                    )
                    quiz_set = convert_legacy_to_quiz_set(payload)
                    shuffle_seed = None
                    current_index = 0
                    format_version = 0

            return {
                "quiz_set": quiz_set,
                "format_version": format_version or 0,
                "shuffle_seed": shuffle_seed,
                "current_index": current_index,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        except sqlite3.Error as e:
            logger.error(f"Error getting QuizSet for node: {e}")
            raise
        finally:
            conn.close()

    def update_quiz_shuffle_seed(self, node_id: str, shuffle_seed: str) -> bool:
        """Update shuffle seed for a node's quiz.

        Args:
            node_id: The concept node identifier
            shuffle_seed: New shuffle seed for deterministic shuffling

        Returns:
            True if updated successfully, False if quiz data not found

        Raises:
            sqlite3.Error: On database errors
        """
        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE quiz_data
                SET shuffle_seed = ?, updated_at = ?
                WHERE node_id = ?
                """,
                (shuffle_seed, now, node_id),
            )
            conn.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.info(
                    f"Updated quiz shuffle seed for node {node_id}: {shuffle_seed}"
                )
            return updated
        except sqlite3.Error as e:
            logger.error(f"Error updating quiz shuffle seed: {e}")
            raise
        finally:
            conn.close()

    def decrement_quiz_set_progress(
        self, node_id: str
    ) -> Optional[Dict[str, Any]]:
        """Decrement the current quiz index for a QuizSet.

        Returns:
            Updated node data dict, or None if not found or not a QuizSet.
        """
        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.cursor()

            # Get current quiz data
            cursor.execute(
                "SELECT payload, format_version, current_index FROM quiz_data WHERE node_id = ?",
                (node_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            format_version = row["format_version"]
            # Only support QuizSet (version 1)
            if format_version is None or format_version < 1:
                # Legacy single quiz, cannot decrement
                return None

            current_index = row["current_index"]
            if current_index <= 0:
                # Already at start, cannot decrement further.
                # Return current node state.
                return self._get_node_by_id(node_id, conn)

            new_index = current_index - 1

            cursor.execute(
                """
                UPDATE quiz_data
                SET current_index = ?, updated_at = ?
                WHERE node_id = ?
                """,
                (new_index, now, node_id),
            )
            conn.commit()

            logger.info(
                f"Decremented QuizSet progress for node {node_id}: index={new_index}"
            )

            return self._get_node_by_id(node_id, conn)
        except sqlite3.Error as e:
            logger.error(f"Error decrementing QuizSet progress: {e}")
            raise
        finally:
            conn.close()

    def update_quiz_set_progress(
        self, node_id: str, current_index: int
    ) -> Optional[Dict[str, Any]]:
        """Update the current quiz index for a QuizSet.

        Args:
            node_id: The concept node identifier
            current_index: New current index (0-based)

        Returns:
            Updated QuizSet data dict, or None if not found

        Raises:
            ValueError: If current_index is invalid for the quiz set
            sqlite3.Error: On database errors
        """
        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.cursor()

            # Get current quiz set to validate index
            cursor.execute(
                "SELECT payload, format_version FROM quiz_data WHERE node_id = ?",
                (node_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            payload = json.loads(row["payload"])
            format_version = row["format_version"]

            # Validate index against quiz set size
            if format_version is None or format_version < 1:
                total_quizzes = 1  # Legacy: single quiz wrapped in QuizSet
            else:
                quiz_set_data = QuizSet.model_validate(payload)
                total_quizzes = len(quiz_set_data.quizzes)

            if current_index < 0 or current_index >= total_quizzes:
                raise ValueError(
                    f"Invalid current_index {current_index} for quiz set "
                    f"with {total_quizzes} quizzes"
                )

            # Update the current_index
            cursor.execute(
                """
                UPDATE quiz_data
                SET current_index = ?, updated_at = ?
                WHERE node_id = ?
                """,
                (current_index, now, node_id),
            )
            conn.commit()

            logger.info(
                f"Updated QuizSet progress for node {node_id}: index={current_index}"
            )

            # Return updated data
            return self.get_quiz_set_for_node(node_id)
        except sqlite3.Error as e:
            logger.error(f"Error updating QuizSet progress: {e}")
            raise
        finally:
            conn.close()

    def create_quiz_attempt(
        self,
        node_id: str,
        selected_option_ids: List[str],
        quiz_index: int = 0,
        revision_session_id: Optional[str] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Dict[str, Any]:
        """Record a quiz attempt and return result with mastery status.

        Supports both single QuizCard and QuizSet (multi-quiz) scenarios.
        For QuizSet, uses quiz_index to select the appropriate quiz.

        Args:
            node_id: The concept node identifier
            selected_option_ids: The selected option UUID(s) (stable IDs)
            quiz_index: Index of quiz in set (0-based, default 0)
            revision_session_id: Optional revision session identifier
            conn: Optional database connection for transactional
                grouping. When provided the caller is responsible
                for committing and closing the connection.

        Returns:
            Dict with attempt details including is_correct, score_percent,
            correct_option_ids, explanation, and is_mastered

        Raises:
            ValueError: If node_id not found, has no quiz, or quiz_index invalid
        """
        owns_connection = conn is None
        active_conn = conn or self._get_connection()
        try:
            cursor = active_conn.cursor()
            node = self._get_node_by_id(node_id, active_conn)
            if node is None:
                raise ValueError(f"Concept node not found: {node_id}")
            session_id = node["learning_session_id"]

            # Get QuizSet data to determine quiz structure
            quiz_set_data = self.get_quiz_set_for_node(node_id)
            if quiz_set_data is None:
                raise ValueError(f"No quiz found for node: {node_id}")

            quiz_set = quiz_set_data["quiz_set"]

            # Validate quiz_index
            if quiz_index < 0 or quiz_index >= len(quiz_set.quizzes):
                raise ValueError(
                    f"Invalid quiz_index {quiz_index} for quiz set with "
                    f"{len(quiz_set.quizzes)} quizzes"
                )

            # Get the specific quiz based on quiz_index
            quiz = quiz_set.quizzes[quiz_index]

            # Log available option IDs for debugging
            available_option_ids = [opt.option_id for opt in quiz.options]
            logger.debug(
                "Validating quiz submission: node_id=%s, quiz_index=%s, "
                "selected_option_ids=%s, available_options=%s",
                node_id,
                quiz_index,
                selected_option_ids,
                available_option_ids,
            )

            # Determine question_type from quiz data
            question_type = getattr(quiz, 'question_type', 'single_choice')

            # Find all correct options and validate selected options
            correct_options = [opt for opt in quiz.options if opt.is_correct]
            correct_option_ids_set = {opt.option_id for opt in correct_options}

            selected_options = []
            for opt_id in selected_option_ids:
                found = False
                for opt in quiz.options:
                    if opt.option_id == opt_id:
                        selected_options.append(opt)
                        found = True
                        break
                if not found:
                    raise ValueError(f"Invalid option id: {opt_id}")

            selected_option_id_set = set(selected_option_ids)

            if question_type == "single_choice":
                is_correct = len(selected_options) == 1 and selected_options[0].is_correct
            else:  # multiple_choice
                # Must select ALL correct options and NO incorrect ones
                is_correct = (correct_option_ids_set == selected_option_id_set)

            score_percent = 100 if is_correct else 0

            # Get next attempt number
            cursor.execute(
                """
                SELECT COALESCE(MAX(attempt_number), 0) + 1 AS next_attempt
                FROM quiz_attempts
                WHERE node_id = ?
                """,
                (node_id,),
            )
            attempt_number = cursor.fetchone()["next_attempt"]

            # Insert attempt record
            attempt_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            # Store as JSON array string for multi-select, or plain string for single
            selected_option_id_str = json.dumps(selected_option_ids) if len(selected_option_ids) > 1 else selected_option_ids[0]
            cursor.execute(
                """
                INSERT INTO quiz_attempts (
                    id, node_id, attempt_number, quiz_index, selected_option_id,
                    revision_session_id, is_correct, score_percent, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    node_id,
                    attempt_number,
                    quiz_index,
                    selected_option_id_str,
                    revision_session_id,
                    1 if is_correct else 0,
                    score_percent,
                    now,
                ),
            )
            # Only update original session metadata for non-revision
            # quiz submissions. Revision activity must not contaminate
            # the original session's last_active_node_id or updated_at.
            if revision_session_id is None:
                self._update_last_active_node_internal(
                    session_id=session_id,
                    node_id=node_id,
                    conn=active_conn,
                )
            if owns_connection:
                active_conn.commit()

            # Calculate mastery for multi-quiz scenario
            # For single quiz: mastery = this attempt is correct
            # For multi-quiz: mastery = all quizzes answered correctly at least once
            total_quizzes = len(quiz_set.quizzes)
            if total_quizzes == 1:
                is_mastered = is_correct
            else:
                # Check if all quizzes have at least one correct attempt
                is_mastered = self._check_multi_quiz_mastery(
                    node_id, total_quizzes, active_conn
                )

            logger.info(
                f"Quiz attempt recorded: node={node_id}, "
                f"attempt={attempt_number}, quiz_index={quiz_index}, "
                f"correct={is_correct}, mastered={is_mastered}"
            )

            return {
                "id": attempt_id,
                "node_id": node_id,
                "attempt_number": attempt_number,
                "quiz_index": quiz_index,
                "selected_option_ids": selected_option_ids,
                "is_correct": is_correct,
                "score_percent": score_percent,
                # Only reveal correct answers when user answered correctly
                "correct_option_ids": list(correct_option_ids_set)
                if is_correct
                else [],
                "explanation": correct_options[0].explanation
                if correct_options and is_correct
                else "",
                "selected_explanation": selected_options[0].explanation
                if not is_correct and selected_options
                else None,
                "is_mastered": is_mastered,
                "created_at": now,
                "updated_at": now,
            }
        except sqlite3.Error as e:
            logger.error(f"Error creating quiz attempt: {e}")
            raise
        finally:
            if owns_connection:
                active_conn.close()

    def _check_multi_quiz_mastery(
        self, node_id: str, total_quizzes: int, conn: sqlite3.Connection
    ) -> bool:
        """Check if all quizzes in a set have been answered correctly.

        Args:
            node_id: The concept node identifier
            total_quizzes: Total number of quizzes in the set
            conn: Database connection

        Returns:
            True if every quiz index has at least one correct attempt
        """
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT quiz_index
            FROM quiz_attempts
            WHERE node_id = ? AND is_correct = 1
            """,
            (node_id,),
        )
        correct_quiz_indices = {row["quiz_index"] for row in cursor.fetchall()}

        # Mastered if all quiz indices 0 to total_quizzes-1 are in correct set
        required_indices = set(range(total_quizzes))
        return correct_quiz_indices.issuperset(required_indices)

    def get_quiz_attempts(self, node_id: str) -> Dict[str, Any]:
        """Get quiz attempt history for a node.

        Args:
            node_id: The concept node identifier

        Returns:
            Dict with total_attempts, is_mastered, best_score, and attempts list
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Get all attempts ordered by attempt_number
            cursor.execute(
                """
                SELECT
                    id, node_id, attempt_number, quiz_index, selected_option_id,
                    is_correct, score_percent, created_at
                FROM quiz_attempts
                WHERE node_id = ?
                ORDER BY attempt_number ASC
                """,
                (node_id,),
            )
            rows = cursor.fetchall()

            cursor.execute(
                """
                SELECT payload, format_version
                FROM quiz_data
                WHERE node_id = ?
                """,
                (node_id,),
            )
            quiz_row = cursor.fetchone()

            quiz_set = None
            if quiz_row:
                payload = json.loads(quiz_row["payload"])
                format_version = quiz_row["format_version"]

                if format_version is None or format_version < 1:
                    try:
                        quiz_set = convert_legacy_to_quiz_set(payload)
                    except ValidationError:
                        logger.warning(
                            f"Failed to parse legacy quiz payload for node {node_id}"
                        )
                else:
                    try:
                        quiz_set = QuizSet.model_validate(payload)
                    except ValidationError:
                        try:
                            quiz_set = convert_legacy_to_quiz_set(payload)
                        except ValidationError:
                            logger.warning(
                                f"Failed to parse quiz payload for node {node_id}"
                            )

            attempts = []
            best_score = 0

            for row in rows:
                score = row["score_percent"]
                if score > best_score:
                    best_score = score

                correct_option_ids = []
                explanation = ""
                quiz_index = row["quiz_index"]
                selected_option_id_raw = row["selected_option_id"]

                # Parse stored value: JSON array for multi-select, plain string for single
                try:
                    selected_option_ids = json.loads(selected_option_id_raw)
                    if not isinstance(selected_option_ids, list):
                        selected_option_ids = [selected_option_id_raw]
                except (json.JSONDecodeError, TypeError):
                    selected_option_ids = [selected_option_id_raw]

                if quiz_set and quiz_index < len(quiz_set.quizzes):
                    quiz = quiz_set.quizzes[quiz_index]

                    for option in quiz.options:
                        if option.is_correct:
                            correct_option_ids.append(option.option_id)

                    for option in quiz.options:
                        if option.option_id in selected_option_ids:
                            explanation = option.explanation
                            break

                    if not explanation:
                        for option in quiz.options:
                            if option.is_correct:
                                explanation = option.explanation
                                break

                attempts.append(
                    {
                        "id": row["id"],
                        "node_id": row["node_id"],
                        "attempt_number": row["attempt_number"],
                        "quiz_index": quiz_index,
                        "selected_option_ids": selected_option_ids,
                        "is_correct": bool(row["is_correct"]),
                        "score_percent": score,
                        "created_at": row["created_at"],
                        "correct_option_ids": correct_option_ids,
                        "explanation": explanation,
                        "is_mastered": score >= 100,
                    }
                )

            # Calculate mastery: for single quiz, any 100% = mastered
            # For multi-quiz, need all quizzes correct
            is_mastered = self._calculate_mastery_from_attempts(node_id, attempts, conn)

            return {
                "node_id": node_id,
                "total_attempts": len(attempts),
                "is_mastered": is_mastered,
                "best_score": best_score,
                "attempts": attempts,
            }
        except sqlite3.Error as e:
            logger.error(f"Error getting quiz attempts: {e}")
            raise
        finally:
            conn.close()

    def _calculate_mastery_from_attempts(
        self,
        node_id: str,
        attempts: List[Dict[str, Any]],
        conn: sqlite3.Connection,
    ) -> bool:
        """Calculate mastery status from attempts list.

        For single quiz: any correct attempt = mastered
        For multi-quiz: all quizzes must have at least one correct attempt

        Args:
            node_id: The concept node identifier
            attempts: List of attempt dictionaries
            conn: Database connection

        Returns:
            True if the quiz/quiz set is mastered
        """
        if not attempts:
            return False

        # Get total quizzes for this node
        quiz_set_data = self.get_quiz_set_for_node(node_id)
        if quiz_set_data is None:
            return False

        quiz_set = quiz_set_data["quiz_set"]
        total_quizzes = len(quiz_set.quizzes)

        if total_quizzes == 1:
            # Single quiz: any correct attempt = mastered
            return any(a["is_correct"] for a in attempts)
        else:
            # Multi-quiz: all quizzes must have at least one correct attempt
            correct_quiz_indices = {
                a["quiz_index"] for a in attempts if a["is_correct"]
            }
            required_indices = set(range(total_quizzes))
            return correct_quiz_indices.issuperset(required_indices)

    def check_mastery(self, node_id: str) -> bool:
        """Check if a node's quiz has been mastered.

        For single quiz: True if any attempt was correct (100%).
        For multi-quiz: True if all quizzes have at least one correct attempt.

        Args:
            node_id: The concept node identifier

        Returns:
            True if mastered, False otherwise
        """
        conn = self._get_connection()
        try:
            # Get quiz set to determine multi-quiz scenario
            quiz_set_data = self.get_quiz_set_for_node(node_id)
            if quiz_set_data is None:
                return False

            quiz_set = quiz_set_data["quiz_set"]
            total_quizzes = len(quiz_set.quizzes)

            cursor = conn.cursor()

            if total_quizzes == 1:
                # Single quiz: any 100% score = mastered
                cursor.execute(
                    """
                    SELECT 1
                    FROM quiz_attempts
                    WHERE node_id = ? AND is_correct = 1
                    LIMIT 1
                    """,
                    (node_id,),
                )
                return cursor.fetchone() is not None
            else:
                # Multi-quiz: need all quizzes correct
                cursor.execute(
                    """
                    SELECT DISTINCT quiz_index
                    FROM quiz_attempts
                    WHERE node_id = ? AND is_correct = 1
                    """,
                    (node_id,),
                )
                correct_quiz_indices = {row["quiz_index"] for row in cursor.fetchall()}
                required_indices = set(range(total_quizzes))
                return correct_quiz_indices.issuperset(required_indices)
        except sqlite3.Error as e:
            logger.error(f"Error checking mastery: {e}")
            raise
        finally:
            conn.close()

    def _get_node_by_id(
        self, node_id: str, conn: sqlite3.Connection
    ) -> Optional[Dict[str, Any]]:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                cn.id,
                cn.learning_session_id,
                cn.sequence_index,
                cn.title,
                cn.content_markdown,
                cn.status,
                cn.error_message,
                cn.retry_available,
                cn.failed_step,
                cn.complexity,
                cn.summary_for_context,
                cn.key_terms,
                cn.created_at,
                cn.updated_at,
                qd.payload AS quiz_payload
            FROM concept_nodes cn
            LEFT JOIN quiz_data qd ON cn.id = qd.node_id
            WHERE cn.id = ?
            """,
            (node_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        quiz_payload = json.loads(row["quiz_payload"]) if row["quiz_payload"] else None
        key_terms_raw = row["key_terms"]
        key_terms = json.loads(key_terms_raw) if key_terms_raw else None
        return {
            "id": row["id"],
            "learning_session_id": row["learning_session_id"],
            "sequence_index": row["sequence_index"],
            "title": row["title"],
            "content_markdown": row["content_markdown"],
            "status": row["status"],
            "error_message": row["error_message"],
            "retry_available": bool(row["retry_available"])
            if row["retry_available"] is not None
            else False,
            "failed_step": row["failed_step"],
            "complexity": row["complexity"],
            "summary_for_context": row["summary_for_context"],
            "key_terms": key_terms,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "quiz": quiz_payload,
        }

    def get_concept_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a concept node by ID, managing the database connection lifecycle."""
        conn = self._get_connection()
        try:
            return self._get_node_by_id(node_id, conn)
        except sqlite3.Error as e:
            logger.error(f"Error getting concept node by ID: {e}")
            raise
        finally:
            conn.close()

    @staticmethod
    def _calculate_progress_percent(completed_nodes: int, total_nodes: int) -> int:
        """Calculate session progress percentage using floor integer math."""
        if total_nodes <= 0:
            return 0
        bounded_completed = min(max(completed_nodes, 0), total_nodes)
        return (bounded_completed * 100) // total_nodes

    def _update_session_progress(
        self,
        session_id: str,
        conn: sqlite3.Connection,
        last_active_node_id: Optional[str] = None,
    ) -> int:
        """Update cached session progress and completion metadata."""
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                COUNT(*) AS total_nodes,
                SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS completed_nodes
            FROM concept_nodes
            WHERE learning_session_id = ?
            """,
            (NodeStatus.COMPLETED.value, session_id),
        )
        row = cursor.fetchone()
        if row is None:
            return 0

        total_nodes = row["total_nodes"] or 0
        completed_nodes = row["completed_nodes"] or 0
        progress_percent = self._calculate_progress_percent(
            completed_nodes=completed_nodes,
            total_nodes=total_nodes,
        )
        session_status = "completed" if progress_percent == 100 else "in_progress"
        now = datetime.now(timezone.utc).isoformat()

        cursor.execute(
            """
            UPDATE learning_sessions
            SET status = ?,
                progress_percent = ?,
                completed_at = CASE
                    WHEN ? = 'completed'
                        THEN COALESCE(completed_at, ?)
                    ELSE completed_at
                END,
                last_active_node_id = COALESCE(?, last_active_node_id),
                updated_at = ?
            WHERE id = ?
            """,
            (
                session_status,
                progress_percent,
                session_status,
                now,
                last_active_node_id,
                now,
                session_id,
            ),
        )
        return progress_percent

    def update_last_active_node(
        self,
        session_id: str,
        node_id: str,
    ) -> None:
        """Update the last active node for a learning session.

        Args:
            session_id: The learning session identifier.
            node_id: The node to mark as last active.

        Raises:
            LookupError: If the session does not exist.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM learning_sessions WHERE id = ?",
                (session_id,),
            )
            if not cursor.fetchone():
                raise LookupError(f"Learning session not found: {session_id}")
            self._update_last_active_node_internal(session_id, node_id, conn)
            conn.commit()
        except LookupError:
            raise
        except sqlite3.Error as e:
            logger.error(f"Error updating last active node: {e}")
            raise
        finally:
            conn.close()

    def _update_last_active_node_internal(
        self,
        session_id: str,
        node_id: str,
        conn: sqlite3.Connection,
    ) -> None:
        """Update the last active node pointer for a learning session."""
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            UPDATE learning_sessions
            SET last_active_node_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (node_id, now, session_id),
        )

    def _ensure_concept_node_columns(self, conn: sqlite3.Connection) -> None:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(concept_nodes)")
        existing_columns = {row["name"] for row in cursor.fetchall()}
        if "error_message" not in existing_columns:
            cursor.execute("ALTER TABLE concept_nodes ADD COLUMN error_message TEXT")
        if "retry_available" not in existing_columns:
            cursor.execute(
                "ALTER TABLE concept_nodes ADD COLUMN retry_available INTEGER DEFAULT 0"
            )
        if "complexity" not in existing_columns:
            cursor.execute(
                "ALTER TABLE concept_nodes ADD COLUMN complexity TEXT DEFAULT 'Intermediate'"
            )
        if "summary_for_context" not in existing_columns:
            cursor.execute(
                "ALTER TABLE concept_nodes ADD COLUMN summary_for_context TEXT"
            )
        if "key_terms" not in existing_columns:
            cursor.execute(
                "ALTER TABLE concept_nodes ADD COLUMN key_terms TEXT"
            )
        if "failed_step" not in existing_columns:
            cursor.execute(
                "ALTER TABLE concept_nodes ADD COLUMN failed_step TEXT"
            )
        if "generation_status" not in existing_columns:
            cursor.execute(
                "ALTER TABLE concept_nodes "
                "ADD COLUMN generation_status TEXT NOT NULL DEFAULT 'READY'"
            )

    def _ensure_session_progress_columns(self, conn: sqlite3.Connection) -> None:
        """Migrate learning_sessions table to include progress tracking."""
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(learning_sessions)")
        existing_columns = {row["name"] for row in cursor.fetchall()}

        if "status" not in existing_columns:
            cursor.execute(
                "ALTER TABLE learning_sessions "
                "ADD COLUMN status TEXT DEFAULT 'in_progress'"
            )
        if "progress_percent" not in existing_columns:
            cursor.execute(
                "ALTER TABLE learning_sessions "
                "ADD COLUMN progress_percent INTEGER DEFAULT 0"
            )
        if "completed_at" not in existing_columns:
            cursor.execute(
                "ALTER TABLE learning_sessions ADD COLUMN completed_at TIMESTAMP"
            )
        if "last_active_node_id" not in existing_columns:
            cursor.execute(
                "ALTER TABLE learning_sessions ADD COLUMN last_active_node_id TEXT"
            )
        if "mode" not in existing_columns:
            cursor.execute(
                "ALTER TABLE learning_sessions "
                "ADD COLUMN mode TEXT NOT NULL DEFAULT 'auto'"
            )
        if "resolved_mode" not in existing_columns:
            cursor.execute(
                "ALTER TABLE learning_sessions "
                "ADD COLUMN resolved_mode TEXT"
            )
        if "title_finalized" not in existing_columns:
            cursor.execute(
                "ALTER TABLE learning_sessions "
                "ADD COLUMN title_finalized INTEGER NOT NULL DEFAULT 1"
            )

    def _ensure_node_timestamp_columns(self, conn: sqlite3.Connection) -> None:
        """Migrate concept_nodes table to include started/completed timestamps."""
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(concept_nodes)")
        existing_columns = {row["name"] for row in cursor.fetchall()}

        if "started_at" not in existing_columns:
            cursor.execute("ALTER TABLE concept_nodes ADD COLUMN started_at TIMESTAMP")
        if "completed_at" not in existing_columns:
            cursor.execute(
                "ALTER TABLE concept_nodes ADD COLUMN completed_at TIMESTAMP"
            )

    def _ensure_quiz_data_columns(self, conn: sqlite3.Connection) -> None:
        """Migrate quiz_data table to support QuizSet format.

        Adds columns for format_version, shuffle_seed, and current_index
        to support multi-quiz sets and deterministic shuffling.

        Migration strategy:
        - format_version: 0 (legacy) or 1 (QuizSet format)
        - shuffle_seed: NULL or stored seed for deterministic shuffle
        - current_index: 0 or index of current quiz in set
        """
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(quiz_data)")
        existing_columns = {row["name"] for row in cursor.fetchall()}

        if "format_version" not in existing_columns:
            cursor.execute("ALTER TABLE quiz_data ADD COLUMN format_version INTEGER")
        if "shuffle_seed" not in existing_columns:
            cursor.execute("ALTER TABLE quiz_data ADD COLUMN shuffle_seed TEXT")
        if "current_index" not in existing_columns:
            cursor.execute(
                "ALTER TABLE quiz_data ADD COLUMN current_index INTEGER DEFAULT 0"
            )
        if "updated_at" not in existing_columns:
            cursor.execute("ALTER TABLE quiz_data ADD COLUMN updated_at TIMESTAMP")

        self._normalize_quiz_data_format_versions(conn)

    def _normalize_quiz_data_format_versions(self, conn: sqlite3.Connection) -> None:
        """Normalize format_version values using the stored payload shape.

        Legacy payloads are single QuizCard dicts and should be version 0.
        QuizSet payloads contain a top-level "quizzes" list and should be 1.
        """
        cursor = conn.cursor()
        cursor.execute("SELECT id, payload, format_version FROM quiz_data")
        rows = cursor.fetchall()
        if not rows:
            return

        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, ValueError):
                continue

            is_quiz_set = isinstance(payload, dict) and isinstance(
                payload.get("quizzes"), list
            )
            expected_version = 1 if is_quiz_set else 0
            if row["format_version"] == expected_version:
                continue

            cursor.execute(
                """
                UPDATE quiz_data
                SET format_version = ?, updated_at = COALESCE(updated_at, ?)
                WHERE id = ?
                """,
                (expected_version, now, row["id"]),
            )

    def _ensure_quiz_attempts_columns(self, conn: sqlite3.Connection) -> None:
        """Migrate quiz_attempts table to support multi-quiz tracking.

        Adds quiz_index column to track which quiz in a set the attempt was for.
        """
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(quiz_attempts)")
        existing_columns = {row["name"] for row in cursor.fetchall()}

        if "quiz_index" not in existing_columns:
            cursor.execute(
                "ALTER TABLE quiz_attempts ADD COLUMN quiz_index INTEGER DEFAULT 0"
            )

    def _ensure_quiz_attempts_revision_column(self, conn: sqlite3.Connection) -> None:
        """Migrate quiz_attempts table to include revision_session_id.

        Note: SQLite ignores FK constraints and CASCADE clauses on
        columns added via ALTER TABLE.  The REFERENCES clause is kept
        for documentation only.  New databases get the full FK with
        CASCADE from the CREATE TABLE statement.  On migrated
        databases, application-level cleanup is required when deleting
        revision sessions.
        """
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(quiz_attempts)")
        existing_columns = {row["name"] for row in cursor.fetchall()}

        if "revision_session_id" not in existing_columns:
            cursor.execute(
                "ALTER TABLE quiz_attempts ADD COLUMN revision_session_id TEXT"
            )

    def _get_next_revision_number(
        self, original_session_id: str, conn: sqlite3.Connection
    ) -> int:
        """Get the next revision number for an original learning session."""
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COALESCE(MAX(revision_number), 0) + 1 AS next_revision
            FROM revision_sessions
            WHERE original_session_id = ?
            """,
            (original_session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return 1
        return int(row["next_revision"])


learning_manager = LearningManager()
