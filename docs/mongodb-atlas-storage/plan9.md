# MongoDB Atlas Storage Phase 7: Deploy Hardening And Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make cloud deployment Mongo-only and fail-fast, finalize dependency
compatibility/security docs, enforce mode guards, and pass full server/client
quality gates.

**Architecture:** Lifespan branches by `DEPLOYMENT_MODE`. Local owns SQLite saver
and optional runtime Mongo swap; cloud requires environment Mongo config,
connects before serving, builds Mongo repositories plus `MongoDBSaver`, and has
no SQLite fallback control path. Shutdown stops generation before closing shared
client.

**Tech Stack:** FastAPI lifespan, PyMongo sync, MongoDBSaver 0.4.0, unittest,
React/Vitest/ESLint/TypeScript, Atlas operational controls.

**Source references:** `docs/mongodb-atlas-storage/goal.md` and
`docs/mongodb-atlas-storage/research.md`, including cloud mode, security, risks,
and dependency guidance. Follow root `AGENTS.md`; referenced
`.planning/codebase/*` files were absent when planned.

**Command note:** For multiline `powershell` blocks, join wrapped lines into one
line and omit display-only trailing `\` characters. `bash` blocks use `\` as
normal shell continuation.

---

## Scope And File Map

| File | Responsibility |
|------|----------------|
| `server/config.py` | Validate cloud environment requirements |
| `server/main.py` | Local/cloud lifespan branches and shutdown order |
| `server/database/storage_mode.py` | Cloud startup/close lifecycle |
| `server/routers/storage.py` | Final cloud guards and safe status |
| `server/.env.example` | Deployment environment examples |
| `server/requirements.txt` | Final compatible Mongo pins |
| `server/tests/test_cloud_storage_startup.py` | Fail-fast/startup/shutdown tests |
| `server/tests/test_storage_router.py` | 403 matrix and no-secret responses |
| `docs/mongodb-atlas-storage/operations.md` | Atlas setup, migration, recovery |
| `README.md` | Link optional cloud storage docs |

New `.py` files require mandatory `AGENTS.md` header.

## Task 1: Cloud Configuration Validation

**Files:**
- Modify: `server/config.py`
- Create: `server/tests/test_cloud_storage_startup.py`

- [ ] **Step 1: Write failing fail-fast tests**

Create test file with mandatory header:

```python
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from server.config import Settings
from server.database.storage_mode import DeploymentMode


class CloudStorageConfigTests(unittest.TestCase):
    def test_cloud_requires_uri(self) -> None:
        with patch.dict(
            os.environ,
            {"DEPLOYMENT_MODE": "cloud", "MONGO_DB": "a2ui"},
            clear=True,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "DEPLOYMENT_MODE=cloud requires MONGO_URI and MONGO_DB",
            ):
                Settings()

    def test_cloud_requires_database(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEPLOYMENT_MODE": "cloud",
                "MONGO_URI": "mongodb://host",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "requires MONGO_URI"):
                Settings()

    def test_local_does_not_require_mongo_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()
        self.assertEqual(settings.deployment_mode, DeploymentMode.LOCAL)
```

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_cloud_storage_startup.CloudStorageConfigTests -v
```

Expected: cloud missing values do not yet fail in `Settings`.

- [ ] **Step 3: Validate cloud config without logging values**

At end of `Settings.__init__`:

```python
if self.deployment_mode == DeploymentMode.CLOUD:
    if not self.mongo_uri or not self.mongo_db:
        raise RuntimeError(
            "DEPLOYMENT_MODE=cloud requires MONGO_URI and MONGO_DB"
        )
```

Never include missing/present URI value in exception.

