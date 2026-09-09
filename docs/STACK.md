# Technology Stack

**Analysis Date:** 2026-09-05

## Languages

**Primary:**
- TypeScript 5.9.3 (declared `~5.9.3` in `client/package.json`; lockfile `5.9.3`) — `client/` SPA. Strict mode in `client/tsconfig.app.json` (`strict`, `noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch`, `erasableSyntaxOnly`). Target ES2022, JSX `react-jsx`, bundler module resolution, `allowImportingTsExtensions`, `verbatimModuleSyntax`, path alias `@/*` → `client/src/*`.
- Python 3.10+ required (`setup.bat`, `README.md`). Local venv `server/.venv` currently Python 3.14.3. Backend lives under `server/` (FastAPI app `server.main:app`). No `pyproject.toml`, `Pipfile`, or `poetry.lock`.

**Secondary:**
- HTML — `client/index.html` Vite entry (`/src/main.tsx`).
- CSS — Tailwind v4 via `@import "tailwindcss"` in `client/src/index.css`; remaining `client/tailwind.config.js` content scan. Google Fonts import for Lexend and Fira Code.
- Batch — `setup.bat`, `run.bat` (Windows install/start).
- Markdown — course content rendered client-side (`react-markdown` + remark/rehype plugins).

No root `package.json`. Client package name `client` version `0.0.0` (`private`, `"type": "module"`).

## Runtime

**Environment:**
- Browser: Vite 7.3.3 dev server default port 5173; production build `tsc -b && vite build` → `client/dist/`.
- Node.js: README/`setup.bat` say Node 18+. Locked Vite 7.3.3 engines: `^20.19.0 || >=22.12.0`. Locked `react-router-dom` 7.13.0 engines: `>=20.0.0`. Treat Node 20.19+ or 22.12+ as the real floor. Local machine observed Node v23.3.0.
- Python: CPython 3.10+; run via `python -m uvicorn server.main:app --reload --port 8000` with `server/.venv`.
- npm 10.9.0 observed locally.

**Package Manager:**
- Client: npm. Lockfile: `client/package-lock.json` present (`lockfileVersion` 3). No `pnpm-lock.yaml`, `yarn.lock`, or `bun.lock`.
- Server: pip + `server/requirements.txt`. No Python lockfile. Most packages unpinned except:
  - `langgraph==1.2.4`
  - `langgraph-checkpoint-sqlite==3.1.0`
  - `aiosqlite==0.22.1`
  - `pymongo[srv]>=4.13,<4.17`
  - `langgraph-checkpoint-mongodb==0.4.0`
- Installed in local `server/.venv` (for reference, not a lock): FastAPI 0.141.1, uvicorn 0.52.1, httpx 0.28.1, openai 2.52.0, pydantic 2.13.4, instructor 1.15.4, tenacity 9.1.4, python-dotenv 1.2.2, langchain 1.3.9, langgraph 1.2.4, pymongo 4.16.0, aiosqlite 0.22.1, jsonref 1.1.0, watchdog 6.0.0, langgraph-checkpoint-sqlite 3.1.0, langgraph-checkpoint-mongodb 0.4.0.

## Frameworks

**Core:**

*Client (`client/`):*
- React 19.2.0 declared; lockfile `react`/`react-dom` 19.2.4 — UI.
- React Router DOM 7.13.0 — routes `/`, `/chat`, `/learn`, `/learn/:sessionId`, revision and `/settings` (`README.md`, `client/src/App.tsx`).
- TanStack React Query 5.90.20 — server state; `client/src/providers/QueryProvider.tsx` (staleTime 5 min, retry 1, `refetchOnWindowFocus: false`).
- Axios 1.13.4 declared; lockfile 1.16.1 — REST clients in `client/src/lib/learningApi.ts`, `providerApi.ts`, `storageApi.ts`. SSE uses native `fetch` (`chatApi.ts`, `regenApi.ts`) and `EventSource` (`useSessionEvents.ts`).
- Tailwind CSS 4.1.18 + `@tailwindcss/vite` 4.1.18 + `@tailwindcss/typography` ^0.5.19 — utility CSS. `clsx` 2.1.1 + `tailwind-merge` 3.4.0 via `cn()` in `client/src/lib/utils.ts`.
- Framer Motion 12.29.2 — learning animations.
- Lucide React 0.563.0 — icons.

