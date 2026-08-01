# Code Review: Internet-Grounded Course Generation
**Reviewer mood:** hostile
**Commit range:** 4251b40..458f183
**Review commit:** PENDING

## Executive verdict
NO_SHIP

This cannot go to production. Main advertised path, web-grounded generation, does
not execute real search at all. Production imports a nonexistent coordinator,
catches the resulting exception, and silently turns every web-enabled course
into degraded model-only generation. Phase 7 acceptance passes because its
harness replaces that broken production path and writes successful research
artifacts itself.

Durability claims are also false. Execution fences do not fence graph writes,
restart handling can strand live-stage jobs or convert shutdown into user
cancellation, and persistence helpers swallow SQLite errors or invent progress
events that were never stored. Progressive polling omits the migrated columns
needed to distinguish shells and skeletons from ready content. Secret canaries
do not flow through real runtime contexts, while the LLM client still logs raw
external exception text.

Verification on reviewed HEAD:

- `server\.venv\Scripts\python.exe -m unittest`: 189 tests pass, with an
  unawaited LangGraph coroutine warning during recovery acceptance.
- `npm run test -- --run`: 87 tests pass, with React `act()` and invalid DOM prop
  warnings.
- `npm run test:generation:coverage`: passes configured per-file 81% thresholds.
- `npm run lint`: passes.
- `npm run build`: fails with `TS2322` at
  `client/src/features/learning/CourseSourcesPanel.test.tsx:171`.
- `git diff --check 4251b40..458f183`: fails on trailing whitespace.

Passing mocked tests do not offset a broken production composition, failed
build, unsafe recovery, or false security audit.

## Spec compliance matrix
| Goal requirement | Status PASS/FAIL/PARTIAL | Evidence |
|---|---|---|
| Web search OFF by default; icon hidden when master OFF; per-course icon starts OFF | PASS | `providerSettings.ts` defaults master/providers OFF; `WebSearchSettingsPanel` hides cards; `TopicInput` initializes local opt-in false and gates icon through `hasWebSearchCapability()`. Tests cover these isolated behaviors. |
| Curated free providers only: Tavily, Exa, Brave, SerpAPI | PASS | `server/search/registry.py` and `client/src/lib/webSearchProviders.ts` contain exactly four locked IDs in required order with current metadata. |
| Shuffle once; rotate only rate/quota/timeout/5xx | FAIL | `ProviderCoordinator` implements approved isolated behavior, but production `run_research()` imports nonexistent `SearchCoordinator` at `server/services/research_runner.py:862` and never instantiates `ProviderCoordinator`. Required behavior is unreachable. |
| Adaptive bounded research budgets | FAIL | Budget types exist, but runner and coordinator use separate ledgers, resume restores only partial counters, elapsed time restarts, and production wrapper hardcodes `resolved_mode="lite"` at `research_runner.py:875`. Repeated resumes can exceed hard limits. |
| Degraded continue without web plus warning | PARTIAL | `researcher_node()` catches failures and emits a generic warning, so model-only generation continues. However, this path runs for every web request because research is broken, and some empty/incomplete research exits `COMPLETE` without a persisted degraded warning. |
| Citations plus Course Sources panel | PARTIAL | Focused citation tables and UI exist. Planner receives whole report text rather than server-scoped topic evidence, brief source IDs are not checked against persisted sources, unsupported citation persistence is swallowed, completed cards hide citations, and client build currently fails in Sources-panel tests. |
| `202` shell and progressive UI; TOC first; briefs 3 then 10 | FAIL | `POST /learning/generate` returns `202`, detached same-process execution exists, and web-off graph tests show 3/10 windows. Real polling omits `title_finalized` and `generation_status`, so skeletons project as finalized/READY; TOC control is unavailable while all nodes are skeletons. |
| Cancel retains partial; resume with fresh secrets | FAIL | App data is generally retained, but cancellation during research is swallowed as degradation and advances to outlining; immediate restart can leave an unexpired lock and active stage with no worker; shutdown cancellation is recorded as user `CANCELLED`; Phase 7 restart proof is fabricated. |
| Secrets never in SQLite/checkpoints/logs/SSE | FAIL | Graph state excludes secrets and typed events are narrow, but `InstructorClient` logs raw exception text at `server/utils/instructor_client.py:301-303`. Canary harness does not run canary contexts through the real job and hand-builds HTTP error JSON. |
| Focused DB modules, no new LearningManager bloat | PASS | Generation jobs, research, artifacts, migrations, and events live in focused `server/database/` modules. `LearningManager` did not gain these APIs. |
| TDD/tests quality, no dead code/security/race holes, all gates pass | FAIL | Unit suites and focused coverage pass, but production build fails, recovery emits a coroutine warning, acceptance mocks the broken subsystem, duplicate-runner fencing is not tested, and stale `server/tests/smoke_phase3_runner.py` is undiscovered. |

