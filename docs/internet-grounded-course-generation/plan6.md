# Internet-Grounded Course Generation Implementation Plan — Phase 6: Progressive Client UI

> **Planning method:** I used writing-plans skill principles: TDD, bite-sized tasks, exact paths, and no placeholders.
>
> **For agentic workers:** REQUIRED: TDD via test-driven-development skill; execute via executing-plans or subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** Let users configure optional web search, opt in per course, navigate immediately to a progressive course, observe SSE/polling stages and skeletons, inspect sources/citations, stop while retaining work, resume with fresh keys, or delete permanently.

**Architecture:** Existing localStorage settings remain browser source of truth. Search keys are built explicitly for generate/resume only; normal session/quiz/research/cancel/delete calls receive no provider secrets. `LearningPage` owns one React Query session snapshot, two-second repair polling, and a credential-free `EventSource`. `LearningPathContainer` renders passed progressive state, replacing generation skeletons with cards without resetting learner carousel state. Sources and citations are structured data, never model-created URLs.

**Tech Stack:** React 19, TypeScript strict mode, React Query 5, browser `EventSource`, Axios, Vitest, Testing Library, Tailwind 4.x, Lucide.

**Depends on:** Phase 5.

**Deliverable:** Responsive Settings, TopicInput, progressive session, sources, citation, warning, cancel/resume/delete flows satisfying every locked UX decision.

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `client/src/features/settings/WebSearchSettingsPanel.tsx` | Master toggle and four curated provider cards. |
| Create | `client/src/features/settings/WebSearchSettingsPanel.test.tsx` | Default-off, hidden controls, key, links, validation tests. |
| Modify | `client/src/features/settings/SettingsPage.tsx` | Add web-search section and accurate key-boundary copy. |
| Create | `client/src/lib/webSearchHeaders.ts` | Pure explicit web-search request header builder. |
| Create | `client/src/lib/webSearchHeaders.test.ts` | OFF/ON/provider-selection header tests. |
| Modify | `client/src/lib/learningApi.ts` | `202`, research, cancel/resume, explicit LLM/search headers, no global secret interceptor. |
| Create | `client/src/lib/learningApi.test.ts` | Endpoint/secret-scope tests with mocked Axios instances. |
| Modify | `client/src/types/learning.ts` | Import generation types; add module status, citations, accepted/control responses. |
| Modify | `client/src/features/learning/TopicInput.tsx` | Hidden capability icon, per-course OFF state, immediate shell navigation. |
| Create | `client/src/features/learning/TopicInput.test.tsx` | Icon visibility/state and `202` navigation tests. |
| Create | `client/src/features/learning/generationEvents.ts` | Immutable event-ID reducer for session cache. |
| Create | `client/src/features/learning/generationEvents.test.ts` | Duplicate/out-of-order/stage event tests. |
| Create | `client/src/features/learning/useSessionEvents.ts` | EventSource lifecycle, cache updates, query invalidation. |
| Create | `client/src/features/learning/useSessionEvents.test.tsx` | Cursor, event listeners, reconnect/fallback/cleanup tests. |
| Create | `client/src/features/learning/GenerationStatusPanel.tsx` | Stage, counts, warning, and controls. |
| Create | `client/src/features/learning/GenerationStatusPanel.test.tsx` | Research/outline/generation/degraded/cancelled states. |
| Modify | `client/src/features/learning/LearningPage.tsx` | Authoritative session query, SSE, repair polling, panels, controls. |
| Modify | `client/src/features/learning/LearningPathContainer.tsx` | Render shells, module skeletons, and arriving cards from session prop. |
| Modify | `client/src/features/learning/SkeletonCard.tsx` | Topic-aware static/animated module skeleton. |
| Modify | `client/src/features/learning/TableOfContentsModal.tsx` | Distinguish generation from learner locks. |
| Create | `client/src/features/learning/CourseSourcesPanel.tsx` | Report sections, normalized sources, providers, limitations, warnings. |
| Create | `client/src/features/learning/CourseSourcesPanel.test.tsx` | Partial/degraded/complete source rendering tests. |
| Create | `client/src/features/learning/SourceCitations.tsx` | Validated card citation footer. |
| Create | `client/src/features/learning/SourceCitations.test.tsx` | Numbering/link safety/provider tests. |
| Modify | `client/src/features/learning/ConceptCard.tsx` | Render citation footer and Sources action. |
| Modify | `client/src/features/learning/CourseCard.tsx` | Generating/paused/cancelled/degraded dashboard badges. |
| Modify | `client/src/features/learning/index.ts` | Named exports for new components/hooks. |
| Create | `client/src/test/FakeEventSource.ts` | Deterministic native EventSource test double. |

## Client Contract Decisions

- Master setting defaults OFF; provider cards hidden while OFF.
- Search icon hidden unless master is ON and at least one enabled provider has nonblank key.
- Icon starts unselected for every `TopicInput` mount/new course.
- `generateCourse()` returns `{ session, generation }`; TopicInput seeds cache and navigates to `/learn/{id}` immediately.
- Poll every 2 seconds until generation stage is terminal, including while concept chat streams.
- SSE is credential-free; event IDs reject duplicate/out-of-order cache updates.
- `GROUNDED` alone may show web-grounded label. `DEGRADED` always shows warning.
- Stop retains all current nodes/report. Resume sends fresh credentials. Delete remains explicit permanent cleanup.

