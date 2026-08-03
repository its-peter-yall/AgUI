# MongoDB Atlas Storage Phase 3B: Mongo Operational Repositories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Mongo generation-job, artifact, research, progress-event,
and app-settings repositories, ensure all indexes, and atomically swap complete
repository bundles on connect/disconnect.

**Architecture:** Sync PyMongo repositories preserve current Pydantic/domain
contracts. Job locks use atomic compare-and-update, progress cursors use a
counter document, and compound SQLite keys become stable compound string `_id`
values. `StorageContext` builds and validates full bundle before publishing it;
no dual-write occurs.

**Tech Stack:** PyMongo sync API, Pydantic v2, Mongo atomic updates and short
transactions, stdlib `unittest.mock`.

**Source references:** `docs/mongodb-atlas-storage/goal.md` and
`docs/mongodb-atlas-storage/research.md`, especially sections 5.3, 6.2, and
7.3. Follow root `AGENTS.md`; referenced `.planning/codebase/*` files were
absent when planned.

**Command note:** For multiline `powershell` blocks, join wrapped lines into one
line and omit display-only trailing `\` characters. `bash` blocks use `\` as
normal shell continuation.

---

## Scope And File Map

| File | Responsibility |
|------|----------------|
| `server/database/repositories/mongo_jobs.py` | Job lifecycle and locks |
| `server/database/repositories/mongo_artifacts.py` | Outline/brief/content/citations |
| `server/database/repositories/mongo_research.py` | Reports/sources/sections/providers |
| `server/database/repositories/mongo_progress.py` | Monotonic replayable events |
| `server/database/repositories/mongo_settings.py` | Plaintext app settings docs |
| `server/database/repositories/mongo_factory.py` | Build complete bundle |
| `server/database/repositories/mongo_indexes.py` | Operational indexes |
| `server/database/storage_mode.py` | Atomic full-bundle swap |
| `server/tests/test_mongo_jobs.py` | Transition/lock tests |
| `server/tests/test_mongo_artifacts.py` | Durable artifact tests |
| `server/tests/test_mongo_research.py` | Research relationship tests |
| `server/tests/test_mongo_progress.py` | Counter/dedupe/replay tests |
| `server/tests/test_mongo_settings.py` | Settings document tests |
| `server/tests/test_storage_mode.py` | Atomic bundle swap regression |

Every new `.py` file requires mandatory `AGENTS.md` header.

## Task 1: Operational Indexes

**Files:**
- Modify: `server/database/repositories/mongo_indexes.py`
- Modify: `server/tests/test_mongo_common.py`

- [ ] **Step 1: Add failing index assertions**

Append:

```python
from server.database.repositories.mongo_indexes import (
    ensure_operational_indexes,
)

def test_operational_indexes_match_sqlite_uniques(self) -> None:
    database = MagicMock()
    ensure_operational_indexes(database)

    database["generation_jobs"].create_index.assert_has_calls(
        [call([("session_id", 1)], unique=True),
         call([("thread_id", 1)], unique=True)]
    )
    database["research_sources"].create_index.assert_any_call(
        [("session_id", 1), ("canonical_url", 1)],
        unique=True,
    )
    database["progress_events"].create_index.assert_any_call(
        [("session_id", 1), ("dedupe_key", 1)],
        unique=True,
    )
```

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_common -v
```

Expected: FAIL because operational function is absent.

- [ ] **Step 3: Implement exact operational index set**

Add:

```python
def ensure_operational_indexes(database: Any) -> None:
    database["generation_jobs"].create_index(
        [("session_id", 1)], unique=True
    )
    database["generation_jobs"].create_index(
        [("thread_id", 1)], unique=True
    )
    database["generation_briefs"].create_index(
        [("node_id", 1)], unique=True
    )
    database["generation_briefs"].create_index(
        [("session_id", 1), ("topic_index", 1)], unique=True
    )
    database["node_sources"].create_index(
        [("node_id", 1), ("source_id", 1)], unique=True
    )
    database["node_sources"].create_index(
        [("node_id", 1), ("citation_order", 1)], unique=True
    )
    database["research_reports"].create_index(
        [("session_id", 1)], unique=True
    )
    database["research_sources"].create_index(
        [("session_id", 1), ("canonical_url", 1)], unique=True
    )
    database["research_sources"].create_index(
        [("session_id", 1), ("content_hash", 1)], unique=True
    )
    database["research_sections"].create_index(
        [("report_id", 1), ("sequence_index", 1)], unique=True
    )
    database["research_section_sources"].create_index(
        [("section_id", 1), ("source_id", 1)], unique=True
    )
    database["research_provider_statuses"].create_index(
        [("report_id", 1), ("provider_id", 1)], unique=True
    )
    database["progress_events"].create_index(
        [("session_id", 1), ("dedupe_key", 1)], unique=True
    )
    database["progress_events"].create_index(
        [("session_id", 1), ("_id", 1)]
    )
```

