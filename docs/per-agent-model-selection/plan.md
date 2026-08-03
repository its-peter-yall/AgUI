# Per-Agent Model Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users pick independent models (provider + thinking) for Researcher, Planner, Generator, and Quizzer via Settings headers, with all four required before generate/resume/regen; depth_router keeps main generation model; chat unchanged.

**Architecture:** Mirror Chat Assistant Model (Approach A). Client stores `agentModels` on active `ProviderConfig` in `localStorage` (`ai_provider_settings`). Learning/regen APIs send per-role headers (`X-Researcher-Model`, `X-Researcher-Provider`, thinking headers, same pattern for planner/generator/quizzer) plus both provider keys when needed. Server `get_llm_context` parses into `LLMContext.agent_models`. `BaseAgent.generate` and `regen_stream` resolve model/provider/key/thinking per role; `depth_router` keeps `llm_context.model` + global thinking.

**Tech Stack:** React 19 + TypeScript (Vitest), FastAPI + Pydantic v2 (unittest), existing `ModelPicker` / `ThinkingModeToggle` / `instructor_client` / `LLMContext`.

**Source of truth:** `docs/per-agent-model-selection/goal.md`

---

## File structure (create / modify)

| Path | Responsibility |
|------|----------------|
| `client/src/types/provider.ts` | Add `AgentRole`, `AgentModelSelection` types |
| `client/src/lib/providerSettings.ts` | Extend `ProviderConfig.agentModels`; load/save; helpers |
| `client/src/lib/providerSettings.test.ts` | Persistence + helper unit tests |
| `client/src/lib/agentModelHeaders.ts` | **Create** — header name constants + `buildAgentModelHeaders` |
| `client/src/lib/agentModelHeaders.test.ts` | **Create** — header builder tests |
| `client/src/lib/learningApi.ts` | Use agent headers in `buildLlmHeaders` |
| `client/src/lib/learningApi.test.ts` | Assert role headers on generate/resume/regen |
| `client/src/lib/regenApi.ts` | Attach agent headers on stream regen |
| `client/src/features/settings/SettingsPage.tsx` | Agent Models section; relabel main model help |
| `client/src/features/settings/OpenRouterSettingsPanel.tsx` | Relabel main picker help → Default / Depth Router |
| `client/src/features/settings/SettingsPage.test.tsx` | Section disclosure includes Agent Models |
| `client/src/features/settings/AgentModelsPanel.tsx` | **Create** — four role pickers + thinking |
| `client/src/features/settings/AgentModelsPanel.test.tsx` | **Create** — render + save wiring |
| `client/src/features/learning/TopicInput.tsx` | Gate generate on `areAgentModelsConfigured` |
| `client/src/features/learning/TopicInput.test.tsx` | Gate tests |
| `client/src/features/learning/GenerationStatusPanel.tsx` | Disable resume when agents incomplete |
| `client/src/features/learning/LearningPage.tsx` | Pass agent-config flag into resume panel / guard mutation |
| `client/src/features/learning/ConceptCard.tsx` | Disable regen when agents incomplete |
| `server/schemas/llm.py` | `AgentModelConfig`; extend `LLMContext`; parse headers; validate |
| `server/utils/instructor_client.py` | No MODEL_CONFIGS model change; keep temp/tokens only |
| `server/agents/base.py` | Resolve per-role model/provider/key/thinking |
| `server/graph/regen_stream.py` | Use generator role resolution (not global model only) |
| `server/services/depth_router.py` | Unchanged path (main model) — verify only |
| `server/routers/learning.py` | Call `require_agent_models` on generate/resume/regen |
| `server/tests/test_llm_context_agent_models.py` | **Create** — parse + 400 validation |
| `server/tests/test_agent_model_resolution.py` | **Create** — BaseAgent / resolution matrix |

**Do not touch:** `client/src/lib/chatApi.ts` behavior, Chat Settings section semantics, SQLite schema, depth_router picker UI.

---

## Phase 1 — Types + settings persistence (client)

### Task 1: Agent role types

**Files:**
- Modify: `client/src/types/provider.ts`
- Modify: `client/src/lib/providerSettings.ts` (interface only in this task if preferred; types may live next to `ProviderConfig`)

- [ ] **Step 1: Add types to `client/src/types/provider.ts`**

Append after `ThinkingConfig`:

```ts
/** Learning pipeline agent roles with selectable models */
export type AgentRole = 'researcher' | 'planner' | 'generator' | 'quizzer';

export const AGENT_ROLES: readonly AgentRole[] = [
  'researcher',
  'planner',
  'generator',
  'quizzer',
] as const;

/** Per-role model pick stored under ProviderConfig.agentModels */
export interface AgentModelSelection {
  modelId: string;
  modelTitle?: string;
  modelProvider?: AIProvider;
  thinking?: ThinkingConfig;
}
```

- [ ] **Step 2: Extend `ProviderConfig` in `client/src/lib/providerSettings.ts`**

```ts
import type {
  AIProvider,
  AgentModelSelection,
  AgentRole,
  ThinkingConfig,
} from '@/types/provider';

export interface ProviderConfig {
  apiKey: string;
  model: string;
  modelTitle: string;
  chatModel?: string;
  chatModelTitle?: string;
  chatModelProvider?: AIProvider;
  maxCompletionTokens?: number;
  thinking?: ThinkingConfig;
  agentModels?: Partial<Record<AgentRole, AgentModelSelection>>;
}
```

- [ ] **Step 3: Commit**

```bash
git add client/src/types/provider.ts client/src/lib/providerSettings.ts
git commit -m "feat(agent-models): add AgentRole and AgentModelSelection types"
```

---

### Task 2: Parse/persist agentModels + helpers (TDD)

**Files:**
- Modify: `client/src/lib/providerSettings.ts`
- Modify: `client/src/lib/providerSettings.test.ts`

- [ ] **Step 1: Write failing tests** in `providerSettings.test.ts`

```ts
import {
  getProviderSettings,
  setProviderConfig,
  areAgentModelsConfigured,
  getAgentModelSelection,
  setAgentModelSelection,
} from '@/lib/providerSettings';
import type { AgentRole } from '@/types/provider';

describe('agent model settings', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('treats missing agentModels as unconfigured', () => {
    setProviderConfig('openrouter', {
      apiKey: 'k',
      model: 'm',
      modelTitle: 'M',
    });
    const cfg = getProviderSettings().providers.openrouter;
    expect(areAgentModelsConfigured(cfg)).toBe(false);
  });

  it('areAgentModelsConfigured true only when all four have modelId', () => {
    const roles: AgentRole[] = [
      'researcher',
      'planner',
      'generator',
      'quizzer',
    ];
    for (const role of roles) {
      setAgentModelSelection('openrouter', role, {
        modelId: `${role}-model`,
        modelTitle: role,
        modelProvider: 'openrouter',
      });
    }
    const cfg = getProviderSettings().providers.openrouter;
    expect(areAgentModelsConfigured(cfg)).toBe(true);
  });

  it('false when one role missing or blank modelId', () => {
    setAgentModelSelection('openrouter', 'researcher', {
      modelId: 'r',
    });
    setAgentModelSelection('openrouter', 'planner', { modelId: 'p' });
    setAgentModelSelection('openrouter', 'generator', { modelId: 'g' });
    // quizzer missing
    expect(
      areAgentModelsConfigured(
        getProviderSettings().providers.openrouter,
      ),
    ).toBe(false);

    setAgentModelSelection('openrouter', 'quizzer', { modelId: '   ' });
    expect(
      areAgentModelsConfigured(
        getProviderSettings().providers.openrouter,
      ),
    ).toBe(false);
  });

  it('round-trips agentModels through localStorage', () => {
    setAgentModelSelection('openrouter', 'planner', {
      modelId: 'openai/gpt-4o',
      modelTitle: 'GPT-4o',
      modelProvider: 'generalcompute',
      thinking: { enabled: true, effort: 'medium' },
    });
    const again = getProviderSettings().providers.openrouter;
    expect(getAgentModelSelection(again, 'planner')).toEqual({
      modelId: 'openai/gpt-4o',
      modelTitle: 'GPT-4o',
      modelProvider: 'generalcompute',
      thinking: { enabled: true, effort: 'medium' },
    });
  });

  it('ignores invalid agentModels shape on load', () => {
    localStorage.setItem(
      'ai_provider_settings',
      JSON.stringify({
        activeProvider: 'openrouter',
        providers: {
          openrouter: {
            apiKey: '',
            model: '',
            modelTitle: '',
            agentModels: { planner: 'bad' },
          },
          generalcompute: {
            apiKey: '',
            model: '',
            modelTitle: '',
          },
        },
      }),
    );
    const cfg = getProviderSettings().providers.openrouter;
    expect(cfg.agentModels?.planner).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd client
npm run test -- --run src/lib/providerSettings.test.ts
```

