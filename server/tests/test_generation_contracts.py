"""
============================================================================
FILE: test_generation_contracts.py
LOCATION: server/tests/test_generation_contracts.py
============================================================================
PURPOSE:
    Freezes durable generation stages, cursors, briefs, batches, and citations.
ROLE IN PROJECT:
    Protects contracts shared by persistence, LangGraph, API, and client phases.
KEY COMPONENTS:
    - GenerationContractTests: Validation and serialization contract tests
DEPENDENCIES:
    - External: pydantic, unittest
    - Internal: server.schemas.generation
USAGE:
    python -m unittest server.tests.test_generation_contracts -v
============================================================================
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from server.schemas.generation import (
    BriefSourceExcerpt,
    GenerationBrief,
    GenerationBriefBatch,
    GenerationCursor,
    GenerationStage,
    GroundingStatus,
    ResearchCursor,
)


def _brief(topic_index: int) -> GenerationBrief:
    return GenerationBrief(
        topic_index=topic_index,
        topic_scope=f"Scope {topic_index}",
        learning_objectives=[f"Explain objective {topic_index}."],
        prerequisites=["Prior topic knowledge."],
        assumed_knowledge=["Basic terminology."],
        current_facts=["Current fact."],
        methodologies=["Current method."],
        conventions=["Current convention."],
        deprecated_approaches=["Deprecated method."],
        migration_notes=["Migration note."],
        caveats=["Important caveat."],
        source_excerpts=None,
        required_examples=["Worked example."],
        common_misconceptions=["Common misconception."],
        failure_modes=["Common failure."],
        pedagogical_guidance="Build from intuition to formal detail.",
        expected_depth="lite",
        boundaries_with_adjacent_topics="Do not duplicate adjacent topics.",
        quiz_learning_targets=["Identify correct application."],
        expected_learner_evidence=["Explain reasoning in one sentence."],
        grounding_status=GroundingStatus.DISABLED,
    )


class GenerationContractTests(unittest.TestCase):
    """Tests generation contract invariants."""

    def test_stage_values_match_locked_workflow(self) -> None:
        self.assertEqual(
            [stage.value for stage in GenerationStage],
            [
                "INITIALIZING",
                "RESEARCHING",
                "OUTLINING",
                "PLANNING_PREVIEW",
                "GENERATING_PREVIEW",
                "PLANNING_BATCH",
                "GENERATING_BATCH",
                "PAUSED",
                "CANCELLED",
                "COMPLETE",
                "COMPLETE_DEGRADED",
                "FAILED",
            ],
        )

    def test_cursor_caps_active_batch_at_ten(self) -> None:
        with self.assertRaises(ValidationError):
            GenerationCursor(
                next_topic_index=3,
                active_batch_start=3,
                active_batch_size=11,
                batch_number=1,
                research=ResearchCursor(),
            )

    def test_disabled_brief_has_no_research_fields_when_dumped(self) -> None:
        payload = _brief(0).model_dump(exclude_none=True)
        self.assertNotIn("source_excerpts", payload)
        self.assertNotIn("research_report_id", payload)

    def test_grounded_brief_requires_approved_source_excerpt(self) -> None:
        data = _brief(0).model_dump()
        data["grounding_status"] = GroundingStatus.GROUNDED
        with self.assertRaises(ValidationError):
            GenerationBrief.model_validate(data)

        data["source_excerpts"] = [
            BriefSourceExcerpt(
                source_id="source-1",
                excerpt="Current supported evidence.",
            ).model_dump()
        ]
        brief = GenerationBrief.model_validate(data)
        self.assertEqual(brief.approved_source_ids, ["source-1"])

    def test_brief_rejects_duplicate_source_ids(self) -> None:
        data = _brief(0).model_dump()
        data["grounding_status"] = GroundingStatus.GROUNDED
        evidence = {
            "source_id": "source-1",
            "excerpt": "Current supported evidence.",
        }
        data["source_excerpts"] = [evidence, evidence]
        with self.assertRaises(ValidationError):
            GenerationBrief.model_validate(data)

    def test_brief_batch_requires_contiguous_expected_indices(self) -> None:
        with self.assertRaises(ValidationError):
            GenerationBriefBatch(
                start_index=0,
                briefs=[_brief(0), _brief(2)],
            )
        batch = GenerationBriefBatch(
            start_index=0,
            briefs=[_brief(0), _brief(1), _brief(2)],
        )
        self.assertEqual(batch.end_index_exclusive, 3)


if __name__ == "__main__":
    unittest.main()