## Tasks

### Task 6.1: Build Default-Off Web Search Settings Panel

**Files:**
- Create: `client/src/features/settings/WebSearchSettingsPanel.tsx`
- Create: `client/src/features/settings/WebSearchSettingsPanel.test.tsx`
- Modify: `client/src/features/settings/SettingsPage.tsx`

- [ ] **Step 1: Write failing Settings panel tests**

Create `client/src/features/settings/WebSearchSettingsPanel.test.tsx`:

```tsx
/**
 * ============================================================================
 * FILE: WebSearchSettingsPanel.test.tsx
 * LOCATION: client/src/features/settings/WebSearchSettingsPanel.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests optional web-search settings and curated provider controls.
 *
 * ROLE IN PROJECT:
 *    Guards default-off visibility, local validation, metadata, and persistence.
 *
 * KEY COMPONENTS:
 *    - WebSearchSettingsPanel interaction tests
 *
 * DEPENDENCIES:
 *    - External: @testing-library/react, vitest
 *    - Internal: WebSearchSettingsPanel, providerSettings
 *
 * USAGE:
 *    npm run test -- --run src/features/settings/WebSearchSettingsPanel.test.tsx
 * ============================================================================
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { WebSearchSettingsPanel } from './WebSearchSettingsPanel';

describe('WebSearchSettingsPanel', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('starts off and hides all provider cards', () => {
    render(<WebSearchSettingsPanel />);
    expect(
      screen.getByRole('switch', { name: /enable web search/i }),
    ).not.toBeChecked();
    expect(screen.queryByText('Tavily')).not.toBeInTheDocument();
    expect(screen.queryByText('Brave Search')).not.toBeInTheDocument();
  });

  it('shows exactly four provider cards after enabling master switch', () => {
    render(<WebSearchSettingsPanel />);
    fireEvent.click(
      screen.getByRole('switch', { name: /enable web search/i }),
    );
    for (const label of ['Tavily', 'Exa', 'Brave Search', 'SerpAPI']) {
      expect(screen.getByRole('heading', { name: label })).toBeInTheDocument();
    }
    expect(screen.getByText(/card required/i)).toBeInTheDocument();
    expect(screen.getByText(/attribution/i)).toBeInTheDocument();
  });

  it('requires a nonblank key before enabling a provider', () => {
    render(<WebSearchSettingsPanel />);
    fireEvent.click(
      screen.getByRole('switch', { name: /enable web search/i }),
    );
    fireEvent.click(
      screen.getByRole('checkbox', { name: /enable tavily/i }),
    );
    expect(screen.getByRole('alert')).toHaveTextContent(/api key is required/i);
    expect(
      screen.getByRole('checkbox', { name: /enable tavily/i }),
    ).not.toBeChecked();
  });

  it('stores key locally and enables configured provider without network call', () => {
    render(<WebSearchSettingsPanel />);
    fireEvent.click(
      screen.getByRole('switch', { name: /enable web search/i }),
    );
    fireEvent.change(screen.getByLabelText(/tavily api key/i), {
      target: { value: 'tvly-browser-key' },
    });
    fireEvent.click(
      screen.getByRole('checkbox', { name: /enable tavily/i }),
    );
    expect(
      screen.getByRole('checkbox', { name: /enable tavily/i }),
    ).toBeChecked();
    expect(localStorage.getItem('web_search_settings')).toContain(
      'tvly-browser-key',
    );
  });

  it('uses safe external signup and docs links', () => {
    render(<WebSearchSettingsPanel />);
    fireEvent.click(
      screen.getByRole('switch', { name: /enable web search/i }),
    );
    const signup = screen.getByRole('link', { name: /get tavily key/i });
    expect(signup).toHaveAttribute('href', 'https://app.tavily.com');
    expect(signup).toHaveAttribute('target', '_blank');
    expect(signup).toHaveAttribute('rel', 'noreferrer noopener');
  });
});
```

- [ ] **Step 2: Run test and verify red state**

Run from `D:\Peter\A2UI\client`:

```powershell
npm run test -- --run src/features/settings/WebSearchSettingsPanel.test.tsx
```

Expected: FAIL because component does not exist.

- [ ] **Step 3: Implement panel and Settings integration**

Build `WebSearchSettingsPanel` from `WEB_SEARCH_PROVIDER_IDS`, `WEB_SEARCH_PROVIDERS`, and Phase 1 settings helpers. Use named export, mandatory header, semantic switch/checkbox/labels, password inputs with provider-specific placeholders, signup/docs external links, free-tier copy, recommended Tavily badge, Brave payment/attribution warning, and inline blank-key validation. Persist on each user change; do not send verification request.

When master turns OFF, keep provider keys/enabled choices in localStorage but hide cards and capability becomes false. This preserves setup while feature remains inactive.

Add Settings section after AI Provider Credentials. Replace inaccurate copy `never uploaded to our servers` with:

