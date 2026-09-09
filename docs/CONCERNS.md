# Codebase Concerns

**Analysis Date:** 2026-09-05

## Tech Debt

**Dual persistence implementations (SQLite + Mongo) must stay in lockstep:**
- Issue: Approach A repository swap duplicates every store. SQLite `LearningManager` is ~3000 lines; Mongo twin is ~1490 lines. Same split exists for jobs, artifacts, research, and progress. Call sites go through `RepositoryFacade` late-binding, so a missing method or semantic drift only fails at runtime on the active backend.
- Files: `server/database/learning_persistence.py`, `server/database/repositories/mongo_learning.py`, `server/database/generation_jobs.py`, `server/database/repositories/mongo_jobs.py`, `server/database/generation_artifacts.py`, `server/database/repositories/mongo_artifacts.py`, `server/database/research_store.py`, `server/database/repositories/mongo_research.py`, `server/database/repositories/facade.py`, `server/database/repositories/protocols.py`, `server/database/storage_mode.py`, `server/database/storage_registry.py`
- Impact: Feature added on one backend silently wrong on the other. Cascade delete, quiz upsert, lock fencing, and progress IDs already have different code paths. Cloud vs local bugs will not reproduce on the other store.
- Fix approach: Treat `server/database/repositories/protocols.py` as the contract. Add behavioral parity tests (same fixtures against SQLite temp DB and mongomock/testcontainer). Extract shared mapping helpers so quiz/node/session dict shapes are not hand-copied. Stop growing `LearningManager`; put new tables in focused stores both backends implement.

**Two SQLite connection factories with different safety knobs:**
- Issue: Generation stores use `server/database/sqlite_utils.py` (`timeout=5.0`, `PRAGMA busy_timeout=5000`, `BEGIN IMMEDIATE`). `LearningManager._get_connection()` opens a bare `sqlite3.connect` with foreign keys only — no busy timeout, no WAL, no immediate lock.
- Files: `server/database/learning_persistence.py`, `server/database/sqlite_utils.py`, `server/database/persistence.py`
- Impact: Learning CRUD and generation workers share `server/data/a2ui.db`. Under fan-out + SSE poll, learning reads can raise `database is locked` while generation holds a write. Two connection styles also make transaction nesting inconsistent.
- Fix approach: Route `LearningManager` through `connect_database` / `optional_transaction`. Enable `PRAGMA journal_mode=WAL` once at schema init. Keep a single connection policy for the whole process.

**Two SQLite files cannot share a transaction:**
- Issue: App data lives in `server/data/a2ui.db` (`DB_PATH`). LangGraph checkpoints live in `server/data/checkpoints.db` (`CHECKPOINT_DB_PATH`). Crash or migrate can leave checkpoint thread ahead/behind concept nodes, briefs, and jobs.
- Files: `server/database/persistence.py`, `server/graph/build.py`, `server/database/checkpoint_migration.py`, `server/main.py`
- Impact: Resume after kill/migrate can skip or redo graph nodes while durable content already exists (or the reverse). Idempotent skips in `generator_node` (`has_durable_content`) paper over some cases, not all.
- Fix approach: Document crash-consistency as best-effort. On resume, reconcile job stage vs node `generation_status` before `graph.ainvoke`. Prefer one backend (Mongo + `MongoDBSaver`) for cloud durability.

**Dual `LearningManager` construction:**
- Issue: `storage_registry.py` builds `sqlite_learning_store = LearningManager(DB_PATH)`. Module still exports `learning_manager = LearningManager()` at the bottom of `learning_persistence.py`. `StorageContext._default_sqlite_repositories` imports the module singleton. Production facades use the registry instance; a default `StorageContext()` without injection can bind the other object.
- Files: `server/database/storage_registry.py`, `server/database/learning_persistence.py`, `server/database/storage_mode.py`
- Impact: Tests or accidental `StorageContext()` can talk to a different manager than routers. Schema init on one instance does not prove the other is used.
- Fix approach: Single factory. Stop exporting the unused module singleton for app paths.

**Cloud mode still constructs SQLite stores at import:**
- Issue: `storage_registry.py` instantiates SQLite `LearningManager`, job/artifact/research/progress stores even when `DEPLOYMENT_MODE=cloud`. Cloud lifespan never calls `initialize_sqlite_storage()`, but unused managers and file-path objects still exist.
- Files: `server/database/storage_registry.py`, `server/main.py`, `server/config.py`
- Impact: Low functional risk; extra import-time coupling and accidental SQLite writes if a code path forgets the facade.
- Fix approach: Lazy-init SQLite bundle only for `DeploymentMode.LOCAL`.

