"""
============================================================================
FILE: generation.py
LOCATION: server/schemas/generation.py
============================================================================
PURPOSE:
    Freezes durable generation stages, cursors, counts, warnings, briefs,
    batches, and source citations shared across the generation pipeline.
ROLE IN PROJECT:
    Defines the contract consumed by persistence, LangGraph, API, and the
    client before runtime implementation exists.
    - Enforces grounding invariants between status and research fields
    - Caps batch sizes and cursor limits at locked bounds
KEY COMPONENTS:
    - GenerationStage, GroundingStatus: Workflow enums
    - GenerationCursor, ResearchCursor: Resumable position state
    - GenerationBrief, GenerationBriefBatch: Topic planning artifacts
    - SourceCitation: Per-claim citation contract
DEPENDENCIES:
    - External: pydantic
    - Internal: server.search.types
USAGE:
    from server.schemas.generation import GenerationBrief
============================================================================
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from server.search.types import SearchProviderId


class GenerationStage(str, Enum):
    INITIALIZING = "INITIALIZING"
    RESEARCHING = "RESEARCHING"
    OUTLINING = "OUTLINING"
    PLANNING_PREVIEW = "PLANNING_PREVIEW"
    GENERATING_PREVIEW = "GENERATING_PREVIEW"
    PLANNING_BATCH = "PLANNING_BATCH"
    GENERATING_BATCH = "GENERATING_BATCH"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    COMPLETE = "COMPLETE"
    COMPLETE_DEGRADED = "COMPLETE_DEGRADED"
    FAILED = "FAILED"


class GroundingStatus(str, Enum):
    DISABLED = "DISABLED"
    PENDING = "PENDING"
    GROUNDED = "GROUNDED"
    DEGRADED = "DEGRADED"


class GenerationCounts(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    topics_total: int = Field(default=0, ge=0, le=30)
    briefs_ready: int = Field(default=0, ge=0, le=30)
    topics_ready: int = Field(default=0, ge=0, le=30)
    topics_failed: int = Field(default=0, ge=0, le=30)
    research_sections: int = Field(default=0, ge=0)
    sources: int = Field(default=0, ge=0, le=40)


class GenerationWarning(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    provider_id: Optional[SearchProviderId] = None


class ResearchCursor(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    iteration: int = Field(default=0, ge=0, le=10)
    next_section_index: int = Field(default=0, ge=0)
    pending_queries: list[str] = Field(default_factory=list, max_length=20)
    completed_themes: list[str] = Field(default_factory=list, max_length=20)
    search_calls: int = Field(default=0, ge=0, le=20)
    llm_turns: int = Field(default=0, ge=0, le=10)
    results_examined: int = Field(default=0, ge=0, le=120)
    provider_bytes: int = Field(default=0, ge=0, le=5_000_000)
    excerpt_chars: int = Field(default=0, ge=0, le=100_000)


class GenerationCursor(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    next_topic_index: int = Field(default=0, ge=0, le=30)
    active_batch_start: Optional[int] = Field(default=None, ge=0, le=29)
    active_batch_size: int = Field(default=0, ge=0, le=10)
    batch_number: int = Field(default=0, ge=0, le=4)
    provider_order: list[SearchProviderId] = Field(
        default_factory=list,
        max_length=4,
    )
    research: ResearchCursor = Field(default_factory=ResearchCursor)


class BriefSourceExcerpt(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: str = Field(min_length=1, max_length=100)
    excerpt: str = Field(min_length=1, max_length=8000)


class GenerationBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    topic_index: int = Field(ge=0, le=29)
    topic_scope: str = Field(min_length=1)
    learning_objectives: list[str] = Field(min_length=1)
    prerequisites: list[str]
    assumed_knowledge: list[str]
    current_facts: list[str]
    methodologies: list[str]
    conventions: list[str]
    deprecated_approaches: list[str]
    migration_notes: list[str]
    caveats: list[str]
    research_report_id: Optional[str] = None
    source_excerpts: Optional[list[BriefSourceExcerpt]] = None
    required_examples: list[str]
    common_misconceptions: list[str]
    failure_modes: list[str]
    pedagogical_guidance: str = Field(min_length=1)
    expected_depth: Literal["lite", "full"]
    boundaries_with_adjacent_topics: str = Field(min_length=1)
    quiz_learning_targets: list[str] = Field(min_length=1)
    expected_learner_evidence: list[str] = Field(min_length=1)
    grounding_status: GroundingStatus

    @model_validator(mode="after")
    def validate_grounding(self) -> "GenerationBrief":
        excerpts = self.source_excerpts or []
        source_ids = [item.source_id for item in excerpts]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("GenerationBrief source IDs must be unique")
        if self.grounding_status == GroundingStatus.GROUNDED and not excerpts:
            raise ValueError("Grounded brief requires approved source excerpts")
        if self.grounding_status == GroundingStatus.DISABLED:
            if self.research_report_id is not None or excerpts:
                raise ValueError("Disabled brief cannot contain research fields")
        return self

    @property
    def approved_source_ids(self) -> list[str]:
        return [item.source_id for item in self.source_excerpts or []]


class GenerationBriefBatch(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start_index: int = Field(ge=0, le=29)
    briefs: list[GenerationBrief] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_indices(self) -> "GenerationBriefBatch":
        expected = list(
            range(self.start_index, self.start_index + len(self.briefs))
        )
        actual = [brief.topic_index for brief in self.briefs]
        if actual != expected:
            raise ValueError("GenerationBriefBatch indices must be contiguous")
        return self

    @property
    def end_index_exclusive(self) -> int:
        return self.start_index + len(self.briefs)


class SourceCitation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: str = Field(min_length=1, max_length=100)
    claim: str = Field(min_length=1, max_length=1000)


class GenerationLock(BaseModel):
    """Fenced worker lock record returned by lock acquisition."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    owner: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=0)
    expires_at: datetime


class GenerationJobRecord(BaseModel):
    """Persisted generation job shell mirroring the generation_jobs row."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    thread_id: str
    stage: GenerationStage
    resume_stage: Optional[GenerationStage] = None
    web_search_requested: bool = False
    grounding_status: GroundingStatus = GroundingStatus.DISABLED
    cursor: GenerationCursor = Field(default_factory=GenerationCursor)
    counts: GenerationCounts = Field(default_factory=GenerationCounts)
    warnings: list[GenerationWarning] = Field(default_factory=list)
    cancel_requested: bool = False
    lock_owner: Optional[str] = None
    lock_version: int = Field(default=0, ge=0)
    lock_expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