```text
Keys are stored in this browser. A2UI sends an AI key only for model work and sends search keys only when a web-enabled course start or resume requires them.
```

Panel layout is one column on mobile and two columns from `md`; preserve current Cyber Yellow accent/card radius/glass treatment.

- [ ] **Step 4: Run Settings tests, lint, and build**

Run:

```powershell
npm run test -- --run src/features/settings/WebSearchSettingsPanel.test.tsx
npm run lint
npm run build
```

Expected: 5 tests PASS; lint/build PASS.

- [ ] **Step 5: Commit Settings UI**

```powershell
git add client/src/features/settings/WebSearchSettingsPanel.tsx client/src/features/settings/WebSearchSettingsPanel.test.tsx client/src/features/settings/SettingsPage.tsx
git commit -m "feat(settings): add web search provider controls"
```

### Task 6.2: Scope Secrets and Add Progressive Learning API Calls

**Files:**
- Create: `client/src/lib/webSearchHeaders.ts`
- Create: `client/src/lib/webSearchHeaders.test.ts`
- Modify: `client/src/lib/learningApi.ts`
- Create: `client/src/lib/learningApi.test.ts`
- Modify: `client/src/types/learning.ts`

- [ ] **Step 1: Write failing header and endpoint-scope tests**

Create `client/src/lib/webSearchHeaders.test.ts`:

```typescript
/**
 * ============================================================================
 * FILE: webSearchHeaders.test.ts
 * LOCATION: client/src/lib/webSearchHeaders.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Tests explicit web-search header construction.
 *
 * ROLE IN PROJECT:
 *    Prevents search credentials from reaching unrelated API endpoints.
 *
 * KEY COMPONENTS:
 *    - buildWebSearchHeaders tests
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: @/lib/webSearchHeaders
 *
 * USAGE:
 *    npm run test -- --run src/lib/webSearchHeaders.test.ts
 * ============================================================================
 */

import { describe, expect, it } from 'vitest';

import { WebSearchConfigurationError, buildWebSearchHeaders } from './webSearchHeaders';
import type { WebSearchSettings } from '@/types/webSearch';

const settings: WebSearchSettings = {
  masterEnabled: true,
  providers: {
    tavily: { apiKey: ' tvly-secret ', enabled: true },
    exa: { apiKey: 'exa-unused', enabled: false },
    brave: { apiKey: 'brave-secret', enabled: true },
    serpapi: { apiKey: '', enabled: false },
  },
};

describe('buildWebSearchHeaders', () => {
  it('returns only false flag when course opt-in is off', () => {
    expect(buildWebSearchHeaders(false, settings)).toEqual({
      'X-Web-Search': 'false',
    });
  });

  it('returns only selected configured provider keys in registry order', () => {
    expect(buildWebSearchHeaders(true, settings)).toEqual({
      'X-Web-Search': 'true',
      'X-Web-Search-Providers': 'tavily,brave',
      'X-Tavily-Key': 'tvly-secret',
      'X-Brave-Key': 'brave-secret',
    });
  });

  it('rejects opt-in when master or configured providers are unavailable', () => {
    expect(() =>
      buildWebSearchHeaders(true, { ...settings, masterEnabled: false }),
    ).toThrow(WebSearchConfigurationError);
    expect(() =>
      buildWebSearchHeaders(true, {
        masterEnabled: true,
        providers: {
          tavily: { apiKey: '', enabled: false },
          exa: { apiKey: '', enabled: false },
          brave: { apiKey: '', enabled: false },
          serpapi: { apiKey: '', enabled: false },
        },
      }),
    ).toThrow(WebSearchConfigurationError);
  });
});
```

Create `client/src/lib/learningApi.test.ts` with a hoisted Axios fake that records `get/post/delete` configs. Test this exact matrix:

```typescript
it.each([
  ['getLearningSession', () => getLearningSession('session-1')],
  ['getCourseResearch', () => getCourseResearch('session-1')],
  ['cancelGeneration', () => cancelGeneration('session-1')],
  ['deleteSession', () => deleteSession('session-1')],
])('%s sends no AI or search key headers', async (_name, invoke) => {
  await invoke();
  const headers = lastRequestConfig()?.headers ?? {};
  expect(JSON.stringify(headers)).not.toMatch(
    /X-OpenRouter-Key|X-GeneralCompute-Key|X-Tavily-Key|X-Exa-Key|X-Brave-Key|X-SerpApi-Key/i,
  );
});

it('generate and resume attach fresh AI and selected search headers', async () => {
  await generateCourse({ query: 'Topic' }, { webSearchEnabled: true });
  expect(lastRequestConfig()?.headers).toMatchObject({
    'X-OpenRouter-Key': 'llm-secret',
    'X-Web-Search': 'true',
    'X-Tavily-Key': 'tvly-secret',
  });
  await resumeGeneration('session-1', { webSearchEnabled: true });
  expect(lastRequestConfig()?.headers).toMatchObject({
    'X-OpenRouter-Key': 'llm-secret',
    'X-Web-Search': 'true',
    'X-Tavily-Key': 'tvly-secret',
  });
});
```