**God files / complexity:**
- Issue: Several modules exceed maintainable size. Broad `except Exception` in graph nodes hides real failures as “degraded” or skipped counters.
- Files: `server/database/learning_persistence.py` (~2999 lines), `server/routers/learning.py` (~1461), `server/database/repositories/mongo_learning.py` (~1490), `server/services/research_runner.py` (~1161), `server/graph/nodes.py` (~1113), `server/schemas/learning.py` (~1094), `server/database/generation_jobs.py` (~961), `client/src/features/learning/MarkdownRenderer.tsx` (~914), `client/src/features/learning/LearningPathContainer.tsx` (~937), `client/src/features/learning/ConceptCard.tsx` (~885)
- Impact: Review and TDD on these files is slow. `nodes.py` swallows persist errors (`except Exception: pass` around progress events) so UI can show success while DB missed an event.
- Fix approach: Split learning router by generate/session/quiz/revision/chat. Split `nodes.py` by stage. Replace bare `except Exception` with typed handling + `log_external_failure`. Cap new code in `LearningManager`.

**Unused / unpinned Python dependencies:**
- Issue: `server/requirements.txt` pins only LangGraph checkpoint stack (`langgraph==1.2.4`, `langgraph-checkpoint-sqlite==3.1.0`, `aiosqlite==0.22.1`, `langgraph-checkpoint-mongodb==0.4.0`, `pymongo[srv]>=4.13,<4.17`). `fastapi`, `httpx`, `openai`, `instructor`, `pydantic`, `tenacity`, `langchain`, `watchdog`, `jsonref` are unpinned. No production import of `langchain`, `watchdog`, or `jsonref` exists under `server/`.
- Files: `server/requirements.txt`
- Impact: Reproducible deploys fail when Instructor/Pydantic/OpenAI shift. Dead packages add supply-chain surface. LangGraph minor bumps historically break `Send`/checkpointer APIs.
- Fix approach: Pin all runtime deps with hashes or a lockfile. Remove unused `langchain`, `watchdog`, `jsonref` after confirming no dynamic import. Add a CI freeze check.

**Health check is a stub:**
- Issue: `GET /health` always returns `openrouter: enabled` and `generalcompute: enabled` with no probe of keys, Mongo, or SQLite.
- Files: `server/main.py`
- Impact: Orchestrators mark the process healthy while storage or providers are down.
- Fix approach: Report `storage_context.active_backend`, Mongo ping when connected, and do not claim providers enabled without a key/path check.

**Client boot failure is silent:**
- Issue: `bootstrapStorage()` catches connect/hydrate errors and returns `{ status: null, error }`. `startApplication` still renders. No toast/banner.
- Files: `client/src/lib/storageBoot.ts`, `client/src/lib/startApplication.ts`
- Impact: Saved Atlas URI fail → app runs on SQLite; user thinks cloud data loaded.
- Fix approach: Surface boot error once (banner on Settings/home). Do not hide `error` on the boot result.

**Settings idle guard is in-process only:**
- Issue: `POST /settings/storage/connect|disconnect|migrate` blocks only when `generation_runtime.active_session_ids` is non-empty. That list is this process’s asyncio tasks, not DB lock rows.
- Files: `server/routers/storage.py`, `server/services/generation_runtime.py`
- Impact: Fine for single-process v1. A second worker or crashed task with a live DB lock would allow storage switch mid-job.
- Fix approach: Also refuse switch if any job row is nonterminal with unexpired lock. Document single-process assumption.

## Known Bugs

**Concept chat routes OpenRouter `openai/` slugs to api.openai.com:**
- Symptoms: Chat against models like `openai/gpt-4o-mini` with `provider=openrouter` sends the OpenRouter key to `https://api.openai.com/v1`. Auth fails or bills the wrong vendor.
- Files: `server/services/concept_chat.py` (`resolve_chat_base_url`)
- Trigger: Default OpenRouter catalog slugs start with `openai/`. Tests in `server/tests/test_concept_chat_loop.py` pass `model_slug="openai/gpt-4o-mini"` and `provider="openrouter"` but mock the client, so they never assert `base_url`.
- Workaround: Pick a non-`openai/` slug, or use General Compute. Fix: if `provider == "openrouter"`, always use OpenRouter base URL; only use `OPENAI_BASE_URL` when a dedicated OpenAI key/provider exists.

