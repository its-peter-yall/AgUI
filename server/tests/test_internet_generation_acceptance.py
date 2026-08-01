"""
============================================================================
FILE: test_internet_generation_acceptance.py
LOCATION: server/tests/test_internet_generation_acceptance.py
============================================================================
PURPOSE:
    Verifies complete staged generation outcomes with deterministic external
    services and real graph, persistence, runtime, and public projections.
ROLE IN PROJECT:
    Provides release-level acceptance coverage across Phases 1-5.
KEY COMPONENTS:
    - InternetGenerationAcceptanceTests: Main scenario matrix
DEPENDENCIES:
    - External: unittest
    - Internal: server.tests.generation_acceptance_harness
USAGE:
    python -m unittest server.tests.test_internet_generation_acceptance -v
============================================================================
"""

from __future__ import annotations

import unittest

from server.tests.generation_acceptance_harness import (
    AcceptanceScenario,
    GenerationAcceptanceHarness,
)


class InternetGenerationAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    """Tests durable generation as one composed system."""

    async def asyncSetUp(self) -> None:
        self.harness = await GenerationAcceptanceHarness.create()

    async def asyncTearDown(self) -> None:
        await self.harness.close()

    async def test_web_off_uses_exact_preview_and_later_batches(self) -> None:
        result = await self.harness.run(
            AcceptanceScenario(topic_count=30, web_search=False)
        )

        self.assertEqual(result.terminal_stage, "COMPLETE")
        self.assertEqual(result.research_calls, 0)
        self.assertEqual(
            result.batch_windows,
            [(0, 3), (3, 10), (13, 10), (23, 7)],
        )
        self.assertEqual(result.ready_indices, list(range(30)))
        self.assertEqual(result.error_indices, [])
        self.assertLess(
            result.stage_events.index("OUTLINING"),
            result.stage_events.index("PLANNING_PREVIEW"),
        )
        self.assertNotIn("RESEARCHING", result.stage_events)

    async def test_grounded_research_precedes_outline_and_citations_validate(
        self,
    ) -> None:
        result = await self.harness.run(
            AcceptanceScenario(topic_count=4, web_search=True)
        )

        self.assertEqual(result.terminal_stage, "COMPLETE")
        self.assertEqual(result.grounding_status, "GROUNDED")
        self.assertGreaterEqual(result.research_section_count, 1)
        self.assertGreaterEqual(result.source_count, 1)
        self.assertLess(
            result.event_types.index("research_section_ready"),
            result.event_types.index("outline_ready"),
        )
        self.assertEqual(
            set(result.public_citation_source_ids),
            set(result.persisted_source_ids)
            & set(result.public_citation_source_ids),
        )
        self.assertTrue(
            set(result.public_citation_source_ids).issubset(
                set(result.persisted_source_ids)
            )
        )
        self.assertNotIn("generation_briefs", result.public_session_json)
        self.assertNotIn("source_excerpts", result.public_session_json)
        self.assertNotIn("https://fabricated.example", result.public_session_json)

    async def test_provider_exhaustion_completes_degraded_without_false_label(
        self,
    ) -> None:
        result = await self.harness.run(
            AcceptanceScenario(
                topic_count=5,
                web_search=True,
                exhaust_providers=True,
            )
        )

        self.assertEqual(result.terminal_stage, "COMPLETE_DEGRADED")
        self.assertEqual(result.grounding_status, "DEGRADED")
        self.assertEqual(result.ready_indices, [0, 1, 2, 3, 4])
        self.assertIn("research_degraded", result.event_types)
        self.assertTrue(result.public_warnings)
        self.assertEqual(result.public_citation_source_ids, [])
        self.assertNotIn('"grounding_status":"GROUNDED"', result.public_session_json)

    async def test_one_topic_failure_does_not_block_siblings_or_next_batch(
        self,
    ) -> None:
        result = await self.harness.run(
            AcceptanceScenario(
                topic_count=14,
                web_search=False,
                fail_generator_indices=frozenset({1}),
                fail_quizzer_indices=frozenset({5}),
            )
        )

        self.assertEqual(result.terminal_stage, "COMPLETE")
        self.assertEqual(result.batch_windows, [(0, 3), (3, 10), (13, 1)])
        self.assertEqual(result.error_indices, [1, 5])
        self.assertEqual(
            result.ready_indices,
            [0, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13],
        )
        self.assertEqual(result.event_types.count("module_failed"), 2)
        self.assertEqual(result.event_types[-1], "generation_complete")


if __name__ == "__main__":
    unittest.main()