The complete test file must define/import the named functions, `lastRequestConfig`, mocked `getProviderSettings`, and mocked `getWebSearchSettings`; every fake request resolves correctly typed minimal data.

- [ ] **Step 2: Run tests and verify red state**

Run:

```powershell
npm run test -- --run src/lib/webSearchHeaders.test.ts src/lib/learningApi.test.ts
```

Expected: FAIL because header builder/endpoints do not exist and global interceptor leaks AI headers.

- [ ] **Step 3: Implement pure headers and explicit endpoint clients**

`buildWebSearchHeaders(courseEnabled, settings=getWebSearchSettings())` follows tests and throws `WebSearchConfigurationError` before request when selected without capability.

Remove `attachProviderHeaders` from standard Axios instance and remove long-timeout generation instance. `202` start uses standard 30-second client. Add private `buildLlmHeaders()` from active provider settings. Explicitly attach LLM plus web headers only to:

```typescript
generateCourse(data, options): Promise<GenerateCourseAcceptedResponse>
resumeGeneration(sessionId, options): Promise<GenerationControlResponse>
```

Keep explicit LLM headers for `regenerateNode`; existing `regenApi.ts` and concept chat retain their own credential handling. Add:

```typescript
getCourseResearch(sessionId): Promise<ResearchReport>
cancelGeneration(sessionId): Promise<GenerationControlResponse>
resumeGeneration(sessionId, options): Promise<GenerationControlResponse>
```

Session/quiz/revision/research/cancel/delete calls send no AI or web keys. Let Axios throw; preserve generic response interceptor without logging request headers.

Update `learning.ts` with `ModuleGenerationStatus`, `NodeCitation`, `generation_status` API mapping as `module_status`, `LearningSessionWithNodes.generation`, accepted/control response types, and imports from `types/generation`. Brief type remains absent.

- [ ] **Step 4: Run API tests, lint, and build**

Run:

```powershell
npm run test -- --run src/lib/webSearchHeaders.test.ts src/lib/learningApi.test.ts
npm run lint
npm run build
```

Expected: all API tests PASS; lint/build PASS.

- [ ] **Step 5: Commit client API changes**

```powershell
git add client/src/lib/webSearchHeaders.ts client/src/lib/webSearchHeaders.test.ts client/src/lib/learningApi.ts client/src/lib/learningApi.test.ts client/src/types/learning.ts
git commit -m "feat(client): add progressive generation API"
```

### Task 6.3: Add Per-Course Search Icon and Immediate Navigation

**Files:**
- Modify: `client/src/features/learning/TopicInput.tsx`
- Create: `client/src/features/learning/TopicInput.test.tsx`

- [ ] **Step 1: Write failing TopicInput tests**

Create `client/src/features/learning/TopicInput.test.tsx`:

```tsx
/**
 * ============================================================================
 * FILE: TopicInput.test.tsx
 * LOCATION: client/src/features/learning/TopicInput.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests per-course search opt-in and immediate accepted-shell navigation.
 *
 * ROLE IN PROJECT:
 *    Guards hidden capability and explicit OFF-by-default course behavior.
 *
 * KEY COMPONENTS:
 *    - TopicInput web-search interaction tests
 *
 * DEPENDENCIES:
 *    - External: React Query, Testing Library, Vitest
 *    - Internal: TopicInput, learningApi, providerSettings
 *
 * USAGE:
 *    npm run test -- --run src/features/learning/TopicInput.test.tsx
 * ============================================================================
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TopicInput } from './TopicInput';

const mocks = vi.hoisted(() => ({
  generateCourse: vi.fn(),
  navigate: vi.fn(),
  capability: true,
}));

vi.mock('@/lib/learningApi', () => ({
  generateCourse: mocks.generateCourse,
}));

vi.mock('@/lib/providerSettings', () => ({
  getProviderSettings: () => ({
    activeProvider: 'openrouter',
    providers: {
      openrouter: { apiKey: 'llm-key', model: 'test/model', modelTitle: 'Test' },
      generalcompute: { apiKey: '', model: '', modelTitle: '' },
    },
  }),
  hasWebSearchCapability: () => mocks.capability,
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return { ...actual, useNavigate: () => mocks.navigate };
});

function renderInput() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <TopicInput />
    </QueryClientProvider>,
  );
  return client;
}

describe('TopicInput web search', () => {
  beforeEach(() => {
    mocks.generateCourse.mockReset();
    mocks.navigate.mockReset();
    mocks.capability = true;
  });

  it('hides search icon when capability is unavailable', () => {
    mocks.capability = false;
    renderInput();
    expect(
      screen.queryByRole('button', { name: /use web search/i }),
    ).not.toBeInTheDocument();
  });

  it('shows search icon unselected for every new input mount', () => {
    const first = renderInput();
    expect(
      screen.getByRole('button', { name: /use web search/i }),
    ).toHaveAttribute('aria-pressed', 'false');
    first.clear();
  });

  it('submits selected search state and navigates from 202 shell', async () => {
    mocks.generateCourse.mockResolvedValue({
      session: {
        id: 'session-1',
        query: 'Modern CSS',
        course_title: 'Modern CSS',
        title_finalized: false,
        nodes: [],
      },
      generation: { id: 'job-1', stage: 'INITIALIZING', last_event_id: 1 },
    });
    const client = renderInput();
    fireEvent.change(screen.getByRole('searchbox'), {
      target: { value: 'Modern CSS' },
    });
    fireEvent.click(screen.getByRole('button', { name: /use web search/i }));
    expect(
      screen.getByRole('button', { name: /use web search/i }),
    ).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: /start learning/i }));
    await waitFor(() => {
      expect(mocks.generateCourse).toHaveBeenCalledWith(
        { query: 'Modern CSS', user_id: undefined, mode: 'auto' },
        { webSearchEnabled: true },
      );
    });
    expect(
      client.getQueryData(['learningSession', 'session-1']),
    ).toMatchObject({ id: 'session-1', generation: { id: 'job-1' } });
    expect(mocks.navigate).toHaveBeenCalledWith('/learn/session-1');
  });
});
```