**Concept chat `AsyncOpenAI` cache keys only `base_url`:**
- Symptoms: First caller’s API key is reused for later callers on the same base URL. Key rotation in Settings does not take effect until process restart. On a shared server, user B can ride user A’s key.
- Files: `server/services/concept_chat.py` (`_client_cache`, `_get_client`)
- Trigger: Two concept-chat requests with different keys, same provider URL; or change key then chat again.
- Workaround: Restart backend after key change. Fix: cache key `(base_url, api_key)` or do not cache clients; never reuse a client across keys.

**`get_brief` / `has_durable_content` swallow `sqlite3.OperationalError`:**
- Symptoms: Missing table or locked DB looks like “no brief” / “no content”. Generator proceeds without a brief or regenerates content that already exists.
- Files: `server/database/generation_artifacts.py`
- Trigger: Schema not migrated, or SQLite lock timeout during generation.
- Workaround: Ensure `initialize_generation_schema` ran. Fix: log and re-raise operational errors except a documented “table missing during tests” path.

**ISO-string lock expiry comparison:**
- Symptoms: Worker lock treated as expired or live incorrectly if `lock_expires_at` and `datetime.isoformat()` differ in timezone suffix (`Z` vs `+00:00`) or microsecond width. SQLite path uses `row["lock_expires_at"] > now.isoformat()` (string compare).
- Files: `server/database/generation_jobs.py`, `server/database/repositories/mongo_jobs.py`
- Trigger: Mixed naive/aware timestamps, or Mongo vs SQLite writers.
- Workaround: Single process + `datetime.now` from the same helper. Fix: parse both sides to aware UTC datetimes before compare.

**Mongo progress counter still burns IDs on insert race:**
- Symptoms: `append_once` find-by-dedupe first (good), but concurrent first-inserts still `$inc` then hit `DuplicateKeyError` and return the existing event. Counter already advanced → gaps in SSE ids.
- Files: `server/database/repositories/mongo_progress.py`
- Trigger: Two workers appending the same `dedupe_key` at once (should be rare with fenced locks).
- Workaround: Accept sparse ids. Fix: reverse `$inc` on pure-dedupe hit, or use deterministic `_id` from `(session_id, dedupe_key)`.

**Regen path skips internet grounding:**
- Symptoms: Failed-node retry calls `generator_agent` / `quizzer_agent` directly with no `SearchContext` or research report. Citations may be empty or invented relative to the original grounded run.
- Files: `server/graph/regen.py`, `server/graph/regen_stream.py`
- Trigger: Retry ERROR node or manual topic regen after a web-grounded course.
- Workaround: Delete session and regenerate with web search. Fix: pass session research sources / brief into regen; do not invent new URLs.

**Research failure is a silent degrade:**
- Symptoms: Any non-cancel exception in `researcher_node` logs a warning, sets `degraded=True`, and continues outlining without web evidence. User may get a model-only course after opting into search.
- Files: `server/graph/nodes.py`, `server/services/research_runner.py`
- Trigger: Bad search key, all providers down, budget bugs, adapter errors.
- Workaround: Check Course Sources / degraded warning in UI. Fix: surface a blocking warning in SSE and job `warnings`; do not hide as generic “ok, outlining”.

**Quiz answers leak after IN_QUIZ:**
- Symptoms: `hide_quiz_card` strips `is_correct` only for `NodeStatus.IN_QUIZ`. Review / feedback paths attach full `quiz` / `quiz_set` with correctness. Anyone who can `GET` the node after submit sees answers. There is no user auth (see Security).
- Files: `server/routers/learning.py`, `server/services/quiz_randomization.py`
- Trigger: Read node in `SHOWING_FEEDBACK` or `COMPLETED`.
- Workaround: Acceptable for local single-user. Fix if multi-user: never return `is_correct` except on submit response.

No `TODO` / `FIXME` / `HACK` / `XXX` markers found in `client/src` or `server` Python/TS (docs-only mentions). No `NotImplemented` stubs. `pass` in `server/search/adapters/_common.py` is datetime parse fallback, not an empty module.

## Security Considerations

**No application authentication or tenancy:**
- Risk: Every learning, generation, SSE, delete, quiz, and storage endpoint is reachable with no user login. `GET /learning/sessions` with default `user_id=None` lists all courses. `DELETE` session, cancel generation, and `GET /learning/sessions/{id}/events` require only a UUID. `user_id` is an optional client-supplied filter, not a verified identity.
- Files: `server/routers/learning.py`, `server/routers/storage.py`, `server/routers/llm.py`, `server/main.py`, `client/src/features/learning/useSessionEvents.ts`
- Current mitigation: Session ids are `uuid4`. Product is framed as a local/single-user app. Generate/resume require provider API key headers (`get_llm_context` → 401 if blank).
- Recommendations: If the server is ever bound beyond localhost or shared: bind auth, scope all queries by user, require auth on SSE (EventSource cannot send `X-OpenRouter-Key` today — by design it is credential-free, which means the stream is public given `session_id`). Do not treat `user_id` query param as security.

