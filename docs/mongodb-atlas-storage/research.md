# Research: Optional MongoDB Atlas Cloud Storage

**Date:** 2026-08-03  
**Scope:** Implementation strategies for Approach A (repository swap) per `goal.md`  
**Status:** Research only — no application code

---

## 1. Executive Summary

A2UI can add optional Atlas storage with a **ports-and-adapters (repository) swap** while keeping local SQLite as the default. The 2026 MongoDB Python stack has shifted: **Motor is deprecated** (EOL 2026-05-14; critical fixes only until 2027-05-14). Official guidance is **PyMongo Async API** (`AsyncMongoClient`) for FastAPI. Goal.md names Motor; Planner should adopt **PyMongo ≥4.13 (stable async)** instead, with Motor only as a short-lived transitional note.

**LangGraph:** Official package `langgraph-checkpoint-mongodb` exists (latest researched: **0.4.0**, 2026-05-12). Prefer `MongoDBSaver` with async methods (`aput`/`aget`/`alist`). Separate class `AsyncMongoDBSaver` is **deprecated** toward removal; do not build new code on it. Checkpoint migration from `AsyncSqliteSaver` / `checkpoints.db` needs a **custom bulk copy** of SQLite checkpoint tables into the Mongo collections the saver owns (or re-run in-flight jobs after migrate — document tradeoff).

**Hardest A2UI gaps:** (1) ~3k-line sync `LearningManager` + generation stores are all **synchronous sqlite3** — Mongo adapters must either stay sync (`MongoClient` + thread pool) or force a large async rewrite of routers/graph nodes; (2) **CASCADE deletes** and multi-table transactions have no free FK cascade in Mongo — must implement application-level cascade; (3) JSON columns (`payload`, `*_json`) become native BSON documents; (4) checkpoint binary blobs + dual checkpointer lifecycle when swapping backends at runtime.

**Recommended path:** Approach A as locked. Use **one `AsyncMongoClient` (or sync `MongoClient` if Protocol stays sync)** held in process memory; repository Protocols wrapping existing managers; idempotent unordered `bulk_write` migrate in ~500–1000 ops/batch; CI with **unittest.mock fakes + optional testcontainers**, not live Atlas. Do **not** dual-write.

---

## 2. Recommended Stack & Versions (2026)

| Component | Recommendation | Notes / source |
|-----------|----------------|----------------|
| Driver | **`pymongo[srv]>=4.13,<5`** | Async API stable since 4.13; 4.15+ common in 2026 docs. Prefer over Motor. |
| Client class | **`pymongo.AsyncMongoClient`** (async path) or **`MongoClient`** (if keeping sync stores) | Official FastAPI tutorial uses Async + lifespan. |
| Motor | **Avoid new code** | Deprecated 2025-05-14; EOL 2026-05-14. Goal.md “Motor” → rewrite to PyMongo Async. |
| LangGraph checkpointer | **`langgraph-checkpoint-mongodb>=0.4.0`** | Pins `pymongo>=4.12,<4.17` (check pin at install time). |
| Checkpointer API | **`MongoDBSaver`** (+ `aput`/`aget`) | `AsyncMongoDBSaver` deprecated. Uses **sync** `MongoClient` in official Atlas docs. |
| Existing SQLite checkpointer | Keep `langgraph-checkpoint-sqlite==3.1.0` + `aiosqlite` | Already in `server/requirements.txt` with `langgraph==1.2.4`. |
| Testing unit | `unittest.mock` Protocol fakes | No Docker; matches current stdlib unittest style. |
| Testing integration (optional) | `testcontainers` + `mongo:7` | Real engine; transactions/indexes. |
| mongomock / mongomock-motor | **Secondary only** | Motor-oriented; incomplete (no multi-doc txns). Deprecating Motor weakens mongomock-motor fit. |
| Atlas | Free/Flex M0-class OK for single-tenant | Network Access IP allowlist + least-privilege DB user. |

**Sources (dates accessed 2026-08-03):**

- MongoDB Motor deprecation: https://www.mongodb.com/docs/drivers/motor/  
- Migrate to PyMongo Async: https://www.mongodb.com/docs/languages/python/pymongo-driver/current/reference/migration/  
- FastAPI + PyMongo: https://www.mongodb.com/docs/languages/python/pymongo-driver/current/integrations/fastapi-integration/  
- Async PyMongo in FastAPI (MongoDB DEV, 2026-04-14): https://dev.to/mongodb/async-pymongo-in-fastapi-p1o  
- langgraph-checkpoint-mongodb PyPI 0.4.0: https://pypi.org/project/langgraph-checkpoint-mongodb/  
- Atlas LangGraph integration: https://www.mongodb.com/docs/atlas/ai-integrations/langgraph/  
- bulkWrite: https://www.mongodb.com/docs/manual/reference/method/db.collection.bulkwrite/  
- Transactions: https://www.mongodb.com/docs/manual/core/transactions/

---

## 3. Architecture Recommendations (Aligned to Approach A)

### 3.1 Target shape (unchanged from goal.md)

```
Client localStorage: mongo uri/db (dev), theme, chat drafts
        │
        ▼ REST
Server StorageContext → active repositories
        ├─ SQLite adapters (wrap LearningManager + focused stores)
        └─ Mongo adapters (PyMongo)
        ▼
  a2ui.db / checkpoints.db     OR     Atlas DB
```

### 3.2 Critical design fork: sync vs async stores

**Current baseline (A2UI):**