## Critical issues (must fix)
### C1: Production web research is dead code behind a degraded fallback
- **Severity:** Critical.
- **Files:** `server/services/research_runner.py:850-878`, `server/graph/nodes.py:318-392`, `server/tests/generation_acceptance_harness.py:400-513,604-609`.
- **Why:** `run_research()` imports `SearchCoordinator`, which does not exist. Actual class is `ProviderCoordinator`. Even after correcting the name, wrapper constructs neither adapters nor shared budget ledger, supplies no acquired `GenerationLock`, and hardcodes lite mode. `researcher_node()` catches every exception and labels course degraded. Result: no production web-enabled course can become genuinely grounded.
- **Test fraud:** Acceptance harness patches `server.graph.nodes.run_research` and directly creates sources, sections, events, counts, and successful status. It proves fake function works, not production research.
- **How to fix:** Build adapters from selected runtime credentials, create one `ProviderCoordinator` with persisted order and shared ledger, pass actual resolved mode and fenced lock, and let only typed provider/research outcomes degrade. Add integration test using production `run_research`, real stores, real coordinator, and `httpx.MockTransport`; patch only external HTTP and Researcher LLM calls.

### C2: Execution lock does not fence execution
- **Severity:** Critical race and corruption risk.
- **Files:** `server/graph/runner.py:84-168`, `server/database/generation_jobs.py:656-705`, `server/graph/nodes.py:273-303,378,434,466,516,903,955`.
- **Why:** Every runner defaults to owner `worker-1`. `try_acquire_lock()` allows a live lock to be reacquired when owner string matches, increments version, and fences the first token. Heartbeat failure only exits heartbeat loop; graph keeps writing. Graph nodes use unlocked `update_stage()` and `update_progress()` instead of `transition_stage()`/`update_cursor()` with lock token. A stale worker can therefore continue LLM calls and overwrite stages, cursors, counts, artifacts, and events after another worker acquires lock.
- **How to fix:** Generate unique worker UUID per execution, reject every live lock regardless of same owner text, put immutable `GenerationLock` in runtime context, require it for every job mutation and durable stage boundary, and cancel/abort graph immediately when renewal fails. Race two real runners in test and prove fenced worker cannot write any surface.

### C3: Real session polling erases progressive module state
- **Severity:** Critical product regression.
- **Files:** `server/database/learning_persistence.py:314-354,1504-1561`, `server/routers/learning.py:493-580`.
- **Why:** `get_learning_session()` does not select `title_finalized`. `get_session_nodes()` does not select `generation_status`. Router defaults missing title flag to true and missing module status to `READY`. Skeleton and generating rows therefore become finalized ready modules in real API responses. Mocked projection test injects both missing fields, so it cannot catch this.
- **Impact:** Polling fallback cannot show TOC skeletons correctly, can expose partially generated content, and disagrees with SSE/cache state. Core progressive UX is broken on real SQLite data.
- **How to fix:** Select and return migrated columns in production LearningManager queries, then test `/learning/sessions/{id}` against a real temporary DB through shell, persisted outline, `GENERATING`, `READY`, and `ERROR` states.