Expose `ensure_all_indexes()` calling learning then operational index functions.

- [ ] **Step 4: Run index tests and commit**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_common -v
```

Expected: PASS.

```bash
git add server/database/repositories/mongo_indexes.py \
  server/tests/test_mongo_common.py
git commit -m "feat(storage): add Mongo operational indexes"
```

## Task 2: Generation Job Repository

**Files:**
- Create: `server/database/repositories/mongo_jobs.py`
- Create: `server/tests/test_mongo_jobs.py`

- [ ] **Step 1: Write failing atomic lock and transition tests**

Create test file with mandatory header:

```python
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from pymongo import ReturnDocument

from server.database.repositories.mongo_jobs import (
    MongoGenerationJobRepository,
)
from server.schemas.generation import GenerationStage


class MongoJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = MagicMock()
        self.repository = MongoGenerationJobRepository(self.database)

    def test_try_acquire_lock_uses_expiry_or_owner_predicate(self) -> None:
        jobs = self.database["generation_jobs"]
        jobs.find_one_and_update.return_value = make_job_document(
            lock_owner="worker",
            lock_version=2,
        )
        lock = self.repository.try_acquire_lock(
            session_id="s1",
            owner="worker",
            ttl_seconds=45,
            now=datetime(2026, 8, 3, tzinfo=timezone.utc),
        )
        query = jobs.find_one_and_update.call_args.args[0]
        self.assertIn("$or", query)
        self.assertEqual(
            jobs.find_one_and_update.call_args.kwargs["return_document"],
            ReturnDocument.AFTER,
        )
        self.assertEqual(lock.version, 2)

    def test_transition_requires_current_stage_and_lock_version(self) -> None:
        jobs = self.database["generation_jobs"]
        jobs.find_one.return_value = make_job_document(
            stage="INITIALIZING",
        )
        jobs.find_one_and_update.return_value = make_job_document(
            stage="OUTLINING",
        )
        lock = make_lock(version=3)
        self.repository.transition_stage(
            session_id="s1",
            target_stage=GenerationStage.OUTLINING,
            lock=lock,
        )
        query = jobs.find_one_and_update.call_args.args[0]
        self.assertEqual(query["stage"], "INITIALIZING")
        self.assertEqual(query["lock_version"], 3)
```

Define actual `make_job_document()` and `make_lock()` fixtures using all required
`GenerationJobRecord` fields and ISO strings.

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_jobs -v
```

Expected: FAIL because Mongo job repository is absent.

- [ ] **Step 3: Implement codecs and atomic lock core**

Create `mongo_jobs.py` with mandatory header. Store cursor/counts/warnings as
native BSON and parse with current Pydantic models:

```python
def _record(document: dict[str, Any]) -> GenerationJobRecord:
    return GenerationJobRecord(
        id=document["_id"],
        session_id=document["session_id"],
        thread_id=document["thread_id"],
        stage=document["stage"],
        resume_stage=document.get("resume_stage"),
        web_search_requested=document["web_search_requested"],
        grounding_status=document["grounding_status"],
        cursor=document["cursor"],
        counts=document["counts"],
        warnings=document["warnings"],
        cancel_requested=document["cancel_requested"],
        lock_owner=document.get("lock_owner"),
        lock_version=document["lock_version"],
        lock_expires_at=document.get("lock_expires_at"),
        created_at=document["created_at"],
        updated_at=document["updated_at"],
    )
```

Atomic acquisition:

```python
updated = self._jobs.find_one_and_update(
    {
        "session_id": session_id,
        "$or": [
            {"lock_owner": None},
            {"lock_expires_at": {"$lte": now.isoformat()}},
            {"lock_owner": owner},
        ],
    },
    {
        "$set": {
            "lock_owner": owner,
            "lock_expires_at": expires_at.isoformat(),
            "updated_at": now.isoformat(),
        },
        "$inc": {"lock_version": 1},
    },
    return_document=ReturnDocument.AFTER,
)
```