**API keys and Mongo URI live in the browser:**
- Risk: OpenRouter, General Compute, Tavily/Exa/Brave/SerpAPI keys, and the MongoDB URI (including password) sit in `localStorage` (`ai_provider_settings`, `web_search_settings`, `a2ui_mongo_storage`). XSS, a malicious extension, or another localhost origin can read them. Keys are sent as custom headers on generate/resume/chat (`X-OpenRouter-Key`, `X-Web-Search-*`). When Mongo is active, `PUT /settings/storage/app-settings` writes those secrets into Atlas.
- Files: `client/src/lib/providerSettings.ts`, `client/src/lib/webSearchHeaders.ts`, `client/src/lib/mongoStorageSettings.ts`, `client/src/lib/storageBoot.ts`, `server/routers/storage.py`, `server/schemas/llm.py`
- Current mitigation: Keys are not stored in SQLite by design. Graph `CourseState` is secret-free. Search HTTP redacts secret query names in logs (`server/search/http.py`). `log_external_failure` logs exception type only. Instructor failures use that helper. Web-search headers are scoped to generate/resume, not list/quiz/delete (`client/src/lib/learningApi.ts`).
- Recommendations: Keep local-only until XSS surface is tight. Prefer OS keychain or server-side secret store for cloud. Never log request headers. Consider encrypting `localStorage` blobs at rest (weak against XSS, helps casual disk theft). Hydration already preserves non-empty local secrets over blank cloud values (`storageBoot.ts`) — keep that invariant.

**CORS is wide for a credentialed API:**
- Risk: `CORSMiddleware` allows configured origins **and** regex `http://(localhost|127\.0\.0\.1)(:[0-9]+)?` with `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`. Any HTTP app on any localhost port can call the API from the browser. Combined with `localStorage` keys if the attacker also injects into the Vite origin, or with unauthenticated session APIs, this is a local CSRF/data-theft path.
- Files: `server/main.py`
- Current mitigation: Default origins are Vite dev URLs. Regex is localhost-only, not LAN.
- Recommendations: Drop `allow_origin_regex` in production. Do not use `allow_credentials` unless cookies exist (this app uses headers, not cookies). Pin exact origins via `CORS_ORIGINS`.

**Unauthenticated storage connect is SSRF / data-exfil:**
- Risk: `POST /settings/storage/connect` accepts any `mongodb://` / `mongodb+srv://` URI and opens a server-side client with ping. An attacker on the same host can point the process at their Atlas cluster, then `POST /migrate` to copy local courses and (if included) credentials. `PUT /settings/storage/app-settings` writes provider/search keys into whatever Mongo is active. Cloud mode blocks these routes (403); local mode does not.
- Files: `server/routers/storage.py`, `server/database/mongo_client.py`, `server/schemas/storage.py`
- Current mitigation: Local-only (`_require_local`). Idle-job guard. URI must use mongodb scheme. Driver errors mapped without echoing URI. `redact_mongo_uri` for diagnostics. Exception `__cause__` may still include host/user in tracebacks if unhandled.
- Recommendations: Bind storage routes to localhost. Confirm UI before connect. Do not migrate secrets unless the user opts in. Scrub pymongo messages in a global handler.

**Prompt injection via untrusted web + concept content:**
- Risk: Search snippets are fenced (`format_untrusted_sources` in `server/search/source_safety.py`) with an ignore-instructions preamble. Concept chat concatenates full `content_markdown`, heading ids, and user history into the system prompt **without** those fences. LLM-generated markdown is then rendered with `rehype-raw` + `rehype-sanitize`, Mermaid `securityLevel: "loose"`, and `dangerouslySetInnerHTML` for SVG.
- Files: `server/search/source_safety.py`, `server/services/concept_chat.py`, `client/src/features/learning/MarkdownRenderer.tsx`, `client/src/features/learning/pdfExportUtils.ts`, `client/src/features/learning/mermaidUtils.ts`
- Current mitigation: Search URL allowlist (http/https, no credentials, block localhost/private IPs as literals, strip secret query params, HTML tag strip). Markdown sanitize plugin. Citation validation in generator (`server/services/citation_validation.py`).
- Recommendations: Fence concept-chat content the same way as search. Set Mermaid `securityLevel: "strict"` (or `"antiscript"`). Do not use `loose` + innerHTML. Keep `rehype-sanitize` after `rehype-raw`. Treat all model output as untrusted HTML.

