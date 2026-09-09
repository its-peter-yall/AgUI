# Testing Patterns

**Analysis Date:** 2026-09-05

Cover both client (Vitest) and server (unittest). Commands come from
`client/package.json`, `client/vite.config.ts`, `client/vitest.generation.config.ts`,
`README.md`, and USAGE blocks in `server/tests/`.

---

## Test Framework

### Client

**Runner:**
- Vitest `^3.2.4`
- Config: `client/vite.config.ts` (`test.environment`, `globals`, `setupFiles`)
- Focused coverage config: `client/vitest.generation.config.ts`
- Setup: `client/vitest.setup.ts` imports `@testing-library/jest-dom`

**Assertion Library:**
- Vitest `expect`
- jest-dom matchers (`toBeInTheDocument`, etc.) via `client/vitest.setup.ts`

**Run Commands:**

```bash
cd client

npm run test                         # Watch mode (vitest)
npm run test -- --run                # Single run, all tests
npm run test -- --run src/lib/learningApi.test.ts
npm run test -- -t "LearningPage"    # Name filter
npm run test -- --coverage           # V8 coverage (ad hoc)
npm run test:generation:coverage     # Focused generation-module coverage gate
```

`client/package.json` scripts:

- `"test": "vitest"`
- `"test:generation:coverage": "vitest run --config vitest.generation.config.ts --coverage"`

Vitest inherits Vite aliases (`@` → `./src`), `environment: 'jsdom'`, `globals: true`.
Still import `describe` / `it` / `expect` / `vi` from `'vitest'` in test files (observed
pattern even with globals enabled).

### Server

**Runner:**
- Python stdlib `unittest` (no pytest in `server/requirements.txt`)
- Discovery package: `server/tests/` (`server/tests/__init__.py`)

**Assertion Library:**
- `unittest.TestCase` (`self.assertEqual`, `self.assertTrue`, `self.assertRaises`, …)

**Run Commands:**

```bash
# From repository root (matches USAGE in test modules)
python -m unittest
python -m unittest server.tests.test_generation_api -v
python -m unittest server.tests.test_generation_api.GenerationApiTests.test_generate_returns_202_before_job_finishes_without_secrets
python -m unittest server.tests.test_storage_router -v
python -m unittest server.tests.test_internet_generation_acceptance -v

# README.md also documents:
cd server
python -m unittest
python -m unittest server.tests.test_learning
python -m unittest server.tests.test_learning.TestLearningSessions.test_create_session
```

Run with `python -m` so `server.*` imports resolve. Use `server/.venv`. Test modules
end with `if __name__ == "__main__": unittest.main()`.

---

## Test File Organization

### Client

**Location:**
- Co-located next to source: `Foo.ts` → `Foo.test.ts`, `Foo.tsx` → `Foo.test.tsx`
- Feature-level acceptance: `client/src/features/learning/__tests__/internetGroundedGeneration.test.tsx`
- Shared doubles: `client/src/test/FakeEventSource.ts`

**Naming:**
- `*.test.ts` / `*.test.tsx` (not `*.spec.*`)

**Structure:**

```
client/src/lib/learningApi.ts
client/src/lib/learningApi.test.ts
client/src/features/learning/ConceptCard.tsx
client/src/features/learning/ConceptCard.test.tsx
client/src/features/learning/generationEvents.test.ts
client/src/features/learning/__tests__/internetGroundedGeneration.test.tsx
client/src/test/FakeEventSource.ts
```

### Server

**Location:**
- Separate tree: `server/tests/test_*.py`
- Shared fixtures/helpers in the same package (not a `fixtures/` folder):
  - `server/tests/llm_test_helpers.py`
  - `server/tests/generation_acceptance_harness.py`

**Naming:**
- `test_<area>.py`
- Classes: `*Tests(unittest.TestCase)` or `*Tests(unittest.IsolatedAsyncioTestCase)`
- Methods: `test_<behavior>`

**Structure:**

```
server/tests/__init__.py
server/tests/test_generation_api.py
server/tests/test_storage_router.py
server/tests/test_internet_generation_acceptance.py
server/tests/llm_test_helpers.py
server/tests/generation_acceptance_harness.py
```

---

## Test Structure

### Client

**Suite Organization:**

```typescript
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { buildWebSearchHeaders, WebSearchConfigurationError } from './webSearchHeaders';
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

  it('rejects opt-in when master or configured providers are unavailable', () => {
    expect(() =>
      buildWebSearchHeaders(true, { ...settings, masterEnabled: false }),
    ).toThrow(WebSearchConfigurationError);
  });
});
```

Component tests wrap with providers and mock heavy deps:

```typescript
describe('ConceptCard Component', () => {
  test('renders the concept node title', () => {
    renderWithProviders(<ConceptCard node={mockNode} isActive={true} />);
    expect(screen.getByText('Introduction to AI')).toBeDefined();
  });
});
```