### C4: Cancel/restart/resume workflow is not durable
- **Severity:** Critical data-lifecycle failure.
- **Files:** `server/graph/nodes.py:333-378`, `server/database/generation_jobs.py:763-801`, `server/services/generation_runtime.py:285-297`, `server/graph/runner.py:207-226`, `server/tests/generation_acceptance_harness.py:780-925`.
- **Why:** `researcher_node()` catches `ResearchCancelled` as generic failure, marks degraded, and advances to `OUTLINING`; resume then skips unfinished research. Startup pauses only jobs whose lock is absent/expired, so an abrupt restart with future lock expiry leaves active-stage job with no task and no allowed resume. Shutdown checks orphans before cancelling local tasks; runner interprets task cancellation as user cancellation and marks retained `CANCELLED`, not restart-resumable `PAUSED`.
- **False proof:** Recovery harness explicitly calls user cancel before "restart", accepts `CANCELLED` as restart state, fabricates repeated thread observations from same field, and sets `fresh_credentials_used_on_resume=True` itself.
- **How to fix:** Propagate research cancellation as generation cancellation without degraded transition; identify boot/worker ownership and pause all prior-process nonterminal jobs on startup; distinguish shutdown pause from user cancel; release/clear owned locks before process exit. Test abrupt process loss without calling cancel, unexpired-lock reconciliation, graceful shutdown, and resumed unfinished research with new contexts.

### C5: Persistence reports success when nothing was persisted
- **Severity:** Critical durability and SSE integrity failure.
- **Files:** `server/database/progress_events.py:132-194`, `server/database/generation_jobs.py:803-859`, `server/graph/nodes.py:419-443,428-484,891-907`.
- **Why:** `ProgressEventStore.append_once()` catches SQLite/lookup errors and returns synthetic event ID 1. `update_stage()` and `update_progress()` swallow database errors. Graph boundaries commit artifact, event, stage, count, and cursor in separate transactions and frequently swallow event failures. Runtime can report progress/completion that cannot survive restart or replay over SSE.
- **How to fix:** Remove synthetic fallback and silent catches; raise typed persistence failures so runner pauses/fails safely. Use caller-owned transaction for outline plus skeletons plus stage/count/event, each research section plus cursor/event, and each batch advancement plus counts/event. Add fault injection after every statement and assert full rollback.

### C6: Secret audit is vacuous and real LLM errors can leak secrets
- **Severity:** Critical security defect.
- **Files:** `server/utils/instructor_client.py:301-303`, `server/tests/generation_acceptance_harness.py:1100-1257`, `server/schemas/llm.py` (`LLMContext.api_key`).
- **Why:** `InstructorClient` logs raw exception text. Provider/SDK exceptions can contain request values, URLs, or credentials. `LLMContext.api_key` is plain string and repr-visible. Phase 7 audit does not pass canary keys through real runtime job: normal `run()` uses fixed test keys, canary provider error is caught inside fake research before production logging, and `http_error_json` is handwritten.
- **How to fix:** Store LLM key as excluded/repr-hidden `SecretStr` or equivalent explicit secret wrapper; route all external failures through fixed-shape logging with no message/traceback/context; disable or handler-filter low-level auth logs. Rebuild audit so canaries flow through actual generate/resume contexts, outbound mocked failures, production TestClient errors, real DB/checkpoint/event/SSE/log surfaces.

### C7: Phase 7 declared success despite failed build and fake acceptance
- **Severity:** Critical release-process failure.
- **Files:** `client/src/features/learning/CourseSourcesPanel.test.tsx:171`, `server/tests/generation_acceptance_harness.py`, `client/src/features/learning/__tests__/internetGroundedGeneration.test.tsx:152-243`, `docs/internet-grounded-course-generation/plan7.md`.
- **Why:** `npm run build` fails because test fixture assigns null to required `retrieved_at`. Server acceptance replaces full research runner, calls runtime/functions directly instead of production HTTP API, simulates HTTP error JSON, and does not exercise duplicate lock contention. Browser acceptance has only two API-mocked scenarios; it does not cover degraded flow, TOC, preview/later batches, sources, citations, delete, reconnect, or mobile layout. Recovery suite emits unawaited-coroutine warning. Yet Phase 7 completion note claims release gates passed.
- **How to fix:** Fix build fixture, remove completion claim until evidence exists, compose acceptance through production router/runtime/stores/graph with only external APIs mocked, and make warning-clean full gates mandatory. `git diff --check` must also pass for reviewed range.

