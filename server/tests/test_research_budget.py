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
        lite = resolve_research_budget("lite", 3)
        full = resolve_research_budget("full", 30)
        self.assertEqual(lite.max_search_calls, 5)
        self.assertEqual(lite.max_sources, 12)
        self.assertEqual(lite.max_elapsed_seconds, 45)
        self.assertEqual(full.max_search_calls, 14)
        self.assertEqual(full.max_llm_turns, 8)
        self.assertEqual(full.max_sources, 25)
        self.assertEqual(full.max_context_chars, 80_000)

    def test_every_retry_consumes_search_call_budget(self) -> None:
        clock = [100.0]
        ledger = ResearchBudgetLedger(
            resolve_research_budget("lite", 10),
            clock=lambda: clock[0],
        )
        for _ in range(6):
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
        clock[0] += 45.01
        with self.assertRaises(ResearchBudgetExceeded) as raised:
            ledger.check_time()
        self.assertEqual(raised.exception.limit_name, "elapsed_seconds")

    def test_result_byte_source_excerpt_and_context_caps_stop(self) -> None:
        limit_methods = [
            ("reserve_results", 41, "results_examined"),
            ("reserve_provider_bytes", 1_000_001, "provider_bytes"),
            ("reserve_sources", 13, "sources"),
            ("reserve_excerpt_chars", 40_001, "excerpt_chars"),
            ("reserve_context_chars", 40_001, "context_chars"),
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


if __name__ == "__main__":
    unittest.main()