**Patterns:**
- Setup: `beforeEach` for `vi.fn()` reset, `QueryClient` construction, `FakeEventSource.reset()`, `vi.stubGlobal('fetch', fetchMock)`
- Teardown: `afterEach` restores `EventSource`, `vi.unstubAllGlobals()`, `client.clear()`, `FakeEventSource.reset()`
- Assertion: `expect(...).toEqual` / `toBe` / `toThrow` / `toMatchObject`; RTL `screen.getByRole` + `toBeInTheDocument()` in settings tests; some learning tests still use `toBeDefined()` / `toBeNull()`
- Prefer `it('does X', ...)` in newer files; older component tests may use `test(...)`

### Server

**Suite Organization:**

```python
class StorageRouterTests(unittest.TestCase):
    def test_status_uses_camel_case_contract(self) -> None:
        response = make_client(
            make_storage(DeploymentMode.LOCAL)
        ).get("/settings/storage/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["activeBackend"], "sqlite")
        self.assertTrue(response.json()["canConnect"])
```

Async:

```python
class BaseAgentGenerateResolutionTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_generate_passes_resolved_model(self) -> None:
        with patch(
            "server.agents.base.instructor_client.create_structured",
            new_callable=AsyncMock,
        ) as mock_cs:
            mock_cs.return_value = _Out()
            await agent.generate(...)
            self.assertEqual(kwargs["model_override"], "quiz/model")
```

**Patterns:**
- Setup: `setUp` creates `tempfile.TemporaryDirectory()` + SQLite path + stores; FastAPI tests build a tiny `FastAPI()` + `TestClient` per test
- Async setup: `asyncSetUp` / `asyncTearDown` on `IsolatedAsyncioTestCase` (acceptance harness)
- Teardown: `self.temp_dir.cleanup()`
- Assertion: `self.assertEqual`, `self.assertNotIn` (secrets must not leak), `self.assertRaises`, `self.assertRaisesRegex`
- Parameterized cases: `with self.subTest(...):`
- Annotate test methods `-> None`

---

## Mocking

### Client

**Framework:** Vitest `vi` (`vi.mock`, `vi.hoisted`, `vi.fn`, `vi.stubGlobal`, `vi.importActual`)

**Patterns:**

Hoist mocks so `vi.mock` factories can close over them:

```typescript
const api = vi.hoisted(() => ({
  getLearningSession: vi.fn(),
  cancelGeneration: vi.fn(),
  resumeGeneration: vi.fn(),
  deleteSession: vi.fn(),
  getCourseResearch: vi.fn(),
}));

vi.mock('@/lib/learningApi', () => ({
  getLearningSession: api.getLearningSession,
  cancelGeneration: api.cancelGeneration,
  resumeGeneration: api.resumeGeneration,
  deleteSession: api.deleteSession,
  getCourseResearch: api.getCourseResearch,
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return {
    ...actual,
    useNavigate: () => api.navigate,
  };
});
```

Axios instance mock (`client/src/lib/learningApi.test.ts`):

```typescript
const mocks = vi.hoisted(() => {
  const instance = {
    get: vi.fn(async () => ({ data: { id: 'session-1', nodes: [] } })),
    post: vi.fn(async () => ({ data: {} })),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  };
  return { instance };
});

vi.mock('axios', () => ({
  default: {
    create: () => mocks.instance,
    isAxiosError: () => false,
  },
}));
```

Framer Motion in jsdom — stub to plain DOM nodes:

```typescript
vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: ComponentPropsWithoutRef<'div'>) => (
      <div {...props}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));
```

SSE: replace `globalThis.EventSource` with `FakeEventSource` from
`client/src/test/FakeEventSource.ts`.

**What to Mock:**
- HTTP (`axios.create`, `fetch`)
- Provider/search settings (`@/lib/providerSettings`, `./webSearchHeaders`)
- Child feature components when testing page chrome (`LearningPathContainer`)
- `framer-motion` (jsdom cannot run animations)
- Browser SSE (`EventSource`)
- `useNavigate` when asserting navigation

**What NOT to Mock:**
- The unit under test
- Pure reducers (`applyGenerationEvent` in `generationEvents.test.ts`)
- React Testing Library queries / jest-dom matchers
- Real `QueryClient` (construct a fresh one with `retry: false`)

### Server

**Framework:** `unittest.mock` (`patch`, `AsyncMock`, `MagicMock`)

**Patterns:**

```python
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

with (
    patch(
        "server.routers.learning.learning_manager.get_learning_session",
        return_value={"id": "s1"},
    ),
    patch(
        "server.routers.learning.learning_manager.delete_learning_session",
        return_value=True,
    ),
):
    with TestClient(app) as client:
        response = client.delete("/learning/sessions/s1")
```