Return `None` when lock unavailable. `renew_lock` and `release_lock` must filter
on `session_id`, `lock_owner`, and exact `lock_version`; no match raises current
`GenerationLockConflict`.

- [ ] **Step 4: Port complete job method matrix**

Implement every Phase 2 Protocol method with these exact Mongo primitives:

| Method group | Primitive and invariant |
|--------------|-------------------------|
| shell + job | short client transaction; string UUIDs; `thread_id=gen-{session}` |
| reads/public | `find_one`, `$in` batch, Pydantic projection |
| stage/cursor | `find_one_and_update` with stage + lock fence |
| cancel/resume | conditional update preserving/using `resume_stage` |
| orphan pause | `update_many` active stages -> `PAUSED` |
| warning | `$addToSet` native warning payload |
| counts | `$inc` selected `counts.<field>` paths |
| mark failed | clear lock and set `FAILED` |

For shell transaction:

```python
with self._db.client.start_session() as session:
    with session.start_transaction():
        self._db["learning_sessions"].insert_one(
            session_document,
            session=session,
        )
        self._jobs.insert_one(job_document, session=session)
```

Map `DuplicateKeyError` to existing `GenerationArtifactConflict` or
`RepositoryConflictError` as appropriate; never return driver errors to router.

- [ ] **Step 5: Run Mongo and SQLite job tests**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_jobs \
  server.tests.test_generation_jobs \
  server.tests.test_generation_recovery -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add server/database/repositories/mongo_jobs.py \
  server/tests/test_mongo_jobs.py
git commit -m "feat(storage): add Mongo generation job repository"
```

## Task 3: Generation Artifact Repository

**Files:**
- Create: `server/database/repositories/mongo_artifacts.py`
- Create: `server/tests/test_mongo_artifacts.py`

- [ ] **Step 1: Write failing durable artifact tests**

Create test file with mandatory header. Cover deterministic IDs, native brief
payload, citation allowlist, and success update:

```python
def test_persist_outline_upserts_deterministic_nodes(self) -> None:
    outline = make_outline()
    rows = self.repository.persist_outline("s1", outline)
    operations = self.database["concept_nodes"].\
        bulk_write.call_args.args[0]
    self.assertEqual(len(operations), len(outline.topics))
    self.assertEqual(rows[0]["sequence_index"], 0)

def test_upsert_brief_stores_native_payload(self) -> None:
    batch = make_brief_batch()
    self.repository.upsert_brief_batch("s1", batch)
    operation = self.database["generation_briefs"].\
        bulk_write.call_args.args[0][0]
    self.assertIsInstance(operation._doc["$set"]["payload"], dict)

def test_replace_sources_rejects_unapproved_source(self) -> None:
    self.database["concept_nodes"].find_one.return_value = {
        "_id": "n1",
        "learning_session_id": "s1",
    }
    self.database["research_sources"].count_documents.return_value = 0
    with self.assertRaises(UnsupportedCitationError):
        self.repository.replace_node_sources(
            "n1",
            [SourceCitation(source_id="missing", claim="claim")],
        )
```

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_artifacts -v
```

Expected: FAIL because repository is absent.

- [ ] **Step 3: Implement complete artifact port**

Create `mongo_artifacts.py` with mandatory header. Reuse current deterministic
`_node_id_for_topic` algorithm exactly. Use unordered `bulk_write` for outline
and brief upserts:

```python
operations.append(
    UpdateOne(
        {"_id": node_id},
        {
            "$set": {
                "learning_session_id": session_id,
                "sequence_index": topic.index,
                "title": topic.title,
                "summary_for_context": topic.summary_for_context,
                "key_terms": topic.key_terms,
                "complexity": topic.complexity,
                "updated_at": now,
            },
            "$setOnInsert": {
                "content_markdown": "",
                "status": "LOCKED",
                "generation_status": "SKELETON",
                "created_at": now,
            },
        },
        upsert=True,
    )
)
```

Port all methods from `GenerationArtifactRepository`. Exact behavior checklist:

| Method | Required parity |
|--------|-----------------|
| `persist_outline` | update title + deterministic skeleton nodes |
| `upsert_brief_batch` / `persist_briefs` | native payload, unique topic/node |
| `get_brief(s)` | Pydantic `GenerationBrief` |
| topic/outline reads | ordered nodes, derived `quiz_count` |
| adjacent summaries | previous/next by sequence |
| content writes | generation status timestamps and markdown |
| durable check | nonblank markdown + ready generation state |
| citations | validate session source allowlist before replace |
| success/error | update quiz/node/citations consistently |