**SSRF via search is limited; DNS rebinding remains a gap in the URL checker:**
- Risk: Adapters call fixed provider APIs (Tavily/Exa/Brave/SerpAPI) with `follow_redirects=False` and byte caps. The server does not fetch citation URLs. `canonicalize_source_url` rejects literal private IPs and `localhost` but does **not** resolve DNS, so `http://127.1.1.1.nip.io` would pass if anything later fetched it.
- Files: `server/search/source_safety.py`, `server/search/http.py`, `server/search/adapters/_common.py`, `server/search/coordinator.py`
- Current mitigation: No server-side fetch of result URLs. Provider HTTP is capped and not redirected.
- Recommendations: If a fetch-html path is added, resolve DNS and re-check IP after connect (pin host). Keep providers on an allowlist of hosts.

**Quiz shuffle is not a security boundary:**
- Issue: `shuffle_quiz_options` uses `secrets.randbelow`; persisted order uses SHA-256 seed + `random.Random`. `DISPLAY_LABELS` is fixed length 4; schema requires exactly 4 options so IndexError is unlikely if validation holds. Hidden cards omit `is_correct` only in IN_QUIZ.
- Files: `server/services/quiz_randomization.py`, `server/schemas/learning.py`
- Current mitigation: Option identity is UUID; evaluation is by `option_id`.
- Recommendations: Keep hiding on IN_QUIZ. Add unit tests (none exist today). Do not treat shuffle as anti-cheat.

## Performance Bottlenecks

**LLM fan-out vs SQLite:**
- Problem: Preview batch size 3, then batches of 10 generator Sends and 10 quizzer Sends. Runner sets `max_concurrency: 3`, so up to 3 LLM calls plus research HTTP run together. Each worker reads/writes SQLite (`BEGIN IMMEDIATE`, 5s busy timeout).
- Files: `server/graph/build.py`, `server/graph/nodes.py`, `server/graph/runner.py`, `server/schemas/generation.py`, `server/database/sqlite_utils.py`
- Cause: LangGraph `Send` fan-out + shared file DB + `LearningManager` connections without `busy_timeout`.
- Improvement path: WAL + shared connection policy. Keep `GENERATION_MAX_CONCURRENCY = 3` (or lower on small machines). For cloud, Mongo pool (`maxPoolSize=50` in `mongo_client.py`) is the path; still cap LLM concurrency to protect OpenRouter rate limits.

**SSE is poll-the-DB, not push:**
- Problem: `stream_session_events` loops `list_after` then `asyncio.sleep(0.5)` and heartbeats every 15s. Each open EventSource hits SQLite/Mongo twice per second. Disconnect does not cancel generation (good) but also does not stop the poll until the generator is GC’d.
- Files: `server/services/session_event_stream.py`, `server/routers/learning.py`, `client/src/features/learning/useSessionEvents.ts`
- Cause: Durable events in a table; no LISTEN/NOTIFY or Mongo change stream.
- Improvement path: Increase poll to 1–2s. Use a process-local asyncio.Condition signaled by `append_once` for same-process clients. Cap concurrent SSE per session.

**Research loop + Instructor retries:**
- Problem: `research_runner.py` is a long iterative plan/search/synthesize loop with provider rotation and budgets. Generator retries Mermaid/citation failures up to 3 times (`server/agents/generator.py`). Instructor uses tenacity. Wall clock for a full web-grounded course is many sequential LLM minutes plus 3 concurrent topic workers.
- Files: `server/services/research_runner.py`, `server/agents/generator.py`, `server/utils/instructor_client.py`, `server/search/budget.py`
- Cause: Quality retries and bounded research by design.
- Improvement path: Keep budgets strict. Cache prompts (`server/utils/prompt_cache.py` already). Fail fast on auth errors (coordinator already does not rotate on 401/403).

**Client markdown / Mermaid / PDF:**
- Problem: `MarkdownRenderer` loads Mermaid, KaTeX, Prism, remark/rehype stack per card. PDF/ZIP export (`pdfExportUtils.ts`, `html2pdf.js`, `html2canvas-pro`, `jspdf`) re-renders diagrams eagerly and can freeze the tab on long courses.
- Files: `client/src/features/learning/MarkdownRenderer.tsx`, `client/src/features/learning/pdfExportUtils.ts`, `client/package.json`
- Cause: Heavy per-card visualization plus html2canvas rasterization.
- Improvement path: Lazy-mount Mermaid. Virtualize the path list. Prefer print-to-PDF over html2canvas for large courses.

