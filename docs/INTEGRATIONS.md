# External Integrations

**Analysis Date:** 2026-09-05

## APIs & External Services

**LLM gateways:**
- OpenRouter — default provider. Structured generation (`server/utils/instructor_client.py` `AsyncOpenAI` + Instructor JSON mode), concept chat streaming (`server/services/concept_chat.py`), model catalog `GET {OPENROUTER_BASE_URL}/models` (`server/routers/llm.py`). Default base `https://openrouter.ai/api/v1`. Attribution headers `HTTP-Referer`, `X-OpenRouter-Title` (`A2UI` from `client/src/lib/providerApi.ts`). Prompt caching breakpoints for `anthropic/`, `google/`, `qwen/` in `server/utils/prompt_cache.py`.
  - SDK/Client: `openai` (`AsyncOpenAI`), `instructor`, `httpx` for `/models`
  - Auth: request header `X-OpenRouter-Key` (Bearer on outbound). Browser store `ai_provider_settings`. Not a server env key in local mode.
- General Compute — second OpenAI-compatible provider. Base default `https://api.generalcompute.com/v1`. Model list `POST {GENERALCOMPUTE_BASE_URL}/models/list`. Health payload in `server/main.py` reports `"generalcompute": "enabled"`.
  - SDK/Client: `openai` (`AsyncOpenAI`), `httpx`
  - Auth: header `X-GeneralCompute-Key`; client also sends `Authorization: Bearer` (`providerApi.ts`)
- OpenAI API — concept-chat only when model slug starts with `openai/` or `gpt-` (`resolve_chat_base_url` in `server/services/concept_chat.py` → `https://api.openai.com/v1`). Uses the OpenRouter key path’s `AsyncOpenAI` client, not a separate OpenAI key env var.
  - SDK/Client: `openai`
  - Auth: same per-request key as active OpenRouter context when that slug is selected

**Web search (optional internet grounding + concept-chat tool):**
- Tavily — `https://api.tavily.com/search` (`server/search/adapters/tavily.py`). Header `X-Tavily-Key`. Metadata `client/src/lib/webSearchProviders.ts`.
- Exa — `https://api.exa.ai/search` (`server/search/adapters/exa.py`). Header `X-Exa-Key`.
- Brave Search — `https://api.search.brave.com/res/v1/web/search` snippets only (`server/search/adapters/brave.py`). Header `X-Brave-Key`. Attribution required (client metadata).
- SerpAPI — `https://serpapi.com/search.json` organic results (`server/search/adapters/serpapi.py`). Header `X-SerpApi-Key`. Query-param key redacted in logs (`server/search/http.py`).
  - SDK/Client: `httpx.AsyncClient` adapters; coordinator `server/search/coordinator.py`; header parse `get_search_context` in `server/schemas/search.py`
  - Auth: ephemeral headers `X-Web-Search`, `X-Web-Search-Providers`, plus per-provider keys. Built only for generate/resume (and concept chat when globe on) via `client/src/lib/webSearchHeaders.ts`. Stored in `localStorage` key `web_search_settings`.

**Client → backend:**
- FastAPI on port 8000. Base URL `VITE_API_URL` or `http://localhost:8000`.
- REST: `client/src/lib/learningApi.ts` (`/learning/*`), `providerApi.ts` (`GET /llm/models`), `storageApi.ts` (`/settings/storage/*`).
- SSE: `GET /learning/sessions/{session_id}/events` (`EventSource`, no credentials in URL — `useSessionEvents.ts`); `POST /learning/sessions/{session_id}/nodes/{node_id}/chat`; `POST /learning/nodes/{node_id}/regenerate/stream`. Generation continues after SSE disconnect (`server/services/generation_runtime.py`).
- CORS: `CORS_ORIGINS` plus regex `http://(localhost|127\.0\.0\.1)(:[0-9]+)?` (`server/main.py`).

**Fonts CDN:**
- Google Fonts — Lexend and Fira Code imported in `client/src/index.css` (`fonts.googleapis.com`). No API key.

**Project skills:** `.claude/skills/` and `.agents/skills/` not detected.

## Data Storage

**Databases:**
- SQLite (default, `DEPLOYMENT_MODE=local`)
  - Connection: filesystem paths, not env. App DB `server/data/a2ui.db` (`server/database/persistence.py`). LangGraph checkpoints `server/data/checkpoints.db` (`server/graph/build.py`).
  - Client: stdlib `sqlite3`; LangGraph `AsyncSqliteSaver` + `aiosqlite==0.22.1`. No ORM.