- [ ] **Step 4: Run test and commit**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_cloud_storage_startup.CloudStorageConfigTests -v
```

Expected: three tests PASS.

```bash
git add server/config.py server/tests/test_cloud_storage_startup.py
git commit -m "feat(storage): fail fast on incomplete cloud config"
```

## Task 2: Mongo-Only Cloud Lifespan

**Files:**
- Modify: `server/main.py`
- Modify: `server/database/storage_mode.py`
- Modify: `server/database/checkpointer.py`
- Modify: `server/tests/test_cloud_storage_startup.py`

- [ ] **Step 1: Write failing cloud lifecycle test**

Test extracted startup helper, not global app import/reload:

```python
class CloudStorageLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_cloud_connects_before_runtime_creation(self) -> None:
        storage = MagicMock()
        storage.mongo_connection.client = MagicMock()
        storage.connect.side_effect = lambda uri, db_name: setattr(
            storage,
            "active_backend",
            StorageBackend.MONGO,
        )
        app_state = SimpleNamespace()
        runtime_type = MagicMock()

        runtime = await start_cloud_runtime(
            app_state=app_state,
            storage=storage,
            uri="mongodb://host",
            db_name="a2ui",
            runtime_type=runtime_type,
        )

        storage.connect.assert_called_once_with(
            "mongodb://host",
            "a2ui",
        )
        self.assertEqual(storage.active_backend, StorageBackend.MONGO)
        runtime_type.assert_called_once_with(app_state=app_state)
        self.assertIs(runtime, runtime_type.return_value)

    async def test_cloud_startup_failure_does_not_create_runtime(self) -> None:
        storage = MagicMock()
        storage.connect.side_effect = MongoUnavailableError("down")
        runtime_type = MagicMock()
        with self.assertRaisesRegex(RuntimeError, "Cloud MongoDB startup failed"):
            await start_cloud_runtime(
                app_state=SimpleNamespace(),
                storage=storage,
                uri="mongodb://user:secret@host",
                db_name="a2ui",
                runtime_type=runtime_type,
            )
        runtime_type.assert_not_called()
```

Use `MagicMock`, `SimpleNamespace`, and required imports.

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_cloud_storage_startup -v
```

Expected: FAIL because cloud helper/branch is absent.

- [ ] **Step 3: Allow controller without SQLite fallback**

Change `CheckpointerController.sqlite_saver` to optional. `activate_sqlite()`
raises `RuntimeError("SQLite checkpointer is unavailable in cloud mode")` when
none. Cloud never calls it; local behavior/tests remain unchanged.

- [ ] **Step 4: Add explicit close without fallback**

In `StorageContext`:

```python
def close(self) -> None:
    """Close active client without selecting another backend."""

    with self._lock:
        connection = self._mongo
        self._mongo = None
    if connection is not None:
        connection.client.close()
```

`close()` is shutdown-only. Public disconnect still restores SQLite and remains
local-only through router guard.

- [ ] **Step 5: Extract cloud startup and branch lifespan**

In `server/main.py` add testable helper. It may call sync connect through
`run_in_threadpool` to avoid blocking loop:

```python
async def start_cloud_runtime(
    *,
    app_state: Any,
    storage: StorageContext,
    uri: str,
    db_name: str,
    runtime_type: type[GenerationRuntime] = GenerationRuntime,
) -> GenerationRuntime:
    controller = CheckpointerController(
        app_state=app_state,
        sqlite_saver=None,
        graph_builder=lambda saver: build_graph(checkpointer=saver),
    )
    storage.set_checkpointer_controller(controller)
    try:
        await run_in_threadpool(storage.connect, uri, db_name)
    except Exception as exc:
        logger.error(
            "Cloud MongoDB startup failed error=%s",
            type(exc).__name__,
        )
        raise RuntimeError("Cloud MongoDB startup failed") from exc
    app_state.storage = storage
    runtime = runtime_type(app_state=app_state)
    app_state.generation_runtime = runtime
    return runtime
```

Lifespan structure:

```python
if settings.deployment_mode == DeploymentMode.CLOUD:
    runtime = await start_cloud_runtime(
        app_state=app.state,
        storage=storage_context,
        uri=settings.mongo_uri,
        db_name=settings.mongo_db,
    )
    try:
        yield
    finally:
        await runtime.shutdown()
        storage_context.close()
    return

# existing local SQLite initialization + AsyncSqliteSaver context
```

Type narrowing after Settings validation can use a helper returning
`tuple[str, str]`; do not use non-null assertions. Cloud branch must not create
or select SQLite checkpointer. Local branch remains default and initializes
SQLite backup.

- [ ] **Step 6: Test shutdown ordering**

Add test with ordered mock events. Assert `runtime.shutdown` occurs before
`storage.close`, preventing workers from using closed client.

- [ ] **Step 7: Run lifecycle tests and commit**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_cloud_storage_startup \
  server.tests.test_checkpointer \
  server.tests.test_storage_mode -v
```

Expected: PASS.

```bash
git add server/main.py server/database/storage_mode.py \
  server/database/checkpointer.py \
  server/tests/test_cloud_storage_startup.py
git commit -m "feat(storage): run cloud deployments on Mongo only"
```

## Task 3: Final Endpoint Guard And Secret-Leak Matrix

**Files:**
- Modify: `server/routers/storage.py`
- Modify: `server/tests/test_storage_router.py`

- [ ] **Step 1: Add complete guard matrix test**

```python
def test_cloud_mutation_guard_matrix(self) -> None:
    client = make_client(make_connected_cloud_storage())
    cases = (
        ("/settings/storage/connect", {"uri": "mongodb://x", "dbName": "d"}),
        ("/settings/storage/disconnect", None),
        (
            "/settings/storage/migrate",
            {"providerSettings": {}, "webSearchSettings": {}},
        ),
    )
    for path, payload in cases:
        with self.subTest(path=path):
            response = client.post(path, json=payload)
            self.assertEqual(response.status_code, 403)

