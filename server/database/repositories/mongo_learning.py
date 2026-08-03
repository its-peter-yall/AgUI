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

from pydantic import ValidationError
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
    convert_legacy_quiz_card,
    convert_legacy_to_quiz_set,
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

    def create_quiz_set(
        self,
        node_id: str,
        quiz_set: QuizSet,
        shuffle_seed: Optional[str] = None,
    ) -> dict[str, Any]:
        now = utc_iso()
        document = {
            "_id": str(uuid.uuid4()),
            "node_id": node_id,
            "payload": model_payload(quiz_set),
            "format_version": 1,
            "shuffle_seed": shuffle_seed,
            "current_index": quiz_set.current_index,
            "created_at": now,
            "updated_at": now,
        }
        self._quizzes.replace_one(
            {"node_id": node_id},
            document,
            upsert=True,
        )
        return document_to_row(document) or {}

    def get_quiz_set_for_node(
        self,
        node_id: str,
    ) -> Optional[dict[str, Any]]:
        row = self._quizzes.find_one({"node_id": node_id})
        if row is None:
            return None
        payload = row.get("payload")
        format_version = row.get("format_version")
        if format_version is None or format_version < 1:
            quiz_set = convert_legacy_to_quiz_set(payload)
            shuffle_seed = row.get("shuffle_seed")
            current_index = row.get("current_index") or 0
        else:
            try:
                quiz_set = QuizSet.model_validate(payload)
                shuffle_seed = row.get("shuffle_seed")
                current_index = row.get("current_index")
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
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def get_quiz_for_node(self, node_id: str) -> Optional[QuizCard]:
        row = self._quizzes.find_one({"node_id": node_id})
        if row is None:
            return None
        payload = row.get("payload")
        format_version = row.get("format_version")
        current_index = row.get("current_index")
        if format_version is None or format_version < 1:
            return convert_legacy_quiz_card(payload)
        try:
            quiz_set = QuizSet.model_validate(payload)
        except ValidationError:
            logger.warning(
                "Detected stale format_version for legacy quiz row: "
                "node_id=%s. Falling back to legacy parsing.",
                node_id,
            )
            return convert_legacy_quiz_card(payload)
        if quiz_set.quizzes:
            idx = (
                current_index
                if current_index is not None
                else quiz_set.current_index
            )
            return quiz_set.quizzes[idx]
        return None

    def update_quiz_shuffle_seed(
        self,
        node_id: str,
        shuffle_seed: str,
    ) -> bool:
        result = self._quizzes.update_one(
            {"node_id": node_id},
            {
                "$set": {
                    "shuffle_seed": shuffle_seed,
                    "updated_at": utc_iso(),
                }
            },
        )
        return result.matched_count > 0

    def decrement_quiz_set_progress(
        self,
        node_id: str,
    ) -> Optional[dict[str, Any]]:
        row = self._quizzes.find_one({"node_id": node_id})
        if row is None:
            return None
        format_version = row.get("format_version")
        if format_version is None or format_version < 1:
            return None
        current_index = row.get("current_index") or 0
        if current_index <= 0:
            return self._get_node_by_id(node_id)
        new_index = current_index - 1
        self._quizzes.update_one(
            {"node_id": node_id},
            {
                "$set": {
                    "current_index": new_index,
                    "updated_at": utc_iso(),
                }
            },
        )
        return self._get_node_by_id(node_id)

    def update_quiz_set_progress(
        self,
        node_id: str,
        current_index: int,
    ) -> Optional[dict[str, Any]]:
        row = self._quizzes.find_one({"node_id": node_id})
        if row is None:
            return None
        payload = row.get("payload")
        format_version = row.get("format_version")
        if format_version is None or format_version < 1:
            total_quizzes = 1
        else:
            quiz_set_data = QuizSet.model_validate(payload)
            total_quizzes = len(quiz_set_data.quizzes)
        if current_index < 0 or current_index >= total_quizzes:
            raise ValueError(
                f"Invalid current_index {current_index} for quiz set "
                f"with {total_quizzes} quizzes"
            )
        self._quizzes.update_one(
            {"node_id": node_id},
            {
                "$set": {
                    "current_index": current_index,
                    "updated_at": utc_iso(),
                }
            },
        )
        return self.get_quiz_set_for_node(node_id)

    def create_quiz_attempt(
        self,
        node_id: str,
        selected_option_ids: list[str],
        quiz_index: int = 0,
        revision_session_id: Optional[str] = None,
    ) -> dict[str, Any]:
        node = self._get_node_by_id(node_id)
        if node is None:
            raise ValueError(f"Concept node not found: {node_id}")
        session_id = node["learning_session_id"]
        quiz_set_data = self.get_quiz_set_for_node(node_id)
        if quiz_set_data is None:
            raise ValueError(f"No quiz found for node: {node_id}")
        quiz_set = quiz_set_data["quiz_set"]
        if quiz_index < 0 or quiz_index >= len(quiz_set.quizzes):
            raise ValueError(
                f"Invalid quiz_index {quiz_index} for quiz set with "
                f"{len(quiz_set.quizzes)} quizzes"
            )
        quiz = quiz_set.quizzes[quiz_index]
        question_type = getattr(quiz, "question_type", "single_choice")
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
            is_correct = (
                len(selected_options) == 1
                and selected_options[0].is_correct
            )
        else:
            is_correct = correct_option_ids_set == selected_option_id_set
        score_percent = 100 if is_correct else 0
        attempt_number = (
            self._attempts.count_documents({"node_id": node_id}) + 1
        )
        attempt_id = str(uuid.uuid4())
        now = utc_iso()
        document = {
            "_id": attempt_id,
            "node_id": node_id,
            "attempt_number": attempt_number,
            "quiz_index": quiz_index,
            "selected_option_id": selected_option_ids,
            "revision_session_id": revision_session_id,
            "is_correct": is_correct,
            "score_percent": score_percent,
            "created_at": now,
        }
        self._attempts.insert_one(document)
        if revision_session_id is None:
            self._sessions.update_one(
                {"_id": session_id},
                {
                    "$set": {
                        "last_active_node_id": node_id,
                        "updated_at": now,
                    }
                },
            )
        total_quizzes = len(quiz_set.quizzes)
        if total_quizzes == 1:
            is_mastered = is_correct
        else:
            is_mastered = self._check_multi_quiz_mastery(
                node_id,
                total_quizzes,
            )
        return {
            "id": attempt_id,
            "node_id": node_id,
            "attempt_number": attempt_number,
            "quiz_index": quiz_index,
            "selected_option_ids": selected_option_ids,
            "is_correct": is_correct,
            "score_percent": score_percent,
            "correct_option_ids": (
                list(correct_option_ids_set) if is_correct else []
            ),
            "explanation": (
                correct_options[0].explanation
                if correct_options and is_correct
                else ""
            ),
            "selected_explanation": (
                selected_options[0].explanation
                if not is_correct and selected_options
                else None
            ),
            "is_mastered": is_mastered,
            "created_at": now,
            "updated_at": now,
        }

    def get_quiz_attempts(self, node_id: str) -> dict[str, Any]:
        cursor = self._attempts.find({"node_id": node_id}).sort(
            "attempt_number",
            ASCENDING,
        )
        quiz_set_data = self.get_quiz_set_for_node(node_id)
        quiz_set = (
            quiz_set_data["quiz_set"] if quiz_set_data is not None else None
        )
        attempts: list[dict[str, Any]] = []
        best_score = 0
        for row in cursor:
            score = int(row.get("score_percent") or 0)
            if score > best_score:
                best_score = score
            quiz_index = int(row.get("quiz_index") or 0)
            selected_raw = row.get("selected_option_id")
            if isinstance(selected_raw, list):
                selected_option_ids = selected_raw
            elif isinstance(selected_raw, str):
                selected_option_ids = [selected_raw]
            else:
                selected_option_ids = []
            correct_option_ids: list[str] = []
            explanation = ""
            if quiz_set is not None and quiz_index < len(quiz_set.quizzes):
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
                    "id": row.get("_id"),
                    "node_id": row.get("node_id"),
                    "attempt_number": row.get("attempt_number"),
                    "quiz_index": quiz_index,
                    "selected_option_ids": selected_option_ids,
                    "is_correct": bool(row.get("is_correct")),
                    "score_percent": score,
                    "created_at": row.get("created_at"),
                    "correct_option_ids": correct_option_ids,
                    "explanation": explanation,
                    "is_mastered": score >= 100,
                }
            )
        is_mastered = self._calculate_mastery_from_attempts(
            node_id,
            attempts,
        )
        return {
            "node_id": node_id,
            "total_attempts": len(attempts),
            "is_mastered": is_mastered,
            "best_score": best_score,
            "attempts": attempts,
        }

    def check_mastery(self, node_id: str) -> bool:
        quiz_set_data = self.get_quiz_set_for_node(node_id)
        if quiz_set_data is None:
            return False
        quiz_set = quiz_set_data["quiz_set"]
        total_quizzes = len(quiz_set.quizzes)
        if total_quizzes == 1:
            return (
                self._attempts.find_one(
                    {"node_id": node_id, "is_correct": True}
                )
                is not None
            )
        return self._check_multi_quiz_mastery(node_id, total_quizzes)

    def create_revision_session(
        self,
        original_session_id: str,
        mode: str,
    ) -> dict[str, Any]:
        allowed_modes = {"full_review", "quiz_only"}
        if mode not in allowed_modes:
            raise ValueError(f"Invalid revision mode: {mode}")
        session = self._sessions.find_one({"_id": original_session_id})
        if session is None:
            raise LookupError(
                f"Learning session not found: {original_session_id}"
            )
        nodes = list(
            self._nodes.find({"learning_session_id": original_session_id})
        )
        nodes.sort(key=lambda item: int(item.get("sequence_index") or 0))
        is_completed = session.get("status") == "completed"
        if not is_completed:
            total_nodes = len(nodes)
            completed_nodes = sum(
                1
                for node in nodes
                if node.get("status") == NodeStatus.COMPLETED.value
            )
            is_completed = total_nodes > 0 and completed_nodes == total_nodes
        if not is_completed:
            raise ValueError(
                "Revision sessions can only be created for completed sessions"
            )
        revision_number = (
            self._revisions.count_documents(
                {"original_session_id": original_session_id}
            )
            + 1
        )
        revision_id = str(uuid.uuid4())
        now = utc_iso()
        revision_doc = {
            "_id": revision_id,
            "original_session_id": original_session_id,
            "revision_number": revision_number,
            "mode": mode,
            "status": "in_progress",
            "progress_percent": 0,
            "total_quiz_score_percent": None,
            "started_at": now,
            "completed_at": None,
        }
        self._revisions.insert_one(revision_doc)
        progress_rows: list[dict[str, Any]] = []
        progress_docs: list[dict[str, Any]] = []
        for node in nodes:
            progress_id = str(uuid.uuid4())
            progress_docs.append(
                {
                    "_id": progress_id,
                    "revision_session_id": revision_id,
                    "node_id": node["_id"],
                    "status": "pending",
                    "reviewed_at": None,
                }
            )
            progress_rows.append(
                {
                    "id": progress_id,
                    "revision_session_id": revision_id,
                    "node_id": node["_id"],
                    "node_title": node.get("title"),
                    "sequence_index": int(node.get("sequence_index") or 0),
                    "status": "pending",
                    "reviewed_at": None,
                }
            )
        if progress_docs:
            self._revision_nodes.insert_many(progress_docs)
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

    def get_revisions_for_session(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        query = {"original_session_id": session_id}
        total = self._revisions.count_documents(query)
        cursor = (
            self._revisions.find(query)
            .sort("started_at", DESCENDING)
            .skip(max(offset, 0))
            .limit(max(limit, 0))
        )
        revisions = []
        for row in cursor:
            item = document_to_row(row) or {}
            item["revision_number"] = int(item.get("revision_number") or 0)
            item["progress_percent"] = int(item.get("progress_percent") or 0)
            revisions.append(item)
        return revisions, total

    def get_revision_session(
        self,
        revision_id: str,
    ) -> Optional[dict[str, Any]]:
        revision = self._revisions.find_one({"_id": revision_id})
        if revision is None:
            return None
        progress_docs = list(
            self._revision_nodes.find(
                {"revision_session_id": revision_id}
            )
        )
        node_ids = [doc["node_id"] for doc in progress_docs]
        nodes_by_id: dict[str, dict[str, Any]] = {}
        if node_ids:
            for node in self._nodes.find({"_id": {"$in": node_ids}}):
                nodes_by_id[node["_id"]] = node
        progress_rows = []
        for doc in progress_docs:
            node = nodes_by_id.get(doc["node_id"], {})
            progress_rows.append(
                {
                    "id": doc["_id"],
                    "revision_session_id": doc["revision_session_id"],
                    "node_id": doc["node_id"],
                    "node_title": node.get("title"),
                    "sequence_index": int(node.get("sequence_index") or 0),
                    "status": doc.get("status"),
                    "reviewed_at": doc.get("reviewed_at"),
                }
            )
        progress_rows.sort(key=lambda item: item["sequence_index"])
        result = document_to_row(revision) or {}
        result["revision_number"] = int(result.get("revision_number") or 0)
        result["progress_percent"] = int(result.get("progress_percent") or 0)
        result["nodes"] = progress_rows
        return result

    def delete_revision_session(self, revision_id: str) -> bool:
        self._attempts.delete_many({"revision_session_id": revision_id})
        self._revision_nodes.delete_many(
            {"revision_session_id": revision_id}
        )
        result = self._revisions.delete_one({"_id": revision_id})
        return result.deleted_count > 0

    def mark_revision_node_reviewed(
        self,
        revision_id: str,
        node_id: str,
    ) -> dict[str, Any]:
        revision = self._revisions.find_one({"_id": revision_id})
        if revision is None:
            raise LookupError(f"Revision session not found: {revision_id}")
        if revision.get("mode") != "full_review":
            raise ValueError(
                "mark-reviewed is only allowed for full_review revisions"
            )
        now = utc_iso()
        updated = self._revision_nodes.find_one_and_update(
            {"revision_session_id": revision_id, "node_id": node_id},
            {"$set": {"status": "reviewed", "reviewed_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise LookupError(
                f"Revision node not found for revision {revision_id}: "
                f"{node_id}"
            )
        self._update_revision_progress(revision_id)
        return {
            "id": updated["_id"],
            "revision_session_id": updated["revision_session_id"],
            "node_id": updated["node_id"],
            "status": updated["status"],
            "reviewed_at": updated["reviewed_at"],
        }

    def submit_revision_quiz(
        self,
        revision_id: str,
        node_id: str,
        selected_option_ids: list[str],
        quiz_index: int = 0,
    ) -> dict[str, Any]:
        revision = self._revisions.find_one({"_id": revision_id})
        if revision is None:
            raise LookupError(f"Revision session not found: {revision_id}")
        progress = self._revision_nodes.find_one(
            {"revision_session_id": revision_id, "node_id": node_id}
        )
        if progress is None:
            raise LookupError(
                f"Revision node not found for revision {revision_id}: "
                f"{node_id}"
            )
        quiz_result = self.create_quiz_attempt(
            node_id=node_id,
            selected_option_ids=selected_option_ids,
            quiz_index=quiz_index,
            revision_session_id=revision_id,
        )
        next_status = (
            "quiz_passed" if quiz_result["is_correct"] else "quiz_failed"
        )
        if progress.get("status") == "quiz_passed":
            next_status = "quiz_passed"
        now = utc_iso()
        set_fields: dict[str, Any] = {"status": next_status}
        if next_status == "quiz_passed" and progress.get("reviewed_at") is None:
            set_fields["reviewed_at"] = now
        self._revision_nodes.update_one(
            {"revision_session_id": revision_id, "node_id": node_id},
            {"$set": set_fields},
        )
        self._update_revision_progress(revision_id)
        return {
            "is_correct": bool(quiz_result["is_correct"]),
            "correct_option_ids": quiz_result.get("correct_option_ids", []),
            "explanation": quiz_result.get("explanation"),
            "selected_explanation": quiz_result.get("selected_explanation"),
            "revision_node_status": next_status,
        }

    def get_revision_summary(self, revision_id: str) -> dict[str, Any]:
        revision = self._revisions.find_one({"_id": revision_id})
        if revision is None:
            raise LookupError(f"Revision session not found: {revision_id}")
        progress_docs = list(
            self._revision_nodes.find({"revision_session_id": revision_id})
        )
        nodes_total = len(progress_docs)
        nodes_reviewed = sum(
            1 for doc in progress_docs if doc.get("status") != "pending"
        )
        attempt_docs = list(
            self._attempts.find({"revision_session_id": revision_id})
        )
        quizzes_total = len(attempt_docs)
        quizzes_passed = sum(
            1 for doc in attempt_docs if doc.get("is_correct")
        )
        quizzes_failed = max(quizzes_total - quizzes_passed, 0)
        revision_quiz_score_percent = (
            (quizzes_passed * 100) // quizzes_total
            if quizzes_total > 0
            else None
        )
        total_quiz_score_percent = (
            revision_quiz_score_percent
            if revision_quiz_score_percent is not None
            else revision.get("total_quiz_score_percent")
        )
        node_ids = [doc["node_id"] for doc in progress_docs]
        comparison = None
        if quizzes_total > 0 and node_ids:
            original_attempts = list(
                self._attempts.find(
                    {
                        "revision_session_id": None,
                        "node_id": {"$in": node_ids},
                    }
                )
            )
            original_total = len(original_attempts)
            if (
                original_total > 0
                and revision_quiz_score_percent is not None
            ):
                original_passed = sum(
                    1
                    for doc in original_attempts
                    if doc.get("is_correct")
                )
                original_score = (original_passed * 100) // original_total
                comparison = {
                    "original_quiz_score_percent": original_score,
                    "improvement_percent": (
                        revision_quiz_score_percent - original_score
                    ),
                }
        started_at = revision.get("started_at")
        completed_at = revision.get("completed_at")
        time_spent_seconds = None
        if started_at and completed_at:
            try:
                from datetime import datetime

                started_dt = datetime.fromisoformat(str(started_at))
                completed_dt = datetime.fromisoformat(str(completed_at))
                delta = int((completed_dt - started_dt).total_seconds())
                time_spent_seconds = max(delta, 0)
            except ValueError:
                time_spent_seconds = None
        return {
            "revision_id": revision["_id"],
            "mode": revision.get("mode"),
            "progress_percent": int(revision.get("progress_percent") or 0),
            "total_quiz_score_percent": total_quiz_score_percent,
            "nodes_reviewed": nodes_reviewed,
            "nodes_total": nodes_total,
            "quizzes_passed": quizzes_passed,
            "quizzes_failed": quizzes_failed,
            "quizzes_total": quizzes_total,
            "time_spent_seconds": time_spent_seconds,
            "comparison": comparison,
        }

    def _update_revision_progress(
        self,
        revision_id: str,
    ) -> dict[str, Any]:
        if self._revisions.find_one({"_id": revision_id}) is None:
            raise LookupError(f"Revision session not found: {revision_id}")
        progress_docs = list(
            self._revision_nodes.find({"revision_session_id": revision_id})
        )
        total_nodes = len(progress_docs)
        completed_nodes = sum(
            1 for doc in progress_docs if doc.get("status") != "pending"
        )
        quizzes_passed = sum(
            1 for doc in progress_docs if doc.get("status") == "quiz_passed"
        )
        quizzes_failed = sum(
            1 for doc in progress_docs if doc.get("status") == "quiz_failed"
        )
        progress_percent = _calculate_progress_percent(
            completed_nodes,
            total_nodes,
        )
        quiz_attempted = quizzes_passed + quizzes_failed
        total_quiz_score_percent = (
            (quizzes_passed * 100) // quiz_attempted
            if quiz_attempted > 0
            else None
        )
        next_status = (
            "completed"
            if total_nodes > 0 and completed_nodes >= total_nodes
            else "in_progress"
        )
        now = utc_iso()
        set_fields: dict[str, Any] = {
            "progress_percent": progress_percent,
            "status": next_status,
            "total_quiz_score_percent": total_quiz_score_percent,
        }
        if next_status == "completed":
            existing = self._revisions.find_one(
                {"_id": revision_id},
                {"completed_at": 1},
            )
            if existing is not None and existing.get("completed_at") is None:
                set_fields["completed_at"] = now
        self._revisions.update_one(
            {"_id": revision_id},
            {"$set": set_fields},
        )
        return {
            "revision_id": revision_id,
            "status": next_status,
            "progress_percent": progress_percent,
            "total_quiz_score_percent": total_quiz_score_percent,
        }

    def _check_multi_quiz_mastery(
        self,
        node_id: str,
        total_quizzes: int,
    ) -> bool:
        correct_indices = {
            int(doc.get("quiz_index") or 0)
            for doc in self._attempts.find(
                {"node_id": node_id, "is_correct": True}
            )
        }
        return correct_indices.issuperset(set(range(total_quizzes)))

    def _calculate_mastery_from_attempts(
        self,
        node_id: str,
        attempts: list[dict[str, Any]],
    ) -> bool:
        if not attempts:
            return False
        quiz_set_data = self.get_quiz_set_for_node(node_id)
        if quiz_set_data is None:
            return False
        total_quizzes = len(quiz_set_data["quiz_set"].quizzes)
        if total_quizzes == 1:
            return any(item["is_correct"] for item in attempts)
        correct_indices = {
            item["quiz_index"] for item in attempts if item["is_correct"]
        }
        return correct_indices.issuperset(set(range(total_quizzes)))