- [ ] **Step 2: Run test and verify red state**

Run:

```powershell
npm run test -- --run src/features/learning/TopicInput.test.tsx
```

Expected: FAIL because icon and accepted response handling do not exist.

- [ ] **Step 3: Implement explicit local opt-in**

Add local `webSearchEnabled=false`. Read `hasWebSearchCapability()` during render. When capable, render compact `Globe2` icon beside depth control with `aria-label="Use web search for this course"`, `aria-pressed`, title explaining current state, Cyber Yellow selected styling, keyboard focus, and no mobile overflow. Hide entire button when capability false.

Mutation calls `generateCourse(data, { webSearchEnabled })`. On success combine shell and generation into `LearningSessionWithNodes`, seed `['learningSession', id]`, invalidate course list, and navigate immediately. Replace old long-running Stop/AbortController UI with disabled `Starting...` state during short request; cancellation happens on course page after shell exists.

Component mount is course boundary, so local search state always starts false. Suggestion/depth changes do not auto-enable it.

- [ ] **Step 4: Run TopicInput tests, lint, and build**

Run:

```powershell
npm run test -- --run src/features/learning/TopicInput.test.tsx
npm run lint
npm run build
```

Expected: 3 tests PASS; lint/build PASS.

- [ ] **Step 5: Commit TopicInput flow**

```powershell
git add client/src/features/learning/TopicInput.tsx client/src/features/learning/TopicInput.test.tsx
git commit -m "feat(learning): add per-course web search opt-in"
```

### Task 6.4: Apply SSE Events to React Query with Polling Repair

**Files:**
- Create: `client/src/features/learning/generationEvents.ts`
- Create: `client/src/features/learning/generationEvents.test.ts`
- Create: `client/src/features/learning/useSessionEvents.ts`
- Create: `client/src/features/learning/useSessionEvents.test.tsx`
- Create: `client/src/test/FakeEventSource.ts`
- Modify: `client/src/features/learning/LearningPage.tsx`

- [ ] **Step 1: Write failing reducer and hook tests**

Create `generationEvents.test.ts` with complete tests:

```typescript
import { describe, expect, it } from 'vitest';

import { applyGenerationEvent } from './generationEvents';
import type { GenerationEvent } from '@/types/generation';
import type { LearningSessionWithNodes } from '@/types/learning';

const session = {
  id: 'session-1',
  nodes: [],
  generation: {
    stage: 'RESEARCHING',
    last_event_id: 4,
    counts: { research_sections: 0, sources: 0 },
  },
} as LearningSessionWithNodes;

describe('applyGenerationEvent', () => {
  it('ignores duplicate and older event IDs', () => {
    const duplicate = {
      id: 4,
      event_type: 'stage_changed',
      generation: { ...session.generation, stage: 'OUTLINING' },
    } as GenerationEvent;
    expect(applyGenerationEvent(session, duplicate)).toBe(session);
  });

  it('immutably applies newest generation snapshot', () => {
    const event = {
      id: 5,
      event_type: 'stage_changed',
      generation: {
        ...session.generation,
        stage: 'OUTLINING',
        last_event_id: 5,
      },
    } as GenerationEvent;
    const next = applyGenerationEvent(session, event);
    expect(next).not.toBe(session);
    expect(next.generation.stage).toBe('OUTLINING');
    expect(session.generation.stage).toBe('RESEARCHING');
  });
});
```

Create `client/src/test/FakeEventSource.ts` implementing constructor URL, `addEventListener`, `removeEventListener`, `close`, and `emit(type, data, lastEventId)`.

Create `useSessionEvents.test.tsx` using a QueryClient preloaded at event ID 4 and fake global EventSource. Assert URL ends `/learning/sessions/session-1/events?after=4`; emitted stage event updates cache; `outline_ready` invalidates session; `research_section_ready` invalidates research; terminal event closes; unmount closes; `error` leaves EventSource available for native reconnect and polling.

- [ ] **Step 2: Run tests and verify red state**

Run:

```powershell
npm run test -- --run src/features/learning/generationEvents.test.ts src/features/learning/useSessionEvents.test.tsx
```

Expected: FAIL because reducer/hook/test double do not exist.

- [ ] **Step 3: Implement event reducer, hook, and repair polling**