- All DB access is **sync** `sqlite3` (`LearningManager`, `GenerationJobStore`, etc.).
- FastAPI routes call stores directly (blocking I/O on event loop today).
- LangGraph uses **`AsyncSqliteSaver`** in `server/main.py` lifespan.

**Options:**

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| **A1 — Sync MongoClient in Mongo adapters** | Protocol methods stay sync; `MongoClient` in thread or call from sync code | Minimal router/graph churn; matches today | Blocks event loop unless `run_in_executor`; two client types if checkpointer needs async |
| **A2 — Async Protocols + AsyncMongoClient** | All repo methods `async def`; rewrite call sites | Aligns with 2026 FastAPI+Mongo guidance | Large blast radius (~routers, graph nodes, services) |
| **A3 — Hybrid** | App data sync `MongoClient`; checkpointer `MongoDBSaver` (sync client + async methods via LangGraph) | Practical for v1 | Two pools to same URI; document carefully |

**Planner recommendation:** **A3 Hybrid for v1** — keep repository Protocols **synchronous** (wrap existing SQLite managers; Mongo adapters use sync `MongoClient`), and use official **`MongoDBSaver(sync MongoClient)`** for graph checkpoints the same way LangGraph docs show. Optionally share one URI, two client instances (sync app + sync checkpointer), or one shared `MongoClient` passed into both. Defer full async repo migration to a later phase.

Rationale: LearningManager is ~3k lines of sync SQL; converting to async in the same feature multiplies risk. Blocking risk already exists with sqlite3.

### 3.3 StorageContext responsibilities

```text
StorageContext
  deployment_mode: local | cloud
  active_backend: sqlite | mongo
  mongo_client: Optional[MongoClient]   # process memory only
  mongo_db_name: Optional[str]
  learning: LearningRepository
  generation_jobs: GenerationJobRepository
  artifacts: GenerationArtifactRepository
  research: ResearchRepository
  progress: ProgressEventRepository
  app_settings: AppSettingsRepository   # mongo-only when active
  checkpointer: BaseCheckpointSaver     # AsyncSqliteSaver | MongoDBSaver
```

**Connect (local):** validate URI → create client → `ping` → build Mongo repos → rebuild/rebind graph checkpointer → set `active_backend=mongo`.

**Disconnect (local):** close client → point repos at SQLite singletons → restore `AsyncSqliteSaver` → clear in-memory URI.

**Cloud deploy:** on lifespan startup require `MONGO_URI`+`MONGO_DB`; fail fast if missing; reject connect/disconnect/migrate with 403.

### 3.4 Module map (confirm goal.md)

| Module | Role |
|--------|------|
| `server/database/storage_mode.py` | Enums, deployment detect, StorageContext |
| `server/database/mongo_client.py` | Client factory, ping, redaction, index ensure |
| `server/database/repositories/` | Protocols + sqlite_ + mongo_ adapters |
| `server/database/migrate_to_mongo.py` | Idempotent bulk copy + app_settings |
| `server/routers/storage.py` | status/connect/disconnect/migrate/app-settings |
| `server/schemas/storage.py` | Pydantic contracts |

Wire routers to **StorageContext getters** (or FastAPI `Depends`) instead of importing module-level `learning_manager` forever. Phase 1 can leave thin facades:

```python
def get_learning_repo() -> LearningRepository:
    return storage_context.learning
```

---

## 4. Library Comparison Tables

### 4.1 Async Mongo drivers (2026)

| Library | Status | FastAPI fit | Use for A2UI? |
|---------|--------|-------------|----------------|
| **PyMongo Async** (`AsyncMongoClient`) | **Recommended**, stable ≥4.13 | Official tutorial + lifespan | **Yes** if Protocols go async |
| **PyMongo sync** (`MongoClient`) | Fully supported | OK if work stays sync / executor | **Yes for v1 hybrid** |
| **Motor** (`AsyncIOMotorClient`) | Deprecated → EOL May 2026 | Legacy blogs | **No** for new code |

### 4.2 LangGraph checkpoint backends

| Backend | Package | Async entry | Notes |
|---------|---------|-------------|-------|
| SQLite (current) | `langgraph-checkpoint-sqlite` | `AsyncSqliteSaver.from_conn_string` | Used in `server/main.py` |
| MongoDB | `langgraph-checkpoint-mongodb` | `MongoDBSaver` + `aput`/`aget` | Official Atlas path ≥0.4.0 |
| MongoDB legacy async class | same | `AsyncMongoDBSaver` | **Deprecated**; avoid |
| Custom collections | none | DIY | Only if saver API insufficient |

### 4.3 Test doubles

| Tool | Real Mongo? | Async | Transactions | CI friction | Verdict |
|------|-------------|-------|--------------|-------------|---------|
| **unittest.mock / Protocol fakes** | No | N/A | N/A | None | **Primary** for unit + mode guards |
| **mongomock** | Fake | Sync | No | Low | OK for simple CRUD shape tests |
| **mongomock-motor** | Fake | Motor API | No | Low | Avoid if not using Motor |
| **testcontainers MongoDbContainer** | Yes | Any driver | Yes | Needs Docker | Optional integration job |
| Live Atlas | Yes | Any | Yes | Secrets + flaky net | **Never required in CI** |

---

## 5. Code Snippets

### 5.1 Client lifecycle (PyMongo Async — cloud / optional async path)

Official FastAPI pattern (adapted):

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pymongo import AsyncMongoClient
from pymongo.server_api import ServerApi
import logging
import re

logger = logging.getLogger(__name__)