FastAPI dependency overrides (do not hit real LLM headers):

```python
app.dependency_overrides[get_llm_context] = lambda: make_test_llm_context(
    api_key="llm-secret",
    model="test/model",
)
```

`SimpleNamespace` fakes for `app.state.storage` / `generation_runtime`.

**What to Mock:**
- LLM / Instructor (`instructor_client.create_structured`)
- Live search providers
- Mongo network
- Runtime `start` when testing HTTP 202 shell acceptance
- Repository methods when testing router mapping

**What NOT to Mock:**
- Pydantic validation (feed dicts into `model_validate`)
- SQLite schema + focused stores in persistence/integration tests (temp file DB)
- Acceptance harness graph/runtime/SSE with *deterministic fakes* for externals only (`server/tests/generation_acceptance_harness.py`)

---

## Fixtures and Factories

### Client

**Test Data:**

Inline typed objects next to the suite. Session shells reuse a `sessionBase` /
`runningSession` / `shell(stage, eventId)` factory.

```typescript
const mockNode: ConceptNode = {
  id: 'node-1',
  learning_session_id: 'session-1',
  sequence_index: 0,
  title: 'Introduction to AI',
  content_markdown: 'Artificial Intelligence is...',
  status: 'VIEWING_EXPLANATION',
  error_message: null,
  retry_available: false,
  complexity: 'Basic',
  quiz: null,
  quiz_set: null,
  quiz_hidden: null,
  quiz_set_hidden: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: null,
};

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}
```

Page tests wrap `MemoryRouter` + `Routes` + `QueryClientProvider`.

**Location:**
- Fixtures live in the test file
- SSE double: `client/src/test/FakeEventSource.ts`

### Server

**Test Data:**

```python
def _accepted() -> dict[str, object]:
    return {
        "session": {"id": "session-1", "query": "Modern CSS", ...},
        "generation": {"id": "job-1", "stage": "INITIALIZING", ...},
    }

def make_test_llm_context(
    api_key: str = "test-key",
    model: str = "test/model",
    **kwargs: object,
) -> LLMContext:
    """Build LLMContext with all four required agent models."""
    ...
```

Persistence tests create a real session shell in `setUp`:

```python
def setUp(self) -> None:
    self.temp_dir = tempfile.TemporaryDirectory()
    self.db_path = Path(self.temp_dir.name) / "a2ui.db"
    self.learning = LearningManager(self.db_path)
    self.learning.init_learning_tables()
    initialize_generation_schema(self.db_path)
    self.jobs = GenerationJobStore(self.db_path)
```

**Location:**
- `server/tests/llm_test_helpers.py` — `make_test_llm_context`
- `server/tests/generation_acceptance_harness.py` — `GenerationAcceptanceHarness`, `AcceptanceScenario`
- Router helpers (`make_client`, `make_storage`) at top of the test module
- No pytest `conftest.py`

---

## Coverage

**Requirements:**
- Project target: >80% for new code (`README.md` contributing notes)
- Enforced gate (client, generation modules only): per-file 81% branches / functions / lines / statements in `client/vitest.generation.config.ts`
- Include list for that gate:
  - `src/lib/webSearchProviders.ts`
  - `src/lib/webSearchHeaders.ts`
  - `src/features/settings/WebSearchSettingsPanel.tsx`
  - `src/features/learning/generationEvents.ts`
  - `src/features/learning/useSessionEvents.ts`
  - `src/features/learning/GenerationStatusPanel.tsx`
  - `src/features/learning/CourseSourcesPanel.tsx`
  - `src/features/learning/SourceCitations.tsx`
- Full-repo Vitest coverage: not a default `package.json` script (use `npm run test -- --coverage`)
- Server: `coverage.py` Not detected in `server/requirements.txt`. No enforced unittest coverage config

**View Coverage:**

```bash
cd client
npm run test:generation:coverage
# or
npm run test -- --coverage
```

Provider: `@vitest/coverage-v8` `^3.2.4`. Thresholds use `perFile: true`.

---

## Test Types

**Unit Tests:**
- Client: pure functions (`generationEvents.test.ts`, `webSearchHeaders.test.ts`, `agentModelHeaders.test.ts`); component render + click (`ConceptCard.test.tsx`, settings panels)
- Server: schema `model_validate`, agent resolution, quiz randomization, routers with `TestClient` and mocked runtime

**Integration Tests:**
- Server: temp SQLite + real `LearningManager` / `GenerationJobStore` / `ProgressEventStore` (`test_generation_persistence_integration.py`, `test_critical_lock_and_poll.py`)
- Client: `LearningPage.test.tsx` with mocked API but real React Query + router
- Acceptance: `test_internet_generation_acceptance.py` composes graph, stores, runtime, SSE via `GenerationAcceptanceHarness` (no live providers)
- Browser-level feature acceptance: `client/src/features/learning/__tests__/internetGroundedGeneration.test.tsx` (jsdom + FakeEventSource)

