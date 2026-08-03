# MongoDB Atlas Storage Phase 5: Migration And App Settings API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one-way idempotent SQLite-to-Mongo migration for every application
table and LangGraph checkpoint, plus Mongo-backed provider/web-search settings
REST APIs.

**Architecture:** Application rows stream from SQLite in batches of 500 and use
unordered `ReplaceOne(..., upsert=True)` operations. JSON text becomes native
BSON; existing IDs become `_id`; composite keys use deterministic strings.
Checkpoint copy uses Phase 4 public saver APIs. SQLite files remain untouched as
backup and active backend remains Mongo.

**Tech Stack:** stdlib `sqlite3`, PyMongo `ReplaceOne`/`bulk_write`,
`AsyncSqliteSaver`, FastAPI, Pydantic v2, stdlib `unittest`.

**Source references:** `docs/mongodb-atlas-storage/goal.md` and
`docs/mongodb-atlas-storage/research.md`, especially sections 5.4, 5.5, 6,
and 8.2. Follow root `AGENTS.md`; referenced `.planning/codebase/*` files were
absent when planned.

**Command note:** For multiline `powershell` blocks, join wrapped lines into one
line and omit display-only trailing `\` characters. `bash` blocks use `\` as
normal shell continuation.

---

## Scope And File Map

| File | Responsibility |
|------|----------------|
| `server/database/migrate_to_mongo.py` | Row conversion, batching, orchestration |
| `server/schemas/storage.py` | Migrate/settings contracts |
| `server/routers/storage.py` | Migrate and app-settings endpoints |
| `server/tests/test_migrate_to_mongo.py` | Mapping, batching, idempotency |
| `server/tests/test_storage_router.py` | API guards and payloads |

New Python files require mandatory `AGENTS.md` header. Migration must never
delete or alter `a2ui.db` or `checkpoints.db`.

## Task 1: Table Mapping And Row Conversion

**Files:**
- Create: `server/database/migrate_to_mongo.py`
- Create: `server/tests/test_migrate_to_mongo.py`

- [ ] **Step 1: Write failing conversion tests**

Create test file with mandatory header:

```python
from __future__ import annotations

import unittest

from server.database.migrate_to_mongo import (
    MIGRATION_TABLES,
    row_to_document,
)


class MigrationMappingTests(unittest.TestCase):
    def test_table_list_covers_all_application_data(self) -> None:
        self.assertEqual(
            set(MIGRATION_TABLES),
            {
                "learning_sessions",
                "concept_nodes",
                "quiz_data",
                "quiz_attempts",
                "revision_sessions",
                "revision_node_progress",
                "generation_jobs",
                "generation_briefs",
                "node_sources",
                "research_reports",
                "research_sources",
                "research_sections",
                "research_section_sources",
                "research_provider_statuses",
                "progress_events",
            },
        )

    def test_maps_id_and_json_columns_to_native_values(self) -> None:
        document = row_to_document(
            "generation_jobs",
            {
                "id": "j1",
                "cursor_json": '{"next_topic_index": 2}',
                "counts_json": '{"topics_total": 3}',
                "warnings_json": "[]",
                "cancel_requested": 1,
            },
        )
        self.assertEqual(document["_id"], "j1")
        self.assertEqual(document["cursor"]["next_topic_index"], 2)
        self.assertEqual(document["counts"]["topics_total"], 3)
        self.assertEqual(document["warnings"], [])
        self.assertIs(document["cancel_requested"], True)

    def test_maps_composite_join_id_deterministically(self) -> None:
        document = row_to_document(
            "research_section_sources",
            {"section_id": "sec", "source_id": "src"},
        )
        self.assertEqual(document["_id"], "sec::src")

    def test_preserves_invalid_json_as_string_and_warning(self) -> None:
        warnings: list[str] = []
        document = row_to_document(
            "concept_nodes",
            {"id": "n1", "key_terms": "not-json"},
            warnings=warnings,
        )
        self.assertEqual(document["key_terms"], "not-json")
        self.assertEqual(len(warnings), 1)
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_migrate_to_mongo.MigrationMappingTests -v
```

Expected: FAIL because migration module is absent.

- [ ] **Step 3: Define exact migration metadata**

Create `migrate_to_mongo.py` with mandatory header:

```python
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from pymongo import ReplaceOne

