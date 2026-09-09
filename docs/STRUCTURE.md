# Codebase Structure

**Analysis Date:** 2026-09-05

## Directory Layout

```
A2UI/
├── client/                          # Vite + React 19 + TypeScript SPA
│   ├── public/                      # Static assets (`vite.svg`)
│   ├── src/
│   │   ├── components/              # Shared chrome (ThemeToggle, SettingsButton)
│   │   ├── features/
│   │   │   ├── learning/            # Primary product UI + hooks + tests
│   │   │   │   ├── animations/      # Confetti, mastery, card transitions
│   │   │   │   └── __tests__/       # Cross-cutting generation UI tests
│   │   │   └── settings/            # Provider, agent models, search, storage
│   │   ├── hooks/                   # App-wide hooks (theme, typewriter)
│   │   ├── lib/                     # HTTP/SSE clients, settings, cn()
│   │   ├── providers/               # QueryProvider, ThemeProvider
│   │   ├── test/                    # Shared test fakes (FakeEventSource)
│   │   ├── types/                   # TS contracts mirroring server schemas
│   │   ├── App.tsx                  # react-router-dom routes
│   │   ├── main.tsx                 # Bootstrap after storage boot
│   │   └── index.css                # Tailwind 4 entry
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts               # Alias `@` → `src`, Vitest jsdom
│   ├── vitest.setup.ts
│   └── vitest.generation.config.ts  # Generation-focused coverage run
├── server/                          # FastAPI package (`python -m uvicorn server.main:app`)
│   ├── agents/                      # Planner, Generator, Quizzer, Researcher
│   ├── data/                        # Runtime SQLite files (gitignored `*.db`)
│   ├── database/
│   │   └── repositories/            # Protocol ports, SQLite adapters, Mongo impls
│   ├── graph/                       # LangGraph topology, runner, regen
│   ├── routers/                     # HTTP API
│   ├── schemas/                     # Pydantic v2 contracts
│   ├── search/
│   │   └── adapters/                # Tavily, Exa, Brave, SerpAPI
│   ├── services/                    # Non-graph orchestration
│   ├── tests/                       # stdlib unittest
│   ├── utils/                       # Instructor, logging, mermaid, prompt cache
│   ├── config.py                    # Env-backed Settings singleton
│   ├── main.py                      # FastAPI entry
│   ├── requirements.txt
│   └── .env.example                 # Template only (do not copy secrets)
├── docs/                            # Feature plans + this architecture map
│   ├── concept-chat-websearch/
│   ├── internet-grounded-course-generation/
│   ├── learning-depth-modes/
│   ├── mongodb-atlas-storage/
│   ├── per-agent-model-selection/
│   └── superpowers/                 # Historical specs/plans — do not overwrite
├── mcps/                            # Local MCP task tool JSON stubs
├── .planning/                       # Specs/roadmaps (gitignored; agent-facing)
├── run.bat / run.sh                 # Start API :8000 + Vite :5173
├── setup.bat / setup.sh             # Bootstrap venv + npm
├── AGENTS.md                        # Agent orientation (gitignored)
├── README.md
└── LICENSE
```

**Not detected on disk:** `conductor/` (named in `.gitignore` and `AGENTS.md`). **Not detected:** `.claude/skills/`, `.agents/skills/`. **Existence only:** root `.env`. Do not read or quote env files.

## Directory Purposes

**`client/`:**
- Purpose: Entire frontend. One Vite app; no Next.js, no additional packages.
- Contains: React 19 + TS strict, Tailwind 4, Vitest colocated tests.
- Key files: `client/src/main.tsx`, `client/src/App.tsx`, `client/package.json`

**`client/src/features/learning/`:**
- Purpose: Adaptive learning product surface.
- Contains: pages, ConceptCard (quiz UI lives here — no `QuizModal`), ChatPanel, generation status, revision, hooks, animations, `*.test.tsx`.
- Key files: `LearningHome.tsx`, `LearningPage.tsx`, `LearningPathContainer.tsx`, `ConceptCard.tsx`, `index.ts` barrel

**`client/src/features/settings/`:**
- Purpose: Provider keys, per-agent models, web search, Mongo storage UI.
- Contains: `SettingsPage.tsx` plus panels.
- Key files: `SettingsPage.tsx`, `AgentModelsPanel.tsx`, `StorageSettingsPanel.tsx`, `WebSearchSettingsPanel.tsx`

