"""
============================================================================
FILE: protocols.py
LOCATION: server/database/repositories/protocols.py
============================================================================
PURPOSE:
    Synchronous repository Protocol ports for learning, generation,
    research, progress, and app-settings persistence.
ROLE IN PROJECT:
    Ports-and-adapters boundary around current sync SQLite stores so Phase 3
    can swap Mongo implementations without changing call sites.
    - Production call-graph methods only (no sqlite3.Connection / db_path)
    - runtime_checkable contracts for structural typing and tests
DEPENDENCIES:
    - External: pydantic, typing
    - Internal: server.schemas.generation, learning, progress, research
USAGE:
    from server.database.repositories.protocols import LearningRepository
============================================================================
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel

from server.schemas.generation import (
    GenerationBrief,
    GenerationBriefBatch,
    GenerationCounts,
    GenerationJobPublic,
    GenerationJobRecord,
    GenerationLock,
    GenerationStage,
    GenerationWarning,
    GroundingStatus,
    SourceCitation,
)
from server.schemas.learning import (
    CourseOutline,
    FailedStep,
    NodeStatus,
    QuizCard,
    QuizSet,
    TopicNode,
)
from server.schemas.progress import ProgressEvent, ProgressEventType
from server.schemas.research import (
    ResearchProviderStatus,
    ResearchReport,
    ResearchSection,
    ResearchSource,
    ResearchStatus,
)


@runtime_checkable
class LearningRepository(Protocol):
    def create_learning_session(
        self,
        query: str,
        course_title: str,
        user_id: Optional[str] = None,
        mode: str = "auto",
        resolved_mode: Optional[str] = None,
    ) -> dict[str, Any]: ...

    def get_learning_session(
        self,
        session_id: str,
    ) -> Optional[dict[str, Any]]: ...

    def get_session_progress(
        self,
        session_id: str,
    ) -> Optional[dict[str, Any]]: ...

    def get_sessions_list(
        self,
        user_id: Optional[str],
        status: str = "all",
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]: ...

    def update_session_resolved_mode(
        self,
        session_id: str,
        resolved_mode: str,
    ) -> None: ...

    def update_last_active_node(
        self,
        session_id: str,
        node_id: str,
    ) -> None: ...

    def delete_learning_session(self, session_id: str) -> bool: ...
    def create_concept_node(self, *args: Any, **kwargs: Any) -> dict: ...
    def get_session_nodes(self, session_id: str) -> list[dict]: ...
    def get_concept_node(self, node_id: str) -> Optional[dict]: ...
    def get_next_node(
        self,
        session_id: str,
        sequence_index: int,
    ) -> Optional[dict]: ...
    def update_node_status(
        self,
        node_id: str,
        status: NodeStatus,
    ) -> Optional[dict]: ...
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
    ) -> Optional[dict]: ...
    def replace_node_content(
        self,
        node_id: str,
        content_markdown: str,
        status: NodeStatus,
        quiz_set: Optional[QuizSet] = None,
    ) -> Optional[dict]: ...
    def get_quiz_for_node(self, node_id: str) -> Optional[QuizCard]: ...
    def create_quiz_set(
        self,
        node_id: str,
        quiz_set: QuizSet,
        shuffle_seed: Optional[str] = None,
    ) -> dict: ...
    def get_quiz_set_for_node(
        self,
        node_id: str,
    ) -> Optional[dict]: ...
    def update_quiz_shuffle_seed(
        self,
        node_id: str,
        shuffle_seed: str,
    ) -> bool: ...
    def decrement_quiz_set_progress(
        self,
        node_id: str,
    ) -> Optional[dict]: ...
    def update_quiz_set_progress(
        self,
        node_id: str,
        current_index: int,
    ) -> Optional[dict]: ...
    def create_quiz_attempt(
        self,
        node_id: str,
        selected_option_ids: list[str],
        quiz_index: int = 0,
        revision_session_id: Optional[str] = None,
    ) -> dict: ...
    def get_quiz_attempts(self, node_id: str) -> dict: ...
    def check_mastery(self, node_id: str) -> bool: ...
    def create_revision_session(
        self,
        original_session_id: str,
        mode: str,
    ) -> dict: ...
    def get_revisions_for_session(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]: ...
    def get_revision_session(
        self,
        revision_id: str,
    ) -> Optional[dict]: ...
    def delete_revision_session(self, revision_id: str) -> bool: ...
    def mark_revision_node_reviewed(
        self,
        revision_id: str,
        node_id: str,
    ) -> dict: ...
    def submit_revision_quiz(
        self,
        revision_id: str,
        node_id: str,
        selected_option_ids: list[str],
        quiz_index: int = 0,
    ) -> dict: ...
    def get_revision_summary(self, revision_id: str) -> dict: ...


@runtime_checkable
class GenerationJobRepository(Protocol):
    def create_session_shell_and_job(
        self,
        *,
        query: str,
        user_id: Optional[str],
        mode: str,
        web_search_requested: bool,
        now: Optional[datetime] = None,
    ) -> tuple[dict, GenerationJobRecord]: ...
    def get_by_session(
        self,
        session_id: str,
    ) -> Optional[GenerationJobRecord]: ...
    def to_public(
        self,
        job: GenerationJobRecord,
        *,
        last_event_id: Optional[int] = None,
    ) -> GenerationJobPublic: ...
    def to_public_by_session(
        self,
        session_id: str,
    ) -> Optional[GenerationJobPublic]: ...
    def get_public_by_sessions(
        self,
        session_ids: list[str],
    ) -> dict[str, GenerationJobPublic]: ...
    def transition_stage(self, **kwargs: Any) -> GenerationJobRecord: ...
    def update_cursor(self, **kwargs: Any) -> GenerationJobRecord: ...
    def request_cancel(self, session_id: str) -> GenerationJobRecord: ...
    def is_cancel_requested(self, session_id: str) -> bool: ...
    def mark_paused(self, **kwargs: Any) -> GenerationJobRecord: ...
    def mark_cancelled(self, **kwargs: Any) -> GenerationJobRecord: ...
    def prepare_resume(self, session_id: str) -> GenerationJobRecord: ...
    def try_acquire_lock(
        self,
        *,
        session_id: str,
        owner: str,
        ttl_seconds: int,
        now: Optional[datetime] = None,
    ) -> Optional[GenerationLock]: ...
    def renew_lock(
        self,
        *,
        lock: GenerationLock,
        ttl_seconds: int,
        now: Optional[datetime] = None,
    ) -> GenerationLock: ...
    def release_lock(self, *, lock: GenerationLock) -> None: ...
    def mark_orphaned_jobs_paused(
        self,
        now: Optional[datetime] = None,
        *,
        pause_all_nonterminal: bool = False,
    ) -> list[str]: ...
    def update_stage(
        self,
        session_id: str,
        stage: GenerationStage,
        *,
        lock: Optional[GenerationLock] = None,
    ) -> None: ...
    def update_progress(
        self,
        session_id: str,
        completed_topics: int,
        *,
        lock: Optional[GenerationLock] = None,
        topics_ready: Optional[int] = None,
        topics_failed: Optional[int] = None,
    ) -> None: ...
    def append_warning(
        self,
        session_id: str,
        warning: GenerationWarning,
    ) -> None: ...
    def bump_counts(
        self,
        session_id: str,
        **increments: int,
    ) -> GenerationCounts: ...
    def set_grounding_status(
        self,
        session_id: str,
        grounding_status: GroundingStatus,
    ) -> None: ...
    def mark_failed(
        self,
        session_id: str,
        safe_message: str = "Generation failed",
    ) -> None: ...


@runtime_checkable
class GenerationArtifactRepository(Protocol):
    def persist_outline(
        self,
        session_id: str,
        outline: CourseOutline,
    ) -> list[dict]: ...
    def upsert_brief_batch(
        self,
        session_id: str,
        batch: GenerationBriefBatch,
    ) -> list[GenerationBrief]: ...
    def persist_briefs(
        self,
        session_id: str,
        batch: GenerationBriefBatch,
    ) -> list[GenerationBrief]: ...
    def get_brief(self, node_id: str) -> Optional[GenerationBrief]: ...
    def get_briefs(
        self,
        session_id: str,
        start_index: int,
        limit: int,
    ) -> list[GenerationBrief]: ...
    def get_topic(self, session_id: str, topic_index: int) -> TopicNode: ...
    def count_topics(self, session_id: str) -> int: ...
    def get_outline(self, session_id: str) -> CourseOutline: ...
    def get_adjacent_summaries(
        self,
        session_id: str,
        topic_index: int,
    ) -> tuple[Optional[str], Optional[str]]: ...
    def node_id_for_topic(
        self,
        session_id: str,
        topic_index: int,
    ) -> str: ...
    def persist_generated_content(
        self,
        node_id: str,
        content_markdown: str,
    ) -> dict: ...
    def has_durable_content(self, node_id: str) -> bool: ...
    def persist_content_with_citations(
        self,
        *,
        node_id: str,
        content_markdown: str,
        citations: list[SourceCitation],
    ) -> dict: ...
    def persist_topic_success(
        self,
        node_id: str,
        quiz_set: QuizSet,
        citations: list[SourceCitation],
    ) -> dict: ...
    def persist_topic_error(
        self,
        node_id: str,
        failed_step: FailedStep,
        safe_error_message: str,
        content_markdown: str,
    ) -> dict: ...
    def replace_node_sources(
        self,
        node_id: str,
        citations: list[SourceCitation],
    ) -> list[dict]: ...
    def list_node_sources(self, node_id: str) -> list[dict]: ...
    def get_citations_by_session(
        self,
        session_id: str,
    ) -> dict[str, list[dict]]: ...


@runtime_checkable
class ResearchRepository(Protocol):
    def create_report(
        self,
        session_id: str,
        now: Optional[datetime] = None,
    ) -> ResearchReport: ...
    def get_report(self, session_id: str) -> Optional[ResearchReport]: ...
    def upsert_source(self, **kwargs: Any) -> ResearchSource: ...
    def upsert_section(self, **kwargs: Any) -> ResearchSection: ...
    def set_provider_status(
        self,
        **kwargs: Any,
    ) -> ResearchProviderStatus: ...
    def finalize_report(
        self,
        *,
        session_id: str,
        status: ResearchStatus,
        summary: str,
        limitations: list[str],
        freshness_note: Optional[str],
    ) -> ResearchReport: ...
    def mark_degraded(self, **kwargs: Any) -> ResearchReport: ...
    def get_planner_context(
        self,
        session_id: str,
        max_excerpt_chars: int,
    ) -> dict: ...
    def get_report_context(
        self,
        report_id_or_session_id: str,
        max_bytes: int = 8000,
    ) -> Optional[str]: ...
    def get_sources_by_ids(
        self,
        session_id: str,
        source_ids: list[str],
    ) -> list[ResearchSource]: ...
    def get_citations_by_session(
        self,
        session_id: str,
    ) -> dict[str, list[dict]]: ...
    def get_public_report(
        self,
        session_id: str,
    ) -> Optional[ResearchReport]: ...


@runtime_checkable
class ProgressEventRepository(Protocol):
    def append_once(
        self,
        *,
        session_id: str,
        event_type: ProgressEventType,
        payload: BaseModel,
        dedupe_key: str,
        now: Optional[datetime] = None,
    ) -> ProgressEvent: ...
    def list_after(
        self,
        session_id: str,
        after_event_id: int,
        limit: int = 100,
    ) -> list[ProgressEvent]: ...
    def latest_id(self, session_id: str) -> int: ...
    def compact_completed(
        self,
        session_id: str,
        keep_last: int = 200,
    ) -> int: ...


@runtime_checkable
class AppSettingsRepository(Protocol):
    def get_provider_settings(self) -> Optional[dict[str, Any]]: ...
    def put_provider_settings(self, payload: dict[str, Any]) -> None: ...
    def get_web_search_settings(self) -> Optional[dict[str, Any]]: ...
    def put_web_search_settings(self, payload: dict[str, Any]) -> None: ...