`persist_topic_success` should use a short transaction because it updates
`quiz_data`, `node_sources`, and `concept_nodes`. Keep transaction under one
topic and never span network/LLM work.

- [ ] **Step 4: Run artifact parity suites**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_artifacts \
  server.tests.test_generation_artifacts \
  server.tests.test_generation_persistence_integration -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/database/repositories/mongo_artifacts.py \
  server/tests/test_mongo_artifacts.py
git commit -m "feat(storage): add Mongo generation artifact repository"
```

## Task 4: Research Repository

**Files:**
- Create: `server/database/repositories/mongo_research.py`
- Create: `server/tests/test_mongo_research.py`

- [ ] **Step 1: Write failing relationship and conflict tests**

Create test file with actual schema fixtures:

```python
def test_create_report_is_idempotent_by_session(self) -> None:
    reports = self.database["research_reports"]
    reports.find_one_and_update.return_value = make_report_document()
    first = self.repository.create_report("s1")
    query = reports.find_one_and_update.call_args.args[0]
    self.assertEqual(query, {"session_id": "s1"})
    self.assertEqual(first.session_id, "s1")

def test_upsert_section_replaces_junction_documents(self) -> None:
    self.database["research_sources"].count_documents.return_value = 2
    self.repository.upsert_section(
        report_id="r1",
        sequence_index=0,
        theme="Theme",
        markdown="Body",
        source_ids=["src1", "src2"],
    )
    self.database["research_section_sources"].delete_many.\
        assert_called_once()
    links = self.database["research_section_sources"].\
        insert_many.call_args.args[0]
    self.assertEqual(
        {link["_id"] for link in links},
        {"section-id::src1", "section-id::src2"},
    )
```

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_research -v
```

Expected: FAIL because repository is absent.

- [ ] **Step 3: Implement report/source/section/provider methods**

Create `mongo_research.py` with mandatory header. Use native arrays for
limitations/warnings. Composite IDs:

```python
def _section_source_id(section_id: str, source_id: str) -> str:
    return f"{section_id}::{source_id}"


def _provider_status_id(report_id: str, provider_id: str) -> str:
    return f"{report_id}::{provider_id}"
```

Use `find_one_and_update(..., upsert=True, return_document=AFTER)` for reports,
sources, sections, and provider status. Validate all section source IDs belong
to report session before replacing junction docs. Port complete Protocol matrix:

```text
create_report, get_report, upsert_source, upsert_section,
set_provider_status, finalize_report, mark_degraded,
get_planner_context, get_report_context, get_sources_by_ids,
get_citations_by_session, get_public_report
```

Preserve `ResearchSourceConflict` for same canonical URL with changed content
hash and `ResearchRelationshipError` for cross-session source links.

- [ ] **Step 4: Run research parity suites**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_research \
  server.tests.test_research_store \
  server.tests.test_research_runner -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/database/repositories/mongo_research.py \
  server/tests/test_mongo_research.py
git commit -m "feat(storage): add Mongo research repository"
```

## Task 5: Progress Event Repository With Monotonic Counter

**Files:**
- Create: `server/database/repositories/mongo_progress.py`
- Create: `server/tests/test_mongo_progress.py`

- [ ] **Step 1: Write failing counter and dedupe tests**

```python
def test_append_allocates_monotonic_integer_id(self) -> None:
    counters = self.database["storage_counters"]
    counters.find_one_and_update.return_value = {
        "_id": "progress_events",
        "value": 42,
    }
    event = self.repository.append_once(
        session_id="s1",
        event_type=ProgressEventType.STAGE_CHANGED,
        payload=make_stage_payload(),
        dedupe_key="stage:1",
    )
    inserted = self.database["progress_events"].\
        insert_one.call_args.args[0]
    self.assertEqual(inserted["_id"], 42)
    self.assertEqual(event.id, 42)

def test_duplicate_equal_payload_returns_existing_event(self) -> None:
    events = self.database["progress_events"]
    events.find_one.return_value = make_event_document()
    events.insert_one.side_effect = DuplicateKeyError("duplicate")
    event = self.repository.append_once(
        session_id="s1",
        event_type=ProgressEventType.STAGE_CHANGED,
        payload=make_stage_payload(),
        dedupe_key="stage:1",
    )
    self.assertEqual(event.id, 1)
