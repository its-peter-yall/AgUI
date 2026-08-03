# Code Review: MongoDB Atlas Storage

**Reviewer role:** Code Review Agent  
**Date:** 2026-08-03  
**Scope:** Full MongoDB Atlas storage feature vs `goal.md`, research, plans 1–9, and implementation  
**Verdict:** **SHIP-WITH-FIXES** (do not treat complete until CRITICAL/HIGH below fixed)

---

## Executive Summary

Approach A repository swap is largely in place: process-wide `StorageContext`, late-bound facades, sync PyMongo (not Motor), `MongoDBSaver` (not `AsyncMongoDBSaver`), local connect/disconnect/migrate APIs, cloud env fail-fast, client boot + Settings panel, and ops docs. Architecture matches locked decisions more than it diverges.

Production risk remains. Several gaps can strand generation jobs after restart, abort real migrations from the browser, wipe credentials on hydrate, or leave partial deletes. Tests exist in quantity but lean on mocks; cascade/parity/resume are under-proven. **Not blocked on architecture.** **Blocked on quality bar for “complete”** until CRITICAL + top HIGH items fixed.

---

## Severity-Ranked Issues

### CRITICAL

#### C1. Cloud (and Mongo-active) startup never pauses orphan generation jobs

**Where:** `server/main.py:104-118` (cloud lifespan); contrast local `124-126`.  
**Also:** After local boot connect to Mongo (`client` → `POST /connect`), no orphan pause on the Mongo job store.

**What’s wrong:** Local SQLite path calls `mark_orphaned_jobs_paused(pause_all_nonterminal=True)` after schema init. Cloud `start_cloud_runtime` connects Mongo, builds runtime, and serves — **never** pauses nonterminal jobs left by a previous process crash/kill. Local mode that auto-connects to Atlas only pauses **SQLite** orphans at startup, then swaps to Mongo where in-flight rows can still say “running” with no worker.

**Why it matters:** Goal success criteria include durable generation + checkpoints. Stuck nonterminal jobs block resume UX, confuse UI stage, and can interact badly with locks. Cloud deploy is the primary production path — this is a fail-open correctness hole.

**Fix:** After successful Mongo connect (cloud startup **and** local `StorageContext.connect` / post-connect hook), call:

```python
storage.jobs.mark_orphaned_jobs_paused(pause_all_nonterminal=True)
```

Add tests in `test_cloud_storage_startup.py` and connect path tests asserting the call.

---

#### C2. Client migrate (and heavy storage calls) hard-timeout at 10s

**Where:** `client/src/lib/storageApi.ts:38-41` — single Axios instance `timeout: 10_000`.  
Used by `migrateStorage` (`67-76`), connect, app-settings.

**What’s wrong:** Migrate copies every app table + checkpoints via saver APIs. Any non-trivial local DB or slow Atlas free tier exceeds 10s. Axios aborts; server may still finish (or leave partial migrate — retryable, but UI shows failure and user may disconnect/retry blindly).

**Why it matters:** Goal success criterion #3 is migrate of courses/quizzes/generation/research/checkpoints/credentials. Feature is broken for real data even if server path is correct.

**Fix:** Separate clients or per-call timeouts, e.g. migrate `120_000`–`300_000`, connect `15_000`, status/settings `10_000`. Surface timeout as distinct UI error. Add client test that migrate request config uses extended timeout.

---

### HIGH

#### H1. Hydration can wipe local provider / web-search keys

**Where:**  
- `client/src/lib/storageBoot.ts:77-87`  
- `client/src/lib/providerSettings.ts:391-417` (`setProviderSettings` merges nested providers; empty string overwrites)  
- `client/src/lib/providerSettings.ts:553-555` (`setWebSearchSettings` **replaces** entire blob)

**What’s wrong:** Goal: after connect, Mongo is source of truth and client hydrates. If Atlas `app_settings` exists with empty `apiKey` fields (empty migrate, other machine defaults, partial docs), boot/Settings hydrate overwrites browser keys with blanks. Web search is full replace — any incomplete cloud snapshot destroys local keys. Truthy check `if (snapshot.providerSettings)` treats `{}` as hydrate-worthy.

**Why it matters:** Users lose OpenRouter/search keys without explicit migrate-of-secrets intent. Silent data loss.