Expected: FAIL — `areAgentModelsConfigured` / `setAgentModelSelection` not defined.

- [ ] **Step 3: Implement helpers + load/save**

Add near other exports in `providerSettings.ts`:

```ts
import type {
  AIProvider,
  AgentModelSelection,
  AgentRole,
  ThinkingConfig,
  ThinkingEffort,
} from '@/types/provider';
import { AGENT_ROLES } from '@/types/provider';

const VALID_EFFORTS = new Set<ThinkingEffort>([
  'minimal',
  'low',
  'medium',
  'high',
  'xhigh',
]);

function parseThinking(
  raw: unknown,
): ThinkingConfig | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const t = raw as Partial<ThinkingConfig>;
  const effort =
    typeof t.effort === 'string' && VALID_EFFORTS.has(t.effort as ThinkingEffort)
      ? (t.effort as ThinkingEffort)
      : 'high';
  return {
    enabled: Boolean(t.enabled),
    effort,
  };
}

function parseAgentModelSelection(
  raw: unknown,
): AgentModelSelection | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const entry = raw as Partial<AgentModelSelection>;
  if (typeof entry.modelId !== 'string' || !entry.modelId.trim()) {
    return undefined;
  }
  const modelProvider =
    entry.modelProvider === 'generalcompute'
      ? 'generalcompute'
      : entry.modelProvider === 'openrouter'
        ? 'openrouter'
        : undefined;
  return {
    modelId: entry.modelId,
    modelTitle:
      typeof entry.modelTitle === 'string' ? entry.modelTitle : undefined,
    modelProvider,
    thinking: parseThinking(entry.thinking),
  };
}

function parseAgentModels(
  raw: unknown,
): Partial<Record<AgentRole, AgentModelSelection>> | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const out: Partial<Record<AgentRole, AgentModelSelection>> = {};
  const src = raw as Record<string, unknown>;
  for (const role of AGENT_ROLES) {
    const parsed = parseAgentModelSelection(src[role]);
    if (parsed) out[role] = parsed;
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

export function areAgentModelsConfigured(config: ProviderConfig): boolean {
  const map = config.agentModels;
  if (!map) return false;
  return AGENT_ROLES.every((role) => {
    const id = map[role]?.modelId;
    return typeof id === 'string' && id.trim().length > 0;
  });
}

export function getAgentModelSelection(
  config: ProviderConfig,
  role: AgentRole,
): AgentModelSelection | undefined {
  return config.agentModels?.[role];
}

export function setAgentModelSelection(
  provider: AIProvider,
  role: AgentRole,
  selection: AgentModelSelection,
): void {
  const settings = getProviderSettings();
  const current = settings.providers[provider];
  const nextModels = {
    ...(current.agentModels ?? {}),
    [role]: {
      modelId: selection.modelId,
      modelTitle: selection.modelTitle,
      modelProvider: selection.modelProvider,
      thinking: selection.thinking
        ? {
            enabled: selection.thinking.enabled,
            effort: selection.thinking.effort,
          }
        : undefined,
    },
  };
  setProviderConfig(provider, { agentModels: nextModels });
}
```

In `getProviderSettings()` provider object builders for both `openrouter` and `generalcompute`, add:

```ts
agentModels: parseAgentModels(parsed?.providers?.openrouter?.agentModels),
// and for generalcompute:
agentModels: parseAgentModels(
  parsed?.providers?.generalcompute?.agentModels,
),
```

`setProviderConfig` already shallow-merges; ensure callers replace full `agentModels` map (as `setAgentModelSelection` does).

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd client
npm run test -- --run src/lib/providerSettings.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add client/src/lib/providerSettings.ts client/src/lib/providerSettings.test.ts client/src/types/provider.ts
git commit -m "feat(agent-models): persist agentModels and configuration helpers"
```

---

## Phase 2 — Settings UI

### Task 3: Relabel main generation model help text

**Files:**
- Modify: `client/src/features/settings/OpenRouterSettingsPanel.tsx`
- Modify: `client/src/features/settings/SettingsPage.tsx` (chat copy stays; only main model if any label there)

- [ ] **Step 1: Find main model label area** in `OpenRouterSettingsPanel.tsx` above `ModelPicker` (or add a short help line if none).

Add/replace help text immediately above the top `ModelPicker`:

```tsx
<p className="text-xs text-muted-foreground mb-3">
  Default / Depth Router Model — used for depth routing and as the
  active provider default. Not a substitute for Researcher, Planner,
  Generator, or Quizzer models below.