**`client/src/lib/`:**
- Purpose: Transport and client-side settings. No React components.
- Contains: Axios learning/storage clients; fetch SSE for chat/regen; header builders; `storageBoot`.
- Key files: `learningApi.ts`, `chatApi.ts`, `regenApi.ts`, `storageApi.ts`, `providerSettings.ts`, `startApplication.ts`

**`client/src/types/`:**
- Purpose: TypeScript mirrors of API payloads.
- Contains: `learning.ts`, `generation.ts`, `storage.ts`, `webSearch.ts`, `provider.ts`, `openrouter.ts`
- Key files: `client/src/types/learning.ts`

**`server/`:**
- Purpose: Importable Python package `server.*`. Run from repo root with `server/.venv`.
- Contains: FastAPI app, graph, agents, persistence.
- Key files: `server/main.py`, `server/config.py`, `server/requirements.txt`

**`server/routers/`:**
- Purpose: HTTP only. No SQLite SQL. Thin: validate → call runtime/facade → map errors.
- Contains: `learning.py`, `llm.py`, `storage.py`, `__init__.py` re-exports.
- Key files: `server/routers/learning.py`

**`server/graph/`:**
- Purpose: Durable course generation state machine and standalone regen.
- Contains: `build.py`, `nodes.py`, `state.py`, `runner.py`, `regen.py`, `regen_stream.py`
- Key files: `server/graph/build.py`, `server/graph/nodes.py`

**`server/agents/`:**
- Purpose: LLM roles with Instructor structured output.
- Contains: `base.py`, `planner.py`, `generator.py`, `quizzer.py`, `researcher.py`
- Key files: `server/agents/base.py`

**`server/services/`:**
- Purpose: Orchestration that is not a graph node and not HTTP.
- Contains: generation runtime, research runner, concept chat, depth router, quiz shuffle, SSE framing, citation sanitize.
- Key files: `server/services/generation_runtime.py`, `concept_chat.py`

**`server/database/`:**
- Purpose: Persistence + storage backend swap.
- Contains: SQLite managers, generation schema migrations, Mongo client, repository ports/adapters, checkpointer controller.
- Key files: `storage_registry.py`, `storage_mode.py`, `learning_persistence.py`, `persistence.py` (`DB_PATH`)

**`server/database/repositories/`:**
- Purpose: Protocol boundary so Mongo can replace SQLite without touching routers.
- Contains: `protocols.py`, `facade.py`, `sqlite.py`, `mongo_*.py`, `bundle.py`, `errors.py`
- Key files: `protocols.py`, `mongo_factory.py`

**`server/schemas/`:**
- Purpose: Pydantic v2 API and agent contracts.
- Contains: `common.py`, `learning.py`, `generation.py`, `progress.py`, `research.py`, `search.py`, `llm.py`, `storage.py`
- Key files: `server/schemas/learning.py`, `generation.py`

**`server/search/`:**
- Purpose: Web search for grounded generation and concept chat.
- Contains: coordinator, budget, source_safety, registry, HTTP helpers, `adapters/`
- Key files: `coordinator.py`, `registry.py`

**`server/utils/`:**
- Purpose: Shared non-domain helpers.
- Contains: Instructor wrapper, safe logging, mermaid validator, prompt cache.
- Key files: `instructor_client.py`

**`server/tests/`:**
- Purpose: `unittest` suite. File names `test_*.py`.
- Contains: graph, generation, mongo, search, concept chat, regen, storage tests + harnesses.
- Key files: `server/tests/generation_acceptance_harness.py`, `llm_test_helpers.py`

**`server/data/`:**
- Purpose: Local `a2ui.db` and `checkpoints.db`.
- Contains: runtime databases (gitignored).
- Key files: paths only — do not commit DB files

**`docs/`:**
- Purpose: Feature implementation docs and this map. Do not overwrite `docs/superpowers/` or feature subfolders when adding architecture docs.
- Contains: plans, research, reviews, `ARCHITECTURE.md`, `STRUCTURE.md`
- Key files: `docs/ARCHITECTURE.md`, `docs/STRUCTURE.md`

**`.planning/`:**
- Purpose: Spec-driven development sources (ARCHITECTURE/STACK/CONVENTIONS/TESTING). Gitignored.
- Contains: codebase specs, milestones, phase notes.
- Key files: `.planning/codebase/ARCHITECTURE.md`, `CONVENTIONS.md`, `STRUCTURE.md`

