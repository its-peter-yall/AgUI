"""
============================================================================
FILE: test_research_budget.py
LOCATION: server/tests/test_research_budget.py
============================================================================
PURPOSE:
    Tests adaptive research sizing and every hard termination counter.
ROLE IN PROJECT:
    Ensures iterative research cannot exceed time, calls, results, bytes, or context.
KEY COMPONENTS:
    - ResearchBudgetTests: Sizing and ledger exhaustion tests
DEPENDENCIES:
    - External: unittest
    - Internal: server.search.budget
USAGE:
    python -m unittest server.tests.test_research_budget -v
============================================================================
"""

from __future__ import annotations

import unittest

from server.search.budget import (
    ResearchBudgetExceeded,
    ResearchBudgetLedger,
    resolve_research_budget,
)


class ResearchBudgetTests(unittest.TestCase):
    """Tests adaptive budgets and hard limits."""

    def test_budget_scales_by_mode_and_concept_count(self) -> None:
        lite_small = resolve_research_budget("lite", 3)
        lite_large = resolve_research_budget("lite", 30)
        full_small = resolve_research_budget("full", 3)
        full_large = resolve_research_budget("full", 30)

        self.assertEqual(lite_small.max_search_calls, 5)
        self.assertEqual(lite_large.max_search_calls, 8)
        self.assertEqual(lite_small.max_llm_turns, 6)
        self.assertEqual(lite_small.max_elapsed_seconds, 90.0)
        self.assertEqual(lite_small.max_results_examined, 60)
        self.assertEqual(lite_small.max_sources, 18)
        self.assertEqual(lite_small.max_provider_bytes, 2_000_000)
        self.assertEqual(lite_small.max_excerpt_chars, 60_000)
        self.assertEqual(lite_small.max_context_chars, 60_000)
        self.assertEqual(lite_small.max_content_chars_per_hit, 6_000)

        self.assertEqual(full_small.max_search_calls, 8)
        self.assertEqual(full_large.max_search_calls, 18)
        self.assertEqual(full_large.max_llm_turns, 10)
        self.assertEqual(full_large.max_elapsed_seconds, 180.0)
        self.assertEqual(full_large.max_results_examined, 120)
        self.assertEqual(full_large.max_sources, 40)
        self.assertEqual(full_large.max_provider_bytes, 5_000_000)
        self.assertEqual(full_large.max_excerpt_chars, 100_000)
        self.assertEqual(full_large.max_context_chars, 100_000)
        self.assertEqual(full_large.max_content_chars_per_hit, 8_000)

    def test_every_retry_consumes_search_call_budget(self) -> None:
        clock = [100.0]
        ledger = ResearchBudgetLedger(
            resolve_research_budget("lite", 10),
            clock=lambda: clock[0],
        )
        for _ in range(8):
            ledger.reserve_search_call()
        with self.assertRaises(ResearchBudgetExceeded) as raised:
            ledger.reserve_search_call()
        self.assertEqual(raised.exception.limit_name, "search_calls")

    def test_wall_time_is_hard_stop(self) -> None:
        clock = [100.0]
        ledger = ResearchBudgetLedger(
            resolve_research_budget("lite", 3),
            clock=lambda: clock[0],
        )
        clock[0] += 90.01
        with self.assertRaises(ResearchBudgetExceeded) as raised:
            ledger.check_time()
        self.assertEqual(raised.exception.limit_name, "elapsed_seconds")

    def test_result_byte_source_excerpt_and_context_caps_stop(self) -> None:
        limit_methods = [
            ("reserve_results", 61, "results_examined"),
            ("reserve_provider_bytes", 2_000_001, "provider_bytes"),
            ("reserve_sources", 19, "sources"),
            ("reserve_excerpt_chars", 60_001, "excerpt_chars"),
            ("reserve_context_chars", 60_001, "context_chars"),
        ]
        for method_name, amount, expected in limit_methods:
            with self.subTest(method_name=method_name):
                ledger = ResearchBudgetLedger(
                    resolve_research_budget("lite", 3),
                    clock=lambda: 100.0,
                )
                with self.assertRaises(ResearchBudgetExceeded) as raised:
                    getattr(ledger, method_name)(amount)
                self.assertEqual(raised.exception.limit_name, expected)

    def test_finalization_turn_bypasses_llm_and_elapsed_limits(self) -> None:
        clock = [100.0]
        ledger = ResearchBudgetLedger(
            resolve_research_budget("lite", 3),
            clock=lambda: clock[0],
        )
        for _ in range(6):
            ledger.reserve_llm_turn()
        clock[0] += 95.0

        with self.assertRaises(ResearchBudgetExceeded):
            ledger.reserve_llm_turn()

        ledger.reserve_finalization_turn()
        usage = ledger.usage_snapshot()
        self.assertEqual(usage.llm_turns, 6)
        self.assertEqual(usage.finalization_turns, 1)

        with self.assertRaises(ResearchBudgetExceeded) as raised:
            ledger.reserve_finalization_turn()
        self.assertEqual(raised.exception.limit_name, "finalization_turns")

    def test_remaining_snapshot_reports_headroom(self) -> None:
        clock = [100.0]
        budget = resolve_research_budget("lite", 3)
        ledger = ResearchBudgetLedger(budget, clock=lambda: clock[0])
        ledger.reserve_search_call()
        ledger.reserve_llm_turn()
        ledger.reserve_sources(2)
        ledger.reserve_results(5)
        clock[0] += 10.0
        snap = ledger.remaining_snapshot()
        self.assertEqual(snap["search_calls"], budget.max_search_calls - 1)
        self.assertEqual(snap["llm_turns"], budget.max_llm_turns - 1)
        self.assertEqual(snap["sources"], budget.max_sources - 2)
        self.assertEqual(
            snap["results_examined"], budget.max_results_examined - 5
        )
        self.assertAlmostEqual(
            snap["elapsed_seconds"],
            budget.max_elapsed_seconds - 10.0,
            places=1,
        )
        self.assertEqual(snap["finalization_turns"], 1)
        self.assertEqual(
            snap["mode_caps"]["max_llm_turns"], budget.max_llm_turns
        )


if __name__ == "__main__":
    unittest.main()
