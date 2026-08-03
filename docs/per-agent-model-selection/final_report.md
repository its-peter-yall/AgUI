# Final Report: Per-Agent Model Selection

**Date:** 2026-08-03  
**Status:** COMPLETE  
**Objective:** `per-agent-model-selection`

---

## Original Objective

Users already pick a separate **Chat Assistant Model**. Extend the same control to learning pipeline roles:

- Researcher
- Planner
- Generator
- Quizzer

So users can assign expensive models to hard work and cheaper models to simpler roles.

---

## Plan

| Doc | Path | Commit |
|-----|------|--------|
| Goal | `docs/per-agent-model-selection/goal.md` | `29556cd` |
| Plan | `docs/per-agent-model-selection/plan.md` | `f69cea6` |

**Approach A (approved):** per-role HTTP headers (mirror Chat), localStorage settings, server `LLMContext.agent_models`, runtime resolve in `BaseAgent` / regen.

**Key decisions:**
- All four roles **required** (no silent fallback)
- Per-role provider + per-role thinking
- Settings **Agent Models** section
- `depth_router` uses main generation model (relabeled Default / Depth Router)
- Chat behavior unchanged

---

## Implementation Commits (ordered)

| Hash | Summary |
|------|---------|
| `29556cd` | docs: goal |
| `f69cea6` | docs: implementation plan |
| `cf46922` | feat: AgentRole + AgentModelSelection types |
| `9485ffe` | feat: persist agentModels + helpers |
| `f9178f6` | feat: Settings Agent Models UI (four pickers + thinking) |
| `8d0bb2b` | feat: per-role headers + generate/resume/regen gates |
| `fbd0ab5` | feat: server parse headers + per-role runtime resolve |
| `98de4d6` | test: LearningPage fixtures + plan checkboxes |

Note: unrelated `30c247e` (mongodb-atlas-storage docs) sits between agent-model commits on branch history.

---

## Code Changes Summary

### Client
- **Types:** `AgentRole`, `AGENT_ROLES`, `AgentModelSelection` in `provider.ts`
- **Settings:** `ProviderConfig.agentModels`, load/save, `areAgentModelsConfigured`, role getters/setters
- **UI:** `AgentModelsPanel` + Settings section; main model help → Default / Depth Router
- **Transport:** `agentModelHeaders.ts` → `X-{Role}-Model|Provider|Thinking-*`
- **Gates:** TopicInput generate, GenerationStatusPanel resume, ConceptCard regen disabled until all four set
- **APIs:** `learningApi` / `regenApi` attach agent headers + both provider keys when needed

### Server
- **`AgentModelConfig`** + `LLMContext.agent_models`
- **Header parse** in `get_llm_context` / learning deps
- **`require_agent_models`** on generate / resume / regen → 400 if incomplete
- **`BaseAgent`** resolves model/provider/key/thinking per role
- **`regen_stream`** uses generator role config
- **`depth_router`** keeps main `llm_context.model`

### Tests added/updated
- Client: providerSettings, agentModelHeaders, learningApi, AgentModelsPanel, SettingsPage, TopicInput, GenerationStatusPanel, LearningPage, ConceptCard
- Server: `test_llm_context_agent_models.py`, `test_agent_model_resolution.py`, shared `llm_test_helpers.py`, fixture updates

---

## Quality Gates (verified 2026-08-03)

| Check | Result |
|-------|--------|
| Client lint | OK |
| Client build | OK |
| Client vitest | **102 passed** / 0 failed (22 files) |
| Server unittest | **216 passed** / 0 failed |

---

## How to Use

1. Open **Settings**
2. Set API keys for providers you need
3. Set **Default / Depth Router Model** (main picker)
4. Open **Agent Models** — pick Researcher, Planner, Generator, Quizzer (optional per-role thinking)
5. Optionally set **Chat Assistant Model**
6. Generate course — blocked until all four agent models set

---

## Gaps / Follow-ups

- Manual browser smoke not run (Settings → four models → network headers)
- No SQLite persistence of agent model choices on jobs (headers re-sent each request)
- No depth_router Settings picker (by design v1)
- No per-role `max_completion_tokens` override (MODEL_CONFIGS temps/tokens only)

---

## Workflow Meta

| Agent | Role | Outcome |
|-------|------|---------|
| Orchestrator | Brainstorm + goal | `29556cd` |
| Planner | writing-plans → plan.md | `f69cea6` |
| Worker | executing-plans + TDD → code | `cf46922`…`98de4d6` |

**Final report commit:** (this commit)