MIGRATION_BATCH_SIZE = 500
MIGRATION_TABLES = (
    "learning_sessions",
    "concept_nodes",
    "quiz_data",
    "quiz_attempts",
    "revision_sessions",
    "revision_node_progress",
    "generation_jobs",
    "generation_briefs",
    "node_sources",
    "research_reports",
    "research_sources",
    "research_sections",
    "research_section_sources",
    "research_provider_statuses",
    "progress_events",
)

JSON_COLUMNS = {
    "concept_nodes": {"key_terms": "key_terms"},
    "quiz_data": {"payload": "payload"},
    "generation_jobs": {
        "cursor_json": "cursor",
        "counts_json": "counts",
        "warnings_json": "warnings",
    },
    "generation_briefs": {"payload_json": "payload"},
    "research_reports": {
        "limitations_json": "limitations",
        "warnings_json": "warnings",
    },
    "progress_events": {"payload_json": "payload"},
}

BOOLEAN_COLUMNS = {
    "learning_sessions": {"title_finalized"},
    "concept_nodes": {"retry_available"},
    "generation_jobs": {
        "web_search_requested",
        "cancel_requested",
    },
    "quiz_attempts": {"is_correct"},
}
```

`generation_schema_migrations` is intentionally skipped: it describes SQLite
DDL, not domain data. Mongo indexes are managed by connect.

- [ ] **Step 4: Implement deterministic row conversion**

```python
def row_to_document(
    table: str,
    row: dict[str, Any],
    *,
    warnings: Optional[list[str]] = None,
) -> dict[str, Any]:
    document = dict(row)
    identifier = document.pop("id", None)
    if identifier is not None:
        document["_id"] = identifier
    elif table == "node_sources":
        document["_id"] = (
            f"{document['node_id']}::{document['source_id']}"
        )
    elif table == "research_section_sources":
        document["_id"] = (
            f"{document['section_id']}::{document['source_id']}"
        )
    elif table == "research_provider_statuses":
        document["_id"] = (
            f"{document['report_id']}::{document['provider_id']}"
        )
    else:
        raise ValueError(f"No migration key for table {table}")

    for source, target in JSON_COLUMNS.get(table, {}).items():
        raw = document.pop(source, None)
        if isinstance(raw, str):
            try:
                document[target] = json.loads(raw)
            except json.JSONDecodeError:
                document[target] = raw
                if warnings is not None:
                    warnings.append(
                        f"{table}.{source} kept as invalid JSON string"
                    )
        else:
            document[target] = raw
    if table == "quiz_attempts":
        selected = document.get("selected_option_id")
        if isinstance(selected, str) and selected.startswith("["):
            try:
                document["selected_option_id"] = json.loads(selected)
            except json.JSONDecodeError:
                pass
    for column in BOOLEAN_COLUMNS.get(table, set()):
        if document.get(column) is not None:
            document[column] = bool(document[column])
    return document
```

- [ ] **Step 5: Run conversion tests and commit**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_migrate_to_mongo.MigrationMappingTests -v
```

Expected: PASS.

```bash
git add server/database/migrate_to_mongo.py \
  server/tests/test_migrate_to_mongo.py
git commit -m "feat(storage): define SQLite to Mongo row mapping"
```

## Task 2: Batched Idempotent Upsert

**Files:**
- Modify: `server/database/migrate_to_mongo.py`
- Modify: `server/tests/test_migrate_to_mongo.py`

- [ ] **Step 1: Write failing batch/idempotency tests**

Add a fake collection that records replacement by `_id` and returns a result
with `matched_count`, `upserted_count`, and `modified_count`. Then:

```python
def test_bulk_upsert_is_unordered_and_retry_safe(self) -> None:
    collection = FakeCollection()
    documents = [
        {"_id": "s1", "query": "one"},
        {"_id": "s2", "query": "two"},
    ]
    first = bulk_upsert(collection, documents)
    second = bulk_upsert(collection, documents)

    self.assertEqual(len(collection.documents), 2)
    self.assertEqual(first.upserted_count, 2)
    self.assertEqual(second.matched_count, 2)
    self.assertFalse(collection.ordered_values[0])

def test_iter_batches_uses_500_row_limit(self) -> None:
    batches = list(iter_batches(range(1001)))
    self.assertEqual([len(batch) for batch in batches], [500, 500, 1])
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_migrate_to_mongo -v
```

Expected: FAIL because batching/upsert functions are absent.

- [ ] **Step 3: Implement batch summaries and upsert**

```python
@dataclass(frozen=True)
class CollectionMigrationSummary:
    collection: str
    rows: int
    matched: int
    upserted: int
    modified: int


def iter_batches(
    values: Iterable[Any],
    size: int = MIGRATION_BATCH_SIZE,
) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def bulk_upsert(collection: Any, documents: list[dict[str, Any]]) -> Any:
    operations = [
        ReplaceOne({"_id": item["_id"]}, item, upsert=True)
        for item in documents
    ]
    if not operations:
        return _EmptyBulkResult()
    return collection.bulk_write(operations, ordered=False)
```

Use a private zero-count result class for empty batches. `migrate_table()` must
stream cursor with `fetchmany(500)`, accumulate driver counts, and wrap errors in:

```python
class MigrationError(RuntimeError):
    def __init__(self, collection: str) -> None:
        super().__init__(f"Migration failed for {collection}")
        self.collection = collection
```

Do not include raw driver message or URI in exception detail.

- [ ] **Step 4: Run tests and commit**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_migrate_to_mongo -v
```

Expected: PASS.

```bash
git add server/database/migrate_to_mongo.py \
  server/tests/test_migrate_to_mongo.py
git commit -m "feat(storage): batch idempotent Mongo migration upserts"
```

## Task 3: Full Application And Checkpoint Migration Service

**Files:**
- Modify: `server/database/migrate_to_mongo.py`
- Modify: `server/tests/test_migrate_to_mongo.py`

- [ ] **Step 1: Write failing orchestration test**

Use temporary SQLite DB with all migration table names and one minimal row per
table, fake Mongo DB collections, and fake saver. Assert:

```python
async def test_migrate_all_copies_tables_settings_and_checkpoints(self) -> None:
    summary = await migrate_to_mongo(
        sqlite_path=self.sqlite_path,
        checkpoint_path=self.checkpoint_path,
        database=self.mongo_database,
        mongo_checkpointer=self.mongo_saver,
        app_settings=self.settings_repository,
        provider_settings={"activeProvider": "openrouter"},
        web_search_settings={"masterEnabled": False},
        sqlite_saver_factory=self.sqlite_saver_factory,
    )
    self.assertEqual(
        set(summary.collections),
        set(MIGRATION_TABLES),
    )
    self.assertEqual(summary.checkpoints, 1)
    self.settings_repository.put_provider_settings.\
        assert_called_once()
    self.settings_repository.put_web_search_settings.\
        assert_called_once()
    self.assertTrue(self.sqlite_path.exists())
    self.assertTrue(self.checkpoint_path.exists())
```

Use `IsolatedAsyncioTestCase` and actual temp paths.

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_migrate_to_mongo -v
```

Expected: FAIL because orchestration is absent.

- [ ] **Step 3: Implement full migration**

Add summary:

```python
@dataclass(frozen=True)
class MigrationSummary:
    collections: dict[str, CollectionMigrationSummary]
    checkpoints: int
    checkpoint_writes: int
    warnings: list[str] = field(default_factory=list)
```

Sync table copy helper opens SQLite read-only where possible:

```python
def migrate_application_data(
    sqlite_path: Path,
    database: Any,
) -> tuple[dict[str, CollectionMigrationSummary], list[str]]:
    warnings: list[str] = []
    summaries = {}
    with sqlite3.connect(sqlite_path) as connection:
        connection.row_factory = sqlite3.Row
        for table in MIGRATION_TABLES:
            summaries[table] = migrate_table(
                connection,
                database[table],
                table,
                warnings,
            )
    progress = database["progress_events"].find_one(
        sort=[("_id", -1)]
    )
    maximum = int(progress["_id"]) if progress is not None else 0
    database["storage_counters"].update_one(
        {"_id": "progress_events"},
        {"$max": {"value": maximum}},
        upsert=True,
    )
    return summaries, warnings
```

Async orchestration calls sync part through `run_in_threadpool`, then:

```python
async with sqlite_saver_factory(str(checkpoint_path)) as source:
    checkpoint_summary = await copy_checkpoints(
        source,
        mongo_checkpointer,
    )
```

Use an injectable wrapper around
`AsyncSqliteSaver.from_conn_string` for tests. Write provider and web-search
settings only after table and checkpoint copies succeed. Retain files.

- [ ] **Step 4: Add retry-after-partial-failure test**

Fake one collection to fail first call after earlier collections succeed. Retry
with failure removed. Assert final document counts equal source counts, no
duplicates, checkpoint keys stable, and settings written once on successful run.

- [ ] **Step 5: Run tests and commit**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_migrate_to_mongo -v
```

Expected: all orchestration/idempotency tests PASS.

```bash
git add server/database/migrate_to_mongo.py \
  server/tests/test_migrate_to_mongo.py
git commit -m "feat(storage): migrate app data and checkpoints to Mongo"
```

## Task 4: Migrate And App Settings Schemas

**Files:**
- Modify: `server/schemas/storage.py`
- Modify: `server/tests/test_storage_schemas.py`

- [ ] **Step 1: Write failing schema tests**

```python
def test_migrate_request_accepts_browser_snapshots(self) -> None:
    request = StorageMigrateRequest.model_validate(
        {
            "providerSettings": {"activeProvider": "openrouter"},
            "webSearchSettings": {"masterEnabled": False},
        }
    )
    self.assertEqual(
        request.provider_settings["activeProvider"],
        "openrouter",
    )

def test_app_settings_response_keeps_camel_case(self) -> None:
    response = AppSettingsResponse(
        provider_settings={},
        web_search_settings={},
    )
    payload = response.model_dump(mode="json", by_alias=True)
    self.assertIn("providerSettings", payload)
    self.assertIn("webSearchSettings", payload)
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_storage_schemas -v
```

Expected: FAIL because models are absent.

- [ ] **Step 3: Add contracts**

Update schema typing import first:

```python
from typing import Any, Optional
```

```python
class StorageMigrateRequest(StorageSchema):
    provider_settings: dict[str, Any]
    web_search_settings: dict[str, Any]


class CollectionMigrationResponse(StorageSchema):
    rows: int = Field(ge=0)
    matched: int = Field(ge=0)
    upserted: int = Field(ge=0)
    modified: int = Field(ge=0)


class StorageMigrateResponse(StorageSchema):
    collections: dict[str, CollectionMigrationResponse]
    checkpoints: int = Field(ge=0)
    checkpoint_writes: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)


class AppSettingsResponse(StorageSchema):
    provider_settings: Optional[dict[str, Any]] = None
    web_search_settings: Optional[dict[str, Any]] = None


class AppSettingsUpdate(StorageSchema):
    provider_settings: dict[str, Any]
    web_search_settings: dict[str, Any]
```

Do not log `model_dump()` for these models. Payload contains plaintext secrets.

- [ ] **Step 4: Run tests and commit**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_storage_schemas -v
```

Expected: PASS.

```bash
git add server/schemas/storage.py \
  server/tests/test_storage_schemas.py
git commit -m "feat(storage): define migrate and app settings contracts"
```

## Task 5: Migrate And App Settings Endpoints

**Files:**
- Modify: `server/routers/storage.py`
- Modify: `server/tests/test_storage_router.py`

- [ ] **Step 1: Write failing endpoint tests**

Add tests for:

```python
def test_migrate_requires_local_mode_connected_mongo(self) -> None:
    local = make_storage(DeploymentMode.LOCAL)
    local.active_backend = StorageBackend.SQLITE
    response = make_client(local).post(
        "/settings/storage/migrate",
        json={"providerSettings": {}, "webSearchSettings": {}},
    )
    self.assertEqual(response.status_code, 409)

def test_cloud_migrate_is_forbidden(self) -> None:
    cloud = make_storage(DeploymentMode.CLOUD)
    response = make_client(cloud).post(
        "/settings/storage/migrate",
        json={"providerSettings": {}, "webSearchSettings": {}},
    )
    self.assertEqual(response.status_code, 403)

def test_app_settings_require_mongo_and_round_trip(self) -> None:
    storage = make_connected_storage()
    storage.app_settings.get_provider_settings.return_value = {"a": 1}
    storage.app_settings.get_web_search_settings.return_value = {"b": 2}
    client = make_client(storage)
    response = client.get("/settings/storage/app-settings")
    self.assertEqual(response.json()["providerSettings"], {"a": 1})
    update = client.put(
        "/settings/storage/app-settings",
        json={
            "providerSettings": {"a": 3},
            "webSearchSettings": {"b": 4},
        },
    )
    self.assertEqual(update.status_code, 200)
```

Mock `migrate_to_mongo` as `AsyncMock` and assert request snapshots pass once.

- [ ] **Step 2: Run tests and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_storage_router -v
```

Expected: 404/failing because endpoints are absent.

- [ ] **Step 3: Implement active-Mongo guard and settings endpoints**

```python
def _require_mongo(context: StorageContext) -> None:
    if context.active_backend != StorageBackend.MONGO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MongoDB storage is not active",
        )


@router.get(
    "/app-settings",
    response_model=AppSettingsResponse,
    summary="Read cloud-backed application settings",
)
async def get_app_settings(request: Request) -> AppSettingsResponse:
    context = _storage(request)
    _require_mongo(context)
    provider = await run_in_threadpool(
        context.app_settings.get_provider_settings
    )
    search = await run_in_threadpool(
        context.app_settings.get_web_search_settings
    )
    return AppSettingsResponse(
        provider_settings=provider,
        web_search_settings=search,
    )
```

PUT writes both docs and returns same response. If second write fails, client may
retry full snapshot safely; fixed IDs make update idempotent.

- [ ] **Step 4: Implement migrate endpoint**

Guard order: local deployment -> idle runtime -> active Mongo. Call migration
with `DB_PATH`, `CHECKPOINT_DB_PATH`, current Mongo database, controller active
saver, and app-settings repository. Map `MigrationError` to 500 detail:

```python
detail={
    "code": "storage_migration_failed",
    "collection": exc.collection,
    "message": "Migration can be retried safely",
}
```

Never include driver exception text. Return per-collection counts and warnings.

- [ ] **Step 5: Run all storage/migration tests**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_migrate_to_mongo \
  server.tests.test_storage_schemas \
  server.tests.test_storage_router \
  server.tests.test_checkpoint_migration -v
```

Expected: PASS.

- [ ] **Step 6: Run full server suite and commit**

```powershell
server\.venv\Scripts\python.exe -m unittest
```

Expected: PASS without Atlas.

```bash
git add server/routers/storage.py server/tests/test_storage_router.py
git commit -m "feat(storage): expose migrate and app settings APIs"
```

## Phase 5 Exit Checkpoint

- [ ] All 15 domain tables copy with deterministic `_id` values.
- [ ] `generation_schema_migrations` stays SQLite-only by design.
- [ ] Checkpoints and pending writes copy through public saver APIs.
- [ ] Progress counter advances to at least migrated max event ID.
- [ ] Retry after partial failure produces no duplicate documents.
- [ ] SQLite app/checkpoint files remain present and unchanged.
- [ ] App settings are plaintext, fixed-ID docs and never logged.
- [ ] Add phase note:

```bash
git notes add -m "Phase 5 complete: idempotent migration and app settings API"
```
