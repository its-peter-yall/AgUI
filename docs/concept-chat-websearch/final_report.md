# Final Report: concept-chat-websearch

## Executive Summary

Concept chat now has the same Settings-gated globe toggle as `/learn` TopicInput.
When the globe is ON, the assistant gets one native `web_search` tool backed by
the Researcher search adapters and `ProviderCoordinator`. Constraints live in
the tool description, not the system prompt. Server enforces a hard 1-search
cap per turn, formats hits as readable untrusted text, shows status + source
chips, persists cleaned results on assistant history for later turns, and keeps
OpenRouter `cache_control` on the system prefix.

Review verdict: **PASSED**. No blocking defects. Non-blocking notes in
`docs/concept-chat-websearch/review.md` (live-delta buffering, abort leftover
searching row, empty-assistant persist).

## Workflow Configuration

- Workflow: MAW
- Skipped Phases: None

## Plan Breakdown & Execution Record

| Plan ID | Title | Commits | Status |
| :--- | :--- | :--- | :--- |
| Plan 1 | Message contracts (Pydantic + TS) | b222b05, c5f2622 | Completed |
| Plan 2 | Readable search formatter | e17df47, cd31b34, 6ef2b50 | Completed |
| Plan 3 | One-shot search + tool schema + ledger | 7debd38, ae82b93, 186e6df | Completed |
| Plan 4 | Concept-chat tool loop + router | 94d95de, 46df2e2, 32cfccd, 6660553, def8ae1, 0d89be8, 52ff5c8, 0115bff, 4b90a46 | Completed |
| Plan 5 | Client chat API + hook persist | faefc5d, 3596d01, 0d7d09e, a57d13f, 2a6771e, 0379e99 | Completed |
| Plan 6 | ChatPanel globe, status, source chips | 8f9163c, a33e5ed, b576ac2, 2a8419d | Completed |

## What shipped

- **Globe:** Hidden until `hasWebSearchCapability()`. Per-chat toggle, starts OFF, persisted per node in `concept_chat_{sessionId}_{nodeId}`.
- **Tool:** `web_search` with single `query` arg. Description holds when/how/1-call/meticulous-query rules.
- **Loop:** Round 1 tools + `tool_choice=auto`. Assemble tool_calls by index. Yield `searching` as soon as name is `web_search`. First `web_search` only. Round 2 **keeps** the same tools + `tool_choice=none` (research override vs original “omit tools”).
- **Formatter:** `deduplicate_results` → slice 5 → `sanitize_source_text` snippet-first → readable template. No extra regex (live Tavily/Exa/SerpAPI). No researcher JSON fences.
- **SSE:** `status`, `search`, `warning`, `delta`, `[DONE]`. Warning copy: `Web search unavailable; answering from the concept.`
- **History:** Optional `search` on assistant messages. Server expands to tool_calls + `role:tool` + answer. Globe OFF still sends prior blobs so the model can reuse them.
- **Cache:** `apply_openrouter_cache_control` on both completions; breakpoint on system only.
- **Keys:** Browser `X-Web-Search*` headers when globe ON. Globe OFF omits those headers. Runtime does not read `.env`.

## Verification & Quality Assurance

Re-run 2026-09-05 after review:

| Check | Result |
|-------|--------|
| Server unittest (schema, format, search helper, loop, router, cache) | **66 OK** |
| Client vitest (types, chatApi, useConceptChat, ChatPanel) | **36 passed** |
| Unified review | **PASSED** (`de619fc`) |

Lint/type: Plan 1 worker ran `npx tsc -b` exit 0. Feature suites green above.

## Research overrides applied

1. Round 2 keeps `tools` + `tool_choice="none"` (OpenRouter validation + Anthropic cache prefix).
2. Extra provider regex: no. Formatter must slice to 5.
3. `ChatSearchLedger` is duck-typed, not `ResearchBudgetLedger`.

## Non-blocking follow-ups (not in this workflow)

See `review.md`: live yield when tools off; gate searching row on `isStreaming` and clear on abort; skip persist of empty assistant content; tighten tools-rejected detection.

## Key Artifacts

- Goal: `docs/concept-chat-websearch/goal.md`
- Research: `docs/concept-chat-websearch/research.md`
- State: `docs/concept-chat-websearch/state.md`
- Plans: `docs/concept-chat-websearch/plan1.md` … `plan6.md`
- Review: `docs/concept-chat-websearch/review.md`