**Learning list/progress queries:**
- Problem: Session list joins counts, last-active titles, revision counts. Mongo list path does per-row `find_one` for last node title (`mongo_learning.py`).
- Files: `server/database/learning_persistence.py`, `server/database/repositories/mongo_learning.py`, `server/routers/learning.py`
- Cause: N+1 lookups for display fields.
- Improvement path: Aggregation or denormalized `last_active_node_title` on the session document.

## Fragile Areas

**LangGraph staged runtime:**
- Files: `server/graph/state.py`, `server/graph/nodes.py`, `server/graph/build.py`, `server/graph/runner.py`, `server/database/checkpointer.py`
- Why fragile: Secret-free `CourseState` holds only compact results; real markdown/quizzes/briefs live in artifact/learning stores. Keyed reducers merge by `(batch_start, sequence_index)`. Checkpointer swap (`CheckpointerController.activate`) rebuilds the compiled graph. Resume uses `input_data=None` and thread_id. Lock heartbeat 15s, TTL 45s; lost heartbeat cancels the graph task. `except Exception` in nodes turns many failures into ERROR cards or skipped counters.
- Safe modification: Change state keys only with a migration/resume test. Keep reducers idempotent. Never put API keys in `CourseState`. Run `server/tests/test_staged_graph.py`, `test_generation_recovery.py`, `test_graph.py`, `test_partial_failure.py` after topology edits.
- Test coverage: Graph/recovery/lock tests exist. Live LangGraph + real SQLite checkpointer + kill-mid-batch is thinner than mock tests.

**Regen vs full graph:**
- Files: `server/graph/regen.py`, `server/graph/regen_stream.py`
- Why fragile: Bypasses LangGraph, research, and batch barriers. Status after regen depends on sibling `COMPLETED` and `sequence_index == 0`. Citation replace failures are logged and ignored.
- Safe modification: Keep ERROR vs non-ERROR entry points separate (`regenerate_failed_node` vs `regenerate_topic_node`). Always go through `update_node_content` + `replace_node_sources`.
- Test coverage: `server/tests/test_regen.py`, `test_regen_stream.py`. No test that regen preserves grounded citations.

**Quiz randomization + persist seed:**
- Files: `server/services/quiz_randomization.py`, `server/routers/learning.py`
- Why fragile: Refresh must show the same order (`get_or_create_shuffle_order` / `shuffle_quiz_set_with_seed`). Seed stored on quiz_data. Wrong seed or missing hide step leaks answers or reshuffles mid-attempt.
- Safe modification: Never shuffle without persisting seed. Keep hide on IN_QUIZ only. Schema still requires exactly 4 options.
- Test coverage: **No `test_quiz_randomization.py`.** Router tests may cover hide indirectly. High gap.

**Storage backend swap at runtime:**
- Files: `server/database/storage_mode.py`, `server/database/checkpointer.py`, `server/routers/storage.py`, `client/src/lib/storageBoot.ts`
- Why fragile: `connect()` builds Mongo indexes and bundle outside the lock, then swaps repos + graph under `RLock`. In-flight requests can straddle SQLite and Mongo. Disconnect reactivates SQLite saver (unavailable in cloud).
- Safe modification: Keep `_require_idle`. Do not call connect from a request that also reads learning. Test facade resolution after connect (`test_repository_facades.py`, `test_storage_mode.py`).
- Test coverage: Connect/idle/cloud startup tests exist. Dual-client overlap during swap is documented as last-wins, not tested.

**Instructor JSON sanitizer:**
- Files: `server/utils/instructor_client.py`
- Why fragile: Custom `sanitize_json_escapes` rewrites model JSON before parse. Easy to corrupt unicode escapes or mask real schema errors.
- Safe modification: Prefer Instructor retries; keep sanitizer covered by unit tests if touched.
- Test coverage: Indirect via agent tests; sanitizer itself may be under-tested.

## Scaling Limits

**Single-process generation runtime:**
- Current capacity: One FastAPI process. `GenerationRuntime` holds `asyncio.Task`s in memory. Locks are DB rows with ~45s TTL. `GENERATION_MAX_CONCURRENCY = 3` LLM workers per job. Preview 3 topics, then 10.
- Limit: Second process will not see in-memory tasks; idle storage guard and SSE poll are local. SQLite writers serialize. A full course is O(topics) LLM calls (planner + 2 per topic + research iterations). OpenRouter 60s timeout (`OPENROUTER_TIMEOUT_SECONDS`).
- Scaling path: One generator worker per deployment until a real job queue exists. Cloud Mongo allows multi-reader UI but not multi-writer generation without fencing across processes (locks exist; runtime does not). Horizontal scale needs a worker pool that respects `try_acquire_lock` and unique `worker-{uuid}`.