*Server (`server/`):*
- FastAPI (unpinned; venv 0.141.1) — `server/main.py` app title `A2UI Backend` version `1.0.0`. Routers: `server/routers/learning.py` prefix `/learning`, `server/routers/llm.py` prefix `/llm`, `server/routers/storage.py` prefix `/settings/storage`.
- Uvicorn `[standard]` (venv 0.52.1) — ASGI server port 8000.
- Pydantic v2 (venv 2.13.4) — `ConfigDict`, `Field`, `SecretStr` in `server/schemas/`.
- LangGraph 1.2.4 — course generation graph in `server/graph/` (`build.py`, `nodes.py`, `state.py`, `runner.py`, `regen.py`, `regen_stream.py`). Checkpointers: `AsyncSqliteSaver` (`langgraph.checkpoint.sqlite.aio`) and `MongoDBSaver` (`langgraph.checkpoint.mongodb`).
- Instructor (venv 1.15.4) — structured JSON via `instructor.from_openai(..., mode=instructor.Mode.JSON)` in `server/utils/instructor_client.py`.
- OpenAI Python SDK (venv 2.52.0) — `AsyncOpenAI` OpenAI-compatible client for OpenRouter / General Compute / (concept-chat only) api.openai.com.

**Testing:**
- Client: Vitest 3.2.4 + jsdom 27.0.1 + Testing Library (`@testing-library/react` ^16.3.2, `@testing-library/jest-dom` ^6.9.1, `@testing-library/dom` ^10.4.1). Config in `client/vite.config.ts` (`environment: 'jsdom'`, `globals: true`, `setupFiles: './vitest.setup.ts'`). Coverage `@vitest/coverage-v8` ^3.2.4. Extra gate: `client/vitest.generation.config.ts` per-file 81% thresholds. Scripts: `npm test`, `npm run test:generation:coverage`. Tests co-located `*.test.ts` / `*.test.tsx`.
- Server: stdlib `unittest` under `server/tests/` (`test_*.py`). Run `python -m unittest`. No pytest.ini / pytest dependency.