_CRED_RE = re.compile(
    r"(mongodb(?:\+srv)?://)([^:/?#]+):([^@]+)@",
    re.IGNORECASE,
)

def redact_mongo_uri(uri: str) -> str:
    """Never log credentials. Safe on malformed input."""
    return _CRED_RE.sub(r"\1\2:***@", uri)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # cloud mode only at startup; local mode may connect later via POST
    uri = os.environ.get("MONGO_URI")
    if deployment_mode == "cloud":
        if not uri or not os.environ.get("MONGO_DB"):
            raise RuntimeError("DEPLOYMENT_MODE=cloud requires MONGO_URI and MONGO_DB")
        client = AsyncMongoClient(
            uri,
            server_api=ServerApi("1"),
            serverSelectionTimeoutMS=5000,
            maxPoolSize=50,
            minPoolSize=0,
            maxConnecting=2,
        )
        app.state.mongo_client = client
        app.state.mongo_db = client[os.environ["MONGO_DB"]]
        ping = await app.state.mongo_db.command("ping")
        if int(ping.get("ok", 0)) != 1:
            raise RuntimeError("Mongo ping failed")
        logger.info("Mongo connected db=%s uri=%s", os.environ["MONGO_DB"], redact_mongo_uri(uri))
    try:
        yield
    finally:
        client = getattr(app.state, "mongo_client", None)
        if client is not None:
            await client.close()
```

### 5.2 Sync client lifecycle (recommended v1 hybrid)

```python
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ConfigurationError, ServerSelectionTimeoutError

def connect_mongo_sync(uri: str, db_name: str, *, timeout_ms: int = 5000) -> tuple[MongoClient, Any]:
    client = MongoClient(
        uri,
        serverSelectionTimeoutMS=timeout_ms,
        maxPoolSize=50,
        minPoolSize=0,
        retryWrites=True,
        w="majority",
    )
    try:
        client.admin.command("ping")
    except (ConnectionFailure, ServerSelectionTimeoutError, ConfigurationError) as exc:
        client.close()
        raise
    return client, client[db_name]


def disconnect_mongo_sync(client: MongoClient | None) -> None:
    if client is not None:
        client.close()
```

**Pooling / `mongodb+srv` notes:**

- SRV resolves seed list via DNS; TLS on by default for `+srv`.
- Constructor returns quickly; **first operation / explicit ping** surfaces auth and network errors — always ping on Connect.
- Defaults: `maxPoolSize=100`, `maxConnecting=2`, `serverSelectionTimeoutMS=30000`. For single-tenant A2UI, **50 / 2 / 5000** is enough and fails faster in UI.
- Cold start: first SRV + TLS handshake can be multi-second; Connect endpoint should use 5–10s timeout and map to 503.
- One client per process; do not create per-request clients.

### 5.3 Repository Protocol sketch

```python
from typing import Protocol, Optional, Any
from typing_extensions import runtime_checkable