</p>
```

Do **not** change Chat Assistant Model section copy or behavior.

- [ ] **Step 2: Commit**

```bash
git add client/src/features/settings/OpenRouterSettingsPanel.tsx
git commit -m "docs(ui): relabel main model as Default / Depth Router"
```

---

### Task 4: AgentModelsPanel component (TDD UI shell)

**Files:**
- Create: `client/src/features/settings/AgentModelsPanel.tsx`
- Create: `client/src/features/settings/AgentModelsPanel.test.tsx`
- Modify: `client/src/features/settings/SettingsPage.tsx`
- Modify: `client/src/features/settings/SettingsPage.test.tsx`

- [ ] **Step 1: Write failing SettingsPage disclosure test**

In `SettingsPage.test.tsx`, extend the collapsed-sections list:

```ts
for (const name of [
  'Appearance',
  'AI Provider Credentials',
  'Web Search',
  'Agent Models',
  'Chat Assistant Model',
]) {
```

Mock new panel:

```ts
vi.mock('./AgentModelsPanel', () => ({
  AgentModelsPanel: () => <div>Agent models panel content</div>,
}));
```

- [ ] **Step 2: Run test — expect FAIL** (no Agent Models button)

```bash
cd client
npm run test -- --run src/features/settings/SettingsPage.test.tsx
```

- [ ] **Step 3: Write AgentModelsPanel tests**

```tsx
/**
 * FILE: AgentModelsPanel.test.tsx
 * LOCATION: client/src/features/settings/AgentModelsPanel.test.tsx
 * (full header per AGENTS.md)
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const setAgentModelSelection = vi.fn();

vi.mock('@/lib/providerSettings', () => ({
  getProviderSettings: () => ({
    activeProvider: 'openrouter',
    providers: {
      openrouter: {
        apiKey: 'or-key',
        model: 'main',
        modelTitle: 'Main',
        agentModels: {},
      },
      generalcompute: { apiKey: 'gc-key', model: '', modelTitle: '' },
    },
  }),
  setAgentModelSelection: (...args: unknown[]) =>
    setAgentModelSelection(...args),
  setProviderConfig: vi.fn(),
}));

vi.mock('./ModelPicker', () => ({
  ModelPicker: ({
    onSelect,
  }: {
    onSelect: (p: string, id: string, title: string) => void;
  }) => (
    <button
      type="button"
      onClick={() => onSelect('openrouter', 'test/model', 'Test Model')}
    >
      pick-model
    </button>
  ),
}));

vi.mock('./ThinkingModeToggle', () => ({
  ThinkingModeToggle: () => <div>thinking-toggle</div>,
}));

import { AgentModelsPanel } from './AgentModelsPanel';

function renderPanel() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <AgentModelsPanel />
    </QueryClientProvider>,
  );
}

describe('AgentModelsPanel', () => {
  beforeEach(() => {
    setAgentModelSelection.mockClear();
  });

  it('renders four role labels', () => {
    renderPanel();
    expect(screen.getByText('Researcher')).toBeInTheDocument();
    expect(screen.getByText('Planner')).toBeInTheDocument();
    expect(screen.getByText('Generator')).toBeInTheDocument();
    expect(screen.getByText('Quizzer')).toBeInTheDocument();
  });

  it('saves selection via setAgentModelSelection on active provider', () => {
    renderPanel();
    fireEvent.click(screen.getAllByText('pick-model')[0]);
    expect(setAgentModelSelection).toHaveBeenCalledWith(
      'openrouter',
      'researcher',
      expect.objectContaining({
        modelId: 'test/model',
        modelTitle: 'Test Model',
        modelProvider: 'openrouter',
      }),
    );
  });
});
```

- [ ] **Step 4: Implement `AgentModelsPanel.tsx`**

```tsx
/**
 * ============================================================================
 * FILE: AgentModelsPanel.tsx
 * LOCATION: client/src/features/settings/AgentModelsPanel.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Four role model pickers + per-role thinking for learning agents.
 *
 * ROLE IN PROJECT:
 *    Settings UI for per-agent model selection (Approach A headers).
 *
 * KEY COMPONENTS:
 *    - AgentModelsPanel: Researcher/Planner/Generator/Quizzer pickers
 *
 * DEPENDENCIES:
 *    - External: react, @tanstack/react-query, lucide-react
 *    - Internal: ModelPicker, ThinkingModeToggle, providerSettings, types
 * ============================================================================
 */

import { useCallback, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Bot } from 'lucide-react';

import { ModelPicker } from './ModelPicker';
import { ThinkingModeToggle } from './ThinkingModeToggle';
import {
  getProviderSettings,
  setAgentModelSelection,
} from '@/lib/providerSettings';
import { getProviderModels, ProviderApiError } from '@/lib/providerApi';
import { AGENT_ROLES } from '@/types/provider';
import type {
  AgentRole,
  AIProvider,
  ProviderModel,
  ThinkingEffort,
} from '@/types/provider';

const ROLE_META: Record<
  AgentRole,
  { label: string; help: string }
> = {
  researcher: {
    label: 'Researcher',
    help: 'Web research plan and synthesis turns.',
  },
  planner: {
    label: 'Planner',
    help: 'Course outline and topic briefs.',
  },
  generator: {
    label: 'Generator',
    help: 'Topic card content generation.',
  },
  quizzer: {
    label: 'Quizzer',
    help: 'Quiz question generation.',
  },
};

export function AgentModelsPanel() {
  const [settings, setSettings] = useState(() => getProviderSettings());
  const activeProvider = settings.activeProvider;
  const activeConfig = settings.providers[activeProvider];

  const { data: orModels } = useQuery<ProviderModel[], ProviderApiError>({
    queryKey: [
      'provider-models',
      'openrouter',
      settings.providers.openrouter.apiKey,
    ],
    queryFn: () =>
      getProviderModels('openrouter', settings.providers.openrouter.apiKey),
    enabled: settings.providers.openrouter.apiKey.trim().length > 0,
    staleTime: 1000 * 60 * 60 * 24,
    retry: false,
  });

  const refresh = useCallback(() => {
    setSettings(getProviderSettings());
  }, []);

  const handleSelect = useCallback(
    (role: AgentRole) =>
      (
        provider: AIProvider,
        modelId: string,
        modelTitle: string,
      ) => {
        const prev = activeConfig.agentModels?.[role];
        setAgentModelSelection(activeProvider, role, {
          modelId,
          modelTitle,
          modelProvider: provider,
          thinking: prev?.thinking ?? { enabled: false, effort: 'high' },
        });
        refresh();
      },
    [activeConfig.agentModels, activeProvider, refresh],
  );

  const handleThinking = useCallback(
    (role: AgentRole) => (enabled: boolean, effort: ThinkingEffort) => {
      const prev = activeConfig.agentModels?.[role];
      if (!prev?.modelId) return;
      setAgentModelSelection(activeProvider, role, {
        ...prev,
        thinking: { enabled, effort },
      });
      refresh();
    },
    [activeConfig.agentModels, activeProvider, refresh],
  );

  return (
    <div className="flex flex-col gap-6">
      <p className="text-xs text-muted-foreground">
        Required before starting, resuming, or regenerating a course. Each
        role may use OpenRouter or General Compute independently.
      </p>
      {AGENT_ROLES.map((role) => {
        const sel = activeConfig.agentModels?.[role];
        const roleProvider =
          sel?.modelProvider ?? activeProvider;
        const supportsThinking = useMemo(() => {
          if (roleProvider !== 'openrouter' || !sel?.modelId) return false;
          return (
            orModels?.find((m) => m.id === sel.modelId)?.supports_thinking ??
            false
          );
        }, [roleProvider, sel?.modelId, orModels]);
        // NOTE: do not call useMemo inside map in real impl —
        // compute supportsThinking inline or via helper outside hooks rules.
        void supportsThinking;

        return (
          <div
            key={role}
            className="border border-border rounded-xl p-4 space-y-3"
          >
            <div className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-[#ffb74d]" aria-hidden="true" />
              <h3 className="text-sm font-semibold">{ROLE_META[role].label}</h3>
            </div>
            <p className="text-xs text-muted-foreground">
              {ROLE_META[role].help}
            </p>
            <ModelPicker
              openRouterKey={settings.providers.openrouter.apiKey}
              generalComputeKey={settings.providers.generalcompute.apiKey}
              activeProvider={roleProvider}
              activeModel={sel?.modelId ?? ''}
              onSelect={handleSelect(role)}
            />
            {sel?.modelTitle && (
              <p className="text-xs text-muted-foreground">
                Selected:{' '}
                <span className="font-medium text-foreground">
                  {sel.modelTitle}
                </span>
              </p>
            )}
            {roleProvider === 'openrouter' && sel?.modelId && (
              <ThinkingModeToggle
                enabled={sel.thinking?.enabled ?? false}
                effort={sel.thinking?.effort ?? 'high'}
                onChange={handleThinking(role)}
                supportsThinking={
                  orModels?.find((m) => m.id === sel.modelId)
                    ?.supports_thinking ?? false
                }
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
```

**Important implementer note:** The snippet above shows intent. Real code must **not** call hooks inside `.map`. Compute `supportsThinking` inline:

```ts
const supportsThinking =
  roleProvider === 'openrouter' &&
  !!sel?.modelId &&
  (orModels?.find((m) => m.id === sel.modelId)?.supports_thinking ?? false);
```

- [ ] **Step 5: Wire SettingsPage**

Extend section key union:

```ts
type SettingsSectionKey =
  | 'appearance'
  | 'ai-provider'
  | 'web-search'
  | 'agent-models'
  | 'chat-model';
```

Initial expanded state: `'agent-models': false`.

Insert **Agent Models** `SettingsSection` after AI Provider Credentials (or after Web Search, before Chat) — goal: under generation model / near Chat. Prefer order:

1. Appearance  
2. AI Provider Credentials (contains Default / Depth Router picker)  
3. Agent Models  
4. Web Search  
5. Chat Assistant Model  

```tsx
import { AgentModelsPanel } from './AgentModelsPanel';
// icon: Bot from lucide-react

<SettingsSection
  headingId="agent-models-heading"
  contentId="agent-models-content"
  title={
    <span className="flex items-center gap-2">
      <Bot aria-hidden="true" className="h-5 w-5 text-[#ffb74d]" />
      Agent Models
    </span>
  }
  isExpanded={expandedSections['agent-models']}
  onToggle={() => toggleSection('agent-models')}
>
  <div className="bg-card border border-border p-6 rounded-xl shadow-sm">
    <AgentModelsPanel />
  </div>
</SettingsSection>
```

- [ ] **Step 6: Run UI tests**

```bash
cd client
npm run test -- --run src/features/settings/SettingsPage.test.tsx src/features/settings/AgentModelsPanel.test.tsx
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add client/src/features/settings/AgentModelsPanel.tsx \
  client/src/features/settings/AgentModelsPanel.test.tsx \
  client/src/features/settings/SettingsPage.tsx \
  client/src/features/settings/SettingsPage.test.tsx \
  client/src/features/settings/OpenRouterSettingsPanel.tsx
git commit -m "feat(agent-models): Settings Agent Models section with four pickers"
```

---

## Phase 3 — Client API headers + gates

### Task 5: Header constants + builder (TDD)

**Files:**
- Create: `client/src/lib/agentModelHeaders.ts`
- Create: `client/src/lib/agentModelHeaders.test.ts`

- [ ] **Step 1: Write failing tests**

```ts
/**
 * FILE: agentModelHeaders.test.ts
 * LOCATION: client/src/lib/agentModelHeaders.test.ts
 */
import { describe, expect, it } from 'vitest';
import { buildAgentModelHeaders } from './agentModelHeaders';
import type { ProviderConfig, AIProviderSettings } from './providerSettings';

const baseConfig = (partial: Partial<ProviderConfig> = {}): ProviderConfig => ({
  apiKey: 'or-key',
  model: 'main/model',
  modelTitle: 'Main',
  thinking: { enabled: true, effort: 'high' },
  agentModels: {
    researcher: {
      modelId: 'r-model',
      modelProvider: 'openrouter',
      thinking: { enabled: false, effort: 'low' },
    },
    planner: {
      modelId: 'p-model',
      modelProvider: 'generalcompute',
      thinking: { enabled: false, effort: 'high' },
    },
    generator: {
      modelId: 'g-model',
      modelProvider: 'openrouter',
      thinking: { enabled: true, effort: 'medium' },
    },
    quizzer: {
      modelId: 'q-model',
      modelProvider: 'openrouter',
    },
  },
  ...partial,
});

const settings = (
  active: ProviderConfig,
): AIProviderSettings => ({
  activeProvider: 'openrouter',
  providers: {
    openrouter: active,
    generalcompute: {
      apiKey: 'gc-key',
      model: '',
      modelTitle: '',
    },
  },
});

describe('buildAgentModelHeaders', () => {
  it('emits model/provider/thinking headers for all four roles', () => {
    const h = buildAgentModelHeaders(settings(baseConfig()));
    expect(h['X-Researcher-Model']).toBe('r-model');
    expect(h['X-Researcher-Provider']).toBe('openrouter');
    expect(h['X-Planner-Model']).toBe('p-model');
    expect(h['X-Planner-Provider']).toBe('generalcompute');
    expect(h['X-Generator-Model']).toBe('g-model');
    expect(h['X-Generator-Thinking-Enabled']).toBe('true');
    expect(h['X-Generator-Thinking-Effort']).toBe('medium');
    expect(h['X-Quizzer-Model']).toBe('q-model');
    // researcher thinking off → no enabled header (or false — pick one; test locks it)
    expect(h['X-Researcher-Thinking-Enabled']).toBeUndefined();
  });

  it('includes both provider keys when roles span providers', () => {
    const h = buildAgentModelHeaders(settings(baseConfig()));
    expect(h['X-OpenRouter-Key']).toBe('or-key');
    expect(h['X-GeneralCompute-Key']).toBe('gc-key');
  });

  it('throws when agent models incomplete', () => {
    expect(() =>
      buildAgentModelHeaders(
        settings(baseConfig({ agentModels: { researcher: { modelId: 'r' } } })),
      ),
    ).toThrow(/Researcher, Planner, Generator, and Quizzer/i);
  });
});
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd client
npm run test -- --run src/lib/agentModelHeaders.test.ts
```

- [ ] **Step 3: Implement `agentModelHeaders.ts`**

```ts
/**
 * ============================================================================
 * FILE: agentModelHeaders.ts
 * LOCATION: client/src/lib/agentModelHeaders.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Centralize per-agent model HTTP header names and builders.
 *
 * ROLE IN PROJECT:
 *    Shared by learningApi and regenApi for generate/resume/regen.
 * ============================================================================
 */

import { AGENT_ROLES } from '@/types/provider';
import type { AgentRole, AIProvider } from '@/types/provider';
import {
  areAgentModelsConfigured,
  type AIProviderSettings,
} from './providerSettings';
import { buildProviderHeaders } from './providerApi';

const ROLE_HEADER_PREFIX: Record<AgentRole, string> = {
  researcher: 'Researcher',
  planner: 'Planner',
  generator: 'Generator',
  quizzer: 'Quizzer',
};

export function agentModelHeaderName(
  role: AgentRole,
  kind: 'Model' | 'Provider' | 'Thinking-Enabled' | 'Thinking-Effort',
): string {
  return `X-${ROLE_HEADER_PREFIX[role]}-${kind}`;
}

/**
 * Build base LLM headers (active provider model for depth_router) plus
 * required per-role agent headers. Throws if four roles incomplete.
 */
export function buildAgentModelHeaders(
  settings: AIProviderSettings,
): Record<string, string> {
  const active = settings.providers[settings.activeProvider];
  if (!areAgentModelsConfigured(active)) {
    throw new Error(
      'Set Researcher, Planner, Generator, and Quizzer models in Settings before generating.',
    );
  }

  const headers = buildProviderHeaders(
    settings.activeProvider,
    active.apiKey,
    active.model || undefined,
    active.thinking,
    active.maxCompletionTokens,
  );

  // Ensure both keys present when any role (or active) needs them
  const orKey = settings.providers.openrouter.apiKey?.trim();
  const gcKey = settings.providers.generalcompute.apiKey?.trim();
  if (orKey) headers['X-OpenRouter-Key'] = orKey;
  if (gcKey) headers['X-GeneralCompute-Key'] = gcKey;

  for (const role of AGENT_ROLES) {
    const sel = active.agentModels![role]!;
    const provider: AIProvider =
      sel.modelProvider ?? settings.activeProvider;
    headers[agentModelHeaderName(role, 'Model')] = sel.modelId.trim();
    headers[agentModelHeaderName(role, 'Provider')] = provider;
    if (sel.thinking?.enabled) {
      headers[agentModelHeaderName(role, 'Thinking-Enabled')] = 'true';
      headers[agentModelHeaderName(role, 'Thinking-Effort')] =
        sel.thinking.effort || 'high';
    }
  }

  return headers;
}
```

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Commit**

```bash
git add client/src/lib/agentModelHeaders.ts client/src/lib/agentModelHeaders.test.ts
git commit -m "feat(agent-models): centralize agent role HTTP headers"
```

---

### Task 6: Wire learningApi + regenApi

**Files:**
- Modify: `client/src/lib/learningApi.ts`
- Modify: `client/src/lib/learningApi.test.ts`
- Modify: `client/src/lib/regenApi.ts`

- [ ] **Step 1: Extend learningApi tests**

Update mock `getProviderSettings` to include full `agentModels` for four roles. Add:

```ts
it('generate attaches per-role agent model headers', async () => {
  await generateCourse({ query: 'Topic' }, { webSearchEnabled: false });
  const headers = lastRequestConfig()?.headers ?? {};
  expect(headers).toMatchObject({
    'X-Researcher-Model': expect.any(String),
    'X-Planner-Model': expect.any(String),
    'X-Generator-Model': expect.any(String),
    'X-Quizzer-Model': expect.any(String),
  });
});
```

Also cover `regenerateNode` if tested, or add a small case.

- [ ] **Step 2: Replace `buildLlmHeaders` in `learningApi.ts`**

```ts
import { getProviderSettings, getWebSearchSettings } from './providerSettings';
import { buildAgentModelHeaders } from './agentModelHeaders';

function buildLlmHeaders(): Record<string, string> {
  const settings = getProviderSettings();
  const activeConfig = settings.providers[settings.activeProvider];
  if (!activeConfig.apiKey) {
    return { 'Content-Type': 'application/json' };
  }
  return buildAgentModelHeaders(settings);
}
```

Note: `generateCourse` / `resumeGeneration` / `regenerateNode` already use `buildLlmHeaders()`. Incomplete agent config will throw — CTAs should be disabled first (Task 7); still safe.

- [ ] **Step 3: Update `regenApi.ts` `streamRegenerateNode`**

```ts
import { getProviderSettings } from './providerSettings';
import { buildAgentModelHeaders } from './agentModelHeaders';

// inside streamRegenerateNode:
const settings = getProviderSettings();
const providerHeaders = buildAgentModelHeaders(settings);
```

Remove direct `buildProviderHeaders` usage here.

- [ ] **Step 4: Run tests**

```bash
cd client
npm run test -- --run src/lib/learningApi.test.ts src/lib/agentModelHeaders.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add client/src/lib/learningApi.ts client/src/lib/learningApi.test.ts client/src/lib/regenApi.ts
git commit -m "feat(agent-models): send per-role headers on generate/resume/regen"
```

---

### Task 7: Client gates (generate / resume / regen)

**Files:**
- Modify: `client/src/features/learning/TopicInput.tsx`
- Modify: `client/src/features/learning/TopicInput.test.tsx`
- Modify: `client/src/features/learning/LearningPage.tsx`
- Modify: `client/src/features/learning/GenerationStatusPanel.tsx`
- Modify: `client/src/features/learning/ConceptCard.tsx`
- Related tests as needed

- [ ] **Step 1: TopicInput gate**

```ts
import {
  getProviderSettings,
  areAgentModelsConfigured,
} from '@/lib/providerSettings';

const settings = getProviderSettings();
const activeConfig = settings.providers[settings.activeProvider];
const hasApiKey = Boolean(activeConfig.apiKey);
const agentsReady = areAgentModelsConfigured(activeConfig);
const canStart = hasApiKey && agentsReady;
```

Use `canStart` everywhere `hasApiKey` currently gates generate UI. Add message when `hasApiKey && !agentsReady`:

```tsx
{hasApiKey && !agentsReady && (
  <p className="mt-3 text-sm text-amber-600 dark:text-amber-400 text-center" role="alert">
    Set Researcher, Planner, Generator, and Quizzer models in Settings
    before starting a course.
  </p>
)}
```

Keep existing API key message when `!hasApiKey`.

- [ ] **Step 2: TopicInput tests** — mock settings without agentModels → Learn disabled; with all four → enabled (when key + query present).

- [ ] **Step 3: GenerationStatusPanel** — add prop:

```ts
canResumeAgents?: boolean; // default true for back-compat in tests
```

```tsx
disabled={pending || canResumeAgents === false}
```

Show small hint when `canResumeAgents === false`.

- [ ] **Step 4: LearningPage** — compute `agentsReady` from `getProviderSettings()` and pass to panel; guard `resumeMutation.mutationFn` early:

```ts
if (!areAgentModelsConfigured(
  getProviderSettings().providers[getProviderSettings().activeProvider],
)) {
  throw new Error(
    'Set Researcher, Planner, Generator, and Quizzer models in Settings before resuming.',
  );
}
```

- [ ] **Step 5: ConceptCard regen** — before `streamRegenerateNode`:

```ts
const settings = getProviderSettings();
const cfg = settings.providers[settings.activeProvider];
if (!areAgentModelsConfigured(cfg)) {
  setLocalError(
    'Set Researcher, Planner, Generator, and Quizzer models in Settings before regenerating.',
  );
  return;
}
```

Disable regen buttons when `!areAgentModelsConfigured(...)`.

- [ ] **Step 6: Run affected client tests**

```bash
cd client
npm run test -- --run src/features/learning/TopicInput.test.tsx src/features/learning/LearningPage.test.tsx src/features/learning/ConceptCard.test.tsx
```

- [ ] **Step 7: Commit**

```bash
git add client/src/features/learning/
git commit -m "feat(agent-models): gate generate/resume/regen on four role models"
```

---

## Phase 4 — Server schemas + context parsing

### Task 8: AgentModelConfig + LLMContext fields (TDD)

**Files:**
- Modify: `server/schemas/llm.py`
- Create: `server/tests/test_llm_context_agent_models.py`

- [ ] **Step 1: Write failing tests**

```python
"""
============================================================================
FILE: test_llm_context_agent_models.py
LOCATION: server/tests/test_llm_context_agent_models.py
============================================================================
PURPOSE:
    Tests agent model header parsing and required-role validation.
============================================================================
"""

import unittest
from unittest.mock import MagicMock

from fastapi import HTTPException
from pydantic import SecretStr

from server.schemas.llm import (
    AIProviderEnum,
    AgentModelConfig,
    LLMContext,
    get_llm_context,
    require_agent_models,
    REQUIRED_AGENT_ROLES,
)


class AgentModelConfigTests(unittest.TestCase):
    def test_reasoning_params_when_enabled(self) -> None:
        cfg = AgentModelConfig(
            model="m",
            thinking_enabled=True,
            thinking_effort="medium",
        )
        self.assertEqual(
            cfg.get_reasoning_params(),
            {"reasoning": {"effort": "medium"}},
        )

    def test_reasoning_params_none_when_disabled(self) -> None:
        cfg = AgentModelConfig(model="m", thinking_enabled=False)
        self.assertIsNone(cfg.get_reasoning_params())


class RequireAgentModelsTests(unittest.TestCase):
    def _ctx(self, **kwargs: object) -> LLMContext:
        base = dict(
            api_key=SecretStr("k"),
            model="main",
            provider=AIProviderEnum.OPENROUTER,
            agent_models={},
            openrouter_api_key=SecretStr("or"),
            generalcompute_api_key=SecretStr("gc"),
        )
        base.update(kwargs)
        return LLMContext(**base)  # type: ignore[arg-type]

    def test_missing_roles_raise_400(self) -> None:
        ctx = self._ctx(
            agent_models={
                "researcher": AgentModelConfig(model="r"),
            }
        )
        with self.assertRaises(HTTPException) as cm:
            require_agent_models(ctx)
        self.assertEqual(cm.exception.status_code, 400)
        detail = str(cm.exception.detail).lower()
        self.assertIn("planner", detail)

    def test_all_roles_pass(self) -> None:
        models = {
            role: AgentModelConfig(model=f"{role}-m")
            for role in REQUIRED_AGENT_ROLES
        }
        require_agent_models(self._ctx(agent_models=models))

    def test_cross_provider_missing_key_raises(self) -> None:
        models = {
            "researcher": AgentModelConfig(
                model="r",
                provider=AIProviderEnum.GENERALCOMPUTE,
            ),
            "planner": AgentModelConfig(model="p"),
            "generator": AgentModelConfig(model="g"),
            "quizzer": AgentModelConfig(model="q"),
        }
        ctx = self._ctx(
            agent_models=models,
            generalcompute_api_key=None,
        )
        with self.assertRaises(HTTPException) as cm:
            require_agent_models(ctx)
        self.assertEqual(cm.exception.status_code, 400)


class GetLlmContextAgentHeadersTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_role_headers(self) -> None:
        ctx = await get_llm_context(
            x_ai_provider="openrouter",
            x_openrouter_key="or-secret",
            x_generalcompute_key="gc-secret",
            x_openrouter_model="main/model",
            x_generalcompute_model=None,
            x_max_completion_tokens=None,
            http_referer=None,
            x_openrouter_title=None,
            x_thinking_enabled="true",
            x_thinking_effort="high",
            x_researcher_model="r-m",
            x_researcher_provider="openrouter",
            x_researcher_thinking_enabled=None,
            x_researcher_thinking_effort=None,
            x_planner_model="p-m",
            x_planner_provider="generalcompute",
            x_planner_thinking_enabled=None,
            x_planner_thinking_effort=None,
            x_generator_model="g-m",
            x_generator_provider="openrouter",
            x_generator_thinking_enabled="true",
            x_generator_thinking_effort="medium",
            x_quizzer_model="q-m",
            x_quizzer_provider=None,
            x_quizzer_thinking_enabled=None,
            x_quizzer_thinking_effort=None,
        )
        self.assertEqual(ctx.agent_models["researcher"].model, "r-m")
        self.assertEqual(
            ctx.agent_models["planner"].provider,
            AIProviderEnum.GENERALCOMPUTE,
        )
        self.assertTrue(ctx.agent_models["generator"].thinking_enabled)
        self.assertEqual(
            ctx.agent_models["generator"].thinking_effort, "medium"
        )
        self.assertEqual(ctx.get_api_key_for_provider(
            AIProviderEnum.GENERALCOMPUTE
        ), "gc-secret")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd server
.venv\Scripts\python -m unittest server.tests.test_llm_context_agent_models
```

- [ ] **Step 3: Implement schemas in `server/schemas/llm.py`**

Keep 80-char lines. Core additions:

```python
REQUIRED_AGENT_ROLES: tuple[str, ...] = (
    "researcher",
    "planner",
    "generator",
    "quizzer",
)

_VALID_EFFORTS = frozenset(
    {"minimal", "low", "medium", "high", "xhigh"}
)


class AgentModelConfig(BaseModel):
    """Per-agent model, optional provider, and thinking settings."""

    model_config = ConfigDict(from_attributes=True)

    model: str = Field(..., min_length=1)
    provider: Optional[AIProviderEnum] = Field(
        default=None,
        description="Override provider; default LLMContext.provider",
    )
    thinking_enabled: bool = False
    thinking_effort: Optional[str] = Field(
        default=None,
        pattern="^(minimal|low|medium|high|xhigh)$",
    )

    def get_reasoning_params(self) -> Optional[dict[str, Any]]:
        if not self.thinking_enabled:
            return None
        effort = self.thinking_effort or "high"
        return {"reasoning": {"effort": effort}}


class LLMContext(BaseModel):
    # ...existing fields...
    openrouter_api_key: Optional[SecretStr] = Field(
        default=None,
        repr=False,
        exclude=True,
    )
    generalcompute_api_key: Optional[SecretStr] = Field(
        default=None,
        repr=False,
        exclude=True,
    )
    agent_models: dict[str, AgentModelConfig] = Field(
        default_factory=dict,
        description="Per-role model configs from request headers",
    )

    def get_api_key_for_provider(
        self, provider: AIProviderEnum
    ) -> str:
        """Resolve plaintext key for a provider (role-aware)."""
        if provider == AIProviderEnum.OPENROUTER:
            secret = self.openrouter_api_key or (
                self.api_key
                if self.provider == AIProviderEnum.OPENROUTER
                else None
            )
        else:
            secret = self.generalcompute_api_key or (
                self.api_key
                if self.provider == AIProviderEnum.GENERALCOMPUTE
                else None
            )
        if secret is None:
            return ""
        return secret.get_secret_value()

    def resolve_agent_call(
        self, role: str
    ) -> tuple[str, AIProviderEnum, str, Optional[dict[str, Any]]]:
        """
        Returns (model, provider, api_key, reasoning_params).

        For researcher/planner/generator/quizzer: require agent_models.
        For depth_router / unknown: main model + global thinking.
        """
        if role in REQUIRED_AGENT_ROLES:
            cfg = self.agent_models.get(role)
            if cfg is None or not cfg.model.strip():
                raise ValueError(
                    f"Missing agent model for role '{role}'. "
                    "Configure all four agent models in Settings."
                )
            provider = cfg.provider or self.provider
            key = self.get_api_key_for_provider(provider)
            if not key:
                raise ValueError(
                    f"Missing API key for provider "
                    f"'{provider.value}' (role={role})."
                )
            return (
                cfg.model.strip(),
                provider,
                key,
                cfg.get_reasoning_params(),
            )
        # depth_router and fallback
        if not self.model or not str(self.model).strip():
            raise ValueError(
                f"No model specified for role '{role}'."
            )
        return (
            str(self.model).strip(),
            self.provider,
            self.get_api_key(),
            self.get_reasoning_params(),
        )


def require_agent_models(llm_context: LLMContext) -> None:
    """Raise HTTP 400 if required agent roles/keys incomplete."""
    missing: list[str] = []
    for role in REQUIRED_AGENT_ROLES:
        cfg = llm_context.agent_models.get(role)
        if cfg is None or not cfg.model.strip():
            missing.append(role)
            continue
        provider = cfg.provider or llm_context.provider
        if not llm_context.get_api_key_for_provider(provider):
            missing.append(f"{role} key ({provider.value})")
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Missing required agent model configuration: "
                + ", ".join(missing)
                + ". Set Researcher, Planner, Generator, and "
                "Quizzer models (and keys) in Settings."
            ),
        )


def _parse_role_agent(
    model: Optional[str],
    provider_str: Optional[str],
    thinking_enabled: Optional[str],
    thinking_effort: Optional[str],
) -> Optional[AgentModelConfig]:
    if not model or not model.strip():
        return None
    provider = None
    if provider_str in {p.value for p in AIProviderEnum}:
        provider = AIProviderEnum(provider_str)
    enabled = bool(
        thinking_enabled and thinking_enabled.lower() == "true"
    )
    effort = None
    if thinking_effort and thinking_effort in _VALID_EFFORTS:
        effort = thinking_effort
    elif enabled:
        effort = "high"
    return AgentModelConfig(
        model=model.strip(),
        provider=provider,
        thinking_enabled=enabled,
        thinking_effort=effort,
    )
```

Extend `get_llm_context` signature with role headers (alias exact names from goal):

```python
async def get_llm_context(
    # ...existing params...
    x_researcher_model: Optional[str] = Header(
        None, alias="X-Researcher-Model"
    ),
    x_researcher_provider: Optional[str] = Header(
        None, alias="X-Researcher-Provider"
    ),
    x_researcher_thinking_enabled: Optional[str] = Header(
        None, alias="X-Researcher-Thinking-Enabled"
    ),
    x_researcher_thinking_effort: Optional[str] = Header(
        None, alias="X-Researcher-Thinking-Effort"
    ),
    # ... same for planner, generator, quizzer ...
) -> LLMContext:
```

When building return value, always stash both keys:

```python
agent_models: dict[str, AgentModelConfig] = {}
for role, parsed in (
    ("researcher", _parse_role_agent(
        x_researcher_model, x_researcher_provider,
        x_researcher_thinking_enabled,
        x_researcher_thinking_effort,
    )),
    # planner, generator, quizzer ...
):
    if parsed is not None:
        agent_models[role] = parsed

return LLMContext(
    provider=provider,
    api_key=SecretStr(api_key.strip()),
    model=model,
    # ...
    openrouter_api_key=(
        SecretStr(x_openrouter_key.strip())
        if x_openrouter_key and x_openrouter_key.strip()
        else None
    ),
    generalcompute_api_key=(
        SecretStr(x_generalcompute_key.strip())
        if x_generalcompute_key and x_generalcompute_key.strip()
        else None
    ),
    agent_models=agent_models,
)
```

**Note:** Existing tests construct `LLMContext(api_key=..., model=...)` — new optional fields default empty so they keep working.

- [ ] **Step 4: Run tests — PASS**

```bash
cd server
.venv\Scripts\python -m unittest server.tests.test_llm_context_agent_models
```

- [ ] **Step 5: Commit**

```bash
git add server/schemas/llm.py server/tests/test_llm_context_agent_models.py
git commit -m "feat(agent-models): parse role headers into LLMContext.agent_models"
```

---

### Task 9: Validate on learning mutating routes

**Files:**
- Modify: `server/routers/learning.py`
- Extend: `server/tests/test_llm_context_agent_models.py` or `test_learning_graph_router.py` / `test_generation_api.py`

- [ ] **Step 1: Call validation at start of**

- `generate_course` (`POST /learning/generate`)
- `resume_generation` (`POST /learning/sessions/{id}/resume`)
- `regenerate_node_endpoint` (`POST /learning/nodes/{id}/regenerate`)
- `stream_regenerate_node_endpoint` (`POST /learning/nodes/{id}/regenerate/stream`)

```python
from server.schemas.llm import LLMContext, get_llm_context, require_agent_models

async def generate_course(...):
    require_agent_models(llm_context)
    ...
```

Do **not** validate on chat endpoint.

- [ ] **Step 2: Add API-level test** (TestClient) that generate without agent headers → 400 with detail listing missing roles. Prefer overriding nothing and sending headers, or unit-test `require_agent_models` already covers logic — add one router integration if easy via existing harness.

If existing tests override `get_llm_context` with bare `LLMContext(api_key=..., model=...)`, update those overrides used for generate/resume/regen to include full `agent_models` dict so tests keep passing:

```python
def _test_llm() -> LLMContext:
    roles = ("researcher", "planner", "generator", "quizzer")
    return LLMContext(
        api_key="test-key",
        model="test/model",
        agent_models={
            r: AgentModelConfig(model=f"test/{r}") for r in roles
        },
    )
```

Search and fix:

```bash
# from repo root
rg "get_llm_context|LLMContext\(" server/tests -n
```

Update overrides that hit generate/resume/regen paths.

- [ ] **Step 3: Run server tests subset**

```bash
cd server
.venv\Scripts\python -m unittest server.tests.test_llm_context_agent_models server.tests.test_generation_api server.tests.test_learning_graph_router server.tests.test_regen_stream
```

- [ ] **Step 4: Commit**

```bash
git add server/routers/learning.py server/tests/
git commit -m "feat(agent-models): require four agent models on generate/resume/regen"
```

---

## Phase 5 — Runtime resolution

### Task 10: BaseAgent uses resolve_agent_call (TDD)

**Files:**
- Modify: `server/agents/base.py`
- Create: `server/tests/test_agent_model_resolution.py`
- Modify: `server/graph/regen_stream.py`

- [ ] **Step 1: Write resolution tests**

```python
"""
============================================================================
FILE: test_agent_model_resolution.py
LOCATION: server/tests/test_agent_model_resolution.py
============================================================================
"""

import unittest
from unittest.mock import AsyncMock, patch

from pydantic import BaseModel, SecretStr

from server.agents.base import BaseAgent
from server.schemas.llm import (
    AIProviderEnum,
    AgentModelConfig,
    LLMContext,
)


class _Out(BaseModel):
    ok: bool = True


class _StubAgent(BaseAgent):
    @property
    def system_prompt(self) -> str:
        return "stub"


class ResolveAgentCallTests(unittest.TestCase):
    def test_role_uses_agent_model_not_main(self) -> None:
        ctx = LLMContext(
            api_key=SecretStr("or"),
            model="main/model",
            provider=AIProviderEnum.OPENROUTER,
            openrouter_api_key=SecretStr("or"),
            generalcompute_api_key=SecretStr("gc"),
            agent_models={
                "planner": AgentModelConfig(
                    model="planner/model",
                    provider=AIProviderEnum.GENERALCOMPUTE,
                    thinking_enabled=True,
                    thinking_effort="low",
                )
            },
        )
        model, provider, key, reasoning = ctx.resolve_agent_call(
            "planner"
        )
        self.assertEqual(model, "planner/model")
        self.assertEqual(provider, AIProviderEnum.GENERALCOMPUTE)
        self.assertEqual(key, "gc")
        self.assertEqual(
            reasoning, {"reasoning": {"effort": "low"}}
        )

    def test_depth_router_uses_main(self) -> None:
        ctx = LLMContext(
            api_key=SecretStr("or"),
            model="main/model",
            thinking_enabled=True,
            thinking_effort="high",
            agent_models={
                "planner": AgentModelConfig(model="p"),
            },
        )
        model, provider, key, reasoning = ctx.resolve_agent_call(
            "depth_router"
        )
        self.assertEqual(model, "main/model")
        self.assertEqual(provider, AIProviderEnum.OPENROUTER)
        self.assertEqual(
            reasoning, {"reasoning": {"effort": "high"}}
        )


class BaseAgentGenerateResolutionTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_generate_passes_resolved_model(self) -> None:
        agent = _StubAgent(role="quizzer")
        ctx = LLMContext(
            api_key=SecretStr("or"),
            model="main/model",
            openrouter_api_key=SecretStr("or"),
            agent_models={
                "quizzer": AgentModelConfig(
                    model="quiz/model",
                    thinking_enabled=False,
                )
            },
        )
        with patch(
            "server.agents.base.instructor_client.create_structured",
            new_callable=AsyncMock,
        ) as mock_cs:
            mock_cs.return_value = _Out()
            await agent.generate(
                response_model=_Out,
                user_message="hi",
                llm_context=ctx,
            )
            kwargs = mock_cs.await_args.kwargs
            self.assertEqual(kwargs["model_override"], "quiz/model")
            self.assertEqual(kwargs["api_key"], "or")
            self.assertIsNone(kwargs["reasoning_params"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run — FAIL** until base.py updated

```bash
cd server
.venv\Scripts\python -m unittest server.tests.test_agent_model_resolution
```

- [ ] **Step 3: Update `BaseAgent.generate`**

Replace model/provider/key/reasoning extraction:

```python
model_override, provider, api_key, reasoning_params = (
    llm_context.resolve_agent_call(self._role)
)
attribution_headers = llm_context.get_attribution_headers()
# If role provider is openrouter but context.provider is GC,
# attribution still OK (empty for GC). Optional improvement:
# only attach OpenRouter attribution when provider is OPENROUTER.

response = await instructor_client.create_structured(
    role=self._role,
    response_model=response_model,
    messages=messages,
    api_key=api_key,
    model_override=model_override,
    attribution_headers=attribution_headers,
    system_prompt=full_system_prompt,
    provider=provider,
    reasoning_params=reasoning_params,
    max_completion_tokens=llm_context.max_completion_tokens,
    **kwargs,
)
```

Remove earlier single-key-only checks that block before resolve; still raise if resolve returns empty key.

- [ ] **Step 4: Update `regen_stream.py`**

Where it currently does:

```python
model_override = llm_context.model
...
provider=llm_context.provider
reasoning_params = llm_context.get_reasoning_params()
api_key = llm_context.get_api_key()
```

Replace with:

```python
model_slug, provider, api_key, reasoning_params = (
    llm_context.resolve_agent_call(generator_agent.role)
)
```

Use `provider` for `_get_provider_config(provider)` and client construction.

- [ ] **Step 5: Verify `depth_router.py` still uses main path**

`classify_depth` already passes `role="depth_router"` and `model_override=llm_context.model`. Optionally refactor to `resolve_agent_call("depth_router")` for consistency — recommended:

```python
model, provider, key, reasoning = llm_context.resolve_agent_call(
    "depth_router"
)
return await instructor_client.create_structured(
    role="depth_router",
    ...
    api_key=key,
    model_override=model,
    provider=provider,
    reasoning_params=reasoning,
    ...
)
```

- [ ] **Step 6: Run tests**

```bash
cd server
.venv\Scripts\python -m unittest server.tests.test_agent_model_resolution server.tests.test_depth_router server.tests.test_regen_stream server.tests.test_researcher_agent server.tests.test_generator_agent
```

- [ ] **Step 7: Commit**

```bash
git add server/agents/base.py server/graph/regen_stream.py \
  server/services/depth_router.py \
  server/tests/test_agent_model_resolution.py
git commit -m "feat(agent-models): resolve per-role model/provider/thinking at runtime"
```

---

## Phase 6 — Integration polish + quality gates

### Task 11: Fix test harnesses + full suite

**Files:**
- Any remaining `server/tests/*` that construct bare `LLMContext` for full graph runs
- Client mocks missing `agentModels`

- [ ] **Step 1: Grep and fix incomplete fixtures**

```bash
rg "LLMContext\(" server/tests -n
rg "getProviderSettings" client/src -g "*.test.*"
```

For server graph/runtime tests that actually invoke agents with real `BaseAgent.generate`, supply `agent_models` for all four roles. For pure mocks of `create_structured`, bare context may still work if generate is mocked.

For client tests mocking settings without agent models, either add four roles or mock `areAgentModelsConfigured` if the component under test only checks API key.

- [ ] **Step 2: Run full server unit tests**

```bash
cd server
.venv\Scripts\python -m unittest
```

Expected: all PASS

- [ ] **Step 3: Run full client checks**

```bash
cd client
npm run test -- --run
npm run lint
npm run build
```

Expected: all PASS

- [ ] **Step 4: Manual smoke checklist** (document in commit message if done)

1. Settings → set main Default/Depth Router model + four agent models (mix providers if both keys set).
2. Start course → network tab shows `X-Researcher-Model` … `X-Quizzer-Model`.
3. Incomplete agents → Learn disabled + amber message.
4. Resume + regen still send role headers.
5. Chat still uses `X-Chat-Model` only; no agent headers required.
6. depth auto mode still works with main model.

- [ ] **Step 5: Final commit**

```bash
git add -A
git status
git commit -m "test(agent-models): align fixtures and pass quality gates"
```

---

## Header name reference (single source)

| Role | Model | Provider | Thinking enabled | Thinking effort |
|------|-------|----------|------------------|-----------------|
| researcher | `X-Researcher-Model` | `X-Researcher-Provider` | `X-Researcher-Thinking-Enabled` | `X-Researcher-Thinking-Effort` |
| planner | `X-Planner-Model` | `X-Planner-Provider` | `X-Planner-Thinking-Enabled` | `X-Planner-Thinking-Effort` |
| generator | `X-Generator-Model` | `X-Generator-Provider` | `X-Generator-Thinking-Enabled` | `X-Generator-Thinking-Effort` |
| quizzer | `X-Quizzer-Model` | `X-Quizzer-Provider` | `X-Quizzer-Thinking-Enabled` | `X-Quizzer-Thinking-Effort` |

Plus existing: `X-AI-Provider`, `X-OpenRouter-Key`, `X-GeneralCompute-Key`, `X-OpenRouter-Model` / `X-GeneralCompute-Model`, global `X-Thinking-*` for depth_router.

---

## Spec coverage checklist

| Goal requirement | Task(s) |
|------------------|---------|
| Four role pickers + per-role thinking | 4 |
| Cross-provider per role | 4, 5, 8, 10 |
| All four required (no fallback) | 2, 5, 7, 9 |
| Server resolve model/key/thinking per role | 8, 10 |
| Chat unchanged | Explicit non-touch + Task 3 |
| Main model = Default / Depth Router | 3, 10 |
| Tests: persistence, headers, validation, resolution | 2, 5, 6, 8, 10, 11 |
| Lint/typecheck/build/unittest | 11 |
| Headers Approach A | 5, 6, 8 |
| depth_router no picker | out of scope; uses main | 

---

## Risks + mitigations (execution)

| Risk | Mitigation |
|------|------------|
| Many tests construct bare `LLMContext` | Task 9/11 batch-update fixtures with four agent_models |
| Hooks-in-map in AgentModelsPanel | Compute supportsThinking without hooks inside loop |
| Cross-provider missing secondary key | Client sends both keys; server `require_agent_models` checks |
| regen_stream bypasses BaseAgent | Task 10 explicitly updates regen_stream |
| Quote style drift (TS single vs double) | Match file being edited |
| Python 80-col | Wrap headers / long strings |

---

## Out of scope (do not implement)

- depth_router Settings picker
- SQLite persistence of agent models on jobs
- Per-role max_completion_tokens
- Chat thinking toggle / chat fallback changes
- Cost estimator / auto model pick

---

## Execution handoff

Plan complete and saved to `docs/per-agent-model-selection/plan.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — execute tasks in one session with checkpoints  

Which approach?