**Build/Dev:**
- Vite 7.3.4 declared; lockfile 7.3.3 — `client/vite.config.ts` plugins `@vitejs/plugin-react` 5.1.2 and `@tailwindcss/vite`. Alias `@` → `./src`. `chunkSizeWarningLimit: 1000`.
- TypeScript project references: `client/tsconfig.json` → `tsconfig.app.json` + `tsconfig.node.json`.
- ESLint 9.39.2 (declared ^9.39.1) flat config `client/eslint.config.js` (`@eslint/js`, `typescript-eslint` ^8.46.4 / lock 8.54.0, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`). Script `npm run lint`.
- Autoprefixer ^10.4.23 and PostCSS ^8.5.6 listed in `client/package.json`; no `postcss.config.*` detected. Tailwind 4 processing is the Vite plugin.
- No Dockerfile, docker-compose, Procfile, `.github/` workflows, `vercel.json`, or similar detected.
- No `.nvmrc`, `.python-version`, `runtime.txt`, `ruff.toml`, `mypy.ini`, or Prettier config detected (gitignore mentions `.ruff_cache/`, `.mypy_cache/`, `.pytest_cache/` only).

## Key Dependencies

**Critical:**
- `openai` + `instructor` + `tenacity` — LLM structured generation with 3-attempt exponential retry in `server/utils/instructor_client.py`. Roles: planner, generator, quizzer, depth_router, researcher.
- `langgraph==1.2.4` — durable staged course graph; checkpoint DB `server/data/checkpoints.db` (`CHECKPOINT_DB_PATH` in `server/graph/build.py`).
- `langgraph-checkpoint-sqlite==3.1.0` + `aiosqlite==0.22.1` — local async SQLite saver (`server/main.py` lifespan).
- `langgraph-checkpoint-mongodb==0.4.0` + `pymongo[srv]` — Atlas checkpointer collections `checkpoints` / `checkpoint_writes` (`server/database/checkpointer.py`).
- `httpx` — OpenRouter/General Compute model catalog proxy (`server/routers/llm.py`) and web-search adapters (`server/search/adapters/`).
- `python-dotenv` — `load_dotenv()` in `server/config.py`.
- `fastapi` CORS — `CORSMiddleware` in `server/main.py`.
- React Query + Axios + EventSource — client ↔ FastAPI; generation progress SSE at `GET /learning/sessions/{id}/events`.
- `react-markdown` ^10.1.0 with `remark-gfm`, `remark-math`, `remark-emoji`, `rehype-katex`, `rehype-raw`, `rehype-sanitize`, `rehype-external-links`, `react-syntax-highlighter` — `client/src/features/learning/MarkdownRenderer.tsx`.
- `katex` 0.16.47 + `mermaid` 11.16.0 — math and diagrams.
- `html2canvas-pro` ^2.3.3 + `jspdf` ^4.2.1 + `jszip` ^3.10.1 — PDF/ZIP export in `client/src/features/learning/pdfExportUtils.ts`. `html2pdf.js` is declared in `client/package.json` but no runtime import in `client/src` (only `client/src/types/html2pdf.d.ts`).

**Infrastructure:**
- SQLite via stdlib `sqlite3` — app DB `server/data/a2ui.db` (`server/database/persistence.py` `DB_PATH`). No SQLAlchemy/ORM.
- MongoDB Atlas optional — `server/database/mongo_client.py` (`MongoClient`, ping, pool `maxPoolSize=50`, `w=majority`). Repository swap in `server/database/storage_mode.py` (`DeploymentMode` local|cloud, `StorageBackend` sqlite|mongo).
- `watchdog`, `jsonref`, `langchain` — listed in `server/requirements.txt`; no application `import` in `server/` detected (langchain appears only as example URLs in tests). Treat as unused declared deps.
- Logging: stdlib `logging.basicConfig(level=logging.INFO)` in `server/main.py`; secret-safe helper `server/utils/safe_logging.py`; search URL redaction in `server/search/http.py`.
- In-process cache: OpenRouter prompt `cache_control` in `server/utils/prompt_cache.py` (Anthropic/Google/Qwen families). No Redis.
- Google Fonts CDN — Lexend + Fira Code from `client/src/index.css`.

## Configuration

**Environment:**
- Server loads dotenv at import (`server/config.py`). Env **names** (never values): `DEPLOYMENT_MODE` (`local`|`cloud`, default `local`), `MONGO_URI`, `MONGO_DB` (required when cloud), `OPENROUTER_BASE_URL` (default `https://openrouter.ai/api/v1`), `OPENROUTER_TIMEOUT_SECONDS` (default `60.0`), `GENERALCOMPUTE_BASE_URL` (default `https://api.generalcompute.com/v1`), `GENERALCOMPUTE_TIMEOUT_SECONDS` (default `60.0`), `CORS_ORIGINS` (default `http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175` plus localhost origin regex in `server/main.py`).
- Client: `VITE_API_URL` (`import.meta.env.VITE_API_URL`, fallback `http://localhost:8000`) in `learningApi.ts`, `providerApi.ts`, `storageApi.ts`, `chatApi.ts`, `regenApi.ts`, `useSessionEvents.ts`, `LearningPage.tsx`.
- LLM/search secrets are **not** server env in local mode. Browser `localStorage` keys: `ai_provider_settings` (legacy `openrouter_settings`), `web_search_settings`, `a2ui_mongo_storage`, theme `agui-theme` (tests), concept chat per-node keys. Request headers carry keys (`X-OpenRouter-Key`, `X-GeneralCompute-Key`, `X-Tavily-Key`, etc.).
- Files present (contents not read): root `.env`; `server/.env.example`. `client/.env` not detected. `.gitignore` ignores `.env` / `.env.local` / `.env.*.local` and allows `!.env.example`.

**Build:**
- Client: `client/package.json` scripts `dev`/`build`/`lint`/`preview`/`test`. Config files: `client/vite.config.ts`, `client/vitest.setup.ts`, `client/vitest.generation.config.ts`, `client/tsconfig.json`, `client/tsconfig.app.json`, `client/tsconfig.node.json`, `client/eslint.config.js`, `client/tailwind.config.js`, `client/src/index.css`.
- Server: `server/requirements.txt`, `server/config.py`. No `pyproject.toml`.
- Windows: `setup.bat` creates `server/.venv`, `pip install -r server/requirements.txt`, `npm install` in `client/`. `run.bat` starts uvicorn :8000 and `npm run dev`.

## Platform Requirements

**Development:**
- Python 3.10+ with venv at `server/.venv`.
- Node 20.19+ or 22.12+ (Vite 7 lockfile engines); npm for `client/`.
- OpenRouter and/or General Compute API key entered in Settings UI (not required in server env for local).
- Optional web search keys (Tavily, Exa, Brave, SerpAPI) in Settings.
- Optional MongoDB Atlas for cloud/local-connect storage.
- Ports: backend 8000, frontend 5173. Health `GET /health`. OpenAPI `http://localhost:8000/docs`.
- OS scripts assume Windows for `setup.bat`/`run.bat`; README documents POSIX venv + uvicorn + `npm run dev`.

**Production:**
- Not detected: no Docker, no CI, no PaaS/host config in-repo.
- Runtime model: Vite-built SPA talking to FastAPI. `DEPLOYMENT_MODE=cloud` requires `MONGO_URI` + `MONGO_DB` at process start (`server/main.py` `_require_cloud_mongo_config`). Local default is SQLite files under `server/data/`.
- CORS must include the real frontend origin via `CORS_ORIGINS`.
- Set `VITE_API_URL` at client build time to the public API origin.

**Project skills:** `.claude/skills/` and `.agents/skills/` not detected. No `SKILL.md`.

---

*Stack analysis: 2026-09-05*
