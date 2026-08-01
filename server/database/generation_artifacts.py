"""
============================================================================
FILE: generation_artifacts.py
LOCATION: server/database/generation_artifacts.py
============================================================================
PURPOSE:
    Durable table-of-contents, private brief, generated content, and
    citation persistence for the internet-grounded course generator.
ROLE IN PROJECT:
    Owns Planner-to-Generator artifacts without growing LearningManager.
    - Persists idempotent SKELETON nodes from a CourseOutline
    - Stores compact private GenerationBrief payloads per topic
    - Replaces node citations only through the brief approval allowlist
KEY COMPONENTS:
    - GenerationArtifactConflict: Conflicting title or brief alignment
    - UnsupportedCitationError: Citation outside the approved source set
    - GenerationArtifactStore: All artifact persistence methods
DEPENDENCIES:
    - External: sqlite3, uuid, logging
    - Internal: server.database.persistence, server.database.sqlite_utils,
                server.schemas.generation, server.schemas.learning
USAGE:
    from server.database.generation_artifacts import GenerationArtifactStore
    store = GenerationArtifactStore()
    nodes = store.persist_outline(session_id, outline)
============================================================================
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from server.database.persistence import DB_PATH
from server.database.sqlite_utils import optional_transaction
from server.schemas.generation import (
    GenerationBrief,
    GenerationBriefBatch,
    SourceCitation,
)
from server.schemas.learning import NodeStatus, QuizSet, TopicNode

logger = logging.getLogger(__name__)

SKELETON_STATUS = "SKELETON"
GENERATING_STATUS = "GENERATING"
READY_STATUS = "READY"
ERROR_STATUS = "ERROR"

NODE_DICT_KEYS = (
    "id, learning_session_id, sequence_index, title, content_markdown,"
    " status, error_message, retry_available, failed_step, complexity,"
    " summary_for_context, key_terms, created_at, updated_at,"
    " generation_status"
)


class GenerationArtifactConflict(RuntimeError):
    """Raised when outline or brief rows disagree with existing state."""


class UnsupportedCitationError(RuntimeError):
    """Raised when a citation references a source outside the approval set."""


def _node_id_for_topic(session_id: str, topic_index: int) -> str:
    """Derive the deterministic node ID for a session topic."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"a2ui:{session_id}:{topic_index}"))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _node_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a concept_nodes row into the public node dictionary shape."""
    key_terms_raw = row["key_terms"]
    key_terms = json.loads(key_terms_raw) if key_terms_raw else None
    return {
        "id": row["id"],
        "learning_session_id": row["learning_session_id"],
        "sequence_index": int(row["sequence_index"]),
        "title": row["title"],
        "content_markdown": row["content_markdown"],
        "status": row["status"],
        "error_message": row["error_message"],
        "retry_available": bool(row["retry_available"]),
        "failed_step": row["failed_step"],
        "complexity": row["complexity"],
        "summary_for_context": row["summary_for_context"],
        "key_terms": key_terms,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "generation_status": row["generation_status"],
    }


