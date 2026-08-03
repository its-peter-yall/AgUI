"""
============================================================================
FILE: mongo_artifacts.py
LOCATION: server/database/repositories/mongo_artifacts.py
============================================================================
PURPOSE:
    Synchronous Mongo implementation of GenerationArtifactRepository for
    outline, briefs, content, and citation persistence.
ROLE IN PROJECT:
    Phase 3B Atlas adapter for generation artifacts. Mirrors
    GenerationArtifactStore public methods with native BSON payloads.
DEPENDENCIES:
    - External: pymongo
    - Internal: server.database.generation_artifacts (exceptions/helpers),
                server.database.repositories.mongo_common,
                server.schemas.generation, server.schemas.learning
USAGE:
    repo = MongoGenerationArtifactRepository(database)
    nodes = repo.persist_outline(session_id, outline)
============================================================================
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from pymongo import ASCENDING, ReturnDocument, UpdateOne
from pymongo.errors import DuplicateKeyError

from server.database.generation_artifacts import (
    ERROR_STATUS,
    GENERATING_STATUS,
    READY_STATUS,
    SKELETON_STATUS,
    GenerationArtifactConflict,
    UnsupportedCitationError,
    _node_id_for_topic,
)
from server.database.repositories.mongo_common import (
    document_to_row,
    model_payload,
    utc_iso,
)
from server.schemas.generation import (
    GenerationBrief,
    GenerationBriefBatch,
    SourceCitation,
)
from server.schemas.learning import (
    CourseOutline,
    FailedStep,
    NodeStatus,
    QuizSet,
    TopicNode,
)

logger = logging.getLogger(__name__)


def _node_document_to_dict(document: dict[str, Any]) -> dict[str, Any]:
    row = document_to_row(document) or {}
    key_terms = row.get("key_terms")
    if key_terms is None:
        key_terms = None
    return {
        "id": row["id"],
        "learning_session_id": row["learning_session_id"],
        "sequence_index": int(row["sequence_index"]),
        "title": row["title"],
        "content_markdown": row.get("content_markdown") or "",
        "status": row["status"],
        "error_message": row.get("error_message"),
        "retry_available": bool(row.get("retry_available")),
        "failed_step": row.get("failed_step"),
        "complexity": row.get("complexity"),
        "summary_for_context": row.get("summary_for_context"),
        "key_terms": key_terms,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "generation_status": row.get("generation_status"),
    }


def _node_source_id(node_id: str, source_id: str) -> str:
    return f"{node_id}::{source_id}"


class MongoGenerationArtifactRepository:
    """Mongo implementation of outline/brief/content/citation persistence."""

    def __init__(self, database: Any) -> None:
        self._db = database
        self._sessions = database["learning_sessions"]
        self._nodes = database["concept_nodes"]
        self._briefs = database["generation_briefs"]
        self._node_sources = database["node_sources"]
        self._research_sources = database["research_sources"]
        self._quizzes = database["quiz_data"]

    def node_id_for_topic(self, session_id: str, topic_index: int) -> str:
        return _node_id_for_topic(session_id, topic_index)

    def _node_id_for_topic(self, session_id: str, topic_index: int) -> str:
        return _node_id_for_topic(session_id, topic_index)

    def persist_outline(
        self,
        session_id: str,
        outline: CourseOutline,
    ) -> list[dict[str, Any]]:
        now = utc_iso()
        self._sessions.update_one(
            {"_id": session_id},
            {
                "$set": {
                    "course_title": outline.course_title,
                    "title_finalized": True,
                    "updated_at": now,
                }
            },
        )
        operations: list[UpdateOne] = []
        for topic in outline.topics:
            node_id = _node_id_for_topic(session_id, topic.index)
            existing = self._nodes.find_one({"_id": node_id})
            if existing is not None and existing.get("title") != topic.title:
                raise GenerationArtifactConflict(
                    f"Topic {topic.index} title differs from stored outline"
                )
            operations.append(
                UpdateOne(
                    {"_id": node_id},
                    {
                        "$set": {
                            "learning_session_id": session_id,
                            "sequence_index": topic.index,
                            "title": topic.title,
                            "summary_for_context": topic.summary_for_context,
                            "key_terms": topic.key_terms,
                            "complexity": topic.complexity,
                            "updated_at": now,
                        },
                        "$setOnInsert": {
                            "content_markdown": "",
                            "status": NodeStatus.LOCKED.value,
                            "error_message": None,
                            "retry_available": False,
                            "failed_step": None,
                            "generation_status": SKELETON_STATUS,
                            "created_at": now,
                        },
                    },
                    upsert=True,
                )
            )
        if operations:
            self._nodes.bulk_write(operations, ordered=False)
        cursor = self._nodes.find(
            {"learning_session_id": session_id}
        ).sort("sequence_index", ASCENDING)
        return [_node_document_to_dict(item) for item in cursor]

    def upsert_brief_batch(
        self,
        session_id: str,
        batch: GenerationBriefBatch,
    ) -> list[GenerationBrief]:
        now = utc_iso()
        operations: list[UpdateOne] = []
        for brief in batch.briefs:
            node_id = _node_id_for_topic(session_id, brief.topic_index)
            node_row = self._nodes.find_one(
                {
                    "_id": node_id,
                    "learning_session_id": session_id,
                }
            )
            if (
                node_row is None
                or int(node_row["sequence_index"]) != brief.topic_index
            ):
                raise GenerationArtifactConflict(
                    f"Node for session {session_id} topic"
                    f" {brief.topic_index} is missing or misaligned"
                )
            operations.append(
                UpdateOne(
                    {
                        "session_id": session_id,
                        "topic_index": brief.topic_index,
                    },
                    {
                        "$set": {
                            "node_id": node_id,
                            "payload": model_payload(brief),
                            "updated_at": now,
                        },
                        "$setOnInsert": {
                            "_id": str(uuid.uuid4()),
                            "session_id": session_id,
                            "topic_index": brief.topic_index,
                            "created_at": now,
                        },
                    },
                    upsert=True,
                )
            )
        if operations:
            try:
                self._briefs.bulk_write(operations, ordered=False)
            except DuplicateKeyError as exc:
                raise GenerationArtifactConflict(
                    "Brief unique constraint conflict"
                ) from exc
        cursor = self._briefs.find(
            {"session_id": session_id}
        ).sort("topic_index", ASCENDING)
        return [
            GenerationBrief.model_validate(item["payload"])
            for item in cursor
        ]

    def persist_briefs(
        self,
        session_id: str,
        batch: GenerationBriefBatch,
    ) -> list[GenerationBrief]:
        return self.upsert_brief_batch(session_id, batch)

    def get_brief(self, node_id: str) -> Optional[GenerationBrief]:
        document = self._briefs.find_one({"node_id": node_id})
        if document is None:
            return None
        return GenerationBrief.model_validate(document["payload"])

    def get_briefs(
        self,
        session_id: str,
        start_index: int,
        limit: int,
    ) -> list[GenerationBrief]:
        cursor = (
            self._briefs.find(
                {
                    "session_id": session_id,
                    "topic_index": {"$gte": start_index},
                }
            )
            .sort("topic_index", ASCENDING)
            .limit(limit)
        )
        return [
            GenerationBrief.model_validate(item["payload"])
            for item in cursor
        ]

    def get_topic(self, session_id: str, topic_index: int) -> TopicNode:
        row = self._nodes.find_one(
            {
                "learning_session_id": session_id,
                "sequence_index": topic_index,
            }
        )
        if row is None:
            raise LookupError(
                f"Topic {topic_index} not found for session {session_id}"
            )
        brief_row = self._briefs.find_one({"node_id": row["_id"]})
        if brief_row is None:
            quiz_count = 1
        else:
            brief = GenerationBrief.model_validate(brief_row["payload"])
            quiz_count = len(brief.quiz_learning_targets)
        key_terms = row.get("key_terms") or []
        return TopicNode(
            index=topic_index,
            title=row["title"],
            summary_for_context=row["summary_for_context"],
            key_terms=key_terms,
            complexity=row.get("complexity") or "Intermediate",
            quiz_count=quiz_count,
        )

    def count_topics(self, session_id: str) -> int:
        return int(
            self._nodes.count_documents(
                {"learning_session_id": session_id}
            )
        )

    def get_outline(self, session_id: str) -> CourseOutline:
        session_row = self._sessions.find_one({"_id": session_id})
        if session_row is None:
            raise LookupError(f"Session not found: {session_id}")
        rows = list(
            self._nodes.find(
                {"learning_session_id": session_id}
            ).sort("sequence_index", ASCENDING)
        )
        topics = [
            TopicNode(
                index=int(row["sequence_index"]),
                title=row["title"],
                summary_for_context=(
                    row.get("summary_for_context") or row["title"]
                ),
                key_terms=(
                    row.get("key_terms") or ["topic", "concept"]
                ),
                complexity=row.get("complexity") or "Intermediate",
                quiz_count=1,
            )
            for row in rows
        ]
        return CourseOutline(
            course_title=session_row.get("course_title") or "Course",
            topics=topics,
        )

    def get_adjacent_summaries(
        self,
        session_id: str,
        topic_index: int,
    ) -> tuple[Optional[str], Optional[str]]:
        prev_summary: Optional[str] = None
        next_summary: Optional[str] = None
        if topic_index > 0:
            prev_row = self._nodes.find_one(
                {
                    "learning_session_id": session_id,
                    "sequence_index": topic_index - 1,
                }
            )
            if prev_row is not None:
                prev_summary = prev_row.get("summary_for_context")
        next_row = self._nodes.find_one(
            {
                "learning_session_id": session_id,
                "sequence_index": topic_index + 1,
            }
        )
        if next_row is not None:
            next_summary = next_row.get("summary_for_context")
        return prev_summary, next_summary

    def persist_generated_content(
        self,
        node_id: str,
        content_markdown: str,
    ) -> dict[str, Any]:
        now = utc_iso()
        updated = self._nodes.find_one_and_update(
            {"_id": node_id},
            {
                "$set": {
                    "content_markdown": content_markdown,
                    "generation_status": GENERATING_STATUS,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise LookupError(f"Node not found: {node_id}")
        return _node_document_to_dict(updated)

    def has_durable_content(self, node_id: str) -> bool:
        row = self._nodes.find_one({"_id": node_id})
        if row is None:
            return False
        content = (row.get("content_markdown") or "").strip()
        status = (row.get("generation_status") or "").upper()
        if not content:
            return False
        return status in {
            GENERATING_STATUS,
            READY_STATUS,
            "READY",
            "GENERATING",
        }

    def persist_content_with_citations(
        self,
        *,
        node_id: str,
        content_markdown: str,
        citations: list[SourceCitation],
    ) -> dict[str, Any]:
        result = self.persist_generated_content(
            node_id=node_id,
            content_markdown=content_markdown,
        )
        self.replace_node_sources(node_id, citations)
        return result

    def persist_topic_success(
        self,
        node_id: str,
        quiz_set: QuizSet,
        citations: list[SourceCitation],
    ) -> dict[str, Any]:
        now = utc_iso()
        node_row = self._nodes.find_one({"_id": node_id})
        if node_row is None:
            raise LookupError(f"Node not found: {node_id}")
        payload = model_payload(quiz_set)
        quiz_document = {
            "node_id": node_id,
            "payload": payload,
            "format_version": 1,
            "shuffle_seed": quiz_set.shuffle_seed,
            "current_index": quiz_set.current_index,
            "updated_at": now,
        }
        learner_status = (
            NodeStatus.VIEWING_EXPLANATION
            if int(node_row["sequence_index"]) == 0
            else NodeStatus.LOCKED
        )
        try:
            with self._db.client.start_session() as session:
                with session.start_transaction():
                    existing_quiz = self._quizzes.find_one(
                        {"node_id": node_id},
                        session=session,
                    )
                    if existing_quiz is None:
                        self._quizzes.insert_one(
                            {
                                "_id": str(uuid.uuid4()),
                                "created_at": now,
                                **quiz_document,
                            },
                            session=session,
                        )
                    else:
                        self._quizzes.update_one(
                            {"node_id": node_id},
                            {"$set": quiz_document},
                            session=session,
                        )
                    self._nodes.update_one(
                        {"_id": node_id},
                        {
                            "$set": {
                                "generation_status": READY_STATUS,
                                "status": learner_status.value,
                                "error_message": None,
                                "retry_available": False,
                                "failed_step": None,
                                "updated_at": now,
                            }
                        },
                        session=session,
                    )
                    self._replace_node_sources_tx(
                        node_id,
                        citations,
                        session=session,
                    )
        except DuplicateKeyError as exc:
            raise GenerationArtifactConflict(
                "Quiz or citation unique constraint conflict"
            ) from exc
        row = self._nodes.find_one({"_id": node_id})
        if row is None:
            raise LookupError(f"Node not found: {node_id}")
        return _node_document_to_dict(row)

    def persist_topic_error(
        self,
        node_id: str,
        failed_step: Any,
        safe_error_message: str,
        content_markdown: str,
    ) -> dict[str, Any]:
        now = utc_iso()
        if isinstance(failed_step, FailedStep):
            step_value: Any = failed_step.value
        else:
            step_value = failed_step
        self._nodes.update_one(
            {"_id": node_id},
            {
                "$set": {
                    "generation_status": ERROR_STATUS,
                    "status": NodeStatus.ERROR.value,
                    "error_message": safe_error_message,
                    "retry_available": True,
                    "failed_step": step_value,
                    "content_markdown": content_markdown,
                    "updated_at": now,
                }
            },
        )
        row = self._nodes.find_one({"_id": node_id})
        if row is None:
            raise LookupError(f"Node not found: {node_id}")
        return _node_document_to_dict(row)

    def replace_node_sources(
        self,
        node_id: str,
        citations: list[SourceCitation],
    ) -> list[dict[str, Any]]:
        return self._replace_node_sources_tx(node_id, citations, session=None)

    def _replace_node_sources_tx(
        self,
        node_id: str,
        citations: list[SourceCitation],
        *,
        session: Any,
    ) -> list[dict[str, Any]]:
        find_kwargs: dict[str, Any] = {}
        if session is not None:
            find_kwargs["session"] = session
        node_row = self._nodes.find_one({"_id": node_id}, **find_kwargs)
        if node_row is None:
            raise LookupError(f"Node not found: {node_id}")
        session_id = node_row["learning_session_id"]
        self._validate_citations(session_id, node_id, citations, **find_kwargs)
        self._node_sources.delete_many({"node_id": node_id}, **find_kwargs)
        if citations:
            docs = [
                {
                    "_id": _node_source_id(node_id, citation.source_id),
                    "node_id": node_id,
                    "source_id": citation.source_id,
                    "citation_order": order,
                    "claim": citation.claim,
                }
                for order, citation in enumerate(citations)
            ]
            self._node_sources.insert_many(docs, **find_kwargs)
        rows = list(
            self._node_sources.find(
                {"node_id": node_id},
                **find_kwargs,
            ).sort("citation_order", ASCENDING)
        )
        return self._links_from_docs(rows)

    def list_node_sources(self, node_id: str) -> list[dict[str, Any]]:
        rows = list(
            self._node_sources.find({"node_id": node_id}).sort(
                "citation_order",
                ASCENDING,
            )
        )
        return self._links_from_docs(rows)

    def get_citations_by_session(
        self,
        session_id: str,
    ) -> dict[str, list[dict[str, Any]]]:
        node_ids = [
            item["_id"]
            for item in self._nodes.find(
                {"learning_session_id": session_id},
                {"_id": 1},
            )
        ]
        if not node_ids:
            return {}
        rows = list(
            self._node_sources.find(
                {"node_id": {"$in": node_ids}}
            ).sort("citation_order", ASCENDING)
        )
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
        session_id: str,
        node_id: str,
        citations: list[SourceCitation],
        **find_kwargs: Any,
    ) -> None:
        brief_row = self._briefs.find_one(
            {"node_id": node_id},
            **find_kwargs,
        )
        approved = (
            GenerationBrief.model_validate(
                brief_row["payload"]
            ).approved_source_ids
            if brief_row is not None
            else []
        )
        source_ids = {citation.source_id for citation in citations}
        if not source_ids:
            return
        existing_count = self._research_sources.count_documents(
            {
                "session_id": session_id,
                "_id": {"$in": list(source_ids)},
            },
            **find_kwargs,
        )
        existing_ids: set[str]
        if existing_count == len(source_ids):
            existing_ids = set(source_ids)
        else:
            existing_docs = self._research_sources.find(
                {
                    "session_id": session_id,
                    "_id": {"$in": list(source_ids)},
                },
                {"_id": 1},
                **find_kwargs,
            )
            existing_ids = {item["_id"] for item in existing_docs}
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
    def _links_from_docs(
        rows: list[dict[str, Any]],
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