**Fix options (pick one, document):**  
1. Hydrate only when cloud payload has non-empty secrets **or** user just migrated.  
2. Deep-merge web search like providers; never overwrite non-empty local secret with empty cloud string.  
3. On first connect with null/empty cloud settings, **push** local snapshot to Mongo before enabling write-through (aligns with “roam credentials” without erase).  
Add regression tests for empty-cloud-vs-full-local.

---

#### H2. `delete_learning_session` cascade is multi-step, non-transactional

**Where:** `server/database/repositories/mongo_learning.py:253-323`

**What’s wrong:** Ordered `delete_many` across research, revisions, quizzes, nodes, jobs, progress, session — no session/transaction. Mid-failure leaves orphans (e.g. nodes gone, session remains or vice versa). SQLite path is single connection + commit (plus FK CASCADE).

**Why it matters:** Research called out application cascade + optional multi-doc txn on Atlas replica set. Orphans break lists, migrate retries, and disk/quota.

**Fix:** Wrap cascade in `client.start_session()` + `start_transaction()` (same pattern as `mongo_jobs.create_session_shell_and_job`), or compensate with best-effort cleanup + structured error. Extend cascade test beyond a few `assert_called_once_with` mocks.

---

#### H3. Checkpoint migrate passes `new_versions={}` always

**Where:** `server/database/checkpoint_migration.py:56-61`

**What’s wrong:** `aput(..., {})` drops channel version map from source tuples. Tests only mock `aput` and never round-trip real `AsyncSqliteSaver` → `MongoDBSaver`. Resume-after-migrate may mis-merge channels or skip writes.

**Why it matters:** Plan 6/goal include checkpoint migrate for generation resume. Silent resume breakage is worse than documented skip.

**Fix:** Pass versions from checkpoint tuple if exposed by LangGraph API (inspect installed saver/`CheckpointTuple`); add integration-style test with real sqlite saver fixture + MongoDBSaver against mongomock/testcontainer, or document skip + force pause/re-derive if versions unavailable.

---

#### H4. Test quality insufficient for “parity” claim

**Where:** `server/tests/test_mongo_*.py` (e.g. learning ~7 tests, jobs 2, research 2, artifacts 3); all MagicMock collections.

**What’s wrong:**  
- No end-to-end learning API test with Mongo bundle active.  
- Cascade test checks a subset of `delete_many` args, not full graph.  
- Job lock/stage tests thin vs SQLite suite.  
- No test that after `connect`, router facades hit Mongo not SQLite.  
- Cloud orphan pause untested (see C1).  
- Client migrate timeout untested.

**Why it matters:** Goal testing strategy requires mode guards **and** critical LearningManager parity. Mocks prove call shapes, not behavioral parity. Junior ship risk: green CI, red prod.

**Fix:** Minimum bar before “complete”:  
1. Facade swap integration test (connect mock bundle → `learning_repository.get_*` resolves Mongo).  
2. In-memory fake or mongomock CRUD for session/node/quiz/delete.  
3. Cloud startup orphan pause.  
4. Client timeout config test.

---

#### H5. `quiz_data.node_id` index not unique

**Where:** `server/database/repositories/mongo_indexes.py:39`

**What’s wrong:** Research/plan: quiz is 1:1 with node; unique `node_id` expected. Non-unique index allows duplicate quiz docs under races; `find_one` returns arbitrary doc.

**Fix:** `create_index([("node_id", 1)], unique=True)` + handle `DuplicateKeyError` on upsert path.

---

#### H6. Progress event counter can skip IDs on dedupe conflict

**Where:** `server/database/repositories/mongo_progress.py:90-125`

**What’s wrong:** `$inc` counter then `insert_one`. Dedupe `DuplicateKeyError` returns existing event but counter already advanced → permanent gaps. Usually OK for monotonic cursors; concurrent same-dedupe burns IDs rapidly under retry storms.

**Why it matters:** Not usually user-visible; can confuse debugging and “latest_id” density. Lower than C1/C2 but real.

**Fix:** Prefer find-by-dedupe first, or reverse counter on pure-dedupe hit, or use deterministic `_id` from hash for deduped rows (harder). Document gaps as accepted if intentional.

---

### MEDIUM

#### M1. `local_data_present` only probes `learning_sessions`