## Major issues (should fix before calling done)
### M1: Research budget is neither shared nor durable
- **Severity:** Major.
- **Files:** `server/services/research_runner.py:195-247,249-381,509-520`, `server/search/coordinator.py`, `server/search/budget.py`.
- **Why:** Runner constructs its own ledger while coordinator consumes another for HTTP attempts/retries. Persisted cursor omits source/context usage and elapsed duration effectively restarts. Cancellation can save a cursor with reset usage. Repeated resume can exceed calls, result, source, byte, context, and wall-time maxima.
- **How to fix:** One ledger object must govern coordinator and runner. Persist complete usage and elapsed budget, restore it on resume, and cap each HTTP/LLM timeout by remaining wall time. Add retry plus repeated-resume hard-stop tests.

### M2: Incomplete or empty research can be labeled complete
- **Severity:** Major false-grounding risk.
- **Files:** `server/services/research_runner.py:249-508`.
- **Why:** Loop exits when no follow-up query remains even if coverage is incomplete. Final status is always `ResearchStatus.COMPLETE`; any retained source yields `GROUNDED`. Empty results can become `COMPLETE` with degraded grounding but no persisted warning/event. One irrelevant source is enough to create grounded label.
- **How to fix:** Completion requires deterministic coverage criteria. Hard stop, empty evidence, insufficient domains/freshness, or incomplete coverage must finalize `DEGRADED` with visible warning and no grounded claim. Add empty, irrelevant-single-source, uncovered-no-follow-up, and explicit-unknown cases.

### M3: Coverage validation accepts fabricated or stale evidence
- **Severity:** Major grounding-integrity defect.
- **Files:** `server/services/research_runner.py:89-147,419-426,459-467,634-673`.
- **Why:** Root-domain criterion counts hostnames, so subdomains can fake diversity. Completion call omits requested recency. `_validate_source_ids()` checks only top-level section IDs; `coverage_updates[*].source_ids` can contain fabricated IDs and mark themes covered. Section Markdown can still contain fake IDs/raw links after metadata list is cleaned.
- **How to fix:** Use registrable domains, publication-date freshness, and persisted source ownership on every coverage update. Parse or structurally represent report citations and strip/reject unknown IDs and arbitrary links before persistence.

### M4: Planner briefs are not topic-scoped or provenance-validated
- **Severity:** Major spec failure.
- **Files:** `server/graph/nodes.py:406-417,477-504`, `server/database/research_store.py:get_report_context`, `server/agents/planner.py:plan_briefs`.
- **Why:** Every batch receives same whole report text capped at 8 KB, not topic-specific excerpts. Planner-returned source IDs/excerpts are not validated against stored report/session provenance before brief persistence. A fabricated ID becomes Generator-approved; citation store later rejects it, and graph swallows that rejection.
- **How to fix:** Server selects scoped source IDs/excerpts per topic, passes structured allowlist, validates report ID/source ownership/excerpt provenance before persisting brief, and pauses after bounded correction if invalid.

### M5: Crash between app DB write and checkpoint repeats external calls
- **Severity:** Major cost and consistency risk.
- **Files:** `server/graph/nodes.py:411-443,495-525,569-608,755-833`, `server/database/generation_artifacts.py`.
- **Why:** LangGraph checkpoint and application artifacts use separate SQLite files. Crash after app artifact commit but before graph checkpoint reruns Planner/Generator/Quizzer. Different output can conflict with deterministic artifacts, leave stale skeletons, duplicate paid calls, or attach content/citations from different generations.
- **How to fix:** Before external call, inspect durable step artifact and reuse completed outcome; persist explicit step/version/idempotency markers. Add crash injection after each artifact write and before checkpoint with changed fake output on resume.

### M6: Batch barrier and public counts lie about failures
- **Severity:** Major correctness issue.
- **Files:** `server/graph/nodes.py:891-907`, `server/database/generation_jobs.py:822-859`.
- **Why:** `advance_batch_node()` does not verify every durable node in current batch is `READY` or `ERROR`. `update_progress()` sets `topics_ready=max(topics_ready,next_index)`, counting failed topics as ready. Partial-failure course can report all topics ready plus failures.
- **How to fix:** In one transaction query all current batch statuses, reject nonterminal rows, compute exact global READY/ERROR counts, update cursor, and emit event. Test partial failures and resumed barrier from real DB.