**`mcps/`:**
- Purpose: Local MCP task tool descriptors.
- Contains: JSON tool stubs under `mcps/tasks/tools/`
- Key files: Not application runtime

## Key File Locations

**Entry Points:**
- `client/src/main.tsx`: SPA bootstrap after `bootstrapStorage`
- `client/src/App.tsx`: Routes `/`, `/learn`, `/learn/:sessionId`, `/learn/:sessionId/revise/:revisionId`, `/settings`
- `client/src/lib/startApplication.ts`: Await storage boot then render
- `server/main.py`: FastAPI `app`, lifespan, CORS, router include
- `server/graph/build.py`: `build_graph` / `get_graph`
- `run.bat` / `run.sh`: Dev process launcher

**Configuration:**
- `server/config.py`: `DEPLOYMENT_MODE`, Mongo, OpenRouter/General Compute URLs
- `server/.env.example`: Env template (existence only)
- `client/vite.config.ts`: `@` alias, Vitest
- `client/tsconfig.app.json`: Strict TS, `@/*` paths
- `client/package.json`: `dev` / `build` / `test` scripts
- `server/requirements.txt`: FastAPI, LangGraph 1.2.4, pymongo, Instructor

**Core Logic:**
- `server/routers/learning.py`: Learning HTTP surface
- `server/services/generation_runtime.py`: Detached generation tasks
- `server/graph/runner.py`: Locked `ainvoke`
- `server/graph/nodes.py`: Staged pipeline nodes
- `server/database/storage_registry.py`: Facade aliases + SQLite init
- `server/database/learning_persistence.py`: Node FSM + learning tables
- `client/src/lib/learningApi.ts`: Typed learning client
- `client/src/features/learning/useLearningMutations.ts`: Optimistic quiz/progress mutations
- `client/src/features/learning/useSessionEvents.ts`: Generation SSE

**Testing:**
- `client/src/**/*.test.ts(x)`: Colocated Vitest + Testing Library
- `client/src/features/learning/__tests__/`: Cross-file generation UI tests
- `client/vitest.setup.ts`: jsdom + jest-dom
- `server/tests/test_*.py`: unittest modules
- `server/tests/llm_test_helpers.py`: Shared LLM test doubles

## Naming Conventions

**Files:**
- Python modules: `snake_case.py` (`generation_runtime.py`, `learning_persistence.py`)
- Python tests: `test_<area>.py` in `server/tests/`
- React components: `UpperCamelCase.tsx` (`ConceptCard.tsx`, `LearningPage.tsx`)
- Hooks: `useX.ts` / `useX.tsx` (`useSessionEvents.ts`, `useErrorToast.tsx`)
- Client tests: colocated `*.test.ts` / `*.test.tsx`
- Types: domain noun `learning.ts`, `generation.ts`
- API modules: `<domain>Api.ts` (`learningApi.ts`, not a single `api.ts`)

**Directories:**
- Client features: `features/<feature>/` with barrel `index.ts`
- Server layers: plural nouns (`routers`, `schemas`, `agents`, `services`)
- Persistence adapters: `database/repositories/mongo_<domain>.py`
- Search providers: `search/adapters/<provider>.py`

**Symbols:**
- Python: `snake_case` functions, `PascalCase` classes, module loggers `__name__`
- TypeScript: named exports; `UpperCamelCase` components/types; hooks start with `use`
- Constants: `CONSTANT_CASE` (`CHECKPOINT_DB_PATH`, `PREVIEW_BATCH_SIZE`)
- FastAPI routers: `APIRouter(prefix=..., tags=...)` then `router` imported as `*_router`

## Where to Add New Code

**New Feature (end-to-end learning capability):**
- Primary UI: `client/src/features/learning/` (or new `client/src/features/<name>/` if it is not learning)
- Barrel: export from `client/src/features/learning/index.ts` or a new feature `index.ts`
- Route: register in `client/src/App.tsx` only if it needs a URL
- Client types: `client/src/types/<domain>.ts`
- HTTP client: `client/src/lib/<domain>Api.ts` (SSE → fetch module like `chatApi.ts`)
- Server schema: `server/schemas/<domain>.py`
- Router: new `server/routers/<domain>.py` **or** endpoints on existing router if it is still learning
- Register router: `server/routers/__init__.py` + `app.include_router` in `server/main.py`
- Tests: colocated Vitest; `server/tests/test_<domain>.py`
- File headers: mandatory 76-`=` block on new `.ts`/`.tsx`/`.py` (see `AGENTS.md`)