```

Create complete fixture imports and mandatory test header.

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_progress -v
```

Expected: FAIL because repository is absent.

- [ ] **Step 3: Implement counter, append, replay, compact**

Create `mongo_progress.py` with mandatory header. Allocate ID atomically:

```python
counter = self._counters.find_one_and_update(
    {"_id": "progress_events"},
    {"$inc": {"value": 1}},
    upsert=True,
    return_document=ReturnDocument.AFTER,
)
event_id = int(counter["value"])
```

`append_once` inserts native payload. On `DuplicateKeyError`, load
`{session_id, dedupe_key}` and compare event type plus canonical native payload;
equal returns existing, mismatch raises existing `ProgressEventConflict`.

Queries:

```python
def list_after(self, session_id: str, after_event_id: int,
               limit: int = 100) -> list[ProgressEvent]:
    safe_limit = max(1, min(limit, 100))
    cursor = self._events.find(
        {"session_id": session_id, "_id": {"$gt": after_event_id}}
    ).sort("_id", 1).limit(safe_limit)
    return [self._event(item) for item in cursor]
```

`latest_id` sorts `_id` descending limit one. `compact_completed` keeps newest N
IDs and deletes older event docs only after generation stage is terminal.

- [ ] **Step 4: Run progress parity suites**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_progress \
  server.tests.test_progress_events \
  server.tests.test_session_events -v
```

Expected: PASS and event IDs remain numeric.

- [ ] **Step 5: Commit**

```bash
git add server/database/repositories/mongo_progress.py \
  server/tests/test_mongo_progress.py
git commit -m "feat(storage): add Mongo progress event repository"
```

## Task 6: Plaintext App Settings Repository

**Files:**
- Create: `server/database/repositories/mongo_settings.py`
- Create: `server/tests/test_mongo_settings.py`

- [ ] **Step 1: Write failing two-document tests**

```python
def test_put_provider_settings_uses_fixed_document_id(self) -> None:
    payload = {"activeProvider": "openrouter", "providers": {}}
    self.repository.put_provider_settings(payload)
    args = self.database["app_settings"].update_one.call_args.args
    self.assertEqual(args[0], {"_id": "provider_settings"})
    self.assertEqual(args[1]["$set"]["payload"], payload)

def test_get_web_search_settings_returns_payload_only(self) -> None:
    self.database["app_settings"].find_one.return_value = {
        "_id": "web_search_settings",
        "payload": {"masterEnabled": False, "providers": {}},
    }
    result = self.repository.get_web_search_settings()
    self.assertEqual(result["masterEnabled"], False)
```

Use full mandatory header and setup.

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_settings -v
```

Expected: FAIL because repository is absent.

- [ ] **Step 3: Implement fixed settings documents**

Create `mongo_settings.py` with mandatory header:

```python
class MongoAppSettingsRepository:
    """Store roaming provider/search settings as plaintext JSON documents."""

    def __init__(self, database: Any) -> None:
        self._settings = database["app_settings"]

    def _get(self, identifier: str) -> Optional[dict[str, Any]]:
        document = self._settings.find_one({"_id": identifier})
        return dict(document["payload"]) if document is not None else None

    def _put(self, identifier: str, payload: dict[str, Any]) -> None:
        self._settings.update_one(
            {"_id": identifier},
            {"$set": {"payload": payload, "updated_at": utc_iso()}},
            upsert=True,
        )

    def get_provider_settings(self) -> Optional[dict[str, Any]]:
        return self._get("provider_settings")

    def put_provider_settings(self, payload: dict[str, Any]) -> None:
        self._put("provider_settings", payload)

    def get_web_search_settings(self) -> Optional[dict[str, Any]]:
        return self._get("web_search_settings")

    def put_web_search_settings(self, payload: dict[str, Any]) -> None:
        self._put("web_search_settings", payload)
```

Never log payload because API keys are plaintext by locked product decision.

- [ ] **Step 4: Run test and commit**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_settings -v
```

Expected: PASS.

```bash
git add server/database/repositories/mongo_settings.py \
  server/tests/test_mongo_settings.py
