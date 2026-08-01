"""
============================================================================
FILE: research.py
LOCATION: server/schemas/research.py
============================================================================
PURPOSE:
    Persisted and public research report, section, source, and provider-state
    contracts for the research phase of course generation.
ROLE IN PROJECT:
    Freezes the research artifact shape consumed by persistence and the API.
    - Enforces referential integrity between sections and sources
    - Exposes only safe error classes, never provider bodies or keys
KEY COMPONENTS:
    - ResearchStatus, ResearchProviderState: State enums
    - ResearchSource, ResearchSection: Research artifacts
    - ResearchProviderStatus: Safe per-provider telemetry
    - ResearchReport: Aggregate report with referential checks
DEPENDENCIES:
    - External: pydantic
    - Internal: server.schemas.generation, server.search.types
USAGE:
    from server.schemas.research import ResearchReport
============================================================================
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from server.schemas.generation import GenerationWarning
from server.search.types import SearchErrorClass, SearchProviderId


class ResearchStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    RESEARCHING = "RESEARCHING"
    COMPLETE = "COMPLETE"
    DEGRADED = "DEGRADED"
    CANCELLED = "CANCELLED"


class ResearchProviderState(str, Enum):
    READY = "READY"
    USED = "USED"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    TIMED_OUT = "TIMED_OUT"
    UNAVAILABLE = "UNAVAILABLE"
    AUTH_FAILED = "AUTH_FAILED"
    INVALID_REQUEST = "INVALID_REQUEST"
    POLICY_REJECTED = "POLICY_REJECTED"


class ResearchSource(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    title: str = Field(min_length=1, max_length=500)
    url: AnyHttpUrl
    publisher: Optional[str] = Field(default=None, max_length=300)
    published_at: Optional[datetime] = None
    retrieved_at: datetime
    provider_id: SearchProviderId
    snippet: str = Field(default="", max_length=2000)
    excerpt: str = Field(default="", max_length=8000)
    relevance_score: Optional[float] = Field(default=None, ge=0, le=1)


class ResearchSection(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    sequence_index: int = Field(ge=0)
    theme: str = Field(min_length=1, max_length=200)
    markdown: str = Field(min_length=1, max_length=20_000)
    source_ids: list[str] = Field(default_factory=list, max_length=40)
    created_at: datetime
    updated_at: datetime

    @field_validator("source_ids")
    @classmethod
    def source_ids_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("ResearchSection source IDs must be unique")
        return values


class ResearchProviderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    provider_id: SearchProviderId
    state: ResearchProviderState
    search_calls: int = Field(ge=0, le=20)
    result_count: int = Field(ge=0, le=120)
    error_class: Optional[SearchErrorClass] = None


class ResearchReport(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    session_id: str
    status: ResearchStatus
    summary: Optional[str] = Field(default=None, max_length=20_000)
    limitations: list[str] = Field(default_factory=list, max_length=30)
    freshness_note: Optional[str] = Field(default=None, max_length=2000)
    sections: list[ResearchSection] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list, max_length=40)
    provider_statuses: list[ResearchProviderStatus] = Field(
        default_factory=list,
        max_length=4,
    )
    warnings: list[GenerationWarning] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def section_sources_exist(self) -> "ResearchReport":
        source_ids = {source.id for source in self.sources}
        referenced = {
            source_id
            for section in self.sections
            for source_id in section.source_ids
        }
        unknown = referenced - source_ids
        if unknown:
            raise ValueError(f"Unknown research source IDs: {sorted(unknown)}")
        return self
