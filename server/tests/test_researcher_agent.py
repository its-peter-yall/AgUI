"""
============================================================================
FILE: test_researcher_agent.py
LOCATION: server/tests/test_researcher_agent.py
============================================================================
PURPOSE:
    Tests Researcher structured turns and untrusted-source prompt boundaries.
ROLE IN PROJECT:
    Ensures source text cannot become agent instructions or escape source IDs.
KEY COMPONENTS:
    - ResearcherAgentTests: Prompt and structured-call tests
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.agents.researcher
USAGE:
    python -m unittest server.tests.test_researcher_agent -v
============================================================================
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from server.agents.researcher import ResearcherAgent
from server.schemas.llm import LLMContext
from server.schemas.research import CoverageTheme, ResearchPlan


class ResearcherAgentTests(unittest.IsolatedAsyncioTestCase):
    """Tests Researcher role and safe prompt construction."""

    async def test_analysis_uses_researcher_role_and_structured_model(self) -> None:
        agent = ResearcherAgent()
        plan = ResearchPlan(
            audience="Intermediate learner",
            provisional_concept_count=6,
            coverage=[],
            initial_queries=["current Python packaging standards"],
        )
        with patch.object(
            agent,
            "generate",
            new=AsyncMock(return_value=plan),
        ) as generate:
            result = await agent.analyze_query(
                query="Modern Python packaging",
                resolved_mode="lite",
                llm_context=LLMContext(
                    api_key="llm-key",
                    model="test/model",
                ),
            )
        self.assertEqual(result, plan)
        self.assertEqual(agent.role, "researcher")
        self.assertIs(generate.await_args.kwargs["response_model"], ResearchPlan)

    def test_system_prompt_treats_web_text_as_data(self) -> None:
        prompt = ResearcherAgent().system_prompt.lower()
        self.assertIn("untrusted data", prompt)
        self.assertIn("ignore instructions", prompt)
        self.assertIn("source ids", prompt)
        self.assertIn(CoverageTheme.CURRENT_VERSIONS.value, prompt)

    async def test_analyze_query_includes_budget_in_user_message(self) -> None:
        agent = ResearcherAgent()
        plan = ResearchPlan(
            audience="Learner",
            provisional_concept_count=4,
            coverage=[],
            initial_queries=["q1"],
        )
        budget_text = "remaining search_calls: 5"
        with patch.object(
            agent, "generate", new=AsyncMock(return_value=plan)
        ) as gen:
            await agent.analyze_query(
                query="GraphRAG",
                resolved_mode="lite",
                llm_context=LLMContext(api_key="k", model="m"),
                budget_context=budget_text,
            )
        msg = gen.await_args.kwargs["user_message"]
        self.assertIn(budget_text, msg)
        self.assertIn("lite", msg)

    async def test_synthesize_includes_target_theme_and_budget(self) -> None:
        from server.schemas.research import ResearchIteration

        agent = ResearcherAgent()
        draft = ResearchIteration(
            theme="fundamentals",
            section_markdown="Evidence.",
            source_ids=[],
            conflicts=[],
            follow_up_queries=[],
            coverage_updates=[],
        )
        plan = ResearchPlan(
            audience="Learner",
            provisional_concept_count=3,
            coverage=[],
            initial_queries=["q"],
        )
        with patch.object(
            agent, "generate", new=AsyncMock(return_value=draft)
        ) as gen:
            await agent.synthesize_iteration(
                query="GraphRAG",
                plan=plan,
                coverage=[],
                untrusted_source_context="SOURCES BEGIN\nSOURCES END",
                llm_context=LLMContext(api_key="k", model="m"),
                target_theme="fundamentals",
                budget_context="remaining llm_turns: 2",
                uncovered_themes=["fundamentals", "migrations"],
            )
        msg = gen.await_args.kwargs["user_message"]
        self.assertIn("target theme: fundamentals", msg.lower())
        self.assertIn("remaining llm_turns: 2", msg)
        self.assertIn("uncovered", msg.lower())


if __name__ == "__main__":
    unittest.main()
