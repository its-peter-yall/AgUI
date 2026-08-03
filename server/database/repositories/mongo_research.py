"""
============================================================================
FILE: mongo_research.py
LOCATION: server/database/repositories/mongo_research.py
============================================================================
PURPOSE:
    Synchronous Mongo implementation of ResearchRepository for reports,
    sources, sections, and provider statuses.
ROLE IN PROJECT:
    Phase 3B Atlas adapter for research persistence. Mirrors ResearchStore
    public methods with compound string IDs for junction collections.
DEPENDENCIES:
    - External: pymongo
    - Internal: server.database.research_store (exceptions),
                server.database.repositories.mongo_common,
                server.database.sqlite_utils,
                server.schemas.research, server.schemas.generation
USAGE:
    repo = MongoResearchRepository(database)
    report = repo.create_report(session_id)
============================================================================
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pymongo import ASCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from server.database.repositories.mongo_common import (
    model_payload,
    utc_iso,
)
from server.database.research_store import (
    ResearchRelationshipError,
    ResearchSourceConflict,
)
from server.database.sqlite_utils import parse_iso_datetime
from server.schemas.generation import GenerationWarning
from server.schemas.research import (
    ResearchProviderState,
    ResearchProviderStatus,
    ResearchReport,
    ResearchSection,
    ResearchSource,
    ResearchStatus,
)
from server.search.types import SearchErrorClass, SearchProviderId

logger = logging.getLogger(__name__)


def _section_source_id(section_id: str, source_id: str) -> str:
    return f"{section_id}::{source_id}"


def _provider_status_id(report_id: str, provider_id: str) -> str:
    return f"{report_id}::{provider_id}"


def _utc_now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


class MongoResearchRepository:
    """Mongo implementation of research report aggregate persistence."""

    def __init__(self, database: Any) -> None:
        self._db = database
        self._reports = database["research_reports"]
        self._sources = database["research_sources"]
        self._sections = database["research_sections"]
        self._section_sources = database["research_section_sources"]
        self._providers = database["research_provider_statuses"]
        self._nodes = database["concept_nodes"]
        self._node_sources = database["node_sources"]

    @staticmethod
    def _source_from_doc(document: dict[str, Any]) -> ResearchSource:
        return ResearchSource(
            id=document["_id"],
            title=document["title"],
            url=document["url"],
            publisher=document.get("publisher"),
            published_at=parse_iso_datetime(
                document.get("published_at")
            ),
            retrieved_at=parse_iso_datetime(document["retrieved_at"]),
            provider_id=SearchProviderId(document["provider_id"]),
            snippet=document.get("snippet") or "",
            excerpt=document.get("excerpt") or "",
            relevance_score=document.get("relevance_score"),
        )

    def create_report(
        self,
        session_id: str,
        now: Optional[datetime] = None,
    ) -> ResearchReport:
        timestamp = _utc_now(now)
        now_iso = timestamp.isoformat()
        report_id = str(uuid.uuid4())
        document = self._reports.find_one_and_update(
            {"session_id": session_id},
            {
                "$setOnInsert": {
                    "_id": report_id,
                    "session_id": session_id,
                    "status": ResearchStatus.PENDING.value,
                    "summary": None,
                    "limitations": [],
                    "freshness_note": None,
                    "warnings": [],
                    "created_at": now_iso,
                    "updated_at": now_iso,
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        logger.info("Created research report %s", document["_id"])
        loaded = self.get_report(session_id)
        if loaded is None:
            raise ResearchRelationshipError(
                f"Research report not found for session {session_id}"
            )
        return loaded

    def get_report(self, session_id: str) -> Optional[ResearchReport]:
        return self._load_report(session_id)

    def _load_report(
        self,
        session_id: str,
    ) -> Optional[ResearchReport]:
        report_row = self._reports.find_one({"session_id": session_id})
        if report_row is None:
            return None
        section_rows = list(
            self._sections.find(
                {"report_id": report_row["_id"]}
            ).sort("sequence_index", ASCENDING)
        )
        source_rows = list(
            self._sources.find({"session_id": session_id})
        )
        provider_rows = list(
            self._providers.find({"report_id": report_row["_id"]})
        )
        sections: list[ResearchSection] = []
        for section_row in section_rows:
            link_rows = list(
                self._section_sources.find(
                    {"section_id": section_row["_id"]}
                ).sort("_id", ASCENDING)
            )
            sections.append(
                ResearchSection(
                    id=section_row["_id"],
                    sequence_index=int(section_row["sequence_index"]),
                    theme=section_row["theme"],
                    markdown=section_row["markdown"],
                    source_ids=[
                        link["source_id"] for link in link_rows
                    ],
                    created_at=parse_iso_datetime(
                        section_row["created_at"]
                    ),
                    updated_at=parse_iso_datetime(
                        section_row["updated_at"]
                    ),
                )
            )
        warnings = [
            GenerationWarning.model_validate(item)
            for item in (report_row.get("warnings") or [])
        ]
        provider_statuses = [
            ResearchProviderStatus(
                provider_id=SearchProviderId(row["provider_id"]),
                state=ResearchProviderState(row["state"]),
                search_calls=int(row["search_calls"]),
                result_count=int(row["result_count"]),
                error_class=(
                    SearchErrorClass(row["error_class"])
                    if row.get("error_class") is not None
                    else None
                ),
            )
            for row in provider_rows
        ]
        return ResearchReport(
            id=report_row["_id"],
            session_id=session_id,
            status=ResearchStatus(report_row["status"]),
            summary=report_row.get("summary"),
            limitations=list(report_row.get("limitations") or []),
            freshness_note=report_row.get("freshness_note"),
            sections=sections,
            sources=[self._source_from_doc(row) for row in source_rows],
            provider_statuses=provider_statuses,
            warnings=warnings,
            created_at=parse_iso_datetime(report_row["created_at"]),
            updated_at=parse_iso_datetime(report_row["updated_at"]),
        )

    def upsert_source(
        self,
        *,
        session_id: str,
        source: ResearchSource,
        canonical_url: str,
        content_hash: str,
    ) -> ResearchSource:
        now_iso = utc_iso()
        existing = self._sources.find_one(
            {
                "session_id": session_id,
                "canonical_url": canonical_url,
            }
        )
        published_at = (
            source.published_at.isoformat()
            if source.published_at is not None
            else None
        )
        payload = {
            "canonical_url": canonical_url,
            "content_hash": content_hash,
            "title": source.title,
            "url": str(source.url),
            "publisher": source.publisher,
            "published_at": published_at,
            "retrieved_at": source.retrieved_at.isoformat(),
            "provider_id": source.provider_id.value,
            "snippet": source.snippet,
            "excerpt": source.excerpt,
            "relevance_score": source.relevance_score,
            "updated_at": now_iso,
        }
        if existing is not None:
            if existing["content_hash"] != content_hash:
                collision = self._sources.find_one(
                    {
                        "session_id": session_id,
                        "content_hash": content_hash,
                        "_id": {"$ne": existing["_id"]},
                    }
                )
                if collision is not None:
                    raise ResearchSourceConflict(
                        "Content hash already attributed to another URL"
                    )
            self._sources.update_one(
                {"_id": existing["_id"]},
                {"$set": payload},
            )
            source_id = existing["_id"]
        else:
            hash_row = self._sources.find_one(
                {
                    "session_id": session_id,
                    "content_hash": content_hash,
                }
            )
            if hash_row is not None:
                raise ResearchSourceConflict(
                    "Content hash already attributed to another URL"
                )
            source_id = str(uuid.uuid4())
            try:
                self._sources.insert_one(
                    {
                        "_id": source_id,
                        "session_id": session_id,
                        "created_at": now_iso,
                        **payload,
                    }
                )
            except DuplicateKeyError as exc:
                raise ResearchSourceConflict(
                    "Source unique constraint conflict"
                ) from exc
        row = self._sources.find_one({"_id": source_id})
        if row is None:
            raise ResearchRelationshipError(
                f"Research source not found: {source_id}"
            )
        return self._source_from_doc(row)

    def upsert_section(
        self,
        *,
        report_id: str,
        sequence_index: int,
        theme: str,
        markdown: str,
        source_ids: list[str],
    ) -> ResearchSection:
        now_iso = utc_iso()
        report_row = self._reports.find_one({"_id": report_id})
        if report_row is None:
            raise ResearchRelationshipError(
                f"Research report not found: {report_id}"
            )
        self._validate_section_sources(
            report_row["session_id"],
            source_ids,
        )
        section_id = str(uuid.uuid4())
        document = self._sections.find_one_and_update(
            {
                "report_id": report_id,
                "sequence_index": sequence_index,
            },
            {
                "$set": {
                    "theme": theme,
                    "markdown": markdown,
                    "updated_at": now_iso,
                },
                "$setOnInsert": {
                    "_id": section_id,
                    "report_id": report_id,
                    "sequence_index": sequence_index,
                    "created_at": now_iso,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        section_id = document["_id"]
        self._section_sources.delete_many({"section_id": section_id})
        if source_ids:
            self._section_sources.insert_many(
                [
                    {
                        "_id": _section_source_id(section_id, source_id),
                        "section_id": section_id,
                        "source_id": source_id,
                    }
                    for source_id in source_ids
                ]
            )
        return self._load_section(section_id)

    def _validate_section_sources(
        self,
        session_id: str,
        source_ids: list[str],
    ) -> None:
        if not source_ids:
            return
        if len(source_ids) != len(set(source_ids)):
            raise ResearchRelationshipError(
                "Section source IDs must be unique"
            )
        count = self._sources.count_documents(
            {
                "session_id": session_id,
                "_id": {"$in": source_ids},
            }
        )
        if count != len(source_ids):
            raise ResearchRelationshipError(
                "Section sources must belong to the report session"
            )

    def _load_section(self, section_id: str) -> ResearchSection:
        row = self._sections.find_one({"_id": section_id})
        if row is None:
            raise ResearchRelationshipError(
                f"Research section not found: {section_id}"
            )
        link_rows = list(
            self._section_sources.find(
                {"section_id": section_id}
            ).sort("_id", ASCENDING)
        )
        return ResearchSection(
            id=section_id,
            sequence_index=int(row["sequence_index"]),
            theme=row["theme"],
            markdown=row["markdown"],
            source_ids=[link["source_id"] for link in link_rows],
            created_at=parse_iso_datetime(row["created_at"]),
            updated_at=parse_iso_datetime(row["updated_at"]),
        )

    def set_provider_status(
        self,
        *,
        report_id: str,
        provider_id: SearchProviderId,
        state: ResearchProviderState,
        search_calls: int,
        result_count: int,
        error_class: Optional[SearchErrorClass] = None,
    ) -> ResearchProviderStatus:
        report_row = self._reports.find_one({"_id": report_id})
        if report_row is None:
            raise ResearchRelationshipError(
                f"Research report not found: {report_id}"
            )
        provider_key = provider_id.value
        self._providers.find_one_and_update(
            {
                "report_id": report_id,
                "provider_id": provider_key,
            },
            {
                "$set": {
                    "state": state.value,
                    "search_calls": search_calls,
                    "result_count": result_count,
                    "error_class": (
                        error_class.value
                        if error_class is not None
                        else None
                    ),
                },
                "$setOnInsert": {
                    "_id": _provider_status_id(report_id, provider_key),
                    "report_id": report_id,
                    "provider_id": provider_key,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return ResearchProviderStatus(
            provider_id=provider_id,
            state=state,
            search_calls=search_calls,
            result_count=result_count,
            error_class=error_class,
        )

    def finalize_report(
        self,
        *,
        session_id: str,
        status: ResearchStatus,
        summary: str,
        limitations: list[str],
        freshness_note: Optional[str],
    ) -> ResearchReport:
        timestamp = utc_iso()
        updated = self._reports.find_one_and_update(
            {"session_id": session_id},
            {
                "$set": {
                    "status": status.value,
                    "summary": summary,
                    "limitations": limitations,
                    "freshness_note": freshness_note,
                    "updated_at": timestamp,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise ResearchRelationshipError(
                f"Research report not found for session {session_id}"
            )
        loaded = self._load_report(session_id)
        if loaded is None:
            raise ResearchRelationshipError(
                f"Research report not found for session {session_id}"
            )
        return loaded

    def mark_degraded(
        self,
        *,
        session_id: str,
        warning: GenerationWarning,
    ) -> ResearchReport:
        timestamp = utc_iso()
        document = self._reports.find_one({"session_id": session_id})
        if document is None:
            raise ResearchRelationshipError(
                f"Research report not found for session {session_id}"
            )
        warnings = [
            GenerationWarning.model_validate(item)
            for item in (document.get("warnings") or [])
        ]
        warnings.append(warning)
        self._reports.update_one(
            {"session_id": session_id},
            {
                "$set": {
                    "status": ResearchStatus.DEGRADED.value,
                    "warnings": [model_payload(item) for item in warnings],
                    "updated_at": timestamp,
                }
            },
        )
        loaded = self._load_report(session_id)
        if loaded is None:
            raise ResearchRelationshipError(
                f"Research report not found for session {session_id}"
            )
        return loaded

    def get_planner_context(
        self,
        session_id: str,
        max_excerpt_chars: int,
    ) -> dict[str, Any]:
        report_row = self._reports.find_one({"session_id": session_id})
        if report_row is None:
            return {
                "session_id": session_id,
                "report_status": None,
                "sections": [],
                "sources": [],
            }
        section_rows = list(
            self._sections.find(
                {"report_id": report_row["_id"]}
            ).sort("sequence_index", ASCENDING)
        )
        source_rows = list(
            self._sources.find({"session_id": session_id}).sort(
                "_id",
                ASCENDING,
            )
        )
        sections: list[dict[str, Any]] = []
        for section_row in section_rows:
            link_rows = list(
                self._section_sources.find(
                    {"section_id": section_row["_id"]}
                ).sort("_id", ASCENDING)
            )
            sections.append(
                {
                    "sequence_index": int(section_row["sequence_index"]),
                    "theme": section_row["theme"],
                    "markdown": section_row["markdown"],
                    "source_ids": [
                        link["source_id"] for link in link_rows
                    ],
                }
            )
        sources = [
            {
                "id": row["_id"],
                "title": row["title"],
                "url": row["url"],
                "publisher": row.get("publisher"),
                "published_at": parse_iso_datetime(
                    row.get("published_at")
                ),
                "provider_id": row["provider_id"],
                "excerpt": (row.get("excerpt") or "")[
                    :max_excerpt_chars
                ],
                "relevance_score": row.get("relevance_score"),
            }
            for row in source_rows
        ]
        return {
            "session_id": session_id,
            "report_status": report_row["status"],
            "sections": sections,
            "sources": sources,
        }

    def get_report_context(
        self,
        report_id_or_session_id: str,
        max_bytes: int = 8000,
    ) -> Optional[str]:
        try:
            report = self.get_report(report_id_or_session_id)
            if report is None:
                row = self._reports.find_one(
                    {"_id": report_id_or_session_id}
                )
                if row is not None:
                    report = self.get_report(row["session_id"])
            if report is None:
                return None
            parts: list[str] = []
            if report.summary:
                parts.append(f"# Research Summary\n{report.summary}")
            for section in report.sections:
                parts.append(f"## {section.theme}\n{section.markdown}")
            full = "\n\n".join(parts)
            return full[:max_bytes]
        except Exception:
            return None

    def get_sources_by_ids(
        self,
        session_id: str,
        source_ids: list[str],
    ) -> list[ResearchSource]:
        if not source_ids:
            return []
        rows = list(
            self._sources.find(
                {
                    "session_id": session_id,
                    "_id": {"$in": source_ids},
                }
            )
        )
        return [self._source_from_doc(row) for row in rows]

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
        link_rows = list(
            self._node_sources.find(
                {"node_id": {"$in": node_ids}}
            ).sort([("node_id", ASCENDING), ("citation_order", ASCENDING)])
        )
        source_ids = list({row["source_id"] for row in link_rows})
        sources_by_id = {
            row["_id"]: row
            for row in self._sources.find(
                {
                    "session_id": session_id,
                    "_id": {"$in": source_ids},
                }
            )
        }
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in link_rows:
            source = sources_by_id.get(row["source_id"])
            if source is None:
                continue
            node_id = row["node_id"]
            order = int(row["citation_order"])
            citation_number = order + 1 if order >= 0 else order
            if citation_number < 1:
                citation_number = len(grouped.get(node_id, [])) + 1
            grouped.setdefault(node_id, []).append(
                {
                    "source_id": row["source_id"],
                    "citation_number": citation_number,
                    "title": source["title"],
                    "url": source["url"],
                    "publisher": source.get("publisher"),
                    "published_at": source.get("published_at"),
                    "retrieved_at": source.get("retrieved_at"),
                    "claim": row.get("claim"),
                }
            )
        return grouped

    def get_public_report(
        self,
        session_id: str,
    ) -> Optional[ResearchReport]:
        return self.get_report(session_id)
