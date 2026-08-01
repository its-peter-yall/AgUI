"""
============================================================================
FILE: research_store.py
LOCATION: server/database/research_store.py
============================================================================
PURPOSE:
    Incremental research report, section, source, and provider-state
    persistence for the research phase of course generation.
ROLE IN PROJECT:
    Owns the durable Researcher output aggregate without growing
    LearningManager.
    - Deduplicates sources by canonical URL and content hash
    - Persists only safe provider states, never raw provider bodies
KEY COMPONENTS:
    - ResearchSourceConflict: Copied evidence attributed to a second URL
    - ResearchRelationshipError: Invalid report/source relationships
    - ResearchStore: Report aggregate persistence
DEPENDENCIES:
    - External: sqlite3, uuid, logging
    - Internal: server.database.persistence, server.database.sqlite_utils,
                server.schemas.research
USAGE:
    from server.database.research_store import ResearchStore
    store = ResearchStore()
    report = store.create_report(session_id)
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
from server.database.sqlite_utils import (
    canonical_json,
    optional_transaction,
    parse_iso_datetime,
)
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


class ResearchSourceConflict(RuntimeError):
    """Raised when one content hash maps to two different canonical URLs."""


class ResearchRelationshipError(RuntimeError):
    """Raised when sections reference sources outside the report session."""


class ResearchStore:
    """Persists research report aggregates for one generation session."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DB_PATH

    @staticmethod
    def _utc_now(now: Optional[datetime]) -> datetime:
        return now or datetime.now(timezone.utc)

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> ResearchSource:
        return ResearchSource(
            id=row["id"],
            title=row["title"],
            url=row["url"],
            publisher=row["publisher"],
            published_at=parse_iso_datetime(row["published_at"]),
            retrieved_at=parse_iso_datetime(row["retrieved_at"]),
            provider_id=SearchProviderId(row["provider_id"]),
            snippet=row["snippet"] or "",
            excerpt=row["excerpt"] or "",
            relevance_score=row["relevance_score"],
        )

    def create_report(
        self,
        session_id: str,
        now: Optional[datetime] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> ResearchReport:
        """Create a PENDING report row for a session; idempotent per session."""
        timestamp = self._utc_now(now)
        now_iso = timestamp.isoformat()
        with optional_transaction(self.db_path, conn) as active_conn:
            existing = active_conn.execute(
                "SELECT id FROM research_reports WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if existing is not None:
                return self._load_report(active_conn, session_id)
            report_id = str(uuid.uuid4())
            active_conn.execute(
                """
                INSERT INTO research_reports (
                    id, session_id, status, summary, limitations_json,
                    freshness_note, warnings_json, created_at, updated_at
                )
                VALUES (?, ?, ?, NULL, '[]', NULL, '[]', ?, ?)
                """,
                (
                    report_id,
                    session_id,
                    ResearchStatus.PENDING.value,
                    now_iso,
                    now_iso,
                ),
            )
        logger.info("Created research report %s", report_id)
        return self.get_report(session_id)

    def get_report(
        self, session_id: str
    ) -> Optional[ResearchReport]:
        with optional_transaction(self.db_path, None) as conn:
            return self._load_report(conn, session_id)

    def _load_report(
        self,
        conn: sqlite3.Connection,
        session_id: str,
    ) -> Optional[ResearchReport]:
        report_row = conn.execute(
            "SELECT * FROM research_reports WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if report_row is None:
            return None

        section_rows = conn.execute(
            """
            SELECT s.* FROM research_sections s
            WHERE s.report_id = ?
            ORDER BY s.sequence_index ASC
            """,
            (report_row["id"],),
        ).fetchall()
        source_rows = conn.execute(
            "SELECT * FROM research_sources WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        provider_rows = conn.execute(
            "SELECT * FROM research_provider_statuses WHERE report_id = ?",
            (report_row["id"],),
        ).fetchall()

        sections: list[ResearchSection] = []
        for section_row in section_rows:
            link_rows = conn.execute(
                """
                SELECT source_id FROM research_section_sources
                WHERE section_id = ?
                ORDER BY rowid ASC
                """,
                (section_row["id"],),
            ).fetchall()
            sections.append(
                ResearchSection(
                    id=section_row["id"],
                    sequence_index=int(section_row["sequence_index"]),
                    theme=section_row["theme"],
                    markdown=section_row["markdown"],
                    source_ids=[link["source_id"] for link in link_rows],
                    created_at=parse_iso_datetime(section_row["created_at"]),
                    updated_at=parse_iso_datetime(section_row["updated_at"]),
                )
            )

        warnings = [
            GenerationWarning.model_validate(item)
            for item in json.loads(report_row["warnings_json"] or "[]")
        ]
        provider_statuses = [
            ResearchProviderStatus(
                provider_id=SearchProviderId(row["provider_id"]),
                state=ResearchProviderState(row["state"]),
                search_calls=int(row["search_calls"]),
                result_count=int(row["result_count"]),
                error_class=(
                    SearchErrorClass(row["error_class"])
                    if row["error_class"] is not None
                    else None
                ),
            )
            for row in provider_rows
        ]
        return ResearchReport(
            id=report_row["id"],
            session_id=session_id,
            status=ResearchStatus(report_row["status"]),
            summary=report_row["summary"],
            limitations=json.loads(report_row["limitations_json"] or "[]"),
            freshness_note=report_row["freshness_note"],
            sections=sections,
            sources=[self._source_from_row(row) for row in source_rows],
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
        conn: Optional[sqlite3.Connection] = None,
    ) -> ResearchSource:
        """Insert a source or update richer metadata on canonical match."""
        timestamp = self._utc_now(None)
        now_iso = timestamp.isoformat()
        with optional_transaction(self.db_path, conn) as active_conn:
            existing = active_conn.execute(
                """
                SELECT id, content_hash FROM research_sources
                WHERE session_id = ? AND canonical_url = ?
                """,
                (session_id, canonical_url),
            ).fetchone()
            if existing is not None:
                if existing["content_hash"] != content_hash:
                    collision = active_conn.execute(
                        """
                        SELECT id FROM research_sources
                        WHERE session_id = ? AND content_hash = ?
                          AND id != ?
                        """,
                        (session_id, content_hash, existing["id"]),
                    ).fetchone()
                    if collision is not None:
                        raise ResearchSourceConflict(
                            "Content hash already attributed to another URL"
                        )
                active_conn.execute(
                    """
                    UPDATE research_sources
                    SET canonical_url = ?, content_hash = ?, title = ?,
                        url = ?, publisher = ?, published_at = ?,
                        retrieved_at = ?, provider_id = ?, snippet = ?,
                        excerpt = ?, relevance_score = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        canonical_url,
                        content_hash,
                        source.title,
                        str(source.url),
                        source.publisher,
                        (
                            source.published_at.isoformat()
                            if source.published_at is not None
                            else None
                        ),
                        source.retrieved_at.isoformat(),
                        source.provider_id.value,
                        source.snippet,
                        source.excerpt,
                        source.relevance_score,
                        now_iso,
                        existing["id"],
                    ),
                )
                source_id = existing["id"]
            else:
                hash_row = active_conn.execute(
                    """
                    SELECT id FROM research_sources
                    WHERE session_id = ? AND content_hash = ?
                    """,
                    (session_id, content_hash),
                ).fetchone()
                if hash_row is not None:
                    raise ResearchSourceConflict(
                        "Content hash already attributed to another URL"
                    )
                source_id = str(uuid.uuid4())
                active_conn.execute(
                    """
                    INSERT INTO research_sources (
                        id, session_id, canonical_url, content_hash, title,
                        url, publisher, published_at, retrieved_at,
                        provider_id, snippet, excerpt, relevance_score,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        session_id,
                        canonical_url,
                        content_hash,
                        source.title,
                        str(source.url),
                        source.publisher,
                        (
                            source.published_at.isoformat()
                            if source.published_at is not None
                            else None
                        ),
                        source.retrieved_at.isoformat(),
                        source.provider_id.value,
                        source.snippet,
                        source.excerpt,
                        source.relevance_score,
                        now_iso,
                        now_iso,
                    ),
                )
            row = active_conn.execute(
                "SELECT * FROM research_sources WHERE id = ?",
                (source_id,),
            ).fetchone()
            return self._source_from_row(row)

    def upsert_section(
        self,
        *,
        report_id: str,
        sequence_index: int,
        theme: str,
        markdown: str,
        source_ids: list[str],
        conn: Optional[sqlite3.Connection] = None,
    ) -> ResearchSection:
        """Insert or replace a section and its links in one transaction."""
        timestamp = self._utc_now(None)
        now_iso = timestamp.isoformat()
        with optional_transaction(self.db_path, conn) as active_conn:
            report_row = active_conn.execute(
                "SELECT id, session_id FROM research_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
            if report_row is None:
                raise ResearchRelationshipError(
                    f"Research report not found: {report_id}"
                )
            self._validate_section_sources(
                active_conn,
                report_row["session_id"],
                source_ids,
            )
            existing = active_conn.execute(
                """
                SELECT id FROM research_sections
                WHERE report_id = ? AND sequence_index = ?
                """,
                (report_id, sequence_index),
            ).fetchone()
            if existing is None:
                section_id = str(uuid.uuid4())
                active_conn.execute(
                    """
                    INSERT INTO research_sections (
                        id, report_id, sequence_index, theme, markdown,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        section_id,
                        report_id,
                        sequence_index,
                        theme,
                        markdown,
                        now_iso,
                        now_iso,
                    ),
                )
            else:
                section_id = existing["id"]
                active_conn.execute(
                    """
                    UPDATE research_sections
                    SET theme = ?, markdown = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (theme, markdown, now_iso, section_id),
                )
            active_conn.execute(
                "DELETE FROM research_section_sources WHERE section_id = ?",
                (section_id,),
            )
            active_conn.executemany(
                """
                INSERT INTO research_section_sources (section_id, source_id)
                VALUES (?, ?)
                """,
                [(section_id, source_id) for source_id in source_ids],
            )
            return self._load_section(active_conn, section_id)

    @staticmethod
    def _validate_section_sources(
        conn: sqlite3.Connection,
        session_id: str,
        source_ids: list[str],
    ) -> None:
        if not source_ids:
            return
        if len(source_ids) != len(set(source_ids)):
            raise ResearchRelationshipError("Section source IDs must be unique")
        placeholders = ",".join("?" for _ in source_ids)
        rows = conn.execute(
            f"""
            SELECT id FROM research_sources
            WHERE session_id = ? AND id IN ({placeholders})
            """,
            (session_id, *source_ids),
        ).fetchall()
        if len(rows) != len(source_ids):
            raise ResearchRelationshipError(
                "Section sources must belong to the report session"
            )

    @staticmethod
    def _load_section(
        conn: sqlite3.Connection,
        section_id: str,
    ) -> ResearchSection:
        row = conn.execute(
            "SELECT * FROM research_sections WHERE id = ?",
            (section_id,),
        ).fetchone()
        if row is None:
            raise ResearchRelationshipError(
                f"Research section not found: {section_id}"
            )
        link_rows = conn.execute(
            """
            SELECT source_id FROM research_section_sources
            WHERE section_id = ?
            ORDER BY rowid ASC
            """,
            (section_id,),
        ).fetchall()
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
        conn: Optional[sqlite3.Connection] = None,
    ) -> ResearchProviderStatus:
        """Upsert safe per-provider telemetry for a report."""
        with optional_transaction(self.db_path, conn) as active_conn:
            report_row = active_conn.execute(
                "SELECT id FROM research_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
            if report_row is None:
                raise ResearchRelationshipError(
                    f"Research report not found: {report_id}"
                )
            active_conn.execute(
                """
                INSERT INTO research_provider_statuses (
                    report_id, provider_id, state, search_calls,
                    result_count, error_class
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (report_id, provider_id) DO UPDATE SET
                    state = excluded.state,
                    search_calls = excluded.search_calls,
                    result_count = excluded.result_count,
                    error_class = excluded.error_class
                """,
                (
                    report_id,
                    provider_id.value,
                    state.value,
                    search_calls,
                    result_count,
                    error_class.value if error_class is not None else None,
                ),
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
        freshness_note: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> ResearchReport:
        """Set terminal research status, summary, and limitations."""
        timestamp = self._utc_now(None)
        with optional_transaction(self.db_path, conn) as active_conn:
            row = active_conn.execute(
                "SELECT id FROM research_reports WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise ResearchRelationshipError(
                    f"Research report not found for session {session_id}"
                )
            active_conn.execute(
                """
                UPDATE research_reports
                SET status = ?, summary = ?, limitations_json = ?,
                    freshness_note = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    status.value,
                    summary,
                    canonical_json(limitations),
                    freshness_note,
                    timestamp.isoformat(),
                    session_id,
                ),
            )
            return self._load_report(active_conn, session_id)

    def mark_degraded(
        self,
        *,
        session_id: str,
        warning: GenerationWarning,
        conn: Optional[sqlite3.Connection] = None,
    ) -> ResearchReport:
        """Mark research degraded and append a safe warning."""
        timestamp = self._utc_now(None)
        with optional_transaction(self.db_path, conn) as active_conn:
            row = active_conn.execute(
                "SELECT warnings_json FROM research_reports WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise ResearchRelationshipError(
                    f"Research report not found for session {session_id}"
                )
            warnings = [
                GenerationWarning.model_validate(item)
                for item in json.loads(row["warnings_json"] or "[]")
            ]
            warnings.append(warning)
            active_conn.execute(
                """
                UPDATE research_reports
                SET status = ?, warnings_json = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    ResearchStatus.DEGRADED.value,
                    canonical_json(warnings),
                    timestamp.isoformat(),
                    session_id,
                ),
            )
            return self._load_report(active_conn, session_id)

    def get_planner_context(
        self,
        session_id: str,
        max_excerpt_chars: int,
    ) -> dict[str, Any]:
        """Return ordered sections and capped source excerpts for planning.

        Omits canonical URLs, content hashes, and provider raw data.
        """
        with optional_transaction(self.db_path, None) as conn:
            report_row = conn.execute(
                """
                SELECT id, status, summary, freshness_note
                FROM research_reports WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if report_row is None:
                return {
                    "session_id": session_id,
                    "report_status": None,
                    "sections": [],
                    "sources": [],
                }
            section_rows = conn.execute(
                """
                SELECT * FROM research_sections
                WHERE report_id = ?
                ORDER BY sequence_index ASC
                """,
                (report_row["id"],),
            ).fetchall()
            source_rows = conn.execute(
                """
                SELECT * FROM research_sources
                WHERE session_id = ?
                ORDER BY rowid ASC
                """,
                (session_id,),
            ).fetchall()

            sections: list[dict[str, Any]] = []
            for section_row in section_rows:
                link_rows = conn.execute(
                    """
                    SELECT source_id FROM research_section_sources
                    WHERE section_id = ?
                    ORDER BY rowid ASC
                    """,
                    (section_row["id"],),
                ).fetchall()
                sections.append(
                    {
                        "sequence_index": int(section_row["sequence_index"]),
                        "theme": section_row["theme"],
                        "markdown": section_row["markdown"],
                        "source_ids": [link["source_id"] for link in link_rows],
                    }
                )
            sources = [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "url": row["url"],
                    "publisher": row["publisher"],
                    "published_at": parse_iso_datetime(row["published_at"]),
                    "provider_id": row["provider_id"],
                    "excerpt": (row["excerpt"] or "")[:max_excerpt_chars],
                    "relevance_score": row["relevance_score"],
                }
                for row in source_rows
            ]
        return {
            "session_id": session_id,
            "report_status": report_row["status"],
            "sections": sections,
            "sources": sources,
        }

    def get_sources_by_ids(
        self,
        session_id: str,
        source_ids: list[str],
    ) -> list[ResearchSource]:
        """Return persisted sources for the session filtered by IDs."""
        if not source_ids:
            return []
        placeholders = ",".join("?" for _ in source_ids)
        with optional_transaction(self.db_path, None) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM research_sources
                WHERE session_id = ? AND id IN ({placeholders})
                """,
                (session_id, *source_ids),
            ).fetchall()
        return [self._source_from_row(row) for row in rows]


research_store = ResearchStore()