### M7: Automatic depth resolution is bypassed
- **Severity:** Major behavior drift.
- **Files:** `server/graph/runner.py:173-203`, `server/graph/nodes.py:281-306`, `server/services/research_runner.py:871-878`.
- **Why:** Runner forces `mode="auto"` to full. Initialize node only normalizes existing values and never calls depth router. Session `resolved_mode` remains null. Research wrapper separately forces lite, so planning and research can use contradictory budgets.
- **How to fix:** Resolve auto mode in initialization, persist once, checkpoint it, and pass same value to Researcher/Planner/Generator. Test both auto-lite and auto-full through real graph/store composition.

### M8: HTTP response cap does not cap network memory
- **Severity:** Major resource/security issue.
- **Files:** `server/search/adapters/_common.py:105-160`, `server/search/http.py:150-209`.
- **Why:** `AsyncClient.request()` buffers entire response before capped JSON reader sees it. Byte accounting can trust `Content-Length`; chunked or underreported payloads can consume unbounded memory and bypass provider-byte ledger.
- **How to fix:** Use streamed response, count actual chunks, stop before cap, reject oversized/mismatched payload, and reserve actual bytes. Test chunked oversized body and false Content-Length.

### M9: Resume can be undone by equal-ID stale polling
- **Severity:** Major client race.
- **Files:** `client/src/features/learning/generationEvents.ts:48-62`, `client/src/features/learning/LearningPage.tsx:82-106,155-176`, `server/services/generation_runtime.py:249-263`.
- **Why:** Poll reconciliation accepts incoming snapshot when event IDs are equal. Resume changes stage but appends no event. Delayed pre-resume poll with same ID can restore `CANCELLED`, stop polling, and close SSE while server continues generation.
- **How to fix:** Persist monotonic event on resume/cancel-state transition and/or reconcile equal IDs using authoritative generation revision. Cancel/fence in-flight poll around controls. Test deferred equal-ID poll across resume.

### M10: Dashboard client consumes response shape server never sends
- **Severity:** Major visible regression.
- **Files:** `client/src/types/learning.ts:248-263`, `client/src/features/learning/CourseCard.tsx:65-114`, `server/schemas/learning.py:846-853`.
- **Why:** Client expects nested `session.generation`; list API returns flat `generation_stage` and `grounding_status`. Generating, paused, cancelled, and degraded dashboard badges disappear. Existing test fabricates nested object and masks contract mismatch.
- **How to fix:** Align one API contract and test with exact serialized `/learning/sessions` response.

### M11: Progressive TOC and carousel violate locked UX
- **Severity:** Major.
- **Files:** `client/src/features/learning/LearningPathContainer.tsx:384-448,851-939`, `client/src/features/learning/ConceptCard.tsx:358-371`.
- **Why:** Skeleton path renders no TOC trigger, while card TOC button appears only for explanation/completed states. TOC is inaccessible immediately after outline, exactly when goal requires it. When first skeleton changes to READY, active-node effect can yank user from manually selected later skeleton back to topic one.
- **How to fix:** Put TOC trigger outside card state whenever nodes exist. Separate learner-state auto-advance from module-generation status changes and preserve selected index. Add all-skeleton TOC and arrival-without-reset tests.

### M12: Retry and source presentation lose valid user actions
- **Severity:** Major UX failure.
- **Files:** `client/src/features/learning/LearningPathContainer.tsx:765-785`, `client/src/features/learning/ConceptCard.tsx:510-542,734-759`, `client/src/features/learning/LearningPage.tsx:480-485`.
- **Why:** All ERROR nodes collapse into global error whose retry only refetches unchanged data, hiding per-card regeneration. Web-off cards still receive Sources callback. Completed grounded cards omit citation footer and source action, so provenance disappears after mastery.
- **How to fix:** Always render retryable ERROR cards; pass source callback only for web-requested jobs; retain validated citations in completed/review states. Add all-error, web-off, and completed-grounded tests.