@runtime_checkable
class LearningRepository(Protocol):
    def create_learning_session(
        self,
        query: str,
        course_title: str,
        user_id: Optional[str] = None,
        mode: str = "auto",
        resolved_mode: Optional[str] = None,
    ) -> dict[str, Any]: ...

    def get_learning_session(self, session_id: str) -> Optional[dict[str, Any]]: ...
    def get_session_progress(self, session_id: str) -> Optional[dict[str, Any]]: ...
    def get_sessions_list(
        self, *, limit: int = 50, offset: int = 0, user_id: Optional[str] = None
    ) -> tuple[list[dict[str, Any]], int]: ...
    def update_session_resolved_mode(self, session_id: str, resolved_mode: str) -> bool: ...
    def delete_learning_session(self, session_id: str) -> bool: ...

    def create_concept_node(self, **kwargs: Any) -> dict[str, Any]: ...
    def get_concept_node(self, node_id: str) -> Optional[dict[str, Any]]: ...
    def get_session_nodes(self, session_id: str) -> list[dict[str, Any]]: ...
    def update_node_status(self, node_id: str, status: str, **kwargs: Any) -> dict[str, Any]: ...
    def update_node_content(self, node_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def replace_node_content(self, node_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def get_next_node(self, session_id: str, current_node_id: str) -> Optional[dict[str, Any]]: ...
    def update_last_active_node(self, session_id: str, node_id: str) -> bool: ...

    def create_quiz_set(self, node_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def get_quiz_set_for_node(self, node_id: str) -> Optional[dict[str, Any]]: ...
    def get_quiz_for_node(self, node_id: str) -> Any: ...
    def update_quiz_shuffle_seed(self, node_id: str, shuffle_seed: str) -> bool: ...
    def update_quiz_set_progress(self, node_id: str, **kwargs: Any) -> Any: ...
    def decrement_quiz_set_progress(self, node_id: str) -> Any: ...
    def create_quiz_attempt(self, node_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def get_quiz_attempts(self, node_id: str) -> dict[str, Any]: ...
    def check_mastery(self, node_id: str) -> bool: ...

    def create_revision_session(self, session_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def get_revisions_for_session(self, session_id: str, **kwargs: Any) -> tuple[list, int]: ...
    def get_revision_session(self, revision_id: str) -> Optional[dict[str, Any]]: ...
    def delete_revision_session(self, revision_id: str) -> bool: ...
    def mark_revision_node_reviewed(self, revision_id: str, node_id: str) -> dict[str, Any]: ...
    def submit_revision_quiz(self, revision_id: str, **kwargs: Any) -> dict[str, Any]: ...
    def get_revision_summary(self, revision_id: str) -> dict[str, Any]: ...


class SqliteLearningRepository:
    """Thin adapter: delegates to existing LearningManager."""
    def __init__(self, manager: LearningManager) -> None:
        self._m = manager
    def get_learning_session(self, session_id: str) -> Optional[dict[str, Any]]:
        return self._m.get_learning_session(session_id)
    # ... one-liner delegates for every Protocol method


class MongoLearningRepository:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._sessions = db["learning_sessions"]
        self._nodes = db["concept_nodes"]
        # ...
    def delete_learning_session(self, session_id: str) -> bool:
        # Application-level cascade (Mongo has no ON DELETE CASCADE)
        node_ids = [d["_id"] for d in self._nodes.find(
            {"learning_session_id": session_id}, {"_id": 1}
        )]
        if node_ids:
            self._db["quiz_attempts"].delete_many({"node_id": {"$in": node_ids}})
            self._db["quiz_data"].delete_many({"node_id": {"$in": node_ids}})
            self._db["generation_briefs"].delete_many({"node_id": {"$in": node_ids}})
            self._db["node_sources"].delete_many({"node_id": {"$in": node_ids}})
            self._nodes.delete_many({"_id": {"$in": node_ids}})
        rev_ids = [d["_id"] for d in self._db["revision_sessions"].find(
            {"original_session_id": session_id}, {"_id": 1}
        )]
        if rev_ids:
            self._db["quiz_attempts"].delete_many(
                {"revision_session_id": {"$in": rev_ids}}
            )
            self._db["revision_node_progress"].delete_many(
                {"revision_session_id": {"$in": rev_ids}}
            )
            self._db["revision_sessions"].delete_many({"_id": {"$in": rev_ids}})
        # generation_jobs, research_*, progress_events by session_id
        self._db["generation_jobs"].delete_many({"session_id": session_id})
        self._db["progress_events"].delete_many({"session_id": session_id})
        # research cascade by session → report → sections ...
        ...
        result = self._sessions.delete_one({"_id": session_id})
        return result.deleted_count > 0
```

**FastAPI DI:**

```python
from fastapi import Depends, Request

def get_storage(request: Request) -> StorageContext:
    return request.app.state.storage

def get_learning(storage: StorageContext = Depends(get_storage)) -> LearningRepository:
    return storage.learning
```

### 5.4 Bulk migrate (idempotent upsert)

```python
from pymongo import ReplaceOne, UpdateOne
from pymongo.collection import Collection

BATCH = 500  # start here; tune 200–1000 for Atlas free tier


def row_to_doc(table: str, row: dict) -> dict:
    doc = dict(row)
    pk = doc.pop("id", None)
    if pk is not None:
        doc["_id"] = pk
    # Parse JSON text columns into BSON
    for key in list(doc):
        if key.endswith("_json") or key in {"payload", "key_terms"}:
            raw = doc[key]
            if isinstance(raw, str) and raw:
                try:
                    doc[key] = json.loads(raw)
                except json.JSONDecodeError:
                    pass  # keep string; warn
    # SQLite INTEGER booleans → bool optional
    return doc


def bulk_upsert(coll: Collection, docs: list[dict], *, ordered: bool = False) -> dict:
    ops = [
        ReplaceOne({"_id": d["_id"]}, d, upsert=True)
        for d in docs
        if "_id" in d
    ]
    if not ops:
        return {"matched": 0, "upserted": 0, "modified": 0}
    result = coll.bulk_write(ops, ordered=ordered)
    return {
        "matched": result.matched_count,
        "upserted": result.upserted_count,
        "modified": result.modified_count,
    }


def migrate_table(sqlite_conn, coll: Collection, table: str) -> dict:
    cur = sqlite_conn.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cur.description]
    batch: list[dict] = []
    total = 0
    counts = {"matched": 0, "upserted": 0, "modified": 0}
    while True:
        rows = cur.fetchmany(BATCH)
        if not rows:
            break
        docs = [row_to_doc(table, dict(zip(cols, r))) for r in rows]
        # progress_events: AUTOINCREMENT id — use int _id
        part = bulk_upsert(coll, docs, ordered=False)
        for k in counts:
            counts[k] += part[k]
        total += len(docs)
    return {"table": table, "rows": total, **counts}
```

**Ordered vs unordered:**

- Migrate table copies: **`ordered=False`** (independent upserts; faster; retry-safe).
- Do **not** wrap entire multi-collection migrate in one multi-doc transaction (60s limit, oplog size, Atlas free constraints). Per-collection batches + upsert idempotency match goal.md “retry safe”.
- Parent-before-child **ordering across collections** is not required for upsert-by-id migrate (no FK enforcement in Mongo). Runtime writes still enforce app-level integrity.

**Composite PK tables** (`research_section_sources`, `research_provider_statuses`, `node_sources`):

```python
doc["_id"] = f"{section_id}::{source_id}"  # or {"section_id": ..., "source_id": ...} as _id object
```

Prefer string compound `_id` for simpler ReplaceOne filters.

### 5.5 LangGraph checkpointer wiring

**Current (`server/main.py`):**

```python
async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB_PATH)) as checkpointer:
    app.state.checkpointer = checkpointer
    app.state.course_graph = build_graph(checkpointer=checkpointer)
```

**Mongo (official 0.4.x pattern):**

```python
from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

client = MongoClient(uri)  # sync
checkpointer = MongoDBSaver(
    client,
    db_name=db_name,
    # default collection names — confirm in installed package:
    # often checkpoints / checkpoint_writes (or *_aio historically)
)
# setup indexes if required by version
graph = build_graph(checkpointer=checkpointer)
```

**Runtime swap complexity:** `get_graph(app_state)` caches `course_graph`. On connect/disconnect **must**:

1. Close old checkpointer context if owned.
2. Build new checkpointer.
3. `app.state.course_graph = build_graph(checkpointer=...)` (invalidate cache).
4. Ensure `GenerationRuntime` picks up new graph/checkpointer.

**Migrate checkpoints from SQLite:**

`AsyncSqliteSaver` stores tables roughly `checkpoints` and `checkpoint_writes` (serde blobs). Options:

1. **Preferred for parity:** Read SQLite checkpoint rows; write into the exact collection schema `MongoDBSaver` expects (inspect package source / `_setup` indexes). Store binary channel values as `Binary` / BSON binary.
2. **Simpler product choice:** Migrate app data only; **do not migrate in-flight graph checkpoints** — mark orphaned generation jobs paused (already done at startup) and require Resume to re-derive from durable artifacts. Document that mid-generation threads may not resume across migrate.

Planner should pick (2) unless research spike proves (1) cheap — checkpoint serde formats differ across checkpointer implementations.

### 5.6 URI redaction helper (mandatory)

```python
def redact_mongo_uri(uri: str) -> str:
    if not uri:
        return uri
    # user:pass@ → user:***@
    redacted = re.sub(
        r"(mongodb(?:\+srv)?://)([^:/?#]+):([^@]+)@",
        r"\1\2:***@",
        uri,
        flags=re.I,
    )
    return redacted
```

Use in: connect logs, exception messages, status payloads (never return full URI to other clients), any Sentry/error middleware.

---

## 6. Mapping: SQLite Tables → Mongo Collections + Index Plan

Use existing string PKs as `_id`. Keep 1:1 collection names for migrate parity.

### 6.1 Learning

| SQLite table | Mongo collection | `_id` | Indexes |
|--------------|------------------|-------|---------|
| `learning_sessions` | `learning_sessions` | `id` | `user_id`; `updated_at` desc (list) |
| `concept_nodes` | `concept_nodes` | `id` | `learning_session_id`; **unique** `(learning_session_id, sequence_index)` |
| `quiz_data` | `quiz_data` | `id` | `node_id` (unique if 1:1 in practice — verify) |
| `quiz_attempts` | `quiz_attempts` | `id` | `node_id`; `(node_id, attempt_number)`; `revision_session_id` |
| `revision_sessions` | `revision_sessions` | `id` | `original_session_id` |
| `revision_node_progress` | `revision_node_progress` | `id` | `revision_session_id`; unique `(revision_session_id, node_id)` if enforced in app |

**JSON-ish columns → BSON:**

- `concept_nodes.key_terms` (TEXT JSON) → array/object  
- `quiz_data.payload` → document  
- Keep `content_markdown` as string (can be large; consider GridFS only if >16MB — unlikely for v1)

### 6.2 Generation / research / progress

| SQLite table | Mongo collection | `_id` | Unique / indexes |
|--------------|------------------|-------|------------------|
| `generation_jobs` | `generation_jobs` | `id` | **unique** `session_id`; **unique** `thread_id` |
| `generation_briefs` | `generation_briefs` | `id` | **unique** `node_id`; **unique** `(session_id, topic_index)` |
| `node_sources` | `node_sources` | compound | **unique** `(node_id, source_id)`; **unique** `(node_id, citation_order)` |
| `research_reports` | `research_reports` | `id` | **unique** `session_id` |
| `research_sources` | `research_sources` | `id` | **unique** `(session_id, canonical_url)`; **unique** `(session_id, content_hash)` |
| `research_sections` | `research_sections` | `id` | **unique** `(report_id, sequence_index)` |
| `research_section_sources` | `research_section_sources` | compound | PK `(section_id, source_id)` |
| `research_provider_statuses` | `research_provider_statuses` | compound | PK `(report_id, provider_id)` |
| `progress_events` | `progress_events` | int or str | **unique** `(session_id, dedupe_key)`; index `session_id` + `_id` for replay |
| `generation_schema_migrations` | skip or `schema_meta` | — | App version doc only |

### 6.3 Checkpoints

| SQLite (`checkpoints.db`) | Mongo | Notes |
|---------------------------|-------|-------|
| checkpointer internal tables | collections owned by `MongoDBSaver` (names version-specific) | Prefer let package create indexes via setup |
| — | optional mirror `checkpoints` / `checkpoint_writes` if custom | Binary payloads as `BinData` |

### 6.4 App settings (new)

```text
app_settings
  _id: "provider_settings" | "web_search_settings"
  payload: { ... plaintext keys ... }
  updated_at: ISO8601
```

### 6.5 Index ensure on connect

Run idempotent `create_index` once after successful ping (cache flag on StorageContext). Do not require Atlas UI admin work for v1.

---

## 7. Existing A2UI Reuse — Protocol Surface & Parity Gaps

### 7.1 Concrete store classes to wrap

| Class | File | Role |
|-------|------|------|
| `LearningManager` | `learning_persistence.py` | Sessions, nodes, quizzes, revisions (~3k LOC) |
| `GenerationJobStore` | `generation_jobs.py` | Job lifecycle, locks, stages |
| `GenerationArtifactStore` | `generation_artifacts.py` | Outline, briefs, content, citations links |
| `ResearchStore` | `research_store.py` | Reports, sources, sections |
| `ProgressEventStore` | `progress_events.py` | Replayable events + dedupe |
| `initialize_generation_schema` | `generation_migrations.py` | SQLite-only DDL |
| Checkpointer | `main.py` + `graph/build.py` | `AsyncSqliteSaver` / path `server/data/checkpoints.db` |
| Client settings | `providerSettings.ts` | localStorage keys `ai_provider_settings`, `web_search_settings` |

Module singletons in `server/database/__init__.py` become **SQLite adapter defaults** behind StorageContext.

### 7.2 Methods that must appear on Protocols

**LearningRepository** — public methods used by routers/graph (non-exhaustive but required):

- Session: `create_learning_session`, `get_learning_session`, `get_session_progress`, `get_sessions_list`, `update_session_resolved_mode`, `delete_learning_session`, `update_last_active_node` (+ any `update_learning_session` used in graph)
- Nodes: `create_concept_node`, `get_concept_node`, `get_session_nodes`, `update_node_status`, `update_node_content`, `replace_node_content`, `get_next_node`
- Quiz: `create_quiz_set`, `get_quiz_set_for_node`, `get_quiz_for_node`, `update_quiz_shuffle_seed`, `update_quiz_set_progress`, `decrement_quiz_set_progress`, `create_quiz_attempt`, `get_quiz_attempts`, `check_mastery`
- Revision: `create_revision_session`, `get_revisions_for_session`, `get_revision_session`, `delete_revision_session`, `mark_revision_node_reviewed`, `submit_revision_quiz`, `get_revision_summary`

**GenerationJobRepository:**  
`create_session_shell_and_job`, `get_by_session`, `to_public`, `to_public_by_session`, `get_public_by_sessions`, `transition_stage`, `update_cursor`, `request_cancel`, `is_cancel_requested`, `mark_paused`, `mark_cancelled`, `prepare_resume`, `try_acquire_lock`, `renew_lock`, `release_lock`, `mark_orphaned_jobs_paused`, `update_stage`, `update_progress`, `mark_failed`

**GenerationArtifactRepository:**  
`persist_outline`, `upsert_brief_batch` / `persist_briefs`, `get_brief(s)`, `get_topic`, `count_topics`, `get_outline`, `get_adjacent_summaries`, `node_id_for_topic`, `persist_generated_content`, `has_durable_content`, `persist_content_with_citations`, `persist_topic_success`, `persist_topic_error`, `replace_node_sources`, `list_node_sources`, `get_citations_by_session`

**ResearchRepository:** public get/persist methods used by graph + learning router (`get_public_report`, `get_report_context`, `get_planner_context`, `get_sources_by_ids`, `get_citations_by_session`, …)

**ProgressEventRepository:** `append_once`, `latest_id`, `compact_completed`, list/replay helpers used by SSE

**AppSettingsRepository (new):** `get_provider_settings`, `put_provider_settings`, `get_web_search_settings`, `put_web_search_settings`

**Init:** SQLite path keeps `init_learning_tables` + `initialize_generation_schema`. Mongo path runs `ensure_indexes()` instead.

### 7.3 Hardest parity gaps

| Gap | SQLite behavior | Mongo strategy |
|-----|-----------------|----------------|
| **CASCADE FK** | `ON DELETE CASCADE` + manual multi-delete in `delete_learning_session` | Always **application cascade** in repository; optional multi-doc txn for delete (Atlas replica set required — Atlas provides this) |
| **Multi-statement transactions** | `BEGIN IMMEDIATE` in `sqlite_utils` / job+artifact writes | Prefer **single-document atomicity**; use transactions only for lock+stage or shell+job creates; keep txn short |
| **Optimistic locks** | `lock_owner` / `lock_version` / `lock_expires_at` on jobs | `find_one_and_update` with version predicate (atomic) — good Mongo fit |
| **JSON TEXT columns** | `json.loads` / `canonical_json` | Store native dict/list; serializers at boundary |
| **AUTOINCREMENT** `progress_events.id` | Integer replay cursor | Use int `_id` from SQLite on migrate; new events: `ObjectId` **or** counter — **prefer keep monotonic int via counter doc** if clients depend on numeric `latest_id` |
| **Unique constraints** | SQL UNIQUE | Unique indexes; handle `DuplicateKeyError` → domain errors |
| **Checkpoints** | Separate `checkpoints.db` + AsyncSqliteSaver | MongoDBSaver collections; migrate optional |
| **Graph cache** | Singleton on app.state | Invalidate on backend swap |
| **Sync call sites** | Everywhere | Keep sync MongoClient v1 |
| **No settings API** | Client-only localStorage | New REST + `app_settings` when mongo active |

### 7.4 Client reuse

- Pattern for new `mongoStorageSettings.ts`: mirror `providerSettings.ts` (get/set/clear, safe parse).
- `StorageSettingsPanel` mounts like `WebSearchSettingsPanel` in `SettingsPage.tsx`.
- Boot: after React app load, `GET status` → conditional `POST connect` → `GET app-settings` hydrate into existing `setProviderSettings` / `setWebSearchSettings`.

---

## 8. Testing Strategy

### 8.1 Layers

1. **Unit (no Mongo):**  
   - `redact_mongo_uri`  
   - `DEPLOYMENT_MODE` parsing  
   - StorageContext connect/disconnect swap with mock repos  
   - Mode guards (403 cloud) via FastAPI `TestClient`  
   - Migrate pure functions: `row_to_doc`, batching, upsert op construction  

2. **Repository parity (fake DB):**  
   - In-memory fake implementing Protocol  
   - Or mongomock **if** sync API used  
   - Critical paths: create session, update node, save quiz, list sessions, delete cascade order  

3. **Optional integration:**  
   - testcontainers `mongo:7` job (nightly / marked)  
   - Real unique index + txn behavior  

4. **Client:**  
   - StorageSettingsPanel local vs cloud rendering  
   - Boot connect-once  
   - Migrate button enablement  

5. **CI rule:** default pipeline **must not** need Atlas credentials or network to `mongodb.net`.

### 8.2 Migrate idempotency test

```text
seed sqlite → migrate → count docs
migrate again → same counts, no duplicates
corrupt mid-table → retry completes via upsert
```

### 8.3 What not to use as primary

- Live Atlas in PR CI  
- mongomock-motor if stack is PyMongo not Motor  
- Assuming mongomock supports transactions / all aggregation

---

## 9. Security

### 9.1 Threat model: client POST URI once at boot

| Threat | Severity | Mitigation |
|--------|----------|------------|
| XSS steals URI from localStorage | High | Same as API keys today; CSP, no dangerous HTML; document risk |
| Malicious page calls connect API if CORS open | High | Keep tight `CORS_ORIGINS`; credentials mode already limited |
| URI logged on server | High | **Redact always**; never write URI to disk in local mode |
| URI in crash dumps / exception `str(exc)` | Medium | Catch driver errors; log redacted + error class only |
| MITM on connect POST | Medium | HTTPS in deploy; local dev localhost |
| Stolen Atlas URI = full DB access | High | Atlas IP allowlist; least-privilege user; rotate password |
| Server process memory dump | Medium | Accept for v1 single-tenant; cloud uses env secrets |

**Accept (product-locked):** browser holds Atlas URI in local dev — same trust model as OpenRouter keys.

### 9.2 Plaintext API keys in `app_settings`

| Mitigation (v1, no full encryption) | Notes |
|-------------------------------------|-------|
| Atlas encryption at rest | Default on Atlas |
| TLS in transit | `mongodb+srv` default |
| DB user read/write only on app DB | Not Atlas admin |
| Network Access allowlist | Dev IP + deploy IP only |
| No URI/keys in logs or status API | Mask keys in any debug endpoint |
| Optional: separate Atlas project per deploy | Ops doc |
| Document “anyone with URI reads keys” | README security section |
| Future: envelope encryption with local KEK | Out of scope v1 |

### 9.3 Atlas Network Access + DB users (single-tenant)

**Recommended ops defaults:**

1. Create database user `a2ui_app` with **readWrite** on database `a2ui` only (not `admin`).  
2. Network Access:  
   - Dev: current IP / temporary  
   - Deploy: host egress IP or Atlas Private Link if available  
   - Avoid `0.0.0.0/0` except short-lived personal experiments  
3. Connection string: least privileges; password URL-encoded.  
4. Rotate password → user updates localStorage URI / deploy secret.  
5. Enable Atlas alerts on auth failures.

---

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Motor in goal.md is EOL | Build on dead stack | Use PyMongo; update goal wording in plan |
| AsyncMongoDBSaver deprecated | Dead end | Use `MongoDBSaver` |
| Full async rewrite of stores | Scope explosion | Sync Protocols + MongoClient v1 |
| CASCADE parity bugs | Orphan docs / broken UI | Centralize cascade helper; parity tests |
| progress_events ID type change | Replay cursor breaks | Preserve integer ids on migrate; define new-id strategy |
| Checkpointer swap mid-request | Corrupt generation | Reject connect/disconnect while job running OR pause jobs first |
| Large markdown / research docs near 16MB | Write fails | Pre-check size; rare for courses |
| Atlas free tier CPU/IO throttle | Slow migrate | Small batches; backoff; progress UI |
| Dual client pools | Connection limits | Share one `MongoClient` for app+checkpointer |
| Blocking ping on event loop | Latency spike | Short timeout; optional executor |
| Partial migrate without txn | Inconsistent cloud | Upsert idempotent + report per-collection errors; allow retry |
| In-flight checkpoint not portable | Resume fails after migrate | Pause jobs; prefer artifact-based resume; optional skip checkpoint migrate |
| LearningManager god-class | Mongo port incomplete | Phase Mongo repos by domain; Protocol completeness checklist |

---

## 11. Explicit Recommendations for the Planner

### Adopt

1. **Approach A** repository swap; single active backend; no dual-write.  
2. **`pymongo[srv]>=4.13`** (+ pin compatible with `langgraph-checkpoint-mongodb`). **Do not add Motor.**  
3. **Sync `MongoClient` + sync Protocols** wrapping existing managers for v1; FastAPI DI via StorageContext.  
4. **`langgraph-checkpoint-mongodb` `MongoDBSaver`** for cloud/local-mongo graph state; rebuild graph on swap.  
5. **Collections 1:1 with tables**; string `_id` = SQLite `id`; unique indexes matching SQL.  
6. **Migrate:** unordered `bulk_write` ReplaceOne upsert, batch **500**, JSON columns → BSON, compound `_id` for junction tables; **no** multi-collection mega-transaction.  
7. **Application-level cascade** for deletes (mirror `delete_learning_session` + generation FKs).  
8. **URI redaction** helper on all logs; URI never on disk in local mode.  
9. **CI:** mock/fakes primary; optional testcontainers; never require live Atlas.  
10. **Cloud mode:** fail startup without env; 403 on connect/disconnect/migrate.  
11. **Job locks** via `find_one_and_update` version checks (natural Mongo win).  
12. **app_settings** two docs for provider + web-search; hydrate client after connect.

### Avoid

1. Motor / mongomock-motor as primary stack.  
2. New code on deprecated `AsyncMongoDBSaver`.  
3. Dual-write or bidirectional sync.  
4. Per-request Mongo clients.  
5. Logging raw URIs or full `app_settings` in info logs.  
6. Rewriting all of LearningManager to async inside this feature.  
7. Relying on Mongo FK cascade (does not exist).  
8. One giant multi-doc transaction for full migrate.  
9. Embedding URI in every API call (goal already forbids).  
10. Migrating theme / concept-chat drafts.  
11. Application-level key encryption scope creep in v1.  
12. Assuming checkpoint binary format is trivial to copy without a spike.

### Suggested implementation phase tweaks (vs goal.md preview)

| Phase | Goal.md | Research tweak |
|-------|---------|----------------|
| 1 | Motor client | **PyMongo client** + redaction + status/connect/disconnect |
| 2 | Protocols + SQLite adapters | Same; define Protocols from **router/graph call graph** not full private methods |
| 3 | Mongo learning + generation | Port high-traffic methods first; cascade helper shared |
| 4 | Checkpoint Mongo | Spike: migrate vs skip in-flight checkpoints; wire MongoDBSaver |
| 5 | Migrate + app_settings | Unordered bulk upsert; skip schema_migrations table |
| 6 | Client UI + boot | Same |
| 7 | Deploy mode + hardening | Atlas ops doc (network + user) |

### Open questions for planning (non-blocking if defaults taken)

1. **Checkpoint migrate vs skip?** Default recommendation: **skip binary checkpoint migrate**; pause jobs; resume from artifacts.  
2. **progress_events `_id` strategy** after migrate for new rows? Default: **IntegerCounters** collection or keep using migrated max(id)+1.  
3. **Share one MongoClient** between app repos and MongoDBSaver? Default: **yes**.  
4. **Connect while generation running?** Default: **403/409 until idle or force-pause**.  
5. **Pin exact pymongo version** after resolving `langgraph-checkpoint-mongodb` upper bound (`<4.17` on 0.4.0 — verify at impl time).

---

## 12. Sources (URLs)

### MongoDB / PyMongo / Motor

- https://www.mongodb.com/docs/drivers/motor/  
- https://www.mongodb.com/docs/languages/python/pymongo-driver/current/reference/migration/  
- https://www.mongodb.com/docs/languages/python/pymongo-driver/current/integrations/fastapi-integration/  
- https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/mongoclient/  
- https://pymongo.readthedocs.io/en/stable/api/pymongo/asynchronous/mongo_client.html  
- https://pymongo.readthedocs.io/en/stable/changelog.html  
- https://dev.to/mongodb/async-pymongo-in-fastapi-p1o  

### LangGraph / checkpoints

- https://pypi.org/project/langgraph-checkpoint-mongodb/  
- https://www.mongodb.com/docs/atlas/ai-integrations/langgraph/  
- https://langchain-mongodb.readthedocs.io/en/stable/langgraph_checkpoint_mongodb/aio/langgraph.checkpoint.mongodb.aio.AsyncMongoDBSaver.html  
- https://github.com/langchain-ai/langchain-mongodb/issues/285  
- https://github.com/langchain-ai/langgraph/issues/6506  

### Bulk write / transactions

- https://www.mongodb.com/docs/manual/core/bulk-write-operations/  
- https://www.mongodb.com/docs/manual/reference/method/db.collection.bulkwrite/  
- https://www.mongodb.com/docs/manual/core/transactions/  
- https://oneuptime.com/blog/post/2026-03-31-mongodb-how-to-choose-between-ordered-and-unordered-bulk-operations/view  
- https://oneuptime.com/blog/post/2026-03-31-mongodb-bulk-operations-with-transactions/view  

### Testing

- https://github.com/michaelkryukov/mongomock_motor  
- https://pypi.org/project/mongomock-motor/  
- https://testcontainers-python.readthedocs.io/en/testcontainers-v4.2.0/modules/mongodb/README.html  
- https://qaskills.sh/blog/testcontainers-python-pytest-integration-guide  
- https://helpmetest.com/blog/mongodb-testing-mongomock/  

### Security / URI

- https://www.mongodb.com/docs/manual/reference/connection-string/  
- https://oneuptime.com/blog/post/2026-03-31-mongodb-secure-connection-strings/view  
- https://github.com/mongodb/mongo-ruby-driver/pull/3039 (redaction pattern reference)

### A2UI baseline (local)

- `docs/mongodb-atlas-storage/goal.md`  
- `server/database/*`  
- `server/graph/build.py`, `server/main.py`, `server/config.py`, `server/requirements.txt`  
- `client/src/lib/providerSettings.ts`, `client/src/features/settings/*`

---

## 13. Appendix — Current dependency baseline

From `server/requirements.txt` (as of research):

```
langgraph==1.2.4
langgraph-checkpoint-sqlite==3.1.0
aiosqlite==0.22.1
```

**Add (planned):**

```
pymongo[srv]>=4.13,<4.17   # reconcile with langgraph-checkpoint-mongodb pin
langgraph-checkpoint-mongodb>=0.4.0
```

**Do not add:** `motor` (unless temporary spike only).

---

*End of research document.*