**New REST endpoint (learning domain):**
- Implementation: `server/routers/learning.py`
- Request/response models: prefer `server/schemas/learning.py` (avoid growing inline router models)
- Persistence: method on `LearningRepository` protocol **and** SQLite `LearningManager` **and** Mongo `mongo_learning.py`
- Client: function on `client/src/lib/learningApi.ts` + types in `client/src/types/learning.ts`

**New LangGraph node / generation stage:**
- State fields: `server/graph/state.py` (never secrets or large markdown)
- Node function: `server/graph/nodes.py`
- Wire topology: `server/graph/build.py`
- Stage/event contracts: `server/schemas/generation.py`, `server/schemas/progress.py`
- Job persistence: `GenerationJobRepository` implementations
- Tests: `server/tests/test_graph.py`, `test_staged_graph.py`, `test_generation_*.py`

**New AI agent role:**
- Class: `server/agents/<role>.py` subclassing `BaseAgent`
- Export singleton: `server/agents/__init__.py`
- Model header/role: `REQUIRED_AGENT_ROLES` in `server/schemas/llm.py` + client `agentModelHeaders.ts` / `AgentModelsPanel.tsx`
- Instructor role config: `server/utils/instructor_client.py` `MODEL_CONFIGS`

**New web-search provider:**
- Metadata: `server/search/registry.py`
- Adapter: `server/search/adapters/<name>.py`
- Header name: `server/schemas/search.py` `_PROVIDER_KEY_HEADERS`
- Client: `client/src/lib/webSearchProviders.ts`, `webSearchHeaders.ts`, `WebSearchSettingsPanel.tsx`

**New Mongo/SQLite persistence method:**
- Add to Protocol in `server/database/repositories/protocols.py`
- Implement on SQLite store (`learning_persistence.py` or focused `generation_*.py`)
- Wrap via `server/database/repositories/sqlite.py` if a new store class
- Implement Mongo counterpart `mongo_*.py`
- Call sites import **facades** from `storage_registry.py`, never the store class

**New shared UI chrome:**
- Implementation: `client/src/components/`
- Do not put page-specific learning widgets here — those stay in `features/learning/`

**Utilities:**
- Shared client helpers: `client/src/lib/utils.ts` (`cn()`) or a focused `client/src/lib/<name>.ts`
- Shared server helpers: `server/utils/`
- Quiz shuffle: `server/services/quiz_randomization.py` (already the home)
- Mermaid: `server/utils/mermaid_validator.py` (server), `client/src/features/learning/mermaidUtils.ts` (client)

**Do not put:**
- SQL in routers or graph nodes (use repositories)
- API keys in `CourseState` or progress payloads
- New default-exported React components (named exports only)
- Architecture docs under `.planning/codebase/` from this mapping job — live copies are `docs/ARCHITECTURE.md` and `docs/STRUCTURE.md`
- Feature plan overwrites under `docs/superpowers/`, `docs/mongodb-atlas-storage/`, etc.

## Special Directories

**`server/.venv/`:**
- Purpose: Python 3.10+ (repo also used 3.14) virtualenv
- Generated: Yes
- Committed: No

**`server/data/`:**
- Purpose: `a2ui.db`, `checkpoints.db`
- Generated: Yes (created at lifespan)
- Committed: No (`*.db` gitignored)

**`client/node_modules/`, `client/dist/`, `client/coverage/`:**
- Purpose: npm deps, production build, Vitest coverage HTML
- Generated: Yes
- Committed: No

**`.planning/`:**
- Purpose: Specs, roadmaps, phase notes for agents
- Generated: No (authored)
- Committed: No (gitignored)

**`conductor/`:**
- Purpose: Product/UI guidelines per `AGENTS.md`
- Generated: No
- Committed: No (gitignored)
- Present: Not detected

**`docs/superpowers/` and other `docs/<feature>/`:**
- Purpose: Historical feature specs/plans/reviews
- Generated: No
- Committed: Yes
- Rule: Do not overwrite when adding architecture maps

**`mcps/`:**
- Purpose: Local MCP task tool JSON
- Generated: No
- Committed: Yes (present)

**`__pycache__/`, `.ruff_cache/`:**
- Purpose: Bytecode / linter cache
- Generated: Yes
- Committed: No

**Root `.env`:**
- Purpose: Local secrets and `DEPLOYMENT_MODE`
- Generated: No (operator-created)
- Committed: No
- Rule: Never read or quote