### M13: Final generation and regeneration can leave unsafe or stale citations
- **Severity:** Major citation-integrity issue.
- **Files:** `server/agents/generator.py:303-379`, `server/graph/nodes.py:584-597`, `server/graph/regen.py:145-180`.
- **Why:** After repeated Mermaid-invalid outputs, Generator returns final content without guaranteed citation/link sanitation. Graph persists content before citation replacement and swallows replacement failure. Regeneration ignores new `content.citations`, leaving old links attached to changed content.
- **How to fix:** Sanitize every final return or fail topic; persist content and citation replacement transactionally; regeneration must replace links including empty set. Test invalid Mermaid plus fabricated URL/ID and changed/no-citation regeneration.

### M14: Event retention and permanent cleanup are broken
- **Severity:** Major operational issue.
- **Files:** `server/database/progress_events.py:242-293`, `server/routers/learning.py:delete_learning_session`.
- **Why:** `compact_completed()` SQL has placeholder/argument mismatch and is never called, so event log grows unbounded despite locked bounded-retention requirement. Delete removes app DB first and treats checkpoint deletion failure as success, leaving orphan checkpoint state.
- **How to fix:** Correct and invoke terminal compaction with replay contract; coordinate idempotent task stop, checkpoint deletion, and app DB cascade, surfacing partial failure and supporting retry.

## Minor / nits
### N1: Malformed active HTML survives source sanitizer
- **Severity:** Minor defense-in-depth gap.
- **Files:** `server/search/source_safety.py:64-69,157-175`.
- **Why:** Active-block regex requires closing tag. Unclosed `<script>ignore prior instructions` becomes plain instruction text. Prompt fencing helps, but strip contract is not met.
- **How to fix:** Use stateful parser that discards malformed/unclosed active elements; add nested, mixed-case, and truncated-tag tests.

### N2: Citation numbering is off after first source
- **Severity:** Minor UI correctness.
- **Files:** `server/database/research_store.py:750-757`.
- **Why:** Stored zero-based order maps to `1, 1, 2...` instead of `1, 2, 3...`.
- **How to fix:** Return `citation_order + 1`; test three citations.

### N3: Sources panel hides valid report data
- **Severity:** Minor.
- **Files:** `client/src/features/learning/CourseSourcesPanel.tsx:147-177`.
- **Why:** Summary is never rendered. Warnings render only inside degraded block, so complete/researching report warnings disappear.
- **How to fix:** Render summary and warnings independently of status.

### N4: Cancel-requested state still looks cancellable
- **Severity:** Minor but confusing.
- **Files:** `client/src/features/learning/GenerationStatusPanel.tsx:69-76,157-174`, `client/src/features/learning/LearningPage.tsx:134-139`.
- **Why:** Real cancel response remains active stage with `cancel_requested=true`; UI ignores flag, re-enables Stop, and keeps normal generating copy.
- **How to fix:** Disable Stop and show persistent `Stopping...` until terminal cancel event while SSE/polling continue.

### N5: Keyboard and mobile controls are fragile
- **Severity:** Minor accessibility/responsiveness.
- **Files:** `client/src/features/learning/CourseCard.tsx:127-135`, `client/src/features/learning/LearningPage.tsx:393-445`, `client/src/features/learning/TableOfContentsModal.tsx`.
- **Why:** Enter/Space on nested buttons bubbles to card and can trigger resume/review in addition to intended action. Narrow header can overflow; hover-only delete and unconstrained TOC modal are poor touch/mobile behavior.
- **How to fix:** Ignore bubbled card key events, wrap header controls, expose mobile delete/focus states, cap modal height, and give table minimum width.

### N6: Enabled provider can retain blank key
- **Severity:** Minor settings inconsistency.
- **Files:** `client/src/features/settings/WebSearchSettingsPanel.tsx:60-70`.
- **Why:** Clearing key persists enabled=true with blank key. Checkbox says enabled while capability/icon vanish.
- **How to fix:** Auto-disable provider or show blocking validation until corrected.

