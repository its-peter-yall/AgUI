# Research Budget Finalization Design

**Date:** 2026-08-03
**Status:** Approved design, implementation pending

## Goal

Increase research capacity by resolved mode while guaranteeing one final LLM
turn after research reaches any normal budget limit. Research must stop safely
when search, data, or research-time budgets are exhausted, but it must still
produce and persist a final report from evidence already collected.

## Current Problem

`ResearchBudgetLedger` uses one hard `llm_turns` counter for planning,
synthesis, source-ID correction, and finalization. `ResearchRunner._finalize`
reserves finalization through that same counter and also performs the normal
elapsed-time check. When either limit is exhausted, the reservation raises
`ResearchBudgetExceeded` before `ResearcherAgent.finalize_report` runs. The
exception is caught by a broad fallback, making the log report a failed
finalizer and obscuring the exhausted limit.

## Budget Policy

Normal research caps are mode-specific and remain hard limits:

| Limit | `lite` | `full` |
|---|---:|---:|
| Search calls | 5-8 by concept count | 8-18 by concept count |
| LLM turns | 6 | 10 |
| Research elapsed time | 90 seconds | 180 seconds |
| Results examined | 60 | 120 |
| Sources | 18 | 40 |
| Provider bytes | 2,000,000 | 5,000,000 |
| Excerpt chars | 60,000 | 100,000 |
| Context chars | 60,000 | 100,000 |
| Content chars per hit | 6,000 | 8,000 |

Search-call sizing remains adaptive. `lite` uses a maximum of eight calls and
`full` uses a maximum of eighteen calls, with each mode retaining its minimum
appropriate for the planned concept count.

One separate finalization allowance exists for every research run. It is not
part of normal `llm_turns`, does not permit more search or evidence ingestion,
and is consumed at most once. Finalization may begin after a normal elapsed
budget is exhausted. Persisted elapsed research time remains bounded by the
existing cursor schema ceiling.

## Data Flow

1. Planner and iterative research consume normal mode budget counters.
2. Any exhausted normal counter records a limitation and ends further
   retrieval/synthesis work.
3. Runner invokes a dedicated finalization reservation.
4. Finalization receives collected sections, coverage, conflicts, and recorded
   limitations, then writes the terminal report.
5. Cursor persistence records finalization allowance usage and bounded elapsed
   time so a resumed job cannot spend the allowance twice.

If finalization itself fails for an external or provider error, the existing
safe fallback report remains, but the warning includes the concrete exception
class and exhausted budget name where applicable.

## Implementation Boundaries

- `server/search/budget.py`: mode caps, finalization allowance state,
  reservation, cursor mapping, and elapsed-time persistence clamp.
- `server/schemas/generation.py`: persisted finalization allowance field with
  a maximum of one.
- `server/services/research_runner.py`: use dedicated finalization reservation,
  preserve limitations, and log exact budget limit names.
- `server/tests/test_research_budget.py`: cap and ledger behavior.
- `server/tests/test_majors_m1_m8.py`: cursor persistence and elapsed bounds.
- `server/tests/test_research_runner.py`: finalization after exhausted LLM and
  elapsed budgets.

No provider, database table, API, or client change is required.

## Error Handling

Normal budget exceptions remain deterministic and terminate only the research
loop. Finalization reservation must not reuse normal elapsed or LLM counters.
The dedicated allowance is single-use; a second reservation falls back to the
existing safe `ResearchFinalization` value without another LLM call.

## Testing

- Verify exact `lite` and `full` cap values and adaptive search-call sizing.
- Verify finalization reservation succeeds when normal LLM turns are full.
- Verify finalization reservation succeeds after elapsed research timeout.
- Verify finalization allowance cannot be reserved twice.
- Verify cursor round-trip preserves allowance usage and stays within schema
  ceilings.
- Run focused server tests, then the full server unittest suite.
