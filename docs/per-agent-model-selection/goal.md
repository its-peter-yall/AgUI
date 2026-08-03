# Goal: Per-Agent Model Selection

**Date:** 2026-08-03  
**Status:** Approved design  
**Objective name:** `per-agent-model-selection`

---

## Original Objective

Users can already pick a separate **Chat Assistant Model** (independent of the main generation model). Extend the same control to the learning pipeline agent roles:

- **Researcher**
- **Planner**
- **Generator**
- **Quizzer**

Goal: let users assign larger/expensive models to hard work (planning, chat) and smaller/cheap models to simpler work (quiz, research), with full control.

---

## Success Criteria

1. Settings UI exposes four role model pickers (plus per-role thinking), patterned after Chat Assistant Model.
2. Each role can use a different provider (OpenRouter or General Compute), same as chat.
3. All four roles **must** be explicitly configured before course generate / resume / node regen.
4. Server resolves the correct model, API key, and thinking params per agent role at call time.
5. Chat Assistant Model behavior remains unchanged.
6. Main generation model remains for **Default / Depth Router** fallback (no depth_router picker in v1).
7. Tests cover settings persistence, header building, server validation, and role model resolution.
8. Lint, typecheck, unit tests, and client build pass.

---

## Decisions (User-Approved)

| Topic | Decision |
|-------|----------|
| Approach | **A — Headers per role** (mirror Chat) |
| Unset fallback | **Require explicit pick** — block generate until all four set |
| Cross-provider | **Same as Chat** — per-role provider allowed |
| Thinking | **Per-role** thinking toggle + effort |
| UI placement | **Agent Models** section under generation model on Settings |
| depth_router | Uses main generation model; no separate picker |
| Main model field | Keep; relabel as Default / Depth Router Model |

---

## Current State (Baseline)

### Client
- `ProviderConfig`: `model`, `modelTitle`, `chatModel`, `chatModelTitle`, `chatModelProvider`, `thinking`, `maxCompletionTokens`
- Storage: `localStorage` key `ai_provider_settings`
- Chat: `X-Chat-Model` via `chatApi.ts`
- Generate/resume/regen: `X-OpenRouter-Model` / `X-GeneralCompute-Model` via `learningApi.ts` / `regenApi.ts`
- UI: `SettingsPage` → Chat Assistant Model section with `ModelPicker`

### Server
- `LLMContext`: single `model` + optional `chat_model` + global thinking
- `MODEL_CONFIGS` in `instructor_client.py`: per-role **temperature/max_tokens only** (no per-role model)
- Agents (`planner`, `generator`, `quizzer`, `researcher`, `depth_router`) share global model override from context
- `get_llm_context()` reads provider key + single model headers

---

## Design

### 1. Client data model

Extend `ProviderConfig` (stored under active provider config; role entries may point at other providers via `modelProvider`):

```ts
export type AgentRole = 'researcher' | 'planner' | 'generator' | 'quizzer';

export interface AgentModelSelection {
  modelId: string;
  modelTitle?: string;
  modelProvider?: AIProvider;
  thinking?: ThinkingConfig;
}

export interface ProviderConfig {
  // ...existing fields...
  agentModels?: Partial<Record<AgentRole, AgentModelSelection>>;
}
```

Migration: missing `agentModels` → treat as unconfigured (all four required).

Helper:

```ts
areAgentModelsConfigured(config: ProviderConfig): boolean
// true iff all four roles have non-empty modelId
```

### 2. Settings UI

New collapsible **Agent Models** section on `SettingsPage` (near generation model / before or after Chat):

For each role (Researcher, Planner, Generator, Quizzer):
- Label + short help text
- `ModelPicker` (cross-provider, same as Chat)
- Selected title readout
- `ThinkingModeToggle` when selected model supports thinking

Relabel main model picker help text to: **Default / Depth Router Model** (used when depth_router runs; not a substitute for the four agent roles).

### 3. Client → server transport (headers)

On generate, resume, and regen requests:

| Purpose | Header |
|---------|--------|
| Researcher model | `X-Researcher-Model` |
| Researcher provider | `X-Researcher-Provider` |
| Researcher thinking on | `X-Researcher-Thinking-Enabled` |
| Researcher thinking effort | `X-Researcher-Thinking-Effort` |
| Planner model | `X-Planner-Model` |
| Planner provider | `X-Planner-Provider` |
| Planner thinking on | `X-Planner-Thinking-Enabled` |
| Planner thinking effort | `X-Planner-Thinking-Effort` |
| Generator model | `X-Generator-Model` |
| Generator provider | `X-Generator-Provider` |
| Generator thinking on | `X-Generator-Thinking-Enabled` |
| Generator thinking effort | `X-Generator-Thinking-Effort` |
| Quizzer model | `X-Quizzer-Model` |
| Quizzer provider | `X-Quizzer-Provider` |
| Quizzer thinking on | `X-Quizzer-Thinking-Enabled` |
| Quizzer thinking effort | `X-Quizzer-Thinking-Effort` |