**Where:** `server/database/storage_mode.py:215-225`

Generation-only / research-only local DBs → `canMigrate=false` though tables have rows. Expand probe to any `MIGRATION_TABLES` row or `SELECT 1` from jobs/nodes too.

---

#### M2. Connect/disconnect/migrate hold graph rebuild under process lock while doing I/O outside carefully

**Where:** `storage_mode.py:158-204` — index + bundle build outside lock (good); `activate` under lock (OK). Concurrent double-connect: last wins (goal OK) but brief dual clients. Acceptable; document.

---

#### M3. Exception `__cause__` may still put URI fragments in server tracebacks

**Where:** `mongo_client.py:85-94` `raise ... from exc`

Logs use type only (good). Tracebacks on unhandled paths can include driver messages with hosts/users. Ensure connect router never logs `str(exc)`; consider scrubbing in global exception handlers.

---

#### M4. Dual `LearningManager` construction

**Where:** `storage_registry.py:66` vs `learning_persistence.py:3236` module singleton; `storage_mode._default_sqlite_repositories` imports module singleton.

Production facades use registry instance. Default `StorageContext()` without injected bundle could bind the **other** manager. Prefer single factory; stop exporting unused module singleton for app paths.

---

#### M5. Cloud mode still constructs SQLite store objects at import

**Where:** `storage_registry.py:66-84`

No schema init in cloud (good), but unused SQLite managers live in process. Low risk; optional lazy init for cloud.

---

#### M6. Settings footer copy still “Local Storage” only

**Where:** `client/src/features/settings/SettingsPage.tsx` (~469)

Misleading after Atlas feature. Update copy.

---

#### M7. Boot failure is silent to user

**Where:** `storageBoot.ts:70-74` + `startApplication.ts`

Connect fail → app renders on SQLite with `error` only in boot result, not surfaced. Settings will show local; user may not know saved URI failed. Surface toast/banner once.

---

#### M8. `can_connect` true while already connected

**Where:** `storage.py:68` — `can_connect=local_mode` always.

Allowed by “last connect wins.” UI allows Connect while Connected without extra confirm. OK product-wise; optional confirm to avoid accidental target switch.

---

#### M9. Migrate does not pause/validate Mongo-side active jobs beyond HTTP idle guard

Idle guard uses **in-process** tasks only (`generation_runtime.active_session_ids`). Another worker/process (future) would not be covered. Single-process assumption OK for v1; document.

---

#### M10. Line length / convention drift

Several mongo repo files exceed 80-col guidance in places; headers present on new files. Not functional.

---

### LOW

#### L1. `replace_node_content` double `update_one` for null clears

`mongo_learning.py:557-584` — awkward `$unset` then `$set` None. Works; simplify.

#### L2. `storageApi` duplicates Axios base URL instead of shared `api` instance

Drift risk for interceptors/auth later.

#### L3. Checkpoint idempotency test uses fake target key sets, not real saver upsert semantics

#### L4. Ops doc solid; README link assumed present (verify if missing)

#### L5. No rate limit on connect endpoint (local single-tenant OK)

---

## What Was Done Well

1. **Approach A without dual-write** — single active bundle, facades resolve every call.  
2. **Stack correction from research** — PyMongo sync + `MongoDBSaver`; no Motor / no deprecated async saver.  
3. **URI hygiene** — redaction helper; connect errors mapped to static details; `uri` `repr=False` on schema; status never echoes URI.  
4. **Atomic-ish connect swap** — build indexes/bundle/saver first; publish under lock; rollback on activate failure; close previous client.  
5. **409 idle guard** on connect/disconnect/migrate while generation tasks run.  
6. **Cloud fail-fast** — `Settings` requires `MONGO_URI`/`MONGO_DB`; 403 on mutable storage routes; ops guide clear.  
7. **Migrate design** — table list coverage, JSON→BSON rename, compound `_id`s, unordered bulk upsert, counter seed for progress, SQLite files untouched.  
8. **Client architecture** — boot-before-render, singleton boot promise, cloud write-through queue, password field for URI, cloud read-only UI.  
9. **Mode/API contracts** — camelCase Pydantic aliases match client types.  
10. **Operations.md** — actionable Atlas user/network/migrate/recovery guidance.

