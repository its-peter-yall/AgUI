<!-- refreshed: 2026-09-05 -->
# Architecture

**Analysis Date:** 2026-09-05

## System Overview

A2UI is a two-process adaptive learning platform: a Vite + React 19 SPA and a FastAPI backend. The browser owns LLM and web-search secrets; the server never stores provider keys in graph checkpoints. Course generation is a durable LangGraph job detached from the HTTP request. Persistence swaps SQLite ↔ MongoDB Atlas through repository facades without changing routers or graph nodes.

```text
[Browser]
  `client/src/main.tsx`
    → `startApplication` (`client/src/lib/startApplication.ts`)
    → `ThemeProvider` + `QueryProvider`
    → `App.tsx` routes: `/`, `/learn/:sessionId`, `/learn/:sessionId/revise/:revisionId`, `/settings`
         │
         ├─ `features/learning/`  page shells, ConceptCard, SSE hooks
         ├─ `features/settings/`  provider / search / storage UI
         └─ `lib/*Api.ts`         Axios + fetch SSE (keys only on generate/resume/regen/chat)
                    │  HTTP / SSE  (`VITE_API_URL` → :8000)
                    ▼
[FastAPI] `server/main.py`  lifespan, CORS, `/` + `/health`
    routers:
      `server/routers/learning.py`   `/learning/*`
      `server/routers/llm.py`        `/llm/models`
      `server/routers/storage.py`    `/settings/storage/*`
                    │
    ┌───────────────┼───────────────────────────────┐
    ▼               ▼                               ▼
`GenerationRuntime` `LangGraph` (`server/graph/`)  `search/` adapters
(`services/generation_runtime.py`)
    │               │  nodes → agents               │
    │               ▼                               ▼
    │         `BaseAgent` + Instructor              Tavily / Exa / Brave / SerpAPI
    │         (`server/agents/`, `utils/instructor_client.py`)
    │               │
    └───────┬───────┘
            ▼
`storage_registry` facades (`server/database/storage_registry.py`)
            ▼
`StorageContext`  SQLite (`server/data/a2ui.db`)  or  Mongo Atlas
            + LangGraph checkpointer (`checkpoints.db` or Mongo collections)
```

**Not detected:** `conductor/` on disk (listed in `.gitignore`; `AGENTS.md` still names `conductor/product-guidelines.md`). **Not detected:** `.claude/skills/` or `.agents/skills/`. **Not detected:** `/chat` route or standalone chat session store. **Existence only:** root `.env`; `server/.env.example`.

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| FastAPI app | Lifespan, CORS, health, router mount | `server/main.py` |
| Settings singleton | `DEPLOYMENT_MODE`, Mongo URI/DB, provider base URLs | `server/config.py` |
| Learning router | Course generate/resume/cancel/delete, sessions, nodes, quizzes, revisions, regen, concept chat, SSE | `server/routers/learning.py` |
| LLM router | Proxy model catalog from OpenRouter or General Compute | `server/routers/llm.py` |
| Storage router | Local connect/disconnect/migrate; Mongo app-settings | `server/routers/storage.py` |
| GenerationRuntime | Detached asyncio tasks; start/resume/cancel/shutdown | `server/services/generation_runtime.py` |
| Graph runner | Lock + heartbeat + `ainvoke`; map cancel/pause/fail | `server/graph/runner.py` |
| Graph factory | Staged StateGraph compile + cached accessor | `server/graph/build.py` |
| Graph nodes | Init, optional research, outline, 3/10 batch gen/quiz, finalize | `server/graph/nodes.py` |
| CourseState | Secret-free checkpointed TypedDict + keyed reducers | `server/graph/state.py` |
| Failed-node regen | Direct generator/quizzer; no full graph | `server/graph/regen.py` |
| Regen SSE | Stream explanation then persist quizzes | `server/graph/regen_stream.py` |
| Planner/Generator/Quizzer/Researcher | Structured LLM agents | `server/agents/` |
| BaseAgent | Instructor `create_structured` contract | `server/agents/base.py` |
| InstructorClient | OpenAI-compatible client + tenacity + role configs | `server/utils/instructor_client.py` |
| Depth router | `auto` → lite/full classify | `server/services/depth_router.py` |
| Research runner | Bounded search/synthesize loop | `server/services/research_runner.py` |
| Concept chat | Direct streaming chat + optional one-shot search | `server/services/concept_chat.py` |
| Quiz randomization | Deterministic option shuffle by seed | `server/services/quiz_randomization.py` |
| Session SSE | Replay-then-tail progress events | `server/services/session_event_stream.py` |
| Citation sanitizer | Strip unapproved URLs from grounded markdown | `server/services/citation_validation.py` |
| Search coordinator | Job-local provider failover | `server/search/coordinator.py` |
| Search adapters | Tavily, Exa, Brave, SerpAPI HTTP | `server/search/adapters/` |
| StorageContext | Backend swap + Mongo lifecycle | `server/database/storage_mode.py` |
| RepositoryFacade | Late-bound protocol proxy | `server/database/repositories/facade.py` |
| LearningManager | SQLite learning/quiz/revision CRUD + state machine | `server/database/learning_persistence.py` |
| Generation stores | Jobs, artifacts, research, progress events | `server/database/generation_jobs.py`, `generation_artifacts.py`, `research_store.py`, `progress_events.py` |
| CheckpointerController | Swap SQLite ↔ Mongo LangGraph saver | `server/database/checkpointer.py` |
| React bootstrap | Storage boot then mount | `client/src/main.tsx` |
| Router shell | Learning + settings routes | `client/src/App.tsx` |
| Learning API | Axios client; secrets only on generate/resume/regen | `client/src/lib/learningApi.ts` |
| Chat / regen SSE | Native fetch ReadableStream | `client/src/lib/chatApi.ts`, `client/src/lib/regenApi.ts` |
| Query cache | TanStack Query 5-minute staleTime | `client/src/providers/QueryProvider.tsx` |

## Pattern Overview

**Overall:** Layered ports-and-adapters around a durable LangGraph workflow. HTTP is a thin contract; generation lifetime lives in `GenerationRuntime`, not the request.

**Key Characteristics:**
- **202 Accepted + detached work.** `POST /learning/generate` creates a session shell and schedules `run_generation_job`; browser disconnect does not cancel the graph.
- **Secret-free checkpoints.** `CourseState` holds IDs, counts, and flags. `LLMContext` / `SearchContext` ride in runtime context only (`server/graph/state.py`).
- **Repository swap.** Routers, graph, and services import `RepositoryFacade` aliases from `server/database/storage_registry.py`. `StorageContext.connect`/`disconnect` swaps SQLite ↔ Mongo bundles at runtime (local) or at process start (cloud).
- **Server-authoritative learning state machine.** Node status and quiz scoring live in `LearningManager`; the client applies optimistic React Query updates then reconciles.
- **Browser-owned credentials.** API keys stay in `localStorage` (and optional Mongo `app_settings` when cloud storage is active). Headers attach only to generate, resume, regen, chat, and `/llm/models`.

## Layers

**Client presentation:**
- Purpose: Routes, learning UX, settings, theme.
- Location: `client/src/features/`, `client/src/components/`, `client/src/App.tsx`
- Contains: Page shells (`LearningHome`, `LearningPage`, `RevisionPage`, `SettingsPage`), concept/quiz UI (`ConceptCard`, not a separate QuizModal), chat panel.
- Depends on: feature hooks, `client/src/lib/*`, `client/src/types/`
- Used by: `client/src/main.tsx`

**Client application state:**
- Purpose: Server-state cache, optimistic mutations, SSE cache patches, ephemeral chat.
- Location: `client/src/providers/`, `client/src/features/learning/use*.ts`
- Contains: `QueryClient`, `useLearningMutations`, `useSessionEvents`, `useConceptChat`, `generationEvents.ts`
- Depends on: Axios/fetch API modules
- Used by: feature components

**HTTP / SSE API:**
- Purpose: REST contracts and streaming.
- Location: `server/routers/`
- Contains: `APIRouter` handlers, Pydantic response models, `StreamingResponse`
- Depends on: schemas, `GenerationRuntime`, repository facades, graph regen, concept chat
- Used by: `client/src/lib/learningApi.ts`, `chatApi.ts`, `regenApi.ts`, `storageApi.ts`

**Orchestration / domain services:**
- Purpose: Generation lifetime, research loop, chat, quiz shuffle, depth classify, SSE framing.
- Location: `server/services/`
- Contains: business orchestration that is not a LangGraph node
- Depends on: agents, search, schemas, repository facades
- Used by: routers and graph nodes

**LangGraph runtime:**
- Purpose: Durable staged course generation with fan-out workers.
- Location: `server/graph/`
- Contains: `StateGraph` topology, node functions, runner lock, regen helpers
- Depends on: agents, `depth_router`, `research_runner`, artifact/job/progress stores
- Used by: `GenerationRuntime` via `get_graph(app.state)`

**Agents:**
- Purpose: Structured LLM calls (outline, content, quizzes, research plan/synthesis).
- Location: `server/agents/`
- Contains: `BaseAgent` subclasses + module singletons (`planner_agent`, …)
- Depends on: `instructor_client`, `server/schemas/learning.py` / `research.py`
- Used by: graph nodes and regen

**Search:**
- Purpose: Grounded generation and concept-chat web search.
- Location: `server/search/`
- Contains: registry metadata, coordinator, budget, source safety, HTTP adapters
- Depends on: `SearchContext` headers; never persists keys
- Used by: `research_runner`, `concept_chat_search`

**Persistence:**
- Purpose: Learning, generation jobs, research, progress events, checkpoints.
- Location: `server/database/`
- Contains: SQLite stores, Mongo repositories, facades, migrations
- Depends on: `DB_PATH` (`server/database/persistence.py`), pymongo when cloud
- Used by: all server layers via facades

**Schemas:**
- Purpose: Pydantic v2 contracts for API and agents.
- Location: `server/schemas/`
- Contains: learning, generation, progress, research, search, llm, storage, common
- Depends on: pydantic, FastAPI `Header` dependencies for LLM/search context
- Used by: routers, agents, stores

## Data Flow

### Primary Request Path

Course generation (happy path, web search optional):

1. User submits topic on home (`client/src/features/learning/TopicInput.tsx` — `generateCourse` mutation ~line 105).
2. Client POSTs `/learning/generate` with LLM + optional `X-Web-Search*` headers (`client/src/lib/learningApi.ts:93`).
3. Router extracts `LLMContext` / `SearchContext`, requires per-agent models, calls runtime (`server/routers/learning.py:336`).
4. `GenerationRuntime.start` creates session shell + job, emits INITIALIZING event, schedules asyncio task (`server/services/generation_runtime.py:141`).
5. HTTP returns **202** shell + public job. Client seeds React Query and navigates to `/learn/:sessionId`.
6. `run_generation_job` acquires job lock, starts heartbeat, `graph.ainvoke` (`server/graph/runner.py:93`, graph task at line 231).
7. `initialize_generation_node` resolves lite/full via `resolve_depth_mode`, persists `resolved_mode` (`server/graph/nodes.py:259`).
8. Conditional research: `route_optional_research` → `researcher_node` → `run_research` (`server/graph/nodes.py:315`, `server/services/research_runner.py`).
9. `outline_planner_node` writes TOC nodes; `plan_brief_batch_node` then `Send` fan-out generators (`server/graph/build.py:75`).
10. Preview batch size 3, then batches of 10 (`PREVIEW_BATCH_SIZE` / `STANDARD_BATCH_SIZE` in `server/schemas/generation.py:224`). Generator then quizzer workers persist artifacts; `advance_batch_node` loops or finalizes.
11. Client `useSessionEvents` opens EventSource on `/learning/sessions/{id}/events` (`client/src/features/learning/useSessionEvents.ts:85`) and patches cache via `applyGenerationEvent`.

### Learning session + quiz (retrieval path)

1. `LearningPage` loads session (`getLearningSession`) and polls while generation is nonterminal (`client/src/features/learning/LearningPage.tsx:81`).
2. `LearningPathContainer` / `ConceptCard` drive VIEWING_EXPLANATION → IN_QUIZ → SHOWING_FEEDBACK → COMPLETED via `useLearningMutations` (`client/src/features/learning/useLearningMutations.ts`).
3. `POST /learning/nodes/{id}/transition` calls `learning_manager.update_node_status` (`server/routers/learning.py:1174`).
4. `POST /learning/nodes/{id}/quiz` scores by stable `option_id`; mastery unlocks next node. Router hides answers while `IN_QUIZ` (`_apply_node_visibility`, `server/routers/learning.py:204`).

### Concept chat

1. `useConceptChat` → `streamConceptChat` fetch SSE (`client/src/lib/chatApi.ts`).
2. `POST /learning/sessions/{session_id}/nodes/{node_id}/chat` (`server/routers/learning.py:1514`).
3. `stream_concept_chat` builds prompt from node markdown, optional one-shot `web_search` tool (`server/services/concept_chat.py`). History capped at 10 messages. Not persisted server-side (client `localStorage` blob).

### Node regeneration

1. ERROR nodes: `regenerate_failed_node` runs only failed step(s) (`server/graph/regen.py:45`).
2. Non-ERROR, non-LOCKED: `regenerate_topic_node` full content + quiz.
3. Streaming path: `POST /learning/nodes/{id}/regenerate/stream` → `stream_regenerate_node_generator` (`server/graph/regen_stream.py:43`; client `client/src/lib/regenApi.ts`).

### Storage backend switch (local deployment)

1. Client `bootstrapStorage` before first render (`client/src/lib/storageBoot.ts:63`).
2. `POST /settings/storage/connect` requires idle generation (`server/routers/storage.py:121`, `_require_idle` line 87).
3. `StorageContext.connect` indexes Mongo, builds Mongo bundle, activates `MongoDBSaver` (`server/database/storage_mode.py:158`). Facades resolve the new bundle on the next call.

**State Management:**
- **Server generation:** LangGraph checkpointer keyed by `thread_id` `gen-{session_id}`; job row + `progress_events` are the public surface.
- **Server learning:** SQLite/Mongo rows; node FSM enforced in `LearningManager.update_node_status` (`server/database/learning_persistence.py:1598`).
- **Client:** TanStack Query keys (`learningQueryKeys` in `optimisticUpdates.ts`). SSE patches `['learningSession', sessionId]`. Theme in `localStorage` (`agui-theme`). Provider/search settings in `localStorage`, optionally hydrated from Mongo `app_settings`.
- **Not applicable:** Redux, Graph DB, RAG index.

## Key Abstractions

**CourseState / CourseGraphContext:**
- Purpose: Checkpointable generation state vs request-scoped secrets.
- Examples: `server/graph/state.py`
- Pattern: TypedDict + `Annotated` keyed list reducers (`merge_generator_results`, `merge_topic_results`)

**RepositoryFacade + Protocol ports:**
- Purpose: Stable import identity while `StorageContext` swaps implementations.
- Examples: `server/database/repositories/facade.py`, `protocols.py`, `sqlite.py`, `mongo_factory.py`
- Pattern: Ports and adapters; `getattr` forwarder

**LLMContext / SearchContext:**
- Purpose: Request-scoped secrets as `SecretStr`, excluded from dumps/repr.
- Examples: `server/schemas/llm.py`, `server/schemas/search.py`
- Pattern: FastAPI `Depends(get_llm_context)` / `get_search_context`

**BaseAgent:**
- Purpose: Role-keyed structured generation.
- Examples: `server/agents/base.py`, `planner.py`, `generator.py`, `quizzer.py`, `researcher.py`
- Pattern: ABC + module-level singleton instances

**GenerationRuntime:**
- Purpose: Strong references to asyncio tasks so GC/disconnect cannot drop work.
- Examples: `server/services/generation_runtime.py`
- Pattern: Process-lifetime task registry on `app.state`

**NodeStatus state machine:**
- Purpose: Sequential mastery path.
- Examples: `server/schemas/learning.py` (`LOCKED` → `VIEWING_EXPLANATION` → `IN_QUIZ` → `SHOWING_FEEDBACK` → `COMPLETED`, plus `ERROR`)
- Pattern: Server-validated transitions; content/quiz visibility in router projection

**ProviderCoordinator:**
- Purpose: Deterministic multi-provider search with one retry then rotate.
- Examples: `server/search/coordinator.py`, `server/search/registry.py`
- Pattern: Job-scoped coordinator; no hidden retries; no rotate on auth errors

## Entry Points

**Vite SPA:**
- Location: `client/src/main.tsx`
- Triggers: Browser load of `client/index.html`
- Responsibilities: `bootstrapStorage()`, then `createRoot` with StrictMode, ThemeProvider, QueryProvider, `App`

**FastAPI process:**
- Location: `server/main.py` (`app`, `lifespan`)
- Triggers: `python -m uvicorn server.main:app --reload --port 8000` (`run.bat` / `run.sh`)
- Responsibilities: Init SQLite or cloud Mongo; bind checkpointer; construct `GenerationRuntime`; mark orphaned jobs paused; register routers

**Course graph compile:**
- Location: `server/graph/build.py` (`build_graph`, `get_graph`)
- Triggers: Lifespan `CheckpointerController.activate*` and first `get_graph(app.state)`
- Responsibilities: Wire START → initialize → optional research → outline → batched generate/quiz → END

**Generate HTTP:**
- Location: `server/routers/learning.py` `generate_course`
- Triggers: `POST /learning/generate`
- Responsibilities: Accept job, return 202; do not run the graph on the request task

## Architectural Constraints

- **Threading:** FastAPI asyncio event loop. Generation is `asyncio.create_task`. SQLite stores are **synchronous** and are called directly from many async route handlers (blocking the loop). Mongo connect/disconnect/migrate and some settings reads use `run_in_threadpool`. `StorageContext` uses `threading.RLock` for backend swap. LangGraph `max_concurrency` is 3 (`GENERATION_MAX_CONCURRENCY`).
- **Global state:** `settings` (`server/config.py:72`); `storage_context` and facade aliases (`server/database/storage_registry.py`); SQLite store instances in the same module; `instructor_client`; agent singletons in `server/agents/__init__.py`; `app.state.generation_runtime` / `course_graph` / `checkpointer` / `storage`; concept-chat `AsyncOpenAI` cache (`server/services/concept_chat.py:61`); client `QueryClient` (`QueryProvider.tsx:39`); `bootstrapStorage` singleton promise.
- **Circular imports:** `storage_registry._resolve_deployment_mode` reads env instead of importing `server.config` (`storage_registry.py:55`). `StorageContext._default_sqlite_repositories` lazy-imports `server.database` (`storage_mode.py:60`). `run_generation_job` lazy-imports `get_graph` (`runner.py:111`). Keep new code on facades; do not import `server.config` from `storage_registry`.
- **Credential boundary:** Never put API keys on `CourseState`, progress payloads, or research public reports. Generate/resume/chat/regen send keys; session GET/list/quiz/delete do not (`learningApi.ts` header policy).
- **Idle generation required** for local storage connect/disconnect/migrate (`server/routers/storage.py:87`).
- **Cloud mode:** `DEPLOYMENT_MODE=cloud` requires `MONGO_URI` and `MONGO_DB` at process start (`server/config.py:65`, `server/main.py:104`). SQLite checkpointer is unavailable (`checkpointer.py:61`).
- **Line budget:** Python public modules follow 80-character convention (`.planning/codebase/CONVENTIONS.md`).
- **Named exports:** Client convention is named exports only; `App.tsx` is the SPA exception (default export for Vite root).

## Anti-Patterns

### Putting generation work on the request task

**What happens:** Awaiting `graph.ainvoke` inside `generate_course`.
**Why it's wrong:** Browser close / proxy timeout cancels the request and the course.
**Do this instead:** `GenerationRuntime.start` + 202 (`server/services/generation_runtime.py:141`, `server/routers/learning.py:351`).

### Importing SQLite store classes from routers

**What happens:** `from server.database.learning_persistence import learning_manager` in a router after the facade cutover.
**Why it's wrong:** Bypasses Mongo swap; local and cloud diverge.
**Do this instead:** `from server.database.storage_registry import learning_repository as learning_manager` (`server/routers/learning.py:48`).

### Checkpointing secrets or full markdown in CourseState

**What happens:** Adding `api_key` or `content_markdown` to `CourseState`.
**Why it's wrong:** Checkpoints persist; keys leak; state bloats.
**Do this instead:** IDs + compact worker results only (`server/graph/state.py:99`). Content lives in `concept_nodes` / artifact stores.

### Client sending provider keys on session GET

**What happens:** Axios interceptor attaching `X-Provider-Api-Key` to every learning call.
**Why it's wrong:** Unnecessary secret exposure; contradicts scoped-header design.
**Do this instead:** Build LLM/search headers only in `generateCourse` / `resumeGeneration` / regen / chat (`client/src/lib/learningApi.ts:82`).

### Default-exporting feature modules

**What happens:** `export default function ConceptCard`.
**Why it's wrong:** Project convention is named exports (`client/src/features/learning/index.ts` barrel).
**Do this instead:** `export function ConceptCard` and re-export from the barrel. Keep `export default App` only in `client/src/App.tsx`.

### New request models living only on the router

**What happens:** Extra `BaseModel` classes in `server/routers/learning.py` (`GenerateCourseRequest` at line 121) while domain types live in `server/schemas/`.
**Why it's wrong:** Split contract; client types drift.
**Do this instead:** Add shared models under `server/schemas/` and import them in the router (existing generation/public types already follow this).

### Swallowing persistence errors without HTTP mapping

**What happens:** Bare `except Exception: pass` around progress `append_once` in the runner (`server/graph/runner.py:269`).
**Why it's wrong:** Client SSE never sees cancel/pause; UI stalls on polling.
**Do this instead:** Log with `log_external_failure` (`server/utils/safe_logging.py`) and still mark the job stage. Do not copy silent `pass` into new paths.

## Error Handling

**Strategy:** Domain exceptions at the store/runtime boundary; routers map to HTTP; graph runner maps to job stage + durable progress events. Re-raise `HTTPException` unchanged.

**Patterns:**
- Router try/except: `HTTPException` re-raise; unexpected → log + 500 (`server/routers/learning.py:361`, `server/routers/llm.py:164`).
- Generation control: `GenerationJobNotFound` → 404; `InvalidGenerationTransition` / `GenerationAlreadyRunning` → 409 (`server/routers/learning.py:897`).
- Node FSM: `ValueError` from `update_node_status` → 400 (`server/routers/learning.py:1196`).
- Regen: `LookupError` → 404; locked node → 400 (`server/routers/learning.py:1430`).
- Storage: `MongoConfigurationError` → 400; `MongoUnavailableError` → 503; cloud mode mutating endpoints → 403 (`server/routers/storage.py:139`).
- Graph: `GenerationCancelled`, `ResumableGenerationError` / `LockHeartbeatLost`, generic fail → job `CANCELLED` / `PAUSED` / `FAILED` (`server/graph/runner.py:248`).
- Client: Axios response interceptor logs URL + body then `Promise.reject` (`client/src/lib/learningApi.ts:66`). Mutations roll back optimistic cache (`useLearningMutations.ts`).

## Cross-Cutting Concerns

**Logging:** `logging.getLogger(__name__)` per module. `logging.basicConfig(level=INFO)` in `server/main.py:52`. External failures through `server/utils/safe_logging.py` (`log_external_failure`) so messages stay secret-free. Concept-chat router currently logs header presence at INFO (`server/routers/learning.py:1539`) — do not log key material.

**Validation:** Pydantic v2 on requests/responses (`Field` constraints, `ConfigDict(from_attributes=True)` in `server/schemas/common.py`). Agent outputs validated by Instructor against Pydantic models. Quiz submit uses stable `option_id` UUIDs, not shuffled labels (`QuizSubmitRequest` in `server/routers/learning.py:172`).

**Authentication:** Not detected as user accounts/sessions. Authorization is **provider-key based**: `X-AI-Provider`, `X-Provider-Api-Key`, per-agent model headers, optional OpenRouter attribution headers (`server/schemas/llm.py`). Search keys via `X-Tavily-Key` / `X-Exa-Key` / `X-Brave-Key` / `X-SerpApi-Key` (`server/schemas/search.py:33`). CORS allows localhost Vite origins (`server/main.py:161`).

**Observability of generation:** Durable `progress_events` + SSE replay (`Last-Event-ID` / `after` query). Disconnect must not cancel jobs (`server/services/session_event_stream.py`).

---

*Architecture analysis: 2026-09-05*
