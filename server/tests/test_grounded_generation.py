"""
============================================================================
FILE: test_grounded_generation.py
LOCATION: server/tests/test_grounded_generation.py
============================================================================
PURPOSE:
    Tests brief-scoped content, citations, quiz targets, and partial failures.
ROLE IN PROJECT:
    Prevents whole-report prompts and fabricated source links in course cards.
KEY COMPONENTS:
    - GroundedGenerationTests: Generator, citation, and Quizzer contracts
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server agents, citation validation, generation schemas
USAGE:
    python -m unittest server.tests.test_grounded_generation -v
============================================================================
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from server.agents.generator import GeneratedContent, GeneratorAgent
from server.agents.quizzer import QuizzerAgent
from server.schemas.generation import (
    BriefSourceExcerpt,
    GenerationBrief,
    GroundingStatus,
    SourceCitation,
)
from server.schemas.learning import TopicNode
from server.schemas.llm import LLMContext
from server.services.citation_validation import sanitize_grounded_content


def _topic() -> TopicNode:
    return TopicNode(
        index=0,
        title="Current Packaging",
        summary_for_context="Current standards-based packaging.",
        key_terms=["pyproject.toml", "build backend"],
        complexity="Intermediate",
        quiz_count=2,
    )


def _brief() -> GenerationBrief:
    return GenerationBrief(
        topic_index=0,
        topic_scope="Current Python build configuration.",
        learning_objectives=["Explain current build metadata."],
        prerequisites=["Python modules."],
        assumed_knowledge=["Virtual environments."],
        current_facts=["PEP 517 build isolation is current."],
        methodologies=["Use a standards-based frontend."],
        conventions=["Use pyproject.toml."],
        deprecated_approaches=["Direct setup.py invocation."],
        migration_notes=["Move metadata incrementally."],
        caveats=["Backend options vary."],
        research_report_id="report-1",
        source_excerpts=[
            BriefSourceExcerpt(
                source_id="source-1",
                excerpt="Use pyproject.toml for build configuration.",
            )
        ],
        required_examples=["Run python -m build."],
        common_misconceptions=["pip is a build backend."],
        failure_modes=["Missing build requirements."],
        pedagogical_guidance="Contrast frontend and backend roles.",
        expected_depth="full",
        boundaries_with_adjacent_topics="Do not cover lock files.",
        quiz_learning_targets=["Identify current build configuration."],
        expected_learner_evidence=["Reject direct setup.py invocation."],
        grounding_status=GroundingStatus.GROUNDED,
    )


class GroundedGenerationTests(unittest.IsolatedAsyncioTestCase):
    """Tests grounded Generator and Quizzer behavior."""

    async def test_generator_prompt_contains_only_brief_approved_source(self) -> None:
        agent = GeneratorAgent()
        content = GeneratedContent(
            content_markdown="# Current Packaging\n" + "Evidence. " * 50,
            key_takeaways=["One", "Two", "Three"],
            citations=[
                SourceCitation(source_id="source-1", claim="Current standard.")
            ],
        )
        with patch.object(
            agent,
            "generate",
            new=AsyncMock(return_value=content),
        ) as generate:
            result = await agent.generate_explanation(
                topic=_topic(),
                brief=_brief(),
                prev_summary=None,
                next_summary="Next topic.",
                llm_context=LLMContext(
                    api_key="llm-key",
                    model="test/model",
                ),
            )
        prompt = generate.await_args.kwargs["user_message"]
        self.assertIn("source-1", prompt)
        self.assertIn("Use pyproject.toml", prompt)
        self.assertNotIn("entire research report", prompt.lower())
        self.assertEqual(result.citations[0].source_id, "source-1")

    async def test_unsupported_citation_gets_one_correction_then_is_removed(
        self,
    ) -> None:
        agent = GeneratorAgent()
        invalid = GeneratedContent(
            content_markdown=(
                "# Current Packaging\n"
                "See [fabricated](https://fabricated.invalid). "
                + "Evidence. " * 40
            ),
            key_takeaways=["One", "Two", "Three"],
            citations=[
                SourceCitation(source_id="fake-source", claim="Fabricated.")
            ],
        )
        with patch.object(
            agent,
            "generate",
            new=AsyncMock(side_effect=[invalid, invalid]),
        ) as generate:
            result = await agent.generate_explanation(
                topic=_topic(),
                brief=_brief(),
                llm_context=LLMContext(
                    api_key="llm-key",
                    model="test/model",
                ),
            )
        self.assertEqual(generate.await_count, 2)
        self.assertEqual(result.citations, [])
        self.assertNotIn("fabricated.invalid", result.content_markdown)
        self.assertIn("removed_unsupported_citations", result.warnings)

    async def test_quizzer_context_contains_brief_targets(self) -> None:
        agent = QuizzerAgent()
        with patch.object(agent, "generate", new=AsyncMock()) as generate:
            generate.side_effect = RuntimeError("stop after prompt capture")
            with self.assertRaises(RuntimeError):
                await agent.generate_quiz_set(
                    topic=_topic(),
                    content="# Content\n" + "Current facts. " * 30,
                    quiz_count=2,
                    brief=_brief(),
                    llm_context=LLMContext(
                        api_key="llm-key",
                        model="test/model",
                    ),
                )
        message = generate.await_args.kwargs["user_message"]
        self.assertIn("Identify current build configuration", message)
        self.assertIn("Reject direct setup.py invocation", message)

    def test_sanitizer_keeps_only_approved_source_ids_and_no_urls(self) -> None:
        cleaned, citations, warnings = sanitize_grounded_content(
            markdown="Use [guide](https://fake.invalid) and current evidence.",
            citations=[
                SourceCitation(source_id="source-1", claim="Current evidence."),
                SourceCitation(source_id="source-2", claim="Unsupported."),
            ],
            approved_source_ids={"source-1"},
        )
        self.assertNotIn("https://fake.invalid", cleaned)
        self.assertEqual([item.source_id for item in citations], ["source-1"])
        self.assertEqual(warnings, ["removed_unsupported_citations"])


if __name__ == "__main__":
    unittest.main()