---

## Checklist vs `goal.md` Locked Decisions

| # | Decision | Result | Notes |
|---|----------|--------|-------|
| 1 | Approach A repository swap, no dual-write | **PASS** | Facades + bundle swap |
| 2 | Sessions+content+creds+checkpoints in Mongo when cloud | **PASS*** | *Orphan pause / checkpoint versions gaps weaken runtime truth |
| 3 | Mongo URI/DB browser-only (local); deploy env | **PASS** | |
| 4 | Boot POST connect local; cloud env-only | **PASS** | |
| 5 | Migrate one-way upsert; SQLite backup kept | **PASS*** | *Client 10s timeout breaks real migrate (C2) |
| 6 | Disconnect local only | **PASS** | 403 cloud |
| 7 | Plaintext `app_settings` OK | **PASS** | |
| 8 | `DEPLOYMENT_MODE` detection | **PASS** | |
| 9 | PyMongo sync not Motor; MongoDBSaver not AsyncMongoDBSaver | **PASS** | |
| 10 | URI redaction; no server disk URI in local | **PASS** | Memory only |
| 11 | Learning HTTP API compatibility | **PASS*** | Shapes mirrored; not fully proven under Mongo in tests |
| 12 | Test coverage quality | **FAIL** | Presence yes; depth no (H4) |
| 13 | Conventions (headers, named exports, 80-col) | **PASS*** | Headers OK; 80-col uneven; client named exports OK |
| 14 | Bugs/races/cascade/hydrate/cloud fail-fast | **FAIL** | C1, C2, H1, H2, H3 |
| 15 | Plan deviations that hurt correctness | **FAIL** | Orphan pause omitted on cloud; migrate client timeout; hydrate erase risk |

\* = conditional / weakened by issues above.

---

## Required Fixes Before Considering Complete

**Must-fix (gate):**

1. **C1** — Pause orphan jobs after every Mongo connect (cloud startup + local connect).  
2. **C2** — Raise client timeout for migrate (and verify connect timeout ≥ server selection).  
3. **H1** — Stop empty cloud snapshots from wiping non-empty local secrets (merge policy or push-on-connect).  
4. **H2** — Transactional or hardened session delete cascade + stronger tests.  
5. **H3** — Fix or explicitly document checkpoint `new_versions` / prove resume after migrate.  
6. **H4** — Add facade-swap + deeper cascade/job tests (minimum set in H4).  
7. **H5** — Unique index on `quiz_data.node_id`.

**Should-fix soon after:**

- M1 local_data_present probe  
- M7 boot error surfacing  
- M6 Settings footer copy  
- H6 counter gap policy  

**Do not expand scope into:** multi-tenant auth, dual-write, app-level key encryption, Motor migration.

---

## Plan Deviation Notes (correctness-relevant)

| Plan / research | Implementation | Risk |
|-----------------|----------------|------|
| Plan 9 / goal: cloud fail-fast + durable jobs | Cloud connects but skips orphan pause present on SQLite local boot | C1 |
| Plan 8: migrate from UI | Shared 10s Axios timeout | C2 |
| Goal: hydrate for UI continuity | Full replace/merge can erase keys | H1 |
| Research: cascade + optional txn | Multi-delete no txn | H2 |
| Plan 6: public-API checkpoint copy | `new_versions={}` unproven | H3 |
| Testing strategy: parity without live Atlas | Mostly mocks; thin method counts | H4 |

Deviations that are **good**: Motor → PyMongo; hybrid sync Protocols (research A3).

---

## Ship Verdict

| Field | Value |
|-------|--------|
| **Verdict** | **ship-with-fixes** |
| **CRITICAL count** | **2** (C1, C2) |
| **HIGH count** | **6** (H1–H6) |
| **Complete?** | **No** until must-fix list done |
| **Architecture direction** | Sound — keep Approach A |

---

## Top 5 Must-Fix (priority order)

1. Orphan job pause on Mongo connect / cloud startup (**C1**)  
2. Client migrate timeout (**C2**)  
3. Hydration must not blank secrets (**H1**)  
4. Session delete cascade atomicity + tests (**H2**)  
5. Checkpoint migrate versions / resume proof or documented skip (**H3**)  

---

*End of review. Review only — no code fixes applied in this pass.*
