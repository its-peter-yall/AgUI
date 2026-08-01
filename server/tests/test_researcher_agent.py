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


if __name__ == "__main__":
    unittest.main()
