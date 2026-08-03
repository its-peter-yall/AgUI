"""
============================================================================
FILE: mongo_learning.py
LOCATION: server/database/repositories/mongo_learning.py
============================================================================
PURPOSE:
    Synchronous Mongo implementation of LearningRepository for sessions,
    concept nodes, quizzes, attempts, and revisions.
ROLE IN PROJECT:
    Phase 3A Atlas adapter for learning persistence. Mirrors LearningManager
    public method names and API shapes using one document per SQLite row.
DEPENDENCIES:
    - External: pymongo, pydantic
    - Internal: server.database.repositories.mongo_common,
                server.schemas.learning
USAGE:
    repo = MongoLearningRepository(database)
    session = repo.create_learning_session("q", "Course")
============================================================================
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from server.database.repositories.mongo_common import (
    document_to_row,
    model_payload,
    utc_iso,
)
from server.schemas.learning import (
    FailedStep,
    NodeStatus,
    QuizCard,
    QuizSet,
)

logger = logging.getLogger(__name__)

_VALID_TRANSITIONS: dict[NodeStatus, set[NodeStatus]] = {
    NodeStatus.LOCKED: {
        NodeStatus.VIEWING_EXPLANATION,
        NodeStatus.ERROR,
    },
    NodeStatus.VIEWING_EXPLANATION: {
        NodeStatus.IN_QUIZ,
        NodeStatus.ERROR,
    },
    NodeStatus.IN_QUIZ: {
        NodeStatus.SHOWING_FEEDBACK,
        NodeStatus.ERROR,
    },
    NodeStatus.SHOWING_FEEDBACK: {
        NodeStatus.IN_QUIZ,
        NodeStatus.COMPLETED,
    },
    NodeStatus.COMPLETED: set(),
    NodeStatus.ERROR: {
        NodeStatus.LOCKED,
        NodeStatus.VIEWING_EXPLANATION,
    },
}


def _is_valid_transition(
    current_status: NodeStatus,
    next_status: NodeStatus,
) -> bool:
    if current_status == next_status:
        return True
    return next_status in _VALID_TRANSITIONS[current_status]


def _calculate_progress_percent(
    completed_nodes: int,
    total_nodes: int,
) -> int:
    if total_nodes <= 0:
        return 0
    bounded = min(max(completed_nodes, 0), total_nodes)
    return (bounded * 100) // total_nodes


class MongoLearningRepository:
    """Mongo implementation of learning, quiz, and revision persistence."""

    def __init__(self, database: Any) -> None:
        self._db = database
        self._sessions = database["learning_sessions"]
        self._nodes = database["concept_nodes"]
        self._quizzes = database["quiz_data"]
        self._attempts = database["quiz_attempts"]
        self._revisions = database["revision_sessions"]
        self._revision_nodes = database["revision_node_progress"]

    def create_learning_session(
        self,
        query: str,
        course_title: str,
        user_id: Optional[str] = None,
        mode: str = "auto",
        resolved_mode: Optional[str] = None,
    ) -> dict[str, Any]:
        now = utc_iso()
        document = {
            "_id": str(uuid.uuid4()),
            "user_id": user_id,
            "query": query,
            "course_title": course_title,
            "title_finalized": True,
            "mode": mode,
            "resolved_mode": resolved_mode,
            "status": "active",
            "progress_percent": 0,
            "completed_at": None,
            "last_active_node_id": None,
            "created_at": now,
            "updated_at": now,
        }
        self._sessions.insert_one(document)
        return document_to_row(document) or {}

    def get_learning_session(
        self,
        session_id: str,
    ) -> Optional[dict[str, Any]]:
        document = self._sessions.find_one({"_id": session_id})
        if document is None:
            return None
        row = document_to_row(document) or {}
        total_nodes = self._nodes.count_documents(
            {"learning_session_id": session_id}
        )
        completed_nodes = self._nodes.count_documents(
            {
                "learning_session_id": session_id,
                "status": NodeStatus.COMPLETED.value,
            }
        )
        title_finalized = row.get("title_finalized")
        if title_finalized is None:
            title_finalized = True
        row["title_finalized"] = bool(title_finalized)
        row["total_nodes"] = total_nodes
        row["completed_nodes"] = completed_nodes
        return row

    def get_session_progress(
        self,
        session_id: str,
    ) -> Optional[dict[str, Any]]:
        session = self._sessions.find_one({"_id": session_id})
        if session is None:
            return None
        total = self._nodes.count_documents(
            {"learning_session_id": session_id}
        )
        completed = self._nodes.count_documents(
            {
                "learning_session_id": session_id,
                "status": NodeStatus.COMPLETED.value,
            }
        )
        progress = _calculate_progress_percent(completed, total)
        last_active_id = session.get("last_active_node_id")
        last_title = None
        if last_active_id is not None:
            last_node = self._nodes.find_one(
                {"_id": last_active_id},
                {"title": 1},
            )
            if last_node is not None:
                last_title = last_node.get("title")
        return {
            "progress_percent": progress,
            "status": session.get("status") or "in_progress",
            "completed_nodes": completed,
            "total_nodes": total,
            "last_active_node_id": last_active_id,
            "last_active_node_title": last_title,
        }

    def get_sessions_list(
        self,
        user_id: Optional[str],
        status: str = "all",
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        query: dict[str, Any] = {}
        if user_id is not None:
            query["user_id"] = user_id
        if status != "all":
            query["status"] = status
        safe_sort = sort_by if sort_by in {
            "created_at",
            "updated_at",
            "course_title",
        } else "updated_at"
        direction = ASCENDING if sort_order == "asc" else DESCENDING
        cursor = self._sessions.find(query).sort(
            safe_sort,
            direction,
        ).skip(offset).limit(limit)
        rows = [document_to_row(item) or {} for item in cursor]
        return rows, self._sessions.count_documents(query)

    def update_session_resolved_mode(
        self,
        session_id: str,
        resolved_mode: str,
    ) -> None:
        if resolved_mode not in ("lite", "full"):
            raise ValueError(f"Invalid resolved_mode: {resolved_mode}")
        result = self._sessions.update_one(
            {"_id": session_id},
            {
                "$set": {
                    "resolved_mode": resolved_mode,
                    "updated_at": utc_iso(),
                }
            },
        )
        if result.matched_count == 0:
            raise LookupError(f"Learning session not found: {session_id}")

    def update_last_active_node(
        self,
        session_id: str,
        node_id: str,
    ) -> None:
        result = self._sessions.update_one(
            {"_id": session_id},
            {
                "$set": {
                    "last_active_node_id": node_id,
                    "updated_at": utc_iso(),
                }
            },
        )
        if result.matched_count == 0:
            raise LookupError(f"Learning session not found: {session_id}")

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
        key_terms: Optional[list[str]] = None,
        failed_step: Optional[FailedStep] = None,
    ) -> dict[str, Any]:
        if self._sessions.find_one({"_id": session_id}) is None:
            raise ValueError(f"Learning session not found: {session_id}")
        now = utc_iso()
        node_id = str(uuid.uuid4())
        document: dict[str, Any] = {
            "_id": node_id,
            "learning_session_id": session_id,
            "sequence_index": sequence_index,
            "title": title,
            "content_markdown": content_markdown,
            "status": status.value,
            "generation_status": "READY",
            "error_message": error_message,
            "retry_available": retry_available,
            "failed_step": (
                failed_step.value if failed_step is not None else None
            ),
            "complexity": complexity,
            "summary_for_context": summary_for_context,
            "key_terms": key_terms,
            "created_at": now,
            "updated_at": now,
        }
        try:
            self._nodes.insert_one(document)
        except DuplicateKeyError as exc:
            raise ValueError(
                "Duplicate concept node for session/sequence"
            ) from exc

        quiz_payload: Any = None
        if quiz_set is not None:
            self._upsert_quiz_document(
                node_id=node_id,
                payload=model_payload(quiz_set),
                format_version=1,
                shuffle_seed=quiz_set.shuffle_seed,
                current_index=quiz_set.current_index,
                now=now,
            )
            quiz_payload = quiz_set.model_dump()
        elif quiz is not None:
            quiz_payload = quiz.model_dump()
            self._upsert_quiz_document(
                node_id=node_id,
                payload=model_payload(quiz),
                format_version=0,
                shuffle_seed=None,
                current_index=0,
                now=now,
            )

        row = document_to_row(document) or {}
        row["quiz"] = quiz_payload
        return row

    def get_session_nodes(self, session_id: str) -> list[dict[str, Any]]:
        cursor = self._nodes.find(
            {"learning_session_id": session_id}
        ).sort("sequence_index", ASCENDING)
        nodes: list[dict[str, Any]] = []
        for item in cursor:
            row = document_to_row(item) or {}
            generation_status = row.get("generation_status")
            if generation_status is None:
                generation_status = "READY"
            row["generation_status"] = generation_status
            row["retry_available"] = bool(row.get("retry_available"))
            quiz_doc = self._quizzes.find_one({"node_id": row["id"]})
            row["quiz"] = (
                quiz_doc.get("payload") if quiz_doc is not None else None
            )
            nodes.append(row)
        return nodes

    def get_concept_node(self, node_id: str) -> Optional[dict[str, Any]]:
        return self._get_node_by_id(node_id)

    def get_next_node(
        self,
        session_id: str,
        sequence_index: int,
    ) -> Optional[dict[str, Any]]:
        document = self._nodes.find_one(
            {
                "learning_session_id": session_id,
                "sequence_index": sequence_index + 1,
            }
        )
        if document is None:
            return None
        return self._node_row_with_quiz(document)

    def update_node_status(
        self,
        node_id: str,
        status: NodeStatus,
    ) -> Optional[dict[str, Any]]:
        current = self._nodes.find_one({"_id": node_id})
        if current is None:
            return None
        current_status = NodeStatus(current["status"])
        if not _is_valid_transition(current_status, status):
            raise ValueError(
                f"Invalid status transition: {current_status} -> {status}"
            )
        now = utc_iso()
        set_fields: dict[str, Any] = {
            "status": status.value,
            "updated_at": now,
        }
        if (
            status == NodeStatus.VIEWING_EXPLANATION
            and current.get("started_at") is None
        ):
            set_fields["started_at"] = now
        if status == NodeStatus.COMPLETED:
            set_fields["completed_at"] = now
        updated = self._nodes.find_one_and_update(
            {"_id": node_id, "status": current_status.value},
            {"$set": set_fields},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise ValueError("retry")
        self._update_session_progress(updated["learning_session_id"])
        if status == NodeStatus.VIEWING_EXPLANATION:
            self._sessions.update_one(
                {"_id": updated["learning_session_id"]},
                {
                    "$set": {
                        "last_active_node_id": node_id,
                        "updated_at": now,
                    }
                },
            )
        return document_to_row(updated)

    def update_node_content(
        self,
        node_id: str,
        content_markdown: str,
        status: NodeStatus,
        quiz: Optional[QuizCard] = None,
        quiz_set: Optional[QuizSet] = None,
        error_message: Optional[str] = None,
        retry_available: bool = False,
        failed_step: Optional[FailedStep] = None,
    ) -> Optional[dict[str, Any]]:
        current = self._nodes.find_one({"_id": node_id})
        if current is None:
            return None
        current_status = NodeStatus(current["status"])
        if not _is_valid_transition(current_status, status):
            raise ValueError(
                "Invalid status transition from "
                f"{current_status.value} to {status.value}"
            )
        now = utc_iso()
        updated = self._nodes.find_one_and_update(
            {"_id": node_id, "status": current_status.value},
            {
                "$set": {
                    "content_markdown": content_markdown,
                    "status": status.value,
                    "error_message": error_message,
                    "retry_available": retry_available,
                    "failed_step": (
                        failed_step.value
                        if failed_step is not None
                        else None
                    ),
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            if self._nodes.find_one({"_id": node_id}) is None:
                return None
            raise ValueError("Node status changed during update; retry")

        if quiz_set is not None:
            self._upsert_quiz_document(
                node_id=node_id,
                payload=model_payload(quiz_set),
                format_version=1,
                shuffle_seed=quiz_set.shuffle_seed,
                current_index=quiz_set.current_index,
                now=now,
            )
        elif quiz is not None:
            self._upsert_quiz_document(
                node_id=node_id,
                payload=model_payload(quiz),
                format_version=0,
                shuffle_seed=None,
                current_index=0,
                now=now,
            )
        else:
            self._quizzes.delete_many({"node_id": node_id})

        return self._get_node_by_id(node_id)

    def replace_node_content(
        self,
        node_id: str,
        content_markdown: str,
        status: NodeStatus,
        quiz_set: Optional[QuizSet] = None,
    ) -> Optional[dict[str, Any]]:
        current = self._nodes.find_one({"_id": node_id})
        if current is None:
            return None
        now = utc_iso()
        self._nodes.update_one(
            {"_id": node_id},
            {
                "$set": {
                    "content_markdown": content_markdown,
                    "status": status.value,
                    "error_message": None,
                    "retry_available": False,
                    "failed_step": None,
                    "updated_at": now,
                },
                "$unset": {
                    "error_message": "",
                    "failed_step": "",
                },
            },
        )
        # Re-apply null clears after unset so API shape stays consistent.
        self._nodes.update_one(
            {"_id": node_id},
            {
                "$set": {
                    "error_message": None,
                    "retry_available": False,
                    "failed_step": None,
                }
            },
        )
        if quiz_set is not None:
            self._upsert_quiz_document(
                node_id=node_id,
                payload=model_payload(quiz_set),
                format_version=1,
                shuffle_seed=quiz_set.shuffle_seed,
                current_index=quiz_set.current_index,
                now=now,
            )
        else:
            self._quizzes.delete_many({"node_id": node_id})
        return self._get_node_by_id(node_id)

    def _update_session_progress(
        self,
        session_id: str,
        last_active_node_id: Optional[str] = None,
    ) -> int:
        total_nodes = self._nodes.count_documents(
            {"learning_session_id": session_id}
        )
        completed_nodes = self._nodes.count_documents(
            {
                "learning_session_id": session_id,
                "status": NodeStatus.COMPLETED.value,
            }
        )
        progress_percent = _calculate_progress_percent(
            completed_nodes,
            total_nodes,
        )
        session_status = (
            "completed" if progress_percent == 100 else "in_progress"
        )
        now = utc_iso()
        set_fields: dict[str, Any] = {
            "status": session_status,
            "progress_percent": progress_percent,
            "updated_at": now,
        }
        if last_active_node_id is not None:
            set_fields["last_active_node_id"] = last_active_node_id
        if session_status == "completed":
            existing = self._sessions.find_one(
                {"_id": session_id},
                {"completed_at": 1},
            )
            if existing is not None and existing.get("completed_at") is None:
                set_fields["completed_at"] = now
        self._sessions.update_one(
            {"_id": session_id},
            {"$set": set_fields},
        )
        return progress_percent

    def _upsert_quiz_document(
        self,
        *,
        node_id: str,
        payload: dict[str, Any],
        format_version: int,
        shuffle_seed: Optional[str],
        current_index: int,
        now: str,
    ) -> dict[str, Any]:
        existing = self._quizzes.find_one({"node_id": node_id})
        if existing is not None:
            document = {
                "_id": existing["_id"],
                "node_id": node_id,
                "payload": payload,
                "format_version": format_version,
                "shuffle_seed": shuffle_seed,
                "current_index": current_index,
                "created_at": existing.get("created_at", now),
                "updated_at": now,
            }
        else:
            document = {
                "_id": str(uuid.uuid4()),
                "node_id": node_id,
                "payload": payload,
                "format_version": format_version,
                "shuffle_seed": shuffle_seed,
                "current_index": current_index,
                "created_at": now,
                "updated_at": now,
            }
        self._quizzes.replace_one(
            {"node_id": node_id},
            document,
            upsert=True,
        )
        return document

    def _get_node_by_id(self, node_id: str) -> Optional[dict[str, Any]]:
        document = self._nodes.find_one({"_id": node_id})
        if document is None:
            return None
        return self._node_row_with_quiz(document)

    def _node_row_with_quiz(
        self,
        document: dict[str, Any],
    ) -> dict[str, Any]:
        row = document_to_row(document) or {}
        row["retry_available"] = bool(row.get("retry_available"))
        quiz_doc = self._quizzes.find_one({"node_id": row["id"]})
        row["quiz"] = (
            quiz_doc.get("payload") if quiz_doc is not None else None
        )
        return row