## SQLite tables (where data lives)

Created by `LearningManager.init_learning_tables` (`server/database/learning_persistence.py`) and `initialize_generation_schema` (`server/database/generation_migrations.py`):

| Table | Owner module |
|-------|----------------|
| `learning_sessions` | `learning_persistence.py` |
| `concept_nodes` | `learning_persistence.py` |
| `quiz_data` | `learning_persistence.py` |
| `revision_sessions` | `learning_persistence.py` |
| `quiz_attempts` | `learning_persistence.py` |
| `revision_node_progress` | `learning_persistence.py` |
| `generation_jobs` | `generation_migrations.py` |
| `research_reports` / `research_sources` / `research_sections` / `research_section_sources` / `research_provider_statuses` | `generation_migrations.py` |
| `generation_briefs` | `generation_migrations.py` |
| `node_sources` | `generation_migrations.py` |
| `progress_events` | `generation_migrations.py` |
| `generation_schema_migrations` | `generation_migrations.py` |

LangGraph checkpoints: `server/data/checkpoints.db` (local) or Mongo collections `checkpoints` / `checkpoint_writes` (`server/database/checkpointer.py`).

## HTTP map (where endpoints live)

All learning routes: prefix `/learning` in `server/routers/learning.py`.

| Method | Path | Handler |
|--------|------|---------|
| POST | `/learning/generate` | `generate_course` |
| GET | `/learning/sessions` | `get_learning_sessions` |
| GET | `/learning/sessions/{id}` | `get_learning_session` |
| GET | `/learning/sessions/{id}/progress` | `get_learning_session_progress` |
| PATCH | `/learning/sessions/{id}/last-active` | `update_last_active` |
| GET | `/learning/sessions/{id}/research` | `get_session_research` |
| GET | `/learning/sessions/{id}/events` | `stream_learning_session_events` (SSE) |
| POST | `/learning/sessions/{id}/cancel` | `cancel_generation` |
| POST | `/learning/sessions/{id}/resume` | `resume_generation` |
| DELETE | `/learning/sessions/{id}` | `delete_learning_session` |
| POST | `/learning/sessions/{id}/revisions` | `create_revision` |
| GET | `/learning/sessions/{id}/revisions` | `get_revisions_for_session` |
| GET/DELETE | `/learning/revisions/{id}` | `get_revision` / `delete_revision` |
| POST | `/learning/revisions/{id}/nodes/{node_id}/reviewed` | `mark_revision_node_reviewed` |
| POST | `/learning/revisions/{id}/quiz` | `submit_revision_quiz` |
| GET | `/learning/revisions/{id}/summary` | `get_revision_summary` |
| GET | `/learning/nodes/{id}` | `get_concept_node` |
| POST | `/learning/nodes/{id}/transition` | `transition_node` |
| GET | `/learning/nodes/{id}/attempts` | `get_quiz_attempts` |
| POST | `/learning/nodes/{id}/quiz` | `submit_quiz` |
| POST | `/learning/nodes/{id}/quiz/retry` | `retry_quiz` |
| POST | `/learning/nodes/{id}/quiz/previous` | `previous_quiz` |
| POST | `/learning/nodes/{id}/regenerate` | `regenerate_node_endpoint` |
| POST | `/learning/nodes/{id}/regenerate/stream` | `stream_regenerate_node_endpoint` |
| POST | `/learning/sessions/{sid}/nodes/{nid}/chat` | `concept_chat` (SSE) |

Other routers: `GET /llm/models` (`server/routers/llm.py`); `/settings/storage/status|connect|disconnect|migrate|app-settings` (`server/routers/storage.py`); `GET /` and `GET /health` (`server/main.py`).

**Not detected:** `GET /chat`, chat-session CRUD, `client/src/lib/api.ts`, `QuizModal.tsx`.

## Import boundaries

Allowed direction (do not invert):

```
routers → services / graph / schemas / storage_registry facades
graph/nodes → agents / services / facades / schemas
agents → instructor_client / schemas / llm context
services → agents / search / facades / schemas
search → types / http / registry (no routers)
database stores → schemas / sqlite_utils
repositories/mongo_* → pymongo + schemas (not sqlite3)
client features → lib + types (not server paths)
```

Client path alias: `import { x } from '@/features/learning'` resolves via `client/vite.config.ts` `@` → `./src`.

Server imports: always `server.<pkg>` (run as `python -m` from repo root).

---

*Structure analysis: 2026-09-05*
