# MongoDB Atlas Storage Phase 4: Checkpointer And Graph Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use `MongoDBSaver` whenever Mongo repositories are active, rebuild
compiled graph on every backend switch, and provide idempotent checkpoint copy
from SQLite through public saver APIs.

**Architecture:** One shared sync PyMongo client serves app repositories and
`MongoDBSaver`; saver async methods use LangGraph's executor bridge. Lifespan
keeps SQLite saver open for fast local fallback. Storage switches are rejected
with 409 while local generation tasks run. Migration reads checkpoint tuples
through `AsyncSqliteSaver.alist()` and writes through `MongoDBSaver.aput()` and
`aput_writes()`, avoiding private binary/document layout coupling.

**Tech Stack:** `langgraph-checkpoint-sqlite==3.1.0`,
`langgraph-checkpoint-mongodb==0.4.0`, `MongoDBSaver`, PyMongo sync client,
`unittest.IsolatedAsyncioTestCase`.

**Source references:** `docs/mongodb-atlas-storage/goal.md` and
`docs/mongodb-atlas-storage/research.md`. Official 0.4.0 source confirms
`MongoDBSaver(client, db_name, "checkpoints", "checkpoint_writes")`, async
`aput`/`aput_writes`/`adelete_thread`, and default `JsonPlusSerializer`.
Follow root `AGENTS.md`; referenced `.planning/codebase/*` files were absent.

**Command note:** For multiline `powershell` blocks, join wrapped lines into one
line and omit display-only trailing `\` characters. `bash` blocks use `\` as
normal shell continuation.

---

## Checkpoint Decision

Checkpoint migration is in scope and feasible without depending on Mongo
collection internals:

1. Open `server/data/checkpoints.db` with current `AsyncSqliteSaver`.
2. Iterate public `CheckpointTuple` values with `alist(None)`.
3. Re-save each tuple using target public `aput`.
4. Group pending writes by `task_id` and call `aput_writes`.
5. Retry safely; both savers key by thread/namespace/checkpoint/task/index.

Do not raw-copy SQLite metadata bytes: MongoDBSaver stores recursively serialized
metadata values, while SQLite stores JSON bytes. Public API conversion is safer.

## Scope And File Map

| File | Responsibility |
|------|----------------|
| `server/database/checkpointer.py` | Saver creation and app-state graph switch |
| `server/database/checkpoint_migration.py` | Public-API checkpoint copy |
| `server/database/storage_mode.py` | Prepare/activate saver with bundle swap |
| `server/graph/build.py` | Explicit graph replacement helper |
| `server/services/generation_runtime.py` | Expose active session IDs |
| `server/routers/storage.py` | 409 guard for active local tasks |
| `server/main.py` | Lifespan SQLite saver ownership/controller binding |
| `server/requirements.txt` | Add Mongo checkpointer package |
| `server/tests/test_checkpointer.py` | Saver/graph switch tests |
| `server/tests/test_checkpoint_migration.py` | Copy/idempotency tests |
| `server/tests/test_storage_router.py` | Busy-switch 409 tests |
| `server/tests/test_graph.py` | Cache replacement tests |

New `.py` files require mandatory `AGENTS.md` header.

## Task 1: Pin And Instantiate MongoDBSaver

**Files:**
- Modify: `server/requirements.txt`
- Create: `server/database/checkpointer.py`
- Create: `server/tests/test_checkpointer.py`

- [ ] **Step 1: Add compatible package pin and install**

Append:

```text
langgraph-checkpoint-mongodb==0.4.0
```

Keep `pymongo[srv]>=4.13,<4.17`, matching package upper bound researched for
0.4.0. Install:

```powershell
server\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
```

Expected: `MongoDBSaver` imports; `AsyncMongoDBSaver` is never imported.

- [ ] **Step 2: Write failing saver factory test**

Create `server/tests/test_checkpointer.py` with mandatory header:

```python
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from server.database.checkpointer import CheckpointerController


class CheckpointerControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sqlite_saver = MagicMock()
        self.app_state = SimpleNamespace()
        self.builder = MagicMock(side_effect=lambda checkpointer: (
            "graph",
            checkpointer,
        ))
        self.controller = CheckpointerController(
            app_state=self.app_state,
            sqlite_saver=self.sqlite_saver,
            graph_builder=self.builder,
        )

    @patch("server.database.checkpointer.MongoDBSaver")
    def test_prepare_mongo_uses_shared_client_and_fixed_collections(
        self,
        saver_type,
    ) -> None:
        client = MagicMock()
        saver = MagicMock()
        saver_type.return_value = saver
        prepared = self.controller.prepare_mongo(client, "a2ui")

        saver_type.assert_called_once_with(
            client,
            db_name="a2ui",
            checkpoint_collection_name="checkpoints",
            writes_collection_name="checkpoint_writes",
        )
        self.assertIs(prepared, saver)

    def test_activate_rebuilds_graph_and_updates_app_state(self) -> None:
        saver = MagicMock()
        self.controller.activate(saver)
        self.assertIs(self.app_state.checkpointer, saver)
        self.assertEqual(self.app_state.course_graph, ("graph", saver))

    def test_activate_sqlite_restores_original_saver(self) -> None:
        self.controller.activate(MagicMock())
        self.controller.activate_sqlite()
        self.assertIs(self.app_state.checkpointer, self.sqlite_saver)
```

- [ ] **Step 3: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_checkpointer -v
```

Expected: FAIL because controller is absent.

- [ ] **Step 4: Implement controller**

Create `server/database/checkpointer.py` with mandatory header:

```python
from __future__ import annotations

from typing import Any, Callable

from langgraph.checkpoint.mongodb import MongoDBSaver


class CheckpointerController:
    """Prepare savers and atomically replace app-state graph bindings."""

    def __init__(
        self,
        *,
        app_state: Any,
        sqlite_saver: Any,
        graph_builder: Callable[[Any], Any],
    ) -> None:
        self._app_state = app_state
        self.sqlite_saver = sqlite_saver
        self._graph_builder = graph_builder
        self.active_saver = sqlite_saver

    def prepare_mongo(self, client: Any, db_name: str) -> MongoDBSaver:
        return MongoDBSaver(
            client,
            db_name=db_name,
            checkpoint_collection_name="checkpoints",
            writes_collection_name="checkpoint_writes",
        )

    def activate(self, saver: Any) -> None:
        graph = self._graph_builder(saver)
        self._app_state.checkpointer = saver
        self._app_state.course_graph = graph
        self.active_saver = saver

    def activate_sqlite(self) -> None:
        self.activate(self.sqlite_saver)
```

Controller does not call `MongoDBSaver.close()`: saver shares app repository
client, and `StorageContext` alone owns closing that client.

- [ ] **Step 5: Run test and verify GREEN**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_checkpointer -v
```

Expected: three tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/requirements.txt server/database/checkpointer.py \
  server/tests/test_checkpointer.py
git commit -m "feat(storage): add MongoDBSaver graph controller"
```

## Task 2: Rebuild Graph During Repository Swap

**Files:**
- Modify: `server/database/storage_mode.py`
- Modify: `server/graph/build.py`
- Modify: `server/main.py`
- Modify: `server/tests/test_checkpointer.py`
- Modify: `server/tests/test_graph.py`

- [ ] **Step 1: Write failing coordinated swap test**

Append to controller/storage tests:

```python
def test_storage_connect_activates_prepared_saver_before_old_close(self) -> None:
    controller = MagicMock()
    mongo_saver = MagicMock()
    controller.prepare_mongo.return_value = mongo_saver
    context = make_context(checkpointer_controller=controller)

    context.connect("mongodb://host", "atlas")

    controller.prepare_mongo.assert_called_once_with(
        self.connection.client,
        "atlas",
    )
    controller.activate.assert_called_once_with(mongo_saver)

def test_storage_disconnect_restores_sqlite_graph(self) -> None:
    controller = MagicMock()
    context = make_context(checkpointer_controller=controller)
    context.connect("mongodb://host", "atlas")
    controller.reset_mock()
    context.disconnect()
    controller.activate_sqlite.assert_called_once_with()
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_checkpointer \
  server.tests.test_storage_mode.StorageContextTests -v
```