`applyGenerationEvent()` returns original cache for `event.id <= generation.last_event_id`; otherwise shallow-copies session and replaces public generation snapshot from event. It does not mutate node arrays. Hook registers all nine exact event names, parses JSON with runtime required-field checks, applies cache via `setQueryData`, and invalidates:

```text
outline_ready, module_ready, module_failed -> learningSession query
research_section_ready, research_degraded -> courseResearch query
```

Terminal `generation_complete`/`generation_cancelled` closes stream after cache update and invalidates both queries. Native EventSource reconnect handles `Last-Event-ID`; remount URL uses cached `?after=` cursor. No credentials in URL/options.

In `LearningPage`, call hook while generation nonterminal. Set `staleTime: 0` and `refetchInterval` function returning `2000` for nonterminal, false for `COMPLETE`, `COMPLETE_DEGRADED`, `CANCELLED`, or `FAILED`. Do not pause repair polling during concept chat.

- [ ] **Step 4: Run event tests, lint, and build**

Run:

```powershell
npm run test -- --run src/features/learning/generationEvents.test.ts src/features/learning/useSessionEvents.test.tsx
npm run lint
npm run build
```

Expected: tests/lint/build PASS.

- [ ] **Step 5: Commit live update layer**

```powershell
git add client/src/features/learning/generationEvents.ts client/src/features/learning/generationEvents.test.ts client/src/features/learning/useSessionEvents.ts client/src/features/learning/useSessionEvents.test.tsx client/src/test/FakeEventSource.ts client/src/features/learning/LearningPage.tsx
git commit -m "feat(learning): sync generation with SSE and polling"
```

### Task 6.5: Render Stages, TOC Skeletons, Preview, and Later Batches

**Files:**
- Create: `client/src/features/learning/GenerationStatusPanel.tsx`
- Create: `client/src/features/learning/GenerationStatusPanel.test.tsx`
- Modify: `client/src/features/learning/LearningPage.tsx`
- Modify: `client/src/features/learning/LearningPathContainer.tsx`
- Modify: `client/src/features/learning/SkeletonCard.tsx`
- Modify: `client/src/features/learning/TableOfContentsModal.tsx`

- [ ] **Step 1: Write failing progressive state tests**

Create `GenerationStatusPanel.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { GenerationStatusPanel } from './GenerationStatusPanel';

const generation = {
  id: 'job-1',
  session_id: 'session-1',
  stage: 'RESEARCHING',
  web_search_requested: true,
  grounding_status: 'PENDING',
  counts: {
    topics_total: 0,
    briefs_ready: 0,
    topics_ready: 0,
    topics_failed: 0,
    research_sections: 2,
    sources: 7,
  },
  warnings: [],
  cancel_requested: false,
  can_cancel: true,
  can_resume: false,
  last_event_id: 3,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
} as const;

describe('GenerationStatusPanel', () => {
  it('renders research before an outline exists', () => {
    render(
      <GenerationStatusPanel
        generation={generation}
        onCancel={vi.fn()}
        onResume={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByText(/researching current sources/i)).toBeInTheDocument();
    expect(screen.getByText(/2 sections/i)).toBeInTheDocument();
    expect(screen.getByText(/7 sources/i)).toBeInTheDocument();
  });

  it.each([
    ['OUTLINING', 'Building table of contents'],
    ['PLANNING_PREVIEW', 'Planning first 3 topics'],
    ['GENERATING_PREVIEW', 'Generating preview topics'],
    ['PLANNING_BATCH', 'Planning next topic batch'],
    ['GENERATING_BATCH', 'Generating next topic batch'],
    ['COMPLETE', 'Course generation complete'],
  ])('maps %s to visible stage copy', (stage, copy) => {
    render(
      <GenerationStatusPanel
        generation={{ ...generation, stage }}
        onCancel={vi.fn()}
        onResume={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByText(new RegExp(copy, 'i'))).toBeInTheDocument();
  });
});
```

Add tests to a new `LearningPathContainer.test.tsx`: empty nonterminal shell renders status rather than `No topics yet`; `SKELETON` and `GENERATING` modules render titled skeletons; READY renders `ConceptCard`; ERROR renders retry card; arrival does not reset manually selected carousel index.

- [ ] **Step 2: Run progressive tests and verify red state**

Run:

```powershell
npm run test -- --run src/features/learning/GenerationStatusPanel.test.tsx src/features/learning/LearningPathContainer.test.tsx
```

Expected: FAIL because status panel/module-status rendering does not exist.

- [ ] **Step 3: Implement progressive responsive presentation**

`GenerationStatusPanel` maps every stage to academic/professional copy, shows counts and accessible live status, and reserves controls slots. Research displays before TOC. Degraded warning uses persistent alert; terminal success removes pulse.

`LearningPage` renders status under header whenever generation exists, even with zero nodes. Pass authoritative session to `LearningPathContainer`.

Remove new-course generation mutation and duplicate active-session query from `LearningPathContainer`; route/TopicInput now own start and LearningPage owns fetch. Keep learner mutations/carousel/chat behavior. For zero-node active job render a calm stage view, not EmptyState. For each node:

```text
SKELETON -> static titled SkeletonCard
GENERATING -> animated titled SkeletonCard
READY -> ConceptCard
ERROR -> ConceptCard existing retry behavior
```

First three cards become usable independently as READY. Later skeletons remain visible and arrive in persisted batches. `SkeletonCard` accepts `title`, `sequenceIndex`, and `animated`; cancelled/paused skeletons are static.

Table of Contents labels module skeletons `Generating` rather than learner `Locked`; READY locked cards remain `Locked`. Keep modal usable at mobile widths with horizontal scroll and status text.

- [ ] **Step 4: Run progressive tests, lint, and build**

Run:

```powershell
npm run test -- --run src/features/learning/GenerationStatusPanel.test.tsx src/features/learning/LearningPathContainer.test.tsx src/features/learning/TableOfContentsModal.test.tsx
npm run lint
npm run build
```

Expected: tests/lint/build PASS.

- [ ] **Step 5: Commit progressive course UI**

```powershell
git add client/src/features/learning/GenerationStatusPanel.tsx client/src/features/learning/GenerationStatusPanel.test.tsx client/src/features/learning/LearningPage.tsx client/src/features/learning/LearningPathContainer.tsx client/src/features/learning/LearningPathContainer.test.tsx client/src/features/learning/SkeletonCard.tsx client/src/features/learning/TableOfContentsModal.tsx
git commit -m "feat(learning): render progressive course stages"
```

### Task 6.6: Render Course Sources, Citations, and Degraded Grounding

**Files:**
- Create: `client/src/features/learning/CourseSourcesPanel.tsx`
- Create: `client/src/features/learning/CourseSourcesPanel.test.tsx`
- Create: `client/src/features/learning/SourceCitations.tsx`
- Create: `client/src/features/learning/SourceCitations.test.tsx`
- Modify: `client/src/features/learning/ConceptCard.tsx`
- Modify: `client/src/features/learning/LearningPage.tsx`
- Modify: `client/src/features/learning/LearningPathContainer.tsx`

- [ ] **Step 1: Write failing sources and citation tests**

Create `SourceCitations.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { SourceCitations } from './SourceCitations';

describe('SourceCitations', () => {
  it('numbers validated sources and opens safe external links', () => {
    render(
      <SourceCitations
        citations={[
          {
            source_id: 'source-1',
            citation_number: 1,
            title: 'Current documentation',
            url: 'https://example.com/docs',
            publisher: 'Example',
            published_at: null,
            retrieved_at: '2026-08-01T00:00:00Z',
          },
        ]}
      />,
    );
    const link = screen.getByRole('link', { name: /1 current documentation/i });
    expect(link).toHaveAttribute('href', 'https://example.com/docs');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noreferrer noopener');
  });

  it('renders nothing for empty validated citations', () => {
    const { container } = render(<SourceCitations citations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

Create `CourseSourcesPanel.test.tsx`: render partial RESEARCHING report and assert section/source count; DEGRADED report shows limitations/warnings and no grounded claim; provider statuses visible; Brave source shows `Powered by Brave`; complete report shows retrieved/published metadata and excerpts; close button accessible.

- [ ] **Step 2: Run source tests and verify red state**

Run:

```powershell
npm run test -- --run src/features/learning/SourceCitations.test.tsx src/features/learning/CourseSourcesPanel.test.tsx
```

Expected: FAIL because source components do not exist.

- [ ] **Step 3: Implement structured sources and citation UI**

`CourseSourcesPanel` is responsive modal/drawer with focus management matching existing TOC. It receives `ResearchReport`, renders status, ordered Markdown sections using existing sanitized renderer, normalized source cards, provider states, source count, limitations, freshness, and warnings. Links use server-validated HTTP(S) URL with `target="_blank" rel="noreferrer noopener"`. If any source provider is Brave, display required `Powered by Brave` attribution near list.

`SourceCitations` renders compact numbered footer on READY/ERROR cards only. It never parses model Markdown to construct URLs. Add it to `ConceptCard` after explanation/partial content and add `View course sources` callback.

LearningPage fetches report when web was requested and Sources panel opens; while report status is PENDING/RESEARCHING, refetch every two seconds. Keep button visible for cancelled/degraded partial reports. Show `Web grounded` badge only for `GroundingStatus.GROUNDED`; DEGRADED gets persistent warning `Web research was incomplete; this course is not fully web-grounded.`

- [ ] **Step 4: Run source tests, lint, and build**

Run:

```powershell
npm run test -- --run src/features/learning/SourceCitations.test.tsx src/features/learning/CourseSourcesPanel.test.tsx src/features/learning/ConceptCard.test.tsx
npm run lint
npm run build
```

Expected: tests/lint/build PASS.

- [ ] **Step 5: Commit sources and citations**

```powershell
git add client/src/features/learning/CourseSourcesPanel.tsx client/src/features/learning/CourseSourcesPanel.test.tsx client/src/features/learning/SourceCitations.tsx client/src/features/learning/SourceCitations.test.tsx client/src/features/learning/ConceptCard.tsx client/src/features/learning/LearningPage.tsx client/src/features/learning/LearningPathContainer.tsx
git commit -m "feat(learning): show course sources and citations"
```

### Task 6.7: Wire Stop, Resume, Delete, and Dashboard Status

**Files:**
- Modify: `client/src/features/learning/GenerationStatusPanel.tsx`
- Modify: `client/src/features/learning/GenerationStatusPanel.test.tsx`
- Modify: `client/src/features/learning/LearningPage.tsx`
- Create: `client/src/features/learning/LearningPage.test.tsx`
- Modify: `client/src/features/learning/CourseCard.tsx`
- Create: `client/src/features/learning/CourseCard.test.tsx`
- Modify: `client/src/features/learning/index.ts`

- [ ] **Step 1: Write failing retained-control tests**

Append to `GenerationStatusPanel.test.tsx`:

```tsx
it('shows Stop while running and Resume after retained cancellation', () => {
  const cancel = vi.fn();
  const resume = vi.fn();
  const { rerender } = render(
    <GenerationStatusPanel
      generation={generation}
      onCancel={cancel}
      onResume={resume}
      onDelete={vi.fn()}
    />,
  );
  screen.getByRole('button', { name: /stop generation/i }).click();
  expect(cancel).toHaveBeenCalledOnce();
  rerender(
    <GenerationStatusPanel
      generation={{
        ...generation,
        stage: 'CANCELLED',
        can_cancel: false,
        can_resume: true,
      }}
      onCancel={cancel}
      onResume={resume}
      onDelete={vi.fn()}
    />,
  );
  screen.getByRole('button', { name: /resume generation/i }).click();
  expect(resume).toHaveBeenCalledOnce();
  expect(screen.getByText(/partial course retained/i)).toBeInTheDocument();
});
```

Create `LearningPage.test.tsx` with mocked API/query data. Assert cancel response updates only generation and retains nodes; resume calls `resumeGeneration` with `{ webSearchEnabled: true }` when unfinished research and capability exists; missing fresh search capability shows actionable error without request; delete requires confirmation, calls `deleteSession`, clears cache, navigates dashboard; SSE/polling remain enabled after cancel until terminal event.

Create `CourseCard.test.tsx`: generating, paused, cancelled, complete-degraded badges render; retained partial card offers resume/open and existing delete menu.

- [ ] **Step 2: Run control tests and verify red state**

Run:

```powershell
npm run test -- --run src/features/learning/GenerationStatusPanel.test.tsx src/features/learning/LearningPage.test.tsx src/features/learning/CourseCard.test.tsx
```

Expected: FAIL because controls/status badges are not wired.

- [ ] **Step 3: Implement retained lifecycle controls**

Use React Query mutations in LearningPage:

```text
Stop -> cancelGeneration; merge returned generation only; keep nodes/report/cache.
Resume -> determine whether research is unfinished; require browser capability then
          resumeGeneration(sessionId, {webSearchEnabled: required}); merge generation.