**E2E Tests:**
- Not used (no Playwright / Cypress / Puppeteer in `client/package.json`)

---

## Common Patterns

### Async Testing

**Client** — `async` tests + `waitFor` / `act` for EventSource and queries:

```typescript
it('opens EventSource with after cursor from cache', async () => {
  renderHook(() => useSessionEvents('session-1', true), { wrapper });
  await waitFor(() => {
    expect(FakeEventSource.instances.length).toBe(1);
  });
  expect(FakeEventSource.instances[0].url).toMatch(
    /\/learning\/sessions\/session-1\/events\?after=4$/,
  );
});
```

```typescript
await expect(
  streamConceptChat({ ...baseParams(), webSearchEnabled: true }),
).resolves.toBeUndefined();
```

Disable React Query retries in tests (`retry: false`) so failures do not flake.

**Server** — `unittest.IsolatedAsyncioTestCase` + `async def test_*`:

```python
class InternetGenerationAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.harness = await GenerationAcceptanceHarness.create()

    async def asyncTearDown(self) -> None:
        await self.harness.close()

    async def test_web_off_uses_exact_preview_and_later_batches(self) -> None:
        result = await self.harness.run(
            AcceptanceScenario(topic_count=30, web_search=False)
        )
        self.assertEqual(result.terminal_stage, "COMPLETE")
        self.assertEqual(result.research_calls, 0)
```

`TestClient` may wrap async routes synchronously. Use `AsyncMock` + `assert_awaited_once_with` for coroutine deps (`checkpointer.adelete_thread.assert_awaited_once_with("gen-s1")`).

### Error Testing

**Client:**

```typescript
await expect(
  streamConceptChat({
    ...baseParams(),
    webSearchEnabled: true,
  }),
).rejects.toThrow(WebSearchConfigurationError);

await expect(
  streamConceptChat({
    ...baseParams(),
    webSearchEnabled: true,
  }),
).rejects.toThrow('No configured web search providers available');

expect(fetchMock).not.toHaveBeenCalled();
```

```typescript
expect(() =>
  buildWebSearchHeaders(true, { ...settings, masterEnabled: false }),
).toThrow(WebSearchConfigurationError);
```

HTTP 422 / secret-boundary tests on the server side are mirrored on the client by asserting headers omit keys on non-generate routes (`learningApi.test.ts`).

**Server:**

```python
def test_invalid_mode_still_returns_422_without_starting_job(self) -> None:
    ...
    with TestClient(app) as client:
        response = client.post(
            "/learning/generate",
            json={"query": "Topic", "mode": "turbo"},
        )
    self.assertEqual(response.status_code, 422)
    runtime.start.assert_not_awaited()
```

```python
with self.assertRaises(GenerationLockConflict):
    self.jobs.update_stage(
        self.session_id,
        GenerationStage.OUTLINING,
        lock=first,
    )
```

```python
with self.assertRaises(ValidationError):
    ConceptChatMessage.model_validate(
        {"role": "tool", "content": "search results"}
    )
```

```python
self.assertNotIn("llm-secret", response.text)
self.assertNotIn("search-secret", response.text)
self.assertNotIn("uri", response.json())
```

Use `assertRaisesRegex` when the message is part of the contract (`RuntimeError`, `"requires MONGO_URI"`).

### HTTP / Router Tests

- Build a **minimal** `FastAPI()` app, `include_router(router)`, set `app.state.*`, then `TestClient(app)`
- Do not boot `server.main:app` for unit/API tests
- Override `get_llm_context` / search deps rather than sending real keys
- Assert status, JSON contract (camelCase vs snake_case as the endpoint defines), and that secrets never appear in the body

### UI Interaction

- `@testing-library/react`: `render`, `screen`, `fireEvent`, `waitFor`, `renderHook`, `act`
- `@testing-library/user-event`: Not detected — use `fireEvent`
- Query by role/label: `getByRole('heading', { name: 'Appearance' })`, `getByLabelText('Regenerate the content')`
- Confirm dialogs: click trigger → assert copy → click Cancel → `queryByText(...).toBeNull()`

### Security / Secret Scope (required in this repo)

When adding generate/resume/chat/search tests:

- LLM and search keys attach **only** to the endpoints that need them
- Responses and logs must not echo `api_key`, `uri`, or provider secrets
- Globe-off chat/search must omit `X-Web-Search*` headers

---

## File Headers on Tests

Test files use the same boxed header as production (see `docs/CONVENTIONS.md`), with
USAGE pointing at the exact run command for that file.

---

*Testing analysis: 2026-09-05*