- MongoDB Atlas (optional)
  - Connection: cloud startup env `MONGO_URI` + `MONGO_DB` (`server/config.py`). Local-mode connect uses request body `uri`/`dbName` from Settings (`POST /settings/storage/connect`, `server/schemas/storage.py`); browser cache `localStorage` key `a2ui_mongo_storage` (`client/src/lib/mongoStorageSettings.ts`). URI schemes `mongodb://` or `mongodb+srv://`.
  - Client: `pymongo[srv]` (`server/database/mongo_client.py`). Checkpointer `MongoDBSaver` collections `checkpoints`, `checkpoint_writes`. App settings documents via `GET`/`PUT /settings/storage/app-settings` when Mongo is active. Migrate `POST /settings/storage/migrate` copies SQLite + checkpoints (`server/database/migrate_to_mongo.py`).

**File Storage:**
- Local filesystem only: SQLite files under `server/data/`, Vite `client/dist/` build output. No S3/GCS/Azure blob client detected.

**Caching:**
- None (no Redis/Memcached).
- Client: TanStack Query in-memory cache (`QueryProvider.tsx`).
- LLM: OpenRouter explicit prompt cache markers (`server/utils/prompt_cache.py`).
- Concept chat: in-process `AsyncOpenAI` client cache by `base_url` (`server/services/concept_chat.py`).

## Authentication & Identity

**Auth Provider:**
- Custom (no Auth0/Cognito/Firebase/JWT user identity). No login, sessions, or cookies for users.
  - Implementation: per-request FastAPI `Header` dependency `get_llm_context` in `server/schemas/llm.py`. Missing active-provider key → HTTP 401 (`X-OpenRouter-Key` or `X-GeneralCompute-Key`). Provider select `X-AI-Provider` (`openrouter`|`generalcompute`). Per-agent models: `X-Researcher-Model` / `X-Planner-Model` / `X-Generator-Model` / `X-Quizzer-Model` plus Provider/Thinking headers (`client/src/lib/agentModelHeaders.ts`). Search keys scoped to generate/resume/chat, not session/quiz/delete (`learningApi.ts`).
  - Secrets live in the browser (`localStorage`) and optional Mongo `app_settings` after migrate/cloud. Server `.env` does not hold LLM keys for local use (`README.md`).

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry, Datadog, OpenTelemetry, or similar imports).

**Logs:**
- Python stdlib `logging` INFO on startup (`server/main.py`). Module loggers `__name__`. External failures log exception **type** only (`server/utils/safe_logging.py`). Search adapters redact secret query params (`server/search/http.py`). Client Axios error interceptor `console.error` in `learningApi.ts`. Health: `GET /health` returns `{ status: ok, services: { openrouter, generalcompute } }` without probing those APIs.

## CI/CD & Deployment

**Hosting:**
- Not detected in-repo (no Docker, PaaS, or cloud app manifests). Local: `run.bat` / uvicorn :8000 + Vite :5173. Cloud in this codebase means **Mongo storage mode**, not app hosting.

**CI Pipeline:**
- None (no `.github/workflows`, GitLab CI, or similar).

## Environment Configuration

**Required env vars:**
- Local default: none required to boot. LLM keys come from UI headers.
- Cloud (`DEPLOYMENT_MODE=cloud`): `MONGO_URI`, `MONGO_DB` (startup fails without both).
- Optional: `DEPLOYMENT_MODE`, `OPENROUTER_BASE_URL`, `OPENROUTER_TIMEOUT_SECONDS`, `GENERALCOMPUTE_BASE_URL`, `GENERALCOMPUTE_TIMEOUT_SECONDS`, `CORS_ORIGINS`.
- Client build/dev optional: `VITE_API_URL`.
- Not server env: OpenRouter/General Compute/Tavily/Exa/Brave/SerpAPI keys (headers + `localStorage`).

**Secrets location:**
- Browser `localStorage`: `ai_provider_settings`, `web_search_settings`, `a2ui_mongo_storage`.
- Server dotenv files: root `.env` exists (contents not read). `server/.env.example` exists (contents not read). `client/.env` not detected. `load_dotenv()` in `server/config.py` (cwd-relative). Gitignore: `.env`, `.env.local`, `.env.*.local`, `.env.development`, `.env.test`, `.env.production`; `!.env.example`.
- Cloud Mongo: process env `MONGO_URI` / `MONGO_DB`. Local Atlas connect: POST body, not persisted on server.
- Never commit keys; do not put LLM keys in server env for the default local path.

## Webhooks & Callbacks

**Incoming:**
- None. No webhook routers. SSE is server→browser (`text/event-stream`), not an inbound webhook. Cursor via query `after` or header `Last-Event-ID` (`server/routers/learning.py`).

**Outgoing:**
- None as webhooks. Outbound HTTPS only: OpenRouter, General Compute, OpenAI (slug-gated chat), Tavily, Exa, Brave, SerpAPI, MongoDB Atlas. No Slack/GitHub/Stripe callback URLs detected.

---

*Integration audit: 2026-09-05*