### N7: Repository still carries dead and warning-dirty test artifacts
- **Severity:** Minor release hygiene.
- **Files:** `server/tests/smoke_phase3_runner.py`, `client/src/features/learning/LearningPathContainer.test.tsx`, `client/src/features/learning/ConceptCard.test.tsx`, `docs/internet-grounded-course-generation/research.md`.
- **Why:** Smoke script is undiscovered and expects obsolete 201 behavior. Client tests emit `act()`/DOM-prop warnings. Range whitespace gate fails.
- **How to fix:** Delete or convert smoke script, make tests warning-clean, and pass `git diff --check`.

## What actually works (begrudging)
- Browser master web-search setting and all provider defaults are OFF.
- Provider controls hide while master is OFF; per-course icon starts unselected.
- Server/client registries contain only Tavily, Exa, Brave, and SerpAPI.
- Adapter normalization and typed status mapping work in mocked HTTP tests.
- Isolated `ProviderCoordinator` correctly distinguishes rotatable and non-rotatable errors.
- Search keys are excluded from `SearchContext` dumps/repr and client statically scopes search headers to generate/resume.
- `POST /learning/generate` returns `202`; same-process generation task is detached from HTTP/SSE connection and strongly referenced.
- Web-off production graph demonstrates TOC-first staging and exact windows `(0,3)`, `(3,10)`, `(13,10)`, `(23,7)`.
- Generator/Quizzer sibling failures produce partial ERROR cards without blocking later web-off batches.
- SSE service replays ordered durable rows after cursor and disconnect does not directly cancel generation.
- New persistence responsibilities are in focused modules instead of added to `LearningManager`.
- URL canonicalization, credentialed/private literal URL rejection, source caps, and prompt fences cover normal tested inputs.
- Grounded badge is gated to `GROUNDED`; degraded warning component exists and is persistent when state reaches client correctly.
- Focused client coverage config genuinely enforces 81% per file for eight selected new modules.

## Test gaps
- No test invokes production `run_research()` with production coordinator composition. This is why nonexistent import shipped.
- Server acceptance does not traverse production HTTP generate/research/events/cancel/resume dependencies; it calls runtime and router functions directly.
- Grounded acceptance patches whole research subsystem and writes expected artifacts itself.
- Duplicate-resume test races two `runtime.resume()` calls, not two acquired runners; every exception becomes a reported conflict.
- Restart test performs user cancellation before shutdown and fabricates some observations instead of abrupt restart with live lock.
- Secret audit does not use canary contexts in actual job, catches canary provider error inside fake, and hand-builds HTTP error response.
- No real-DB route test covers shell title flag or skeleton/generating module projection.
- No crash-injection tests cover app DB commit before LangGraph checkpoint.
- No shared-ledger resume test proves cumulative hard research limits.
- No test proves incomplete coverage cannot become grounded.
- Browser acceptance contains only stale-poll and stop/resume mocks. Missing degraded, TOC, preview-first, later-batch, sources, citations, reconnect, delete, dashboard contract, and mobile flows.
- API header-scope test uses Axios fake that does not execute request interceptors, so it would miss future global secret interceptor leakage.
- Build is not passing despite plan claiming full release gates.

## Recommended fix order
1. Fix production `run_research()` composition and add real grounded integration test. Nothing else makes web grounding real.
2. Make execution lock unique, fenced, and fatal on renewal loss; remove unlocked worker mutations.
3. Stop swallowing persistence errors and make stage/artifact/count/event/cursor boundaries transactional.
4. Fix real polling queries for `title_finalized` and `generation_status`; add real SQLite API tests.
5. Correct cancel, shutdown, orphan reconciliation, and resume semantics; emit monotonic control events.
6. Make research ledger fully shared/durable and require coverage before grounded completion.
7. Enforce server-built topic-scoped citation provenance and sanitize transactional generation/regeneration outputs.
8. Remove raw external exception logging and rebuild canary audit through production surfaces.
9. Fix dashboard contract, TOC access, carousel stability, ERROR-card retry, and source/citation visibility.
10. Replace fabricated Phase 7 harness assertions with production composition; expand browser acceptance.
11. Fix production build, warning-dirty tests, dead smoke script, and whitespace gate.
12. Rerun full server tests, full client tests, focused coverage, lint, build, `git diff --check`, and an explicit production-composition grounded smoke test with mocked external transport before reconsidering ship status.