Expected: FAIL because context does not coordinate checkpointer.

- [ ] **Step 3: Add explicit graph replacement helper**

In `server/graph/build.py` add:

```python
def replace_graph(app_state: Any, checkpointer: Any) -> Any:
    """Compile and publish graph bound to selected checkpointer."""

    graph = build_graph(checkpointer=checkpointer)
    app_state.checkpointer = checkpointer
    app_state.course_graph = graph
    return graph
```

Add test proving `get_graph` returns replacement, not old cached graph.

- [ ] **Step 4: Coordinate context swap**

Add optional controller setter/property to `StorageContext`. Connect order:

1. Ping candidate.
2. Ensure indexes.
3. Build repository bundle.
4. `prepare_mongo(candidate.client, db_name)`.
5. Under context lock publish candidate/bundle/backend and activate saver.
6. Close previous Mongo client after lock.

If steps 2-4 fail, close candidate and leave old backend. If `activate` raises,
restore old context values before releasing lock, close candidate, and re-raise.

Disconnect order under lock: activate SQLite graph, then publish SQLite bundle
and backend; close old Mongo client after lock.

- [ ] **Step 5: Bind controller in lifespan**

In `server/main.py`, inside existing SQLite saver context:

```python
controller = CheckpointerController(
    app_state=app.state,
    sqlite_saver=checkpointer,
    graph_builder=lambda saver: build_graph(checkpointer=saver),
)
controller.activate_sqlite()
storage_context.set_checkpointer_controller(controller)
```

Before lifespan exits, run `await runtime.shutdown()`, force
`storage_context.disconnect()` only for local mode, and clear controller. Cloud
mode shutdown is finalized in Phase 7.

- [ ] **Step 6: Run graph/controller tests**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_checkpointer \
  server.tests.test_graph \
  server.tests.test_storage_mode -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add server/database/storage_mode.py server/graph/build.py \
  server/main.py server/tests/test_checkpointer.py \
  server/tests/test_graph.py
git commit -m "feat(storage): switch graph checkpointer with backend"
```

## Task 3: Reject Storage Switches During Active Generation

**Files:**
- Modify: `server/services/generation_runtime.py`
- Modify: `server/routers/storage.py`
- Modify: `server/schemas/storage.py`
- Modify: `server/tests/test_generation_runtime.py`
- Modify: `server/tests/test_storage_router.py`

- [ ] **Step 1: Write failing active-session tests**

Add runtime test:

```python
def test_active_session_ids_excludes_finished_tasks(self) -> None:
    active = MagicMock()
    active.done.return_value = False
    finished = MagicMock()
    finished.done.return_value = True
    self.runtime._session_tasks = {"s1": active, "s2": finished}
    self.assertEqual(self.runtime.active_session_ids, ["s1"])
```

Add router test:

```python
def test_connect_returns_409_while_generation_is_active(self) -> None:
    storage = make_storage(DeploymentMode.LOCAL)
    client = make_client(storage, active_session_ids=["s1"])
    response = client.post(
        "/settings/storage/connect",
        json={"uri": "mongodb://host", "dbName": "a2ui"},
    )
    self.assertEqual(response.status_code, 409)
    self.assertEqual(response.json()["detail"]["sessionIds"], ["s1"])
    storage.connect.assert_not_called()
```

Update test app helper to attach
`app.state.generation_runtime.active_session_ids`.

- [ ] **Step 2: Run tests and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_generation_runtime \
  server.tests.test_storage_router -v
```

Expected: FAIL because property/guard is absent.

- [ ] **Step 3: Expose active IDs and add guard**

In runtime:

```python
@property
def active_session_ids(self) -> list[str]:
    """Return sorted sessions with unfinished local tasks."""

    return sorted(
        session_id
        for session_id, task in self._session_tasks.items()
        if not task.done()
    )
```

In storage router, before connect/disconnect/migrate:

```python
def _require_idle(request: Request) -> None:
    runtime = getattr(request.app.state, "generation_runtime", None)
    session_ids = runtime.active_session_ids if runtime is not None else []
    if session_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "storage_switch_requires_idle_jobs",
                "message": (
                    "Cancel or wait for active generation before "
                    "switching storage"
                ),
                "sessionIds": session_ids,
            },
        )
```

