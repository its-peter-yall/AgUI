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
    - Defines Researcher structured plan/iteration/finalization models
KEY COMPONENTS:
    - ResearchStatus, ResearchProviderState: State enums
    - CoverageTheme, CoverageItem, ResearchPlan: Planning contracts
    - ResearchIteration, ResearchFinalization: Loop turn contracts
    - ResearchSource, ResearchSection: Research artifacts
    - ResearchProviderStatus: Safe per-provider telemetry
    - ResearchReport: Aggregate report with referential checks
DEPENDENCIES:
    - External: pydantic
    - Internal: server.schemas.generation, server.search.types
USAGE:
    from server.schemas.research import ResearchReport, ResearchPlan
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


class CoverageTheme(str, Enum):
    FUNDAMENTALS = "fundamentals"
    CURRENT_VERSIONS = "current_versions"
    CONVENTIONS = "conventions"
    METHODOLOGIES = "methodologies"
    PARADIGM_SHIFTS = "paradigm_shifts"
    DEPRECATED_APPROACHES = "deprecated_approaches"
    MIGRATIONS = "migrations"
    DISPUTED_CLAIMS = "disputed_claims"


class CoverageItem(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    theme: CoverageTheme
    required: bool = True
    freshness_sensitive: bool = False
    covered: bool = False
    explicit_unknown: bool = False
    source_ids: list[str] = Field(default_factory=list, max_length=40)

    @field_validator("source_ids")
    @classmethod
    def source_ids_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("CoverageItem source IDs must be unique")
        return values


class ResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    audience: str = Field(min_length=1, max_length=500)
    provisional_concept_count: int = Field(ge=3, le=30)
    coverage: list[CoverageItem] = Field(default_factory=list, max_length=20)
    initial_queries: list[str] = Field(min_length=1, max_length=3)

    @field_validator("initial_queries")
    @classmethod
    def queries_nonempty(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values if item and item.strip()]
        if not cleaned:
            raise ValueError("At least one initial query is required")
        if len(cleaned) > 3:
            raise ValueError("At most three initial queries per turn")
        return cleaned


class ResearchIteration(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    theme: str = Field(min_length=1, max_length=200)
    section_markdown: str = Field(min_length=1, max_length=20_000)
    source_ids: list[str] = Field(default_factory=list, max_length=40)
    conflicts: list[str] = Field(default_factory=list, max_length=20)
    follow_up_queries: list[str] = Field(default_factory=list, max_length=3)
    coverage_updates: list[CoverageItem] = Field(
        default_factory=list,
        max_length=20,
    )

    @field_validator("source_ids")
    @classmethod
    def source_ids_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("ResearchIteration source IDs must be unique")
        return values

    @field_validator("follow_up_queries")
    @classmethod
    def follow_ups_capped(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values if item and item.strip()]
        if len(cleaned) > 3:
            raise ValueError("At most three follow-up queries per turn")
        return cleaned


class ResearchFinalization(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    summary: str = Field(min_length=1, max_length=20_000)
    limitations: list[str] = Field(default_factory=list, max_length=30)
    freshness_note: str = Field(min_length=1, max_length=2000)


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
    """Public research report projection (no canonical URL/content hash)."""

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


# Alias documenting the public API surface (no private brief/canonical fields).
PublicResearchReport = ResearchReport
