---
objective: concept-chat-websearch
workflow: maw
status: complete
skipped_phases: []
---

# State & Dependency Graph: concept-chat-websearch

## Workflow Milestones
- [x] Step 1: Brainstorming & Goal Alignment (`docs/concept-chat-websearch/goal.md`)
- [x] Step 2: Technical Research (`docs/concept-chat-websearch/research.md`)
- [x] Step 3: Planning Completed (All plans written)
- [x] Step 4: Execution Completed (All workers finished)
- [x] Step 5: Unified Code Review (`docs/concept-chat-websearch/review.md`)
- [x] Step 6: Final Verification & Report (`docs/concept-chat-websearch/final_report.md`)

## Research overrides vs goal.md
- Round 2 keeps the **same** `tools` array + `tool_choice="none"` (do not omit tools; Anthropic/OpenRouter cache + validation). Still never execute a second search.
- Extra provider regex: **NO**. Formatter must **slice to 5** after dedupe (SerpAPI returned 9).
- Chat ledger is a duck-typed stub, not `ResearchBudgetLedger`.

## Dependency Matrix & Execution Status
| Plan ID | Title & Scope | Dependencies | Touched Files / Subsystems | Planner Status | Worker Status | Commits |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Plan 1** | Message contracts (Pydantic + TS) | None | `server/schemas/learning.py`, `client/src/types/learning.ts` | [x] Done | [x] Completed | b222b05, c5f2622 |
| **Plan 2** | Readable search formatter | None | `server/search/chat_format.py` | [x] Done | [x] Completed | e17df47, cd31b34, 6ef2b50 |
| **Plan 3** | One-shot search + tool schema + ledger | None | `server/services/concept_chat_search.py` | [x] Done | [x] Completed | 7debd38, ae82b93, 186e6df |
| **Plan 4** | Concept-chat tool loop + router | Plan 1, 2, 3 | `concept_chat.py`, `learning.py` router | [x] Done | [x] Completed | 94d95de, 46df2e2, 32cfccd, 6660553, def8ae1, 0d89be8, 52ff5c8, 0115bff, 4b90a46 |
| **Plan 5** | Client chat API + hook persist | Plan 1 | `chatApi.ts`, `useConceptChat.ts` | [x] Done | [x] Completed | faefc5d, 3596d01, 0d7d09e, a57d13f, 2a6771e, 0379e99 |
| **Plan 6** | ChatPanel globe, status, source chips | Plan 5 | `ChatPanel.tsx` | [x] Done | [x] Completed | 8f9163c, a33e5ed, b576ac2, 2a8419d |
