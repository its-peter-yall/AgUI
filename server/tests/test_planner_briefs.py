"""
============================================================================
FILE: test_planner_briefs.py
LOCATION: server/tests/test_planner_briefs.py
============================================================================
PURPOSE:
    Tests TOC-first planning and exact contiguous generation brief batches.
ROLE IN PROJECT:
    Freezes Planner knowledge-transfer behavior for staged graph generation.
KEY COMPONENTS:
    - PlannerBriefTests: Report context, 3/10 batching, and web-off tests
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.agents.planner and generation schemas
USAGE:
    python -m unittest server.tests.test_planner_briefs -v
============================================================================
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from server.agents.planner import PlannerAgent, ResumablePlannerError
from server.schemas.generation import (
    GenerationBrief,
    GenerationBriefBatch,
    GroundingStatus,
)
from server.schemas.learning import CourseOutline, TopicNode
from server.schemas.llm import LLMContext


def _topics(count: int) -> list[TopicNode]:
    return [
        TopicNode(
            index=index,
            title=f"Topic {index}",
            summary_for_context=f"Summary {index}",
            key_terms=["term-a", "term-b"],
            complexity="Basic" if index == 0 else "Intermediate",
            quiz_count=1 if index == 0 else 2,
        )
        for index in range(count)
    ]


def _brief(index: int) -> GenerationBrief:
    return GenerationBrief(
        topic_index=index,
        topic_scope=f"Scope {index}",
        learning_objectives=[f"Objective {index}"],
        prerequisites=[],
        assumed_knowledge=[],
        current_facts=[],
        methodologies=[],
        conventions=[],
        deprecated_approaches=[],
        migration_notes=[],
        caveats=[],
        source_excerpts=None,
        required_examples=["Example"],
        common_misconceptions=["Misconception"],
        failure_modes=["Failure mode"],
        pedagogical_guidance="Explain clearly.",
        expected_depth="full",
        boundaries_with_adjacent_topics="Keep scope atomic.",
        quiz_learning_targets=["Recall target"],
        expected_learner_evidence=["Explain target"],
        grounding_status=GroundingStatus.DISABLED,
    )


class PlannerBriefTests(unittest.IsolatedAsyncioTestCase):
    """Tests separate Planner TOC and brief calls."""

    async def test_outline_receives_completed_report_context(self) -> None:
        agent = PlannerAgent()
        outline = CourseOutline(course_title="Course", topics=_topics(3))
        with patch.object(
            agent,
            "generate",
            new=AsyncMock(return_value=outline),
        ) as generate:
            result = await agent.plan(
                "Current topic",
                research_context="Current fact [source-1].",
                llm_context=LLMContext(
                    api_key="llm-key",
                    model="test/model",
                ),
                mode="lite",
            )
        self.assertEqual(result, outline)
        prompt = generate.await_args.kwargs["user_message"]
        self.assertIn("Current fact [source-1]", prompt)
        self.assertIn("table of contents", prompt.lower())
        self.assertNotIn("generation brief", prompt.lower())

    async def test_preview_and_later_calls_request_exact_indices(self) -> None:
        agent = PlannerAgent()
        outline = CourseOutline(course_title="Course", topics=_topics(15))
        generated = [
            GenerationBriefBatch(
                start_index=0,
                briefs=[_brief(0), _brief(1), _brief(2)],
            ),
            GenerationBriefBatch(
                start_index=3,
                briefs=[_brief(index) for index in range(3, 13)],
            ),
        ]
        with patch.object(
            agent,
            "generate",
            new=AsyncMock(side_effect=generated),
        ) as generate:
            preview = await agent.plan_briefs(
                outline=outline,
                start_index=0,
                batch_size=3,
                research_context=None,
                grounding_status=GroundingStatus.DISABLED,
                llm_context=LLMContext(
                    api_key="llm-key",
                    model="test/model",
                ),
                mode="full",
            )
            later = await agent.plan_briefs(
                outline=outline,
                start_index=3,
                batch_size=10,
                research_context=None,
                grounding_status=GroundingStatus.DISABLED,
                llm_context=LLMContext(
                    api_key="llm-key",
                    model="test/model",
                ),
                mode="full",
            )
        self.assertEqual([item.topic_index for item in preview.briefs], [0, 1, 2])
        self.assertEqual(
            [item.topic_index for item in later.briefs],
            list(range(3, 13)),
        )
        self.assertIn("0, 1, 2", generate.await_args_list[0].kwargs["user_message"])
        self.assertIn(
            "3, 4, 5, 6, 7, 8, 9, 10, 11, 12",
            generate.await_args_list[1].kwargs["user_message"],
        )

    async def test_web_off_briefs_reject_research_fields(self) -> None:
        agent = PlannerAgent()
        outline = CourseOutline(course_title="Course", topics=_topics(3))
        invalid = GenerationBrief.model_construct(
            topic_index=0,
            topic_title="Topic 0",
            learning_objectives=["Obj 1"],
            key_concepts=["Concept 1"],
            quiz_learning_targets=["Target 1"],
            common_misconceptions=["Misconception 1"],
            expected_learner_evidence=["Evidence 1"],
            grounding_status=GroundingStatus.DISABLED,
            research_report_id="report-1",
            source_excerpts=None,
        )
        with patch.object(
            agent,
            "generate",
            new=AsyncMock(
                return_value=GenerationBriefBatch.model_construct(
                    start_index=0,
                    briefs=[invalid],
                )
            ),
        ):
            with self.assertRaises(ResumablePlannerError):
                await agent.plan_briefs(
                    outline=outline,
                    start_index=0,
                    batch_size=1,
                    research_context=None,
                    grounding_status=GroundingStatus.DISABLED,
                    llm_context=LLMContext(
                        api_key="llm-key",
                        model="test/model",
                    ),
                    mode="lite",
                )


if __name__ == "__main__":
    unittest.main()