Client Phase 6 displays this message and session IDs. Cooperative cancel must
finish before retry; no forced mid-node switch.

- [ ] **Step 4: Run tests and commit**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_generation_runtime \
  server.tests.test_storage_router -v
```

Expected: PASS.

```bash
git add server/services/generation_runtime.py \
  server/routers/storage.py server/tests/test_generation_runtime.py \
  server/tests/test_storage_router.py
git commit -m "feat(storage): block backend switch during generation"
```

## Task 4: Public-API Checkpoint Copy

**Files:**
- Create: `server/database/checkpoint_migration.py`
- Create: `server/tests/test_checkpoint_migration.py`

- [ ] **Step 1: Write failing async copy test**

Create test file with mandatory header:

```python
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from server.database.checkpoint_migration import copy_checkpoints


class FakeSqliteSaver:
    def __init__(self, tuples):
        self.tuples = tuples

    async def alist(self, config):
        for item in self.tuples:
            yield item


class CheckpointMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_copies_checkpoint_and_groups_writes_by_task(self) -> None:
        item = SimpleNamespace(
            config={
                "configurable": {
                    "thread_id": "gen-s1",
                    "checkpoint_ns": "",
                    "checkpoint_id": "cp2",
                }
            },
            checkpoint={"id": "cp2", "v": 1},
            metadata={"step": 2},
            parent_config={
                "configurable": {
                    "thread_id": "gen-s1",
                    "checkpoint_ns": "",
                    "checkpoint_id": "cp1",
                }
            },
            pending_writes=[
                ("task-a", "alpha", 1),
                ("task-a", "beta", 2),
                ("task-b", "gamma", 3),
            ],
        )
        target = SimpleNamespace(
            aput=AsyncMock(),
            aput_writes=AsyncMock(),
        )
        summary = await copy_checkpoints(
            FakeSqliteSaver([item]),
            target,
        )

        write_config = target.aput.call_args.args[0]
        self.assertEqual(
            write_config["configurable"]["checkpoint_id"],
            "cp1",
        )
        self.assertEqual(target.aput_writes.await_count, 2)
        self.assertEqual(summary.checkpoints, 1)
        self.assertEqual(summary.writes, 3)

    async def test_empty_source_is_successful(self) -> None:
        target = SimpleNamespace(
            aput=AsyncMock(),
            aput_writes=AsyncMock(),
        )
        summary = await copy_checkpoints(FakeSqliteSaver([]), target)
        self.assertEqual(summary.checkpoints, 0)
        target.aput.assert_not_awaited()
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_checkpoint_migration -v
```

Expected: FAIL because migration helper is absent.

- [ ] **Step 3: Implement copy through public APIs**

Create `checkpoint_migration.py` with mandatory header:

```python
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CheckpointMigrationSummary:
    checkpoints: int
    writes: int


async def copy_checkpoints(
    source: Any,
    target: Any,
) -> CheckpointMigrationSummary:
    """Copy saver tuples using backend-neutral LangGraph APIs."""

    checkpoint_count = 0
    write_count = 0
    async for item in source.alist(None):
        configurable = item.config["configurable"]
        write_config = {
            "configurable": {
                "thread_id": configurable["thread_id"],
                "checkpoint_ns": configurable.get("checkpoint_ns", ""),
            }
        }
        if item.parent_config is not None:
            parent = item.parent_config["configurable"]
            write_config["configurable"]["checkpoint_id"] = (
                parent["checkpoint_id"]
            )
        await target.aput(
            write_config,
            item.checkpoint,
            item.metadata,
            {},
        )
        checkpoint_count += 1

        by_task: dict[str, list[tuple[str, Any]]] = defaultdict(list)
        for task_id, channel, value in item.pending_writes or []:
            by_task[task_id].append((channel, value))
            write_count += 1
        for task_id, writes in by_task.items():
            await target.aput_writes(item.config, writes, task_id)

    return CheckpointMigrationSummary(
        checkpoints=checkpoint_count,
        writes=write_count,
    )