Also continue sending:
- `X-AI-Provider` (active provider)
- `X-OpenRouter-Key` / `X-GeneralCompute-Key` as needed (both keys when any role or active path needs them)
- Existing generation model headers for depth_router / default
- Existing thinking headers for global/default path if still used by depth_router

Chat path unchanged (`X-Chat-Model` only).

### 4. Client gates

- `areAgentModelsConfigured` false → disable generate / resume / regen CTAs
- Show clear message: set Researcher, Planner, Generator, and Quizzer models in Settings
- Do not send incomplete role sets

### 5. Server `LLMContext`

```python
class AgentModelConfig(BaseModel):
    model: str
    provider: Optional[AIProviderEnum] = None  # default: context.provider
    thinking_enabled: bool = False
    thinking_effort: Optional[str] = None

class LLMContext(BaseModel):
    # ...existing...
    agent_models: dict[str, AgentModelConfig] = Field(default_factory=dict)
```

`get_llm_context()` (or sibling dependency used by learning routes) parses role headers into `agent_models`.

**Validation** on generate/resume/regen:
- Require keys: `researcher`, `planner`, `generator`, `quizzer`
- Each must have non-empty `model`
- If role `provider` set, corresponding API key header must be present
- Else 400 with explicit missing role/key list

### 6. Model resolution (`instructor_client` / agents)

For `create_structured(role=...)` and equivalent calls:

1. If `role` in `{researcher, planner, generator, quizzer}`:
   - Require `llm_context.agent_models[role]`
   - Use that model slug
   - Resolve provider = role.provider or context.provider
   - Resolve API key for that provider
   - Apply role thinking params (not global) when building reasoning payload
2. If `role == depth_router` (or unknown):
   - Use `llm_context.model` (main generation model) + global thinking as today
3. Keep `MODEL_CONFIGS[role]` for temperature / max_tokens only

### 7. Out of scope (v1)

- depth_router Settings picker
- Persisting agent models on session/job rows in SQLite
- Per-role `max_completion_tokens` overrides
- Changing Chat Assistant fallback behavior
- Server-side named model profiles

---

## Architecture Data Flow

```
Settings (localStorage agentModels)
    → learningApi / regenApi header builder
    → FastAPI get_llm_context
    → LLMContext.agent_models
    → LangGraph / agents / research_runner
    → instructor_client.create_structured(role)
    → provider API with role-specific model + key + thinking
```

---

## Implementation Phases (for Planner)

### Phase 1 — Types + settings persistence (client)
- Extend types and `providerSettings` load/save/migrate
- Helpers: `areAgentModelsConfigured`, getters/setters for agent role models
- Unit tests for persistence and helpers

### Phase 2 — Settings UI
- Agent Models section + four pickers + per-role thinking
- Relabel main model help text
- Wire save handlers

### Phase 3 — Client API headers + gates
- Header builders for learning/regen
- Disable generate/resume/regen when incomplete
- Unit tests for headers and gates

### Phase 4 — Server schemas + context parsing
- `AgentModelConfig`, extend `LLMContext`
- Parse role headers; validate required roles on mutating learning routes
- Tests for parse + 400 cases

### Phase 5 — Runtime resolution
- `instructor_client` + agent base path use per-role model/provider/thinking
- depth_router keeps main model
- Tests for resolution matrix

### Phase 6 — Integration polish + quality gates
- End-to-end smoke where feasible
- `npm run lint`, `npm run build`, client tests
- `python -m unittest` server
- Fix regressions

---

## Key Files (expected touch list)

### Client
- `client/src/lib/providerSettings.ts`
- `client/src/types/provider.ts` (if types live here)
- `client/src/features/settings/SettingsPage.tsx`
- `client/src/features/settings/ModelPicker.tsx` (reuse)
- `client/src/features/settings/ThinkingModeToggle.tsx` (reuse)
- `client/src/lib/learningApi.ts`
- `client/src/lib/regenApi.ts`
- `client/src/lib/providerApi.ts` (if shared header helpers)
- Learning page CTA components (generate/resume disable)
- Co-located `*.test.ts(x)` files

### Server
- `server/schemas/llm.py`
- `server/utils/instructor_client.py`
- `server/agents/base.py`
- `server/routers/learning.py`
- `server/graph/nodes.py` / regen paths (if they construct LLM calls)
- `server/tests/test_*.py` (new or extended)

---

## Risks + Mitigations

| Risk | Mitigation |
|------|------------|
| Header sprawl / typos | Centralize header name constants client + server |
| Cross-provider missing key | Validate both sides; clear 400 detail |
| Breaking existing users | Require explicit config; show Settings CTA; no silent wrong model |
| Thinking on non-supporting model | Only show toggle when `supports_thinking`; server ignores if disabled |
| Job resume without headers | Client must re-send role headers on resume (same as today for model key) |

---

## Non-Goals

- Auto-picking cheap vs expensive models
- Cost estimator UI
- Per-topic model overrides

---

## Approval

- Approach A approved by user
- Design §1–§3 approved by user
- This goal doc is the source of truth for the Planner

**Next:** Planner writes `docs/per-agent-model-selection/plan.md` via writing-plans skill, then Worker executes.
