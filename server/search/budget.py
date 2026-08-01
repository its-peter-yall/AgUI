"""
============================================================================
FILE: budget.py
LOCATION: server/search/budget.py
============================================================================
PURPOSE:
    Adaptive research hard limits and durable counter ledger.
ROLE IN PROJECT:
    Guarantees iterative research always terminates within mode budgets.
    - Sizes search/LLM/source caps from mode and concept count
    - Reserves counters before side effects; never silent overflow
KEY COMPONENTS:
    - ResearchBudget / ResearchBudgetUsage: Immutable limit and usage
    - ResearchBudgetLedger: Mutable ledger with hard stops
    - resolve_research_budget: Adaptive sizing formula
    - ResearchBudgetExceeded: Deterministic limit exception
DEPENDENCIES:
    - External: None
    - Internal: server.schemas.generation.ResearchCursor
USAGE:
    budget = resolve_research_budget("lite", 6)
    ledger = ResearchBudgetLedger(budget)
============================================================================
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Literal, Optional

from server.schemas.generation import ResearchCursor

ResearchMode = Literal["lite", "full"]

Clock = Callable[[], float]


class ResearchBudgetExceeded(RuntimeError):
    """Raised when a hard research budget counter would be exceeded."""

    def __init__(self, limit_name: str) -> None:
        self.limit_name = limit_name
        super().__init__(f"Research budget exceeded: {limit_name}")


@dataclass(frozen=True)
class ResearchBudget:
    """Immutable hard limits for one research run."""

    mode: ResearchMode
    provisional_concept_count: int
    max_search_calls: int
    max_llm_turns: int
    max_elapsed_seconds: float
    max_results_examined: int
    max_sources: int
    max_provider_bytes: int
    max_excerpt_chars: int
    max_context_chars: int
    max_content_chars_per_hit: int


@dataclass(frozen=True)
class ResearchBudgetUsage:
    """Immutable snapshot of consumed counters."""

    search_calls: int = 0
    llm_turns: int = 0
    results_examined: int = 0
    sources: int = 0
    provider_bytes: int = 0
    excerpt_chars: int = 0
    context_chars: int = 0
    started_at: float = 0.0


# Absolute validation ceilings (defensive clamps)
_ABS_MAX = {
    "max_search_calls": 20,
    "max_llm_turns": 10,
    "max_elapsed_seconds": 180,
    "max_results_examined": 120,
    "max_sources": 40,
    "max_provider_bytes": 5_000_000,
    "max_excerpt_chars": 100_000,
    "max_context_chars": 100_000,
    "max_content_chars_per_hit": 8_000,
}


def resolve_research_budget(
    mode: str,
    provisional_concept_count: int,
) -> ResearchBudget:
    """Compute adaptive hard limits for a research mode and concept count.

    Args:
        mode: "lite" or "full".
        provisional_concept_count: Planned concept count (clamped 3-30).

    Returns:
        Immutable ResearchBudget.
    """
    normalized_mode: ResearchMode
    if mode == "full":
        normalized_mode = "full"
    else:
        normalized_mode = "lite"

    concepts = max(3, min(30, int(provisional_concept_count)))
    base_calls = 3 + math.ceil(concepts / 2)
    if normalized_mode == "lite":
        max_search_calls = min(6, max(4, base_calls))
        max_llm_turns = 4
        max_elapsed_seconds = 45.0
        max_results_examined = 40
        max_sources = 12
        max_provider_bytes = 1_000_000
        max_excerpt_chars = 40_000
        max_context_chars = 40_000
        max_content_chars_per_hit = 4_000
    else:
        max_search_calls = min(14, max(6, base_calls))
        max_llm_turns = 8
        max_elapsed_seconds = 120.0
        max_results_examined = 100
        max_sources = 25
        max_provider_bytes = 3_000_000
        max_excerpt_chars = 80_000
        max_context_chars = 80_000
        max_content_chars_per_hit = 8_000

    return ResearchBudget(
        mode=normalized_mode,
        provisional_concept_count=concepts,
        max_search_calls=min(
            max_search_calls, _ABS_MAX["max_search_calls"]
        ),
        max_llm_turns=min(max_llm_turns, _ABS_MAX["max_llm_turns"]),
        max_elapsed_seconds=min(
            max_elapsed_seconds, _ABS_MAX["max_elapsed_seconds"]
        ),
        max_results_examined=min(
            max_results_examined, _ABS_MAX["max_results_examined"]
        ),
        max_sources=min(max_sources, _ABS_MAX["max_sources"]),
        max_provider_bytes=min(
            max_provider_bytes, _ABS_MAX["max_provider_bytes"]
        ),
        max_excerpt_chars=min(
            max_excerpt_chars, _ABS_MAX["max_excerpt_chars"]
        ),
        max_context_chars=min(
            max_context_chars, _ABS_MAX["max_context_chars"]
        ),
        max_content_chars_per_hit=min(
            max_content_chars_per_hit,
            _ABS_MAX["max_content_chars_per_hit"],
        ),
    )


class ResearchBudgetLedger:
    """Mutable hard-stop ledger for one research job."""

    def __init__(
        self,
        budget: ResearchBudget,
        *,
        clock: Optional[Clock] = None,
        usage: Optional[ResearchBudgetUsage] = None,
    ) -> None:
        self.budget = budget
        self._clock = clock or time.monotonic
        started = usage.started_at if usage is not None else self._clock()
        self._search_calls = usage.search_calls if usage else 0
        self._llm_turns = usage.llm_turns if usage else 0
        self._results_examined = usage.results_examined if usage else 0
        self._sources = usage.sources if usage else 0
        self._provider_bytes = usage.provider_bytes if usage else 0
        self._excerpt_chars = usage.excerpt_chars if usage else 0
        self._context_chars = usage.context_chars if usage else 0
        self._started_at = started

    def check_time(self) -> None:
        """Raise if wall-clock elapsed budget is exhausted."""
        if self._elapsed() > self.budget.max_elapsed_seconds:
            raise ResearchBudgetExceeded("elapsed_seconds")

    def remaining_seconds(self) -> float:
        """Seconds remaining before hard wall-clock stop (floor at 0)."""
        remaining = self.budget.max_elapsed_seconds - self._elapsed()
        return max(0.0, remaining)

    def reserve_search_call(self, amount: int = 1) -> None:
        self._reserve(
            "search_calls",
            current=self._search_calls,
            amount=amount,
            limit=self.budget.max_search_calls,
            setter=lambda value: setattr(self, "_search_calls", value),
        )

    def reserve_llm_turn(self, amount: int = 1) -> None:
        self._reserve(
            "llm_turns",
            current=self._llm_turns,
            amount=amount,
            limit=self.budget.max_llm_turns,
            setter=lambda value: setattr(self, "_llm_turns", value),
        )

    def reserve_results(self, amount: int) -> None:
        self._reserve(
            "results_examined",
            current=self._results_examined,
            amount=amount,
            limit=self.budget.max_results_examined,
            setter=lambda value: setattr(self, "_results_examined", value),
        )

    def reserve_sources(self, amount: int) -> None:
        self._reserve(
            "sources",
            current=self._sources,
            amount=amount,
            limit=self.budget.max_sources,
            setter=lambda value: setattr(self, "_sources", value),
        )

    def reserve_provider_bytes(self, amount: int) -> None:
        self._reserve(
            "provider_bytes",
            current=self._provider_bytes,
            amount=amount,
            limit=self.budget.max_provider_bytes,
            setter=lambda value: setattr(self, "_provider_bytes", value),
        )

    def reserve_excerpt_chars(self, amount: int) -> None:
        self._reserve(
            "excerpt_chars",
            current=self._excerpt_chars,
            amount=amount,
            limit=self.budget.max_excerpt_chars,
            setter=lambda value: setattr(self, "_excerpt_chars", value),
        )

    def reserve_context_chars(self, amount: int) -> None:
        self._reserve(
            "context_chars",
            current=self._context_chars,
            amount=amount,
            limit=self.budget.max_context_chars,
            setter=lambda value: setattr(self, "_context_chars", value),
        )

    def usage_snapshot(self) -> ResearchBudgetUsage:
        """Return immutable usage snapshot."""
        return ResearchBudgetUsage(
            search_calls=self._search_calls,
            llm_turns=self._llm_turns,
            results_examined=self._results_examined,
            sources=self._sources,
            provider_bytes=self._provider_bytes,
            excerpt_chars=self._excerpt_chars,
            context_chars=self._context_chars,
            started_at=self._started_at,
        )

    def to_cursor(
        self,
        *,
        iteration: int = 0,
        next_section_index: int = 0,
        pending_queries: Optional[list[str]] = None,
        completed_themes: Optional[list[str]] = None,
    ) -> ResearchCursor:
        """Map durable counters into Phase 1 ResearchCursor fields."""
        return ResearchCursor(
            iteration=iteration,
            next_section_index=next_section_index,
            pending_queries=list(pending_queries or []),
            completed_themes=list(completed_themes or []),
            search_calls=self._search_calls,
            llm_turns=self._llm_turns,
            results_examined=self._results_examined,
            provider_bytes=self._provider_bytes,
            excerpt_chars=self._excerpt_chars,
        )

    @classmethod
    def from_cursor(
        cls,
        budget: ResearchBudget,
        cursor: ResearchCursor,
        *,
        clock: Optional[Clock] = None,
        sources: int = 0,
        context_chars: int = 0,
        started_at: Optional[float] = None,
    ) -> "ResearchBudgetLedger":
        """Restore ledger counters from a persisted ResearchCursor.

        sources/context_chars are not on ResearchCursor; pass explicitly
        when resuming so consumed limits cannot reset.
        """
        active_clock = clock or time.monotonic
        usage = ResearchBudgetUsage(
            search_calls=cursor.search_calls,
            llm_turns=cursor.llm_turns,
            results_examined=cursor.results_examined,
            sources=sources,
            provider_bytes=cursor.provider_bytes,
            excerpt_chars=cursor.excerpt_chars,
            context_chars=context_chars,
            started_at=(
                started_at if started_at is not None else active_clock()
            ),
        )
        return cls(budget, clock=active_clock, usage=usage)

    def _elapsed(self) -> float:
        return max(0.0, self._clock() - self._started_at)

    def _reserve(
        self,
        limit_name: str,
        *,
        current: int,
        amount: int,
        limit: int,
        setter: Callable[[int], None],
    ) -> None:
        if amount < 0:
            raise ValueError("Reservation amount must be non-negative")
        self.check_time()
        proposed = current + amount
        if proposed > limit:
            raise ResearchBudgetExceeded(limit_name)
        setter(proposed)