class GenerationArtifactStore:
    """Persists outline, brief, content, and citation artifacts."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DB_PATH

    def persist_outline(
        self,
        session_id: str,
        outline: Any,
        conn: Optional[sqlite3.Connection] = None,
    ) -> list[dict[str, Any]]:
        """Upsert session title and every outline topic in one transaction.

        Node IDs are deterministic UUID5 values, so repeated identical
        writes return the same IDs. A conflicting existing title raises
        GenerationArtifactConflict.
        """
        timestamp = _utc_now()
        now_iso = timestamp.isoformat()
        with optional_transaction(self.db_path, conn) as active_conn:
            active_conn.execute(
                """
                UPDATE learning_sessions
                SET course_title = ?, title_finalized = 1, updated_at = ?
                WHERE id = ?
                """,
                (outline.course_title, now_iso, session_id),
            )
            for topic in outline.topics:
                node_id = _node_id_for_topic(session_id, topic.index)
                existing = active_conn.execute(
                    """
                    SELECT title FROM concept_nodes
                    WHERE id = ?
                    """,
                    (node_id,),
                ).fetchone()
                if existing is not None and existing["title"] != topic.title:
                    raise GenerationArtifactConflict(
                        f"Topic {topic.index} title differs from stored outline"
                    )
                active_conn.execute(
                    """
                    INSERT INTO concept_nodes (
                        id, learning_session_id, sequence_index, title,
                        content_markdown, status, error_message,
                        retry_available, failed_step, complexity,
                        summary_for_context, key_terms, created_at,
                        updated_at, generation_status
                    )
                    VALUES (?, ?, ?, ?, '', ?, NULL, 0, NULL, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (learning_session_id, sequence_index)
                    DO UPDATE SET
                        title = excluded.title,
                        complexity = excluded.complexity,
                        summary_for_context = excluded.summary_for_context,
                        key_terms = excluded.key_terms,
                        updated_at = excluded.updated_at
                    """,
                    (
                        node_id,
                        session_id,
                        topic.index,
                        topic.title,
                        NodeStatus.LOCKED.value,
                        topic.complexity,
                        topic.summary_for_context,
                        json.dumps(topic.key_terms),
                        now_iso,
                        now_iso,
                        SKELETON_STATUS,
                    ),
                )
            rows = active_conn.execute(
                f"""
                SELECT {NODE_DICT_KEYS} FROM concept_nodes
                WHERE learning_session_id = ?
                ORDER BY sequence_index ASC
                """,
                (session_id,),
            ).fetchall()
        return [_node_row_to_dict(row) for row in rows]

    def upsert_brief_batch(
        self,
        session_id: str,
        batch: GenerationBriefBatch,
        conn: Optional[sqlite3.Connection] = None,
    ) -> list[GenerationBrief]:
        """Upsert a contiguous brief batch after node alignment checks.

        Each brief must map to an existing skeleton node for the session
        with a matching sequence index, otherwise GenerationArtifactConflict
        is raised. Payloads are stored compactly with excluded None fields.
        """
        timestamp = _utc_now()
        now_iso = timestamp.isoformat()
        briefs: list[GenerationBrief] = []
        with optional_transaction(self.db_path, conn) as active_conn:
            for brief in batch.briefs:
                node_id = _node_id_for_topic(session_id, brief.topic_index)
                node_row = active_conn.execute(
                    """
                    SELECT sequence_index FROM concept_nodes
                    WHERE id = ? AND learning_session_id = ?
                    """,
                    (node_id, session_id),
                ).fetchone()
                if (
                    node_row is None
                    or int(node_row["sequence_index"]) != brief.topic_index
                ):
                    raise GenerationArtifactConflict(
                        f"Node for session {session_id} topic"
                        f" {brief.topic_index} is missing or misaligned"
                    )
                active_conn.execute(
                    """
                    INSERT INTO generation_briefs (
                        id, session_id, node_id, topic_index, payload_json,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (session_id, topic_index) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        str(uuid.uuid4()),
                        session_id,
                        node_id,
                        brief.topic_index,
                        brief.model_dump_json(exclude_none=True),
                        now_iso,
                        now_iso,
                    ),
                )
            rows = active_conn.execute(
                """
                SELECT payload_json FROM generation_briefs
                WHERE session_id = ?
                ORDER BY topic_index ASC
                """,
                (session_id,),
            ).fetchall()
            briefs = [
                GenerationBrief.model_validate_json(row["payload_json"])
                for row in rows
            ]
        return briefs

    def get_brief(
        self, node_id: str
    ) -> Optional[GenerationBrief]:
        """Return the stored brief for a node, or None when absent."""
        with optional_transaction(self.db_path, None) as conn:
            row = conn.execute(
                "SELECT payload_json FROM generation_briefs WHERE node_id = ?",
                (node_id,),
            ).fetchone()
        if row is None:
            return None
        return GenerationBrief.model_validate_json(row["payload_json"])

    def get_briefs(
        self,
        session_id: str,
        start_index: int,
        limit: int,
    ) -> list[GenerationBrief]:
        """Return briefs for a session ordered by topic index from a start."""
        with optional_transaction(self.db_path, None) as conn:
            rows = conn.execute(
                """
                SELECT payload_json FROM generation_briefs
                WHERE session_id = ? AND topic_index >= ?
                ORDER BY topic_index ASC
                LIMIT ?
                """,
                (session_id, start_index, limit),
            ).fetchall()
        return [
            GenerationBrief.model_validate_json(row["payload_json"])
            for row in rows
        ]

    def get_topic(
        self, session_id: str, topic_index: int
    ) -> TopicNode:
        """Return the outline TopicNode for a session topic index."""
        with optional_transaction(self.db_path, None) as conn:
            row = conn.execute(
                """
                SELECT id, title, summary_for_context, key_terms, complexity
                FROM concept_nodes
                WHERE learning_session_id = ? AND sequence_index = ?
                """,
                (session_id, topic_index),
            ).fetchone()
            if row is None:
                raise LookupError(
                    f"Topic {topic_index} not found for session {session_id}"
                )
            brief_row = conn.execute(
                "SELECT payload_json FROM generation_briefs WHERE node_id = ?",
                (row["id"],),
            ).fetchone()
        if brief_row is None:
            quiz_count = 1
        else:
            brief = GenerationBrief.model_validate_json(
                brief_row["payload_json"]
            )
            quiz_count = len(brief.quiz_learning_targets)
        key_terms = (
            json.loads(row["key_terms"]) if row["key_terms"] else []
        )
        return TopicNode(
            index=topic_index,
            title=row["title"],
            summary_for_context=row["summary_for_context"],
            key_terms=key_terms,
            complexity=row["complexity"] or "Intermediate",
            quiz_count=quiz_count,
        )

    def persist_generated_content(
        self,
        node_id: str,
        content_markdown: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> dict[str, Any]:
        """Store generated markdown without exposing the node as ready."""
        timestamp = _utc_now()
        with optional_transaction(self.db_path, conn) as active_conn:
            active_conn.execute(
                """
                UPDATE concept_nodes
                SET content_markdown = ?, generation_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (content_markdown, GENERATING_STATUS, timestamp.isoformat(), node_id),
            )
            row = active_conn.execute(
                f"SELECT {NODE_DICT_KEYS} FROM concept_nodes WHERE id = ?",
                (node_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"Node not found: {node_id}")
        return _node_row_to_dict(row)

    def persist_topic_success(
        self,
        node_id: str,
        quiz_set: QuizSet,
        citations: list[SourceCitation],
        conn: Optional[sqlite3.Connection] = None,
    ) -> dict[str, Any]:
        """Write quiz payload, mark READY, and replace approved citations."""
        timestamp = _utc_now()
        with optional_transaction(self.db_path, conn) as active_conn:
            node_row = active_conn.execute(
                "SELECT learning_session_id, sequence_index FROM concept_nodes"
                " WHERE id = ?",
                (node_id,),
            ).fetchone()
            if node_row is None:
                raise LookupError(f"Node not found: {node_id}")
            existing_quiz = active_conn.execute(
                "SELECT id FROM quiz_data WHERE node_id = ?",
                (node_id,),
            ).fetchone()
            payload = json.dumps(quiz_set.model_dump())
            if existing_quiz is None:
                active_conn.execute(
                    """
                    INSERT INTO quiz_data (
                        id, node_id, payload, format_version, shuffle_seed,
                        current_index, created_at, updated_at
                    )
                    VALUES (?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        node_id,
                        payload,
                        quiz_set.shuffle_seed,
                        quiz_set.current_index,
                        timestamp.isoformat(),
                        timestamp.isoformat(),
                    ),
                )
            else:
                active_conn.execute(
                    """
                    UPDATE quiz_data
                    SET payload = ?, format_version = 1,
                        shuffle_seed = ?, current_index = ?, updated_at = ?
                    WHERE node_id = ?
                    """,
                    (
                        payload,
                        quiz_set.shuffle_seed,
                        quiz_set.current_index,
                        timestamp.isoformat(),
                        node_id,
                    ),
                )
            learner_status = (
                NodeStatus.VIEWING_EXPLANATION
                if int(node_row["sequence_index"]) == 0
                else NodeStatus.LOCKED
            )
            active_conn.execute(
                """
                UPDATE concept_nodes
                SET generation_status = ?, status = ?, error_message = NULL,
                    retry_available = 0, failed_step = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    READY_STATUS,
                    learner_status.value,
                    timestamp.isoformat(),
                    node_id,
                ),
            )
            if citations:
                self.replace_node_sources(
                    node_id,
                    citations,
                    conn=active_conn,
                )
            row = active_conn.execute(
                f"SELECT {NODE_DICT_KEYS} FROM concept_nodes WHERE id = ?",
                (node_id,),
            ).fetchone()
        return _node_row_to_dict(row)

    def persist_topic_error(
        self,
        node_id: str,
        failed_step: str,
        safe_error_message: str,
        content_markdown: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> dict[str, Any]:
        """Mark a topic failed with retry available and safe error text."""
        timestamp = _utc_now()
        with optional_transaction(self.db_path, conn) as active_conn:
            active_conn.execute(
                """
                UPDATE concept_nodes
                SET generation_status = ?, status = ?, error_message = ?,
                    retry_available = 1, failed_step = ?,
                    content_markdown = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    ERROR_STATUS,
                    NodeStatus.ERROR.value,
                    safe_error_message,
                    failed_step,
                    content_markdown,
                    timestamp.isoformat(),
                    node_id,
                ),
            )
            row = active_conn.execute(
                f"SELECT {NODE_DICT_KEYS} FROM concept_nodes WHERE id = ?",
                (node_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"Node not found: {node_id}")
        return _node_row_to_dict(row)

    def replace_node_sources(
        self,
        node_id: str,
        citations: list[SourceCitation],
        conn: Optional[sqlite3.Connection] = None,
    ) -> list[dict[str, Any]]:
        """Replace node citations after validating the complete new set.

        Every citation must reference a source approved by the node brief
        and persisted in the node session; any violation raises
        UnsupportedCitationError before old links are deleted.
        """
        timestamp = _utc_now()
        with optional_transaction(self.db_path, conn) as active_conn:
            node_row = active_conn.execute(
                "SELECT learning_session_id FROM concept_nodes WHERE id = ?",
                (node_id,),
            ).fetchone()
            if node_row is None:
                raise LookupError(f"Node not found: {node_id}")
            session_id = node_row["learning_session_id"]
            self._validate_citations(
                active_conn, session_id, node_id, citations
            )
            active_conn.execute(
                "DELETE FROM node_sources WHERE node_id = ?",
                (node_id,),
            )
            active_conn.executemany(
                """
                INSERT INTO node_sources (
                    node_id, source_id, citation_order, claim
                )
                VALUES (?, ?, ?, ?)
                """,
                [
                    (node_id, citation.source_id, order, citation.claim)
                    for order, citation in enumerate(citations)
                ],
            )
            rows = active_conn.execute(
                """
                SELECT node_id, source_id, citation_order, claim
                FROM node_sources
                WHERE node_id = ?
                ORDER BY citation_order ASC
                """,
                (node_id,),
            ).fetchall()
        return self._links_from_rows(rows)

    def list_node_sources(
        self, node_id: str
    ) -> list[dict[str, Any]]:
        """Return a node's citations ordered by citation order."""
        with optional_transaction(self.db_path, None) as conn:
            rows = conn.execute(
                """
                SELECT node_id, source_id, citation_order, claim
                FROM node_sources
                WHERE node_id = ?
                ORDER BY citation_order ASC
                """,
                (node_id,),
            ).fetchall()
        return self._links_from_rows(rows)

    def get_citations_by_session(
        self, session_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Return node-id-keyed citation lists for a session."""
        with optional_transaction(self.db_path, None) as conn:
            rows = conn.execute(
                """
                SELECT ns.node_id, ns.source_id, ns.citation_order, ns.claim
                FROM node_sources ns
                JOIN concept_nodes cn ON ns.node_id = cn.id
                WHERE cn.learning_session_id = ?
                ORDER BY ns.citation_order ASC
                """,
                (session_id,),
            ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["node_id"], []).append(
                {
                    "node_id": row["node_id"],
                    "source_id": row["source_id"],
                    "citation_order": int(row["citation_order"]),
                    "claim": row["claim"],
                }
            )
        return grouped

    def _validate_citations(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        node_id: str,
        citations: list[SourceCitation],
    ) -> None:
        """Raise UnsupportedCitationError on any non-approved source."""
        brief_row = conn.execute(
            "SELECT payload_json FROM generation_briefs WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        approved = (
            GenerationBrief.model_validate_json(
                brief_row["payload_json"]
            ).approved_source_ids
            if brief_row is not None
            else []
        )
        source_ids = {citation.source_id for citation in citations}
        if not source_ids:
            return
        placeholders = ",".join("?" for _ in source_ids)
        existing = conn.execute(
            f"""
            SELECT id FROM research_sources
            WHERE session_id = ? AND id IN ({placeholders})
            """,
            (session_id, *source_ids),
        ).fetchall()
        existing_ids = {row["id"] for row in existing}
        for citation in citations:
            if citation.source_id not in approved:
                raise UnsupportedCitationError(
                    f"Source {citation.source_id} is not approved for node"
                )
            if citation.source_id not in existing_ids:
                raise UnsupportedCitationError(
                    f"Source {citation.source_id} is not persisted for session"
                )

    @staticmethod
    def _links_from_rows(
        rows: list[sqlite3.Row],
    ) -> list[dict[str, Any]]:
        return [
            {
                "node_id": row["node_id"],
                "source_id": row["source_id"],
                "citation_order": int(row["citation_order"]),
                "claim": row["claim"],
            }
            for row in rows
        ]
