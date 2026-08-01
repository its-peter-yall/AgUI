"""
============================================================================
FILE: progress.py
LOCATION: server/schemas/progress.py
============================================================================
PURPOSE:
    Closed progress-event type set with secret-safe typed payload contracts.
ROLE IN PROJECT:
    Defines replayable generation progress events for persistence and SSE.
    - Maps each event type to exactly one payload class
    - Forbids unknown fields so credentials and raw provider bodies fail
KEY COMPONENTS:
    - ProgressEventType: The nine locked event values
    - Payload models: Typed per-event payload contracts
    - ProgressEvent: Discriminated event envelope
DEPENDENCIES:
    - External: pydantic
    - Internal: server.schemas.generation
USAGE:
    from server.schemas.progress import ProgressEvent, ProgressEventType
============================================================================
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Type

from pydantic import BaseModel, ConfigDict, Field, model_validator

from server.schemas.generation import (
    GenerationCounts,
    GenerationStage,
    GenerationWarning,
    GroundingStatus,
)


class ProgressEventType(str, Enum):
    STAGE_CHANGED = "stage_changed"
    RESEARCH_SECTION_READY = "research_section_ready"
    RESEARCH_DEGRADED = "research_degraded"
    OUTLINE_READY = "outline_ready"
    MODULE_READY = "module_ready"
    MODULE_FAILED = "module_failed"
    GENERATION_PAUSED = "generation_paused"
    GENERATION_CANCELLED = "generation_cancelled"
    GENERATION_COMPLETE = "generation_complete"


class StageChangedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    previous_stage: GenerationStage
    stage: GenerationStage


class ResearchSectionReadyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    report_id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    sequence_index: int = Field(ge=0)
    source_count: int = Field(ge=0)


class ResearchDegradedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    warning: GenerationWarning


class OutlineReadyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    course_title: str = Field(min_length=1)
    topic_count: int = Field(ge=0)


class ModuleReadyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    node_id: str = Field(min_length=1)
    sequence_index: int = Field(ge=0)


class ModuleFailedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    node_id: str = Field(min_length=1)
    sequence_index: int = Field(ge=0)
    failed_step: str = Field(min_length=1)
    warning: GenerationWarning


class GenerationPausedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    stage: GenerationStage
    warning: GenerationWarning


class GenerationCancelledPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    stage: GenerationStage


class GenerationCompletePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    stage: GenerationStage
    counts: GenerationCounts
    grounding_status: GroundingStatus


PAYLOAD_BY_EVENT_TYPE: dict[ProgressEventType, Type[BaseModel]] = {
    ProgressEventType.STAGE_CHANGED: StageChangedPayload,
    ProgressEventType.RESEARCH_SECTION_READY: ResearchSectionReadyPayload,
    ProgressEventType.RESEARCH_DEGRADED: ResearchDegradedPayload,
    ProgressEventType.OUTLINE_READY: OutlineReadyPayload,
    ProgressEventType.MODULE_READY: ModuleReadyPayload,
    ProgressEventType.MODULE_FAILED: ModuleFailedPayload,
    ProgressEventType.GENERATION_PAUSED: GenerationPausedPayload,
    ProgressEventType.GENERATION_CANCELLED: GenerationCancelledPayload,
    ProgressEventType.GENERATION_COMPLETE: GenerationCompletePayload,
}


class ProgressEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(ge=1)
    session_id: str = Field(min_length=1)
    event_type: ProgressEventType
    payload: BaseModel
    created_at: datetime

    @model_validator(mode="after")
    def payload_matches_event_type(self) -> "ProgressEvent":
        expected = PAYLOAD_BY_EVENT_TYPE[self.event_type]
        if not isinstance(self.payload, expected):
            raise ValueError(
                "Payload type does not match event type "
                f"{self.event_type.value}"
            )
        return self