git commit -m "feat(storage): add Mongo app settings repository"
```

## Task 7: Atomic Repository Swap On Connect And Disconnect

**Files:**
- Create: `server/database/repositories/mongo_factory.py`
- Modify: `server/database/repositories/__init__.py`
- Modify: `server/database/storage_mode.py`
- Modify: `server/tests/test_storage_mode.py`

- [ ] **Step 1: Write failing complete-swap tests**

Append:

```python
def test_connect_publishes_complete_mongo_bundle_atomically(self) -> None:
    mongo_bundle = make_bundle("mongo")
    bundle_factory = MagicMock(return_value=mongo_bundle)
    indexer = MagicMock()
    context = make_context(
        mongo_factory=MagicMock(return_value=self.connection),
        mongo_bundle_factory=bundle_factory,
        mongo_indexer=indexer,
    )

    context.connect("mongodb://host", "atlas")

    indexer.assert_called_once_with(self.connection.database)
    bundle_factory.assert_called_once_with(self.connection.database)
    self.assertIs(context.learning, mongo_bundle.learning)
    self.assertIs(context.jobs, mongo_bundle.jobs)
    self.assertEqual(context.active_backend, StorageBackend.MONGO)

def test_bundle_build_failure_keeps_sqlite_and_closes_candidate(self) -> None:
    context = make_context(
        mongo_factory=MagicMock(return_value=self.connection),
        mongo_bundle_factory=MagicMock(side_effect=RuntimeError("bad")),
    )
    with self.assertRaises(RuntimeError):
        context.connect("mongodb://host", "atlas")
    self.connection.client.close.assert_called_once_with()
    self.assertEqual(context.active_backend, StorageBackend.SQLITE)
    self.assertIs(context.learning, context.sqlite_repositories.learning)
```

Use actual `RepositoryBundle` fixture with six `MagicMock` fields.

- [ ] **Step 2: Run tests and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_storage_mode.StorageContextTests -v
```

Expected: FAIL because bundle factory/indexer are not connected.

- [ ] **Step 3: Finish bundle factory**

Create `mongo_factory.py` with mandatory header and actual imports:

```python
def build_mongo_bundle(database: Any) -> RepositoryBundle:
    return RepositoryBundle(
        learning=MongoLearningRepository(database),
        jobs=MongoGenerationJobRepository(database),
        artifacts=MongoGenerationArtifactRepository(database),
        research=MongoResearchRepository(database),
        progress=MongoProgressEventRepository(database),
        app_settings=MongoAppSettingsRepository(database),
    )
```

Export Mongo classes/factory from repository package.

- [ ] **Step 4: Expand `StorageContext.connect` atomically**

Inject `mongo_bundle_factory=build_mongo_bundle` and
`mongo_indexer=ensure_all_indexes`. Build candidate outside lock; close it on
any failure. Publish connection, bundle, and backend in one lock:

```python
candidate = self._mongo_factory(uri, db_name)
try:
    self._mongo_indexer(candidate.database)
    repositories = self._mongo_bundle_factory(candidate.database)
except Exception:
    candidate.client.close()
    raise
with self._lock:
    previous = self._mongo
    self._mongo = candidate
    self._repositories = repositories
    self.active_backend = StorageBackend.MONGO
if previous is not None:
    previous.client.close()
```

`disconnect()` must restore `_sqlite_repositories` in same lock before closing
old client. Add read-only `sqlite_repositories` property for migration and tests.

- [ ] **Step 5: Run all Phase 3 tests and full server suite**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_common \
  server.tests.test_mongo_learning \
  server.tests.test_mongo_jobs \
  server.tests.test_mongo_artifacts \
  server.tests.test_mongo_research \
  server.tests.test_mongo_progress \
  server.tests.test_mongo_settings \
  server.tests.test_storage_mode -v
server\.venv\Scripts\python.exe -m unittest
```

Expected: PASS; no live Mongo connection.

- [ ] **Step 6: Commit**

```bash
git add server/database/repositories/mongo_factory.py \
  server/database/repositories/__init__.py \
  server/database/storage_mode.py server/tests/test_storage_mode.py
git commit -m "feat(storage): swap complete Mongo repository bundle"
```

## Phase 3B Exit Checkpoint

- [ ] All application collections and unique indexes are represented.
- [ ] Progress event IDs remain monotonic integers via `storage_counters`.
- [ ] Lock mutations fence owner and version atomically.
- [ ] App settings use two plaintext fixed-ID documents and no payload logging.
- [ ] Connect publishes all repositories together; failure preserves old backend.
- [ ] Disconnect restores untouched SQLite adapters; no dual-write exists.
- [ ] Add phase note:

```bash
git notes add -m "Phase 3B complete: all Mongo repositories and atomic swap"
```