```

No serializer imports, BSON `Binary`, or direct collection fields belong here.
This remains compatible as long as both savers implement LangGraph public API.

- [ ] **Step 4: Add idempotency test**

Add this target fake and test to `test_checkpoint_migration.py`:

```python
class IdempotentTarget:
    def __init__(self) -> None:
        self.checkpoints: set[tuple[str, str, str]] = set()
        self.writes: set[tuple[str, str, str, str, int]] = set()

    async def aput(self, config, checkpoint, metadata, new_versions):
        values = config["configurable"]
        self.checkpoints.add(
            (
                values["thread_id"],
                values.get("checkpoint_ns", ""),
                checkpoint["id"],
            )
        )

    async def aput_writes(self, config, writes, task_id):
        values = config["configurable"]
        for index, _write in enumerate(writes):
            self.writes.add(
                (
                    values["thread_id"],
                    values.get("checkpoint_ns", ""),
                    values["checkpoint_id"],
                    task_id,
                    index,
                )
            )


class CheckpointMigrationIdempotencyTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_retry_does_not_grow_target_key_sets(self) -> None:
        item = make_checkpoint_tuple()
        target = IdempotentTarget()
        await copy_checkpoints(FakeSqliteSaver([item]), target)
        first_counts = (len(target.checkpoints), len(target.writes))
        await copy_checkpoints(FakeSqliteSaver([item]), target)
        self.assertEqual(
            (len(target.checkpoints), len(target.writes)),
            first_counts,
        )
```

Define `make_checkpoint_tuple()` with same complete `SimpleNamespace` fixture
from Step 1. Source summary counts describe rows processed both times while
target unique keys remain stable.

- [ ] **Step 5: Run tests and commit**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_checkpoint_migration -v
```

Expected: all copy/idempotency tests PASS.

```bash
git add server/database/checkpoint_migration.py \
  server/tests/test_checkpoint_migration.py
git commit -m "feat(storage): copy LangGraph checkpoints to Mongo"
```

## Task 5: Verify Delete And Resume Against Swapped Saver

**Files:**
- Modify: `server/tests/test_generation_recovery.py`
- Modify: `server/tests/test_generation_api.py`
- Modify: `server/tests/test_checkpointer.py`

- [ ] **Step 1: Add Mongo-saver resume/delete contract tests**

Use saver fake implementing `aget_tuple`, `aput`, `aput_writes`, and
`adelete_thread`. Assert:

```python
await checkpointer.adelete_thread("gen-s1")
checkpointer.adelete_thread.assert_awaited_once_with("gen-s1")
```

For recovery, keep existing invariant: runner calls `graph.ainvoke(None, ...)`
with same `gen-{session_id}` after checkpoint copy. Assert copied target's latest
tuple exists before resume.

- [ ] **Step 2: Run recovery and API tests**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_generation_recovery \
  server.tests.test_generation_api \
  server.tests.test_checkpointer -v
```

Expected: PASS. `learning.py` delete endpoint needs no backend branch because
both saver types expose `adelete_thread`.

- [ ] **Step 3: Run full server suite and commit**

```powershell
server\.venv\Scripts\python.exe -m unittest
```

Expected: PASS without Atlas.

```bash
git add server/tests/test_generation_recovery.py \
  server/tests/test_generation_api.py server/tests/test_checkpointer.py
git commit -m "test(storage): verify Mongo checkpoint resume and delete"
```

## Phase 4 Exit Checkpoint

- [ ] `MongoDBSaver`, not deprecated `AsyncMongoDBSaver`, is used.
- [ ] One shared `MongoClient` owns app repositories and saver collections.
- [ ] Graph is rebuilt on connect and disconnect; runtime resolves new graph.
- [ ] Active in-process jobs block storage switch with explicit 409 UX payload.
- [ ] Public-API checkpoint copy preserves parents, metadata, and pending writes.
- [ ] Retry does not duplicate checkpoint/write keys.
- [ ] Add phase note:

```bash
git notes add -m "Phase 4 complete: MongoDBSaver wiring and checkpoint copy"
```