**SQLite file DB:**
- Current capacity: Fine for one learner, dozens of courses, megabytes of markdown.
- Limit: Writer lock + 5s busy timeout under concurrent generate + SSE + list. No WAL. Two files (`a2ui.db`, `checkpoints.db`).
- Scaling path: WAL + busy_timeout everywhere, then Mongo Atlas (`DeploymentMode.CLOUD` or local connect).

**Mongo Atlas:**
- Current capacity: Sync PyMongo, pool 50, `w=majority`. App settings + learning + jobs + checkpoints (`MongoDBSaver`).
- Limit: Multi-document transactions required for delete cascade (now wrapped). Change streams unused. Progress `$inc` counter is a hotspot per session.
- Scaling path: Keep one writer generation; use Atlas for read-mostly UI and roam. Do not run unbounded migrate from the browser on huge DBs (client migrate timeout is 300s — `STORAGE_MIGRATE_TIMEOUT_MS`).

**Search providers:**
- Current capacity: Four curated providers, job-local shuffle, one retry then rotate on rate/timeout/5xx. Response cap 1_000_000 bytes. Chat search is one-shot (`concept_chat_search.py`).
- Limit: Auth errors do not rotate (by design). All-providers-down degrades the course. No app-level rate limit on `/learning/generate` — cost is the user’s API key, but a looped client can burn quota.
- Scaling path: Keep coordinator policy. Add generate rate limit if the server is shared.

## Dependencies at Risk

**LangGraph 1.2.4 + split checkpointers:**
- Risk: Fast-moving APIs (`Send`, `context_schema`, SQLite vs Mongo savers). `langgraph-checkpoint-mongodb==0.4.0` must stay compatible with `langgraph==1.2.4`. Checkpoint migrate uses public `alist`/`aput`/`aput_writes` and `checkpoint["channel_versions"]`.
- Impact: Graph compile, resume, or migrate breaks on a casual upgrade.
- Migration plan: Upgrade in a branch with `test_staged_graph.py`, `test_checkpointer.py`, `test_checkpoint_migration.py`, and a real sqlite→mongo resume. Do not float LangGraph.

**Instructor + OpenAI + Pydantic unpinned:**
- Risk: Instructor mode JSON and OpenAI client breaking changes are frequent. Server requires Pydantic v2 (`ConfigDict`, `model_validate`).
- Impact: Structured planner/generator/quizzer calls fail closed.
- Migration plan: Pin versions that CI installs. Add a smoke `create_structured` test with httpx mock.

**html2pdf.js + html2canvas-pro:**
- Risk: `html2pdf.js` is a thin, slowly maintained wrapper. Export already duplicates html2canvas-pro/jsPDF usage. Layout bugs on long mermaid/markdown.
- Impact: PDF/ZIP export quality, not core learning.
- Migration plan: Prefer `jspdf` + `html2canvas-pro` only, or browser print. Isolate export so mermaid `securityLevel` can be strict in the live UI.

**Mermaid 11.x with `securityLevel: "loose"`:**
- Risk: Loose mode allows richer diagrams and script-like clicks. Combined with model-generated chart strings and SVG innerHTML.
- Impact: XSS in the learning UI if a model or injected content emits a malicious diagram.
- Migration plan: `strict` / `antiscript`. Sanitize chart text in `mermaidUtils.ts` before `mermaid.render`.

**langchain / watchdog / jsonref:**
- Risk: Declared in `server/requirements.txt` but not imported by production server code.
- Impact: Unused attack surface and install time.
- Migration plan: Remove after grep-confirmed unused.

**react-syntax-highlighter:**
- Risk: Heavy; Prism theme import from `/esm/styles/prism`. Not unmaintained, but large for every code fence.
- Impact: Bundle size / first paint on concept cards.
- Migration plan: Lazy load highlighter.

## Missing Critical Features

**User accounts and access control:**
- Problem: No login, no per-user isolation, no CSRF tokens. Optional `user_id` is not verified.
- Blocks: Shared/cloud deployment, classroom use, any untrusted network bind.

**Server-side secret storage (local mode):**
- Problem: Keys and Mongo URI only in the browser (and in Mongo `app_settings` after connect). Process restart does not have keys until the client sends headers.
- Blocks: Headless resume after reboot without the same browser profile. Background workers cannot call LLMs without the original request headers (runtime does keep `LLMContext` on the in-memory task for that process lifetime).

**Multi-instance generation:**
- Problem: `GenerationRuntime` is in-process. No queue, no external worker.
- Blocks: Horizontal scale, surviving process replace without pause/resume protocol (pause-on-shutdown exists for this process only).