Delete -> window.confirm explicit permanent warning; deleteSession; remove session and
          research queries; invalidate courses; navigate /learn.
```

Disable duplicate buttons while mutation pending. Render safe server detail only for known 400/409 messages; never display/request-log key material. Cancellation copy says current report, outline, and cards remain. Resume copy says fresh credentials are sent for resumed work.

Course dashboard cards map generation stages to `Generating`, `Paused`, `Cancelled`, `Complete`, or `Complete with research warning`; learner completion progress remains separate. Preserve existing rename/delete/navigation patterns.

Export new named components/hooks from `features/learning/index.ts`. Verify desktop and narrow viewport class behavior: controls wrap, Sources uses full-width mobile drawer, no fixed-width overflow.

- [ ] **Step 4: Run client suite and quality gates**

Run:

```powershell
npm run test -- --run
npm run lint
npm run build
```

Expected: full Vitest suite, ESLint, TypeScript, and Vite build PASS.

- [ ] **Step 5: Commit retained controls**

```powershell
git add client/src/features/learning/GenerationStatusPanel.tsx client/src/features/learning/GenerationStatusPanel.test.tsx client/src/features/learning/LearningPage.tsx client/src/features/learning/LearningPage.test.tsx client/src/features/learning/CourseCard.tsx client/src/features/learning/CourseCard.test.tsx client/src/features/learning/index.ts
git commit -m "feat(learning): add retained generation controls"
```

## Phase Checkpoint

- [ ] Run full client gates:

```powershell
npm run test -- --run
npm run test -- --run --coverage
npm run lint
npm run build
```

- [ ] Verify search keys are referenced only by settings/header builder and generate/resume path:

```powershell
rg "X-Tavily-Key|X-Exa-Key|X-Brave-Key|X-SerpApi-Key" client/src
```

Expected: metadata/header tests/header builder; no quiz/session/research/cancel/delete call site.

- [ ] Verify icon OFF initialization and terminal polling logic:

```powershell
rg "useState\(false\)|refetchInterval|2000|useSessionEvents" client/src/features/learning/TopicInput.tsx client/src/features/learning/LearningPage.tsx
```

Expected: per-course false state and two-second nonterminal polling.

- [ ] Record checkpoint:

```powershell
git notes add -m "Phase 6 complete: progressive web-grounded course UI verified"
```