def test_cloud_app_settings_remain_read_write(self) -> None:
    client = make_client(make_connected_cloud_storage())
    self.assertEqual(
        client.get("/settings/storage/app-settings").status_code,
        200,
    )
    self.assertEqual(
        client.put(
            "/settings/storage/app-settings",
            json={"providerSettings": {}, "webSearchSettings": {}},
        ).status_code,
        200,
    )

def test_status_and_errors_never_return_uri_or_password(self) -> None:
    storage = make_connected_cloud_storage()
    storage.mongo_uri = "mongodb://user:secret@host"
    response = make_client(storage).get("/settings/storage/status")
    body = response.text
    self.assertNotIn("secret", body)
    self.assertNotIn("mongodb://", body)
```

- [ ] **Step 2: Run tests and verify RED if any guard leaks**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_storage_router -v
```

Expected: all locked guards pass after any necessary fixes.

- [ ] **Step 3: Harden exception logging**

Review storage router/context/migration catches. Required pattern:

```python
logger.error(
    "Mongo operation failed operation=%s error=%s",
    operation,
    type(exc).__name__,
)
```

Never interpolate `exc`, request payload, app settings, or URI. Keep user-facing
errors generic plus retry/action guidance.

- [ ] **Step 4: Run tests and commit**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_storage_router \
  server.tests.test_mongo_client -v
```

Expected: PASS.

```bash
git add server/routers/storage.py server/tests/test_storage_router.py
git commit -m "fix(storage): harden cloud guards and secret handling"
```

## Task 4: Final Dependency And Environment Documentation

**Files:**
- Modify: `server/requirements.txt`
- Modify: `server/.env.example`
- Create: `docs/mongodb-atlas-storage/operations.md`
- Modify: `README.md`

- [ ] **Step 1: Reconcile dependency pins against installed metadata**

Final Mongo lines:

```text
pymongo[srv]>=4.13,<4.17
langgraph-checkpoint-mongodb==0.4.0
```

Verify resolver and package integrity:

```powershell
server\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
server\.venv\Scripts\python.exe -m pip check
server\.venv\Scripts\python.exe -c \
  "from langgraph.checkpoint.mongodb import MongoDBSaver; print(MongoDBSaver)"
```

Expected: dependency resolution succeeds; `pip check` reports no broken
requirements; import prints `MongoDBSaver` class.

- [ ] **Step 2: Document environment variables**

Append to `server/.env.example` without real credentials:

```dotenv
# Storage deployment policy: local (default) or cloud
DEPLOYMENT_MODE=local

# Required only when DEPLOYMENT_MODE=cloud
MONGO_URI=mongodb+srv://a2ui_app:<password>@<cluster-host>/?retryWrites=true&w=majority
MONGO_DB=a2ui
```

- [ ] **Step 3: Write operator guide with concrete procedures**

Create `docs/mongodb-atlas-storage/operations.md` containing these complete
sections:

1. Local default: no env, SQLite/localStorage behavior.
2. Atlas provisioning: database user `a2ui_app`, `readWrite` on one DB only.
3. Network Access: dev IP/deploy egress IP; avoid `0.0.0.0/0`.
4. URI password URL encoding and TLS/SRV expectations.
5. Local connect: URI stored in browser, server memory only, last connect wins.
6. Migration: stop/wait active jobs, connect, migrate, retry semantics, counts.
7. Checkpoints: copied through saver APIs; paused/cancelled resumes supported.
8. Disconnect: returns to untouched SQLite backup; Atlas remains unchanged.
9. Cloud deploy: three env vars, startup fail-fast, no disconnect/migrate UI.
10. Plaintext keys: Atlas at-rest encryption/TLS, anyone with URI can read them.
11. Rotation: update browser URI or deployment secret and restart/reconnect.
12. Recovery: retry migration; disconnect to SQLite; never delete backup first.
13. Monitoring: auth failures, connection errors, storage quotas, index creation.
14. Non-goals: multi-tenant auth, dual-write, bidirectional sync, key encryption.

Include API examples using placeholders only:

```bash
curl http://localhost:8000/settings/storage/status
curl -X POST http://localhost:8000/settings/storage/connect \
  -H "Content-Type: application/json" \
  -d '{"uri":"mongodb+srv://<user>:<password>@<host>","dbName":"a2ui"}'