**End-to-end Mongo parity proof:**
- Problem: Mongo learning/job tests use `MagicMock` collections (`server/tests/test_mongo_learning.py` header: “without live Atlas”). No learning-router test with a real Mongo bundle.
- Blocks: Confident “cloud complete” claim; cascade/lock/resume bugs slip through.

**Operational health and metrics:**
- Problem: `/health` is static. No queue depth, lock owners, or search budget metrics.
- Blocks: Production alerting.

**Rate limiting and abuse controls:**
- Problem: Unauthenticated `POST /learning/generate` with a stolen/copied key header can start expensive jobs. No per-IP limit.
- Blocks: Safe LAN or cloud exposure.

## Test Coverage Gaps

**Quiz randomization (High):**
- What's not tested: Fisher-Yates, seeded shuffle stability, `hide_quiz_card` / `hide_quiz_set` field omission, `evaluate_quiz_answer` single vs multi, `get_or_create_shuffle_order` seed persistence, router IN_QUIZ vs review payload.
- Files: `server/services/quiz_randomization.py`, `server/routers/learning.py`
- Risk: Answer leak, reshuffle mid-quiz, wrong scoring by `option_id`.
- Priority: High

**Concept chat base URL and client cache (High):**
- What's not tested: `resolve_chat_base_url("openai/gpt-4o-mini", "openrouter")` must stay on OpenRouter; cache must not reuse another key.
- Files: `server/services/concept_chat.py`, `server/tests/test_concept_chat_loop.py`
- Risk: Auth failures and cross-user key reuse.
- Priority: High

**Mongo behavioral parity (High):**
- What's not tested: Real CRUD/cascade/locks against mongomock or a container. Facade swap then `GET /learning/sessions/{id}` hitting Mongo. Resume-after-migrate with real savers (checkpoint tests still mock-heavy).
- Files: `server/tests/test_mongo_*.py`, `server/tests/test_checkpoint_migration.py`, `server/database/repositories/mongo_learning.py`
- Risk: Green CI, broken Atlas.
- Priority: High

**SQLite locking under generation (Medium):**
- What's not tested: Concurrent `LearningManager` reads vs `BEGIN IMMEDIATE` generation writes; `database is locked` handling.
- Files: `server/database/learning_persistence.py`, `server/tests/test_critical_lock_and_poll.py`
- Risk: Failed polls and 500s during generate on Windows (this repo’s primary OS).
- Priority: Medium

**Client learning hooks and home (Medium):**
- What's not tested: `useLearningMutations.ts`, `useRevisionSession.ts`, `useRevisionMutations.ts`, `useQuizFeedback.ts`, `useNodeState.ts`, `useChatStreaming.ts`, `useCourseList.ts`, `LearningHome.tsx`, `QuizFeedback.tsx`, `RevisionConceptCard.tsx`, `optimisticUpdates.ts`, `mermaidUtils.ts`, `ErrorStates.tsx`, settings `OpenRouterSettingsPanel.tsx` / `ModelPicker.tsx`.
- Files: `client/src/features/learning/*`, `client/src/features/settings/*`
- Risk: Optimistic cache bugs, broken revision flow, silent mutation failures.
- Priority: Medium

**Mermaid XSS / sanitize (Medium):**
- What's not tested: Malicious mermaid string under `securityLevel: "loose"`; rehype-raw + sanitize allowlist.
- Files: `client/src/features/learning/MarkdownRenderer.tsx`, `client/src/features/learning/MarkdownRenderer.test.ts`
- Risk: XSS in concept cards and chat.
- Priority: Medium

**Regen grounding (Medium):**
- What's not tested: Regen with existing `node_sources` / briefs; empty citation replace; ERROR vs BOTH step dispatch against real stores.
- Files: `server/graph/regen.py`, `server/tests/test_regen.py`
- Risk: Ungrounded retries after web-enabled generate.
- Priority: Medium

**Storage boot UX (Low):**
- What's not tested: Failed Atlas connect still rendering the app without user-visible error (unit tests cover merge/timeouts more than UX).
- Files: `client/src/lib/storageBoot.ts`, `client/src/lib/startApplication.ts`
- Risk: Silent fallback to empty SQLite.
- Priority: Low

**Graph `except Exception` swallow paths (Low):**
- What's not tested: Progress event persist failure still returning `content_ready: True`; warning append skip.
- Files: `server/graph/nodes.py`
- Risk: UI/SSE diverge from DB.
- Priority: Low

---

*Concerns audit: 2026-09-05*
