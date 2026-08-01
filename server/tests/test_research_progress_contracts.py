"""
============================================================================
FILE: test_research_progress_contracts.py
LOCATION: server/tests/test_research_progress_contracts.py
============================================================================
PURPOSE:
    Verifies research artifact and replayable progress-event contracts.
ROLE IN PROJECT:
    Prevents unsupported source relationships and untyped event payloads.
KEY COMPONENTS:
    - ResearchProgressContractTests: Research and event validation tests
DEPENDENCIES:
    - External: pydantic, unittest
    - Internal: server.schemas.progress, server.schemas.research
USAGE:
    python -m unittest server.tests.test_research_progress_contracts -v
============================================================================
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from server.schemas.generation import GenerationStage
from server.schemas.progress import (
    ProgressEvent,
    ProgressEventType,
    StageChangedPayload,
)
from server.schemas.research import (
    ResearchProviderState,
    ResearchProviderStatus,
    ResearchReport,
    ResearchSection,
    ResearchSource,
    ResearchStatus,
)
from server.search.types import SearchErrorClass, SearchProviderId


def _source(source_id: str = "source-1") -> ResearchSource:
    return ResearchSource(
        id=source_id,
        title="Current documentation",
        url="https://example.com/docs",
        publisher="Example",
        published_at=None,
        retrieved_at=datetime.now(timezone.utc),
        provider_id=SearchProviderId.TAVILY,
        snippet="Current documentation summary.",
        excerpt="Current documentation evidence.",
        relevance_score=0.9,
    )


class ResearchProgressContractTests(unittest.TestCase):
    """Tests public and persisted research/progress invariants."""

    def test_section_rejects_duplicate_source_ids(self) -> None:
        with self.assertRaises(ValidationError):
            ResearchSection(
                id="section-1",
                sequence_index=0,
                theme="Current versions",
                markdown="Current evidence.",
                source_ids=["source-1", "source-1"],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

    def test_report_rejects_unknown_section_source(self) -> None:
        section = ResearchSection(
            id="section-1",
            sequence_index=0,
            theme="Current versions",
            markdown="Current evidence.",
            source_ids=["missing-source"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        with self.assertRaises(ValidationError):
            ResearchReport(
                id="report-1",
                session_id="session-1",
                status=ResearchStatus.COMPLETE,
                summary="Research summary.",
                limitations=[],
                freshness_note="Retrieved 2026-08-01.",
                sections=[section],
                sources=[_source()],
                provider_statuses=[],
                warnings=[],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

    def test_provider_status_exposes_only_safe_error_class(self) -> None:
        status = ResearchProviderStatus(
            provider_id=SearchProviderId.EXA,
            state=ResearchProviderState.AUTH_FAILED,
            search_calls=1,
            result_count=0,
            error_class=SearchErrorClass.AUTHENTICATION,
        )
        payload = status.model_dump(mode="json")
        self.assertNotIn("error_body", payload)
        self.assertNotIn("api_key", payload)

    def test_event_type_set_matches_locked_contract(self) -> None:
        self.assertEqual(
            [event.value for event in ProgressEventType],
            [
                "stage_changed",
                "research_section_ready",
                "research_degraded",
                "outline_ready",
                "module_ready",
                "module_failed",
                "generation_paused",
                "generation_cancelled",
                "generation_complete",
            ],
        )

    def test_event_rejects_payload_for_wrong_type(self) -> None:
        with self.assertRaises(ValidationError):
            ProgressEvent(
                id=1,
                session_id="session-1",
                event_type=ProgressEventType.MODULE_READY,
                payload=StageChangedPayload(
                    previous_stage=GenerationStage.INITIALIZING,
                    stage=GenerationStage.RESEARCHING,
                ),
                created_at=datetime.now(timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