```

Warn command history can retain URI; Settings UI is preferred.

- [ ] **Step 4: Link guide from README**

Add short Optional MongoDB Atlas Storage section linking:

```markdown
Optional cloud persistence is documented in
[`docs/mongodb-atlas-storage/operations.md`](docs/mongodb-atlas-storage/operations.md).
Local SQLite remains default.
```

- [ ] **Step 5: Commit**

```bash
git add server/requirements.txt server/.env.example README.md \
  docs/mongodb-atlas-storage/operations.md
git commit -m "docs(storage): add Atlas deployment and recovery guide"
```

## Task 5: Full Automated Verification

**Files:**
- Modify only files needed to fix failures caused by this feature.

- [ ] **Step 1: Run focused server storage suites**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_storage_mode \
  server.tests.test_mongo_client \
  server.tests.test_storage_schemas \
  server.tests.test_storage_router \
  server.tests.test_repository_contracts \
  server.tests.test_repository_facades \
  server.tests.test_sqlite_repositories \
  server.tests.test_mongo_common \
  server.tests.test_mongo_learning \
  server.tests.test_mongo_jobs \
  server.tests.test_mongo_artifacts \
  server.tests.test_mongo_research \
  server.tests.test_mongo_progress \
  server.tests.test_mongo_settings \
  server.tests.test_checkpointer \
  server.tests.test_checkpoint_migration \
  server.tests.test_migrate_to_mongo \
  server.tests.test_cloud_storage_startup -v
```

Expected: PASS; no Atlas credentials/network required.

- [ ] **Step 2: Run full server suite**

```powershell
server\.venv\Scripts\python.exe -m unittest
```

Expected: all tests PASS. Fix feature regressions only; do not refactor unrelated
failures.

- [ ] **Step 3: Run full client suite, lint, and build**

With workdir `client`:

```powershell
npm run test -- --run
npm run lint
npm run build
```

Expected: Vitest PASS, ESLint PASS, `tsc -b && vite build` PASS.

- [ ] **Step 4: Verify no forbidden stack or secret patterns**

```powershell
git grep -n -E "AsyncIOMotorClient|motor|AsyncMongoDBSaver" -- server client
git grep -n -E \
  "logger\.(info|error|exception).*uri|print\(.*MONGO_URI" \
  -- server
git grep -n -E "mongodb(\+srv)?://[^<[:space:]]+:[^<@]+@" \
  -- ':!docs/**' ':!server/.env.example'
```

Expected: no output and exit status 1. Documentation examples are excluded and
must use placeholders.

- [ ] **Step 5: Verify default local boot manually**

Start without Mongo env:

```powershell
server\.venv\Scripts\python.exe -m uvicorn server.main:app --port 8000
```

Expected status JSON includes `deploymentMode: local`,
`activeBackend: sqlite`, and `connected: false`. Existing course list/create
works unchanged.

- [ ] **Step 6: Optional Atlas smoke test outside CI**

Using a disposable DB and least-privilege user:

1. Connect in Settings.
2. Create course and verify no new rows in local SQLite.
3. Migrate existing local data twice; counts/doc totals remain stable.
4. Cancel a generation, migrate checkpoints, then resume from Mongo.
5. Disconnect; pre-migration SQLite data reappears.
6. Reconnect; Atlas data remains.

Do not run this with production credentials in shared shell history.

- [ ] **Step 7: Commit verification fixes if any**

If verification required code changes, inspect and stage each reported storage
file explicitly; never use `git add .`:

```bash
git status --short
git diff --check
git commit -m "fix(storage): resolve full-suite regressions"
```

Skip commit when no files changed; never create empty commit.

## Final Definition Of Done

- [ ] Local fresh clone behaves exactly as SQLite + localStorage default.
- [ ] Local connect switches all app repositories and graph checkpointer to Mongo.
- [ ] No app-data reads/writes hit SQLite while Mongo is active.
- [ ] Migration copies all domain rows, checkpoints, and credentials idempotently.
- [ ] Disconnect restores untouched SQLite backup and leaves Atlas untouched.
- [ ] Cloud mode serves only after successful env Mongo connection.
- [ ] Cloud connect/disconnect/migrate return 403; app-settings remains usable.
- [ ] URI and app settings never appear in logs or status/error responses.
- [ ] Tests require no live Atlas and new code meets project coverage target.
- [ ] Server/client full suites, lint, build, and `pip check` pass.
- [ ] Add final phase note:

```bash
git notes add -m "Phase 7 complete: cloud hardening, docs, and full verification"
```
