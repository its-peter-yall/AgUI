# Goal: MongoDB Atlas Cloud Storage

## Original Objective

Session and learning data currently live in local SQLite. API credentials and
provider settings live in the browser's localStorage. This feature adds an
optional MongoDB Atlas backend so both datasets can live in the cloud.

Users configure only the MongoDB connection URL and database name in Settings;
those two values stay in browser storage. Everything else (learning data,
generation state, checkpoints, provider/web-search API credentials) is stored
in Atlas when cloud mode is active.

This is an optional path for developers who clone the project:

1. **Full local setup** — SQLite + localStorage (today's default).
2. **Cloud setup** — connect Atlas, optionally click **Migrate** to copy local
   data into Atlas, then run against cloud.

Deployed (production) environments have a single option: cloud setup via server
environment variables. No local SQLite option in that mode.

## Why

- Local SQLite and browser storage do not survive machine switches or reinstalls.
- Devs who want a shared/persistent backend need a zero-ops cloud database.
- Atlas free tier fits a single-tenant dev/deploy profile without introducing
  multi-tenant auth complexity.
- Keeping Mongo URL/DB name client-side (local dev) preserves the existing
  "secrets in the browser" product pattern already used for LLM API keys.

## Locked Product Decisions

1. **Approach A — Repository swap.** Store interfaces with SQLite and Mongo
   implementations. Runtime selects active backend. No dual-write.
2. **Data in Mongo when cloud active:**
   - All current SQLite application data (sessions, concept nodes + markdown,
     quizzes, attempts, revisions, generation jobs/briefs, research, progress
     events).
   - LangGraph checkpoints (`checkpoints.db` contents).
   - Provider settings and web-search settings (API keys plaintext in an
     `app_settings` document — same trust model as localStorage today).
3. **Data that stays browser-only:**
   - MongoDB URI and database name (local dev).
   - Theme preference.
   - Ephemeral concept-chat draft cache (optional local convenience; not part
     of migrate).
4. **Connection model (local dev):** On app boot, if URI+DB saved, client
   `POST`s them once to the server. Server holds `AsyncIOMotorClient` in
   process memory. URI is not sent on every subsequent API call and is never
   written to server disk.
5. **Connection model (deploy):** `DEPLOYMENT_MODE=cloud` plus `MONGO_URI` and
   `MONGO_DB` env vars. Server connects at startup. Client connect POST is
   rejected (403). Settings UI is read-only cloud status.
6. **Deployment detection:** Server env `DEPLOYMENT_MODE` = `local` | `cloud`
   (default `local` if unset). Exposed to client via
   `GET /settings/storage/status`.
7. **Single active Mongo target per server process.** No multi-tenant mapping
   of many browser URLs to many connections. Last successful connect wins in
   local dev; deploy uses env only.
8. **Migrate:** One-way copy SQLite → Mongo (upsert by existing IDs), including
   checkpoints, then push browser provider/web-search settings into
   `app_settings`. Switch remains on Mongo. Local SQLite files are **not**
   deleted (backup).
9. **Disconnect (local dev only):** Drop in-memory Mongo client, revert stores
   to SQLite. Atlas data remains. Local SQLite backup remains. Cloud deploy
   cannot disconnect (403 + no UI).
10. **API keys in Mongo:** Plaintext JSON document. No application-level
    encryption in v1.
11. **Source of truth when `mode=mongo`:** Mongo `app_settings` for
    provider/web-search config. After connect, client fetches and hydrates
    localStorage for UI continuity.
12. **Source of truth when `mode=local`:** localStorage for credentials; SQLite
    for session data (unchanged).
13. **Idempotent migrate:** Safe to retry after partial failure (upsert).
14. **No bidirectional sync. No continuous dual-write.**

## Current State (baseline)

### Server (SQLite)

- `server/database/persistence.py` — `DB_PATH` → `server/data/a2ui.db`
- `server/database/learning_persistence.py` — `LearningManager` (~3k lines)
- `server/database/generation_jobs.py`, `generation_artifacts.py`,
  `research_store.py`, `progress_events.py`, `generation_migrations.py`
- `server/database/sqlite_utils.py` — connection + transaction helpers
- LangGraph checkpointer: `server/graph/build.py` → `server/data/checkpoints.db`
- ~18 tables in `a2ui.db` plus checkpoint tables

### Client (localStorage)

| Key | Content |
|-----|---------|
| `ai_provider_settings` | Provider API keys, models, thinking config |
| `web_search_settings` | Web search master flag + provider keys |
| `agui-theme` | Theme |
| `concept_chat_*` | Per-node chat drafts (1h TTL) |

Settings UI: `client/src/features/settings/SettingsPage.tsx` and panels.
No settings REST API today. No cloud storage abstraction exists.

### Gaps

- No server-side settings store
- No storage mode / backend swap
- No env-based deployment mode
- No migrate path

## Target Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Client                                                      │
│  localStorage: mongo uri/db (dev), theme, chat cache        │
│  Boot → GET status → optional POST connect                  │
│  Settings → StorageSettingsPanel                            │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST
┌──────────────────────────▼──────────────────────────────────┐
│ Server                                                      │
│  DEPLOYMENT_MODE + optional MONGO_URI/MONGO_DB              │
│  StorageContext → active repositories                       │
│       ├─ SQLite adapters (existing managers/stores)         │
│       └─ Mongo adapters (Motor)                             │
│  Routers unchanged at HTTP contract level where possible    │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
        a2ui.db /                 MongoDB Atlas
        checkpoints.db            (collections ≈ tables)
```

### Server modules (new)

| Module | Responsibility |
|--------|----------------|
| `server/database/storage_mode.py` | Mode enum, deployment detect, active backend, connect/disconnect |
| `server/database/mongo_client.py` | Motor factory, ping, db handle, URI redaction for logs |
| `server/database/repositories/` | Protocols + SQLite adapters + Mongo adapters |
| `server/database/migrate_to_mongo.py` | One-way idempotent copy + app_settings write |
| `server/routers/storage.py` | status, connect, disconnect, migrate, get/put app settings |
| `server/schemas/storage.py` | Request/response models |

### Mongo collections

Mirror SQLite tables 1:1 initially (predictable migrate, parity testing):

- `learning_sessions`, `concept_nodes`, `quiz_data`, `quiz_attempts`
- `revision_sessions`, `revision_node_progress`
- `generation_jobs`, `generation_briefs`, `node_sources`
- `research_reports`, `research_sources`, `research_sections`
- `research_section_sources`, `research_provider_statuses`
- `progress_events`
- `checkpoints`, `checkpoint_writes` (binary checkpoint payloads as BinData)
- `app_settings` — documents for provider + web-search config

Use existing string IDs as `_id` where tables already use string primary keys.
Preserve UNIQUE and lookup indexes equivalent to SQLite constraints.

### Client modules (new/changed)

| Module | Responsibility |
|--------|----------------|
| `lib/mongoStorageSettings.ts` | Read/write `{ uri, dbName }` in localStorage |
| `lib/storageApi.ts` | status / connect / disconnect / migrate / app settings |
| `features/settings/StorageSettingsPanel.tsx` | UI section |
| `SettingsPage.tsx` | Mount new section |
| App boot (`main.tsx` / `App.tsx`) | Connect-on-load when URI present and mode allows |

### Settings UI behavior

**Local dev (`deploymentMode=local`):**

- Inputs: MongoDB URI, Database name
- Actions: Save, Test/Connect, Disconnect, Migrate
- Status badge: `Local SQLite` | `Connected (Atlas)`
- Migrate enabled only when connected to Mongo and local SQLite has data
- Footer copy explains URI stays in browser; data lives in Atlas when connected

**Cloud deploy (`deploymentMode=cloud`):**

- Read-only status: Cloud storage (MongoDB), connected/degraded
- No URI fields, no Migrate, no Disconnect

## API Contract (draft)

### `GET /settings/storage/status`

```json
{
  "deploymentMode": "local",
  "activeBackend": "sqlite",
  "connected": false,
  "mongoDbName": null,
  "canConnect": true,
  "canDisconnect": false,
  "canMigrate": false,
  "localDataPresent": true
}
```

### `POST /settings/storage/connect` (local only)

Request: `{ "uri": "mongodb+srv://...", "dbName": "a2ui" }`  
Success: status payload with `activeBackend: "mongo"`.  
Errors: 400 invalid, 403 cloud mode, 503 unreachable.

### `POST /settings/storage/disconnect` (local only)

Reverts to SQLite. 403 in cloud mode.

### `POST /settings/storage/migrate` (local only, requires mongo connected)

Request body includes current browser settings snapshot:

```json
{
  "providerSettings": { },
  "webSearchSettings": { }
}
```

Response: per-collection row counts + warnings. Idempotent upsert.

### `GET /settings/storage/app-settings` / `PUT /settings/storage/app-settings`

Available when `activeBackend=mongo`. Reads/writes `app_settings` docs.
Used after connect to hydrate client; used when user saves provider keys while
on Mongo so cloud remains source of truth.

## Data Flows

### Boot (local, URI saved)

1. `GET /settings/storage/status`
2. `POST /settings/storage/connect` with saved URI/DB
3. On success `GET /settings/storage/app-settings` → hydrate localStorage
4. App continues; all learning APIs hit Mongo-backed repos

### Migrate

1. User connected to Atlas
2. Clicks Migrate
3. Client sends provider + web-search snapshots
4. Server copies every SQLite table/checkpoint into Mongo (batched upsert)
5. Writes `app_settings`
6. Returns summary; backend stays Mongo; SQLite files retained

### Disconnect

1. `POST /settings/storage/disconnect`
2. Server closes Motor client, points StorageContext at SQLite
3. UI shows local mode; Atlas unchanged

## Error Handling

| Case | Behavior |
|------|----------|
| Invalid URI / auth failure | 400, remain SQLite, UI error |
| Network timeout to Atlas | 503/504, remain SQLite |
| Migrate partial failure | Abort with collection+error; retry safe (upsert) |
| Cloud mode missing `MONGO_URI` | Fail startup with clear log message |
| Connect/disconnect/migrate in cloud | 403 |
| URI logging | Always redact credentials |

## Security Notes

- Mongo URI only on connect endpoint; not persisted server-side in local mode.
- Plaintext API keys in Mongo `app_settings` (explicit v1 tradeoff).
- Single-tenant assumption: one logical user/data set per deployment or dev
  machine.
- Atlas network access list and DB user permissions are operator
  responsibilities (document in ops notes).

## Testing Strategy

- Unit: deployment mode parsing, URI redaction, storage context swap.
- Unit: migrate idempotency with mocked Motor / mongomock-style fakes.
- Unit: Mongo repository parity for critical LearningManager operations
  (create session, update node, save quiz, list sessions).
- API tests: status/connect/disconnect/migrate status codes and mode guards.
- Client tests: StorageSettingsPanel local vs cloud rendering; boot connect
  once; migrate button enablement rules.
- CI must not require a live Atlas cluster.

## Success Criteria

1. Fresh clone defaults to full local SQLite + localStorage behavior (no regen).
2. Dev can paste Atlas URI + DB name, Connect, and create/load courses from
   Atlas with no SQLite reads/writes while connected.
3. Migrate copies existing local courses, quizzes, generation state, research,
   checkpoints, and credentials into Atlas; retry does not duplicate rows.
4. Disconnect returns dev to local SQLite data that existed pre-migrate backup.
5. `DEPLOYMENT_MODE=cloud` with env Mongo config starts server on Atlas only;
   Settings shows read-only cloud status.
6. Existing learning HTTP API shapes remain backward compatible for the client.
7. Tests cover mode guards and migrate idempotency without live Atlas.

## Out of Scope (v1)

- Multi-tenant auth / per-user Mongo databases
- Bidirectional or continuous sync
- Application-level encryption of API keys
- Migrating theme or concept-chat draft cache
- Changing LLM key-per-request header pattern for generate endpoints
  (keys may still be sent from client for generate calls; cloud settings are
  for persistence/roaming, not necessarily removing headers in v1)
- Admin UI for Atlas index management

## Implementation Phases (preview for planning)

1. **Storage mode + Mongo client + status/connect/disconnect API**
2. **Repository protocols + SQLite adapters (wrap existing stores)**
3. **Mongo repositories for learning + generation/research/progress**
4. **Checkpoint store in Mongo + graph wiring**
5. **Migrate job + app_settings sync**
6. **Client Settings UI + boot connect + hydrate settings**
7. **Deploy mode (env), docs, hardening, full test pass**

## Open Questions for Research

1. Best Motor / PyMongo patterns in 2026 for FastAPI async apps.
2. LangGraph MongoDB checkpointer availability vs custom checkpoint
   collections.
3. Efficient bulk migrate (ordered bulk_write batch sizes, transaction
   session usage on Atlas).
4. Connection pooling and cold-start behavior with `mongodb+srv`.
5. Whether mongomock / motor mocks are still the right CI approach.

## References

- Existing stores under `server/database/`
- Client settings: `client/src/lib/providerSettings.ts`,
  `client/src/features/settings/`
- Prior MAW doc style: `docs/internet-grounded-course-generation/goal.md`
