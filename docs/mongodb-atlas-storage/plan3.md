# MongoDB Atlas Storage Phase 2B: Repository Facades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every production persistence call through stable dynamic
facades backed by one process-wide `StorageContext`, while preserving existing
module-local names and test patch targets.

**Architecture:** A storage registry constructs current SQLite stores once,
wraps them in Phase 2A adapters, and owns process `StorageContext`. Facades
resolve repository on every call, so later atomic bundle swaps affect routers,
graph nodes, detached workers, and services without re-importing modules.

**Tech Stack:** Python sync repository Protocols, existing FastAPI/LangGraph
modules, stdlib `unittest.mock`.

**Source references:** `docs/mongodb-atlas-storage/goal.md` and
`docs/mongodb-atlas-storage/research.md`, especially repository swap and
singleton call-graph findings. Follow root `AGENTS.md`; referenced
`.planning/codebase/*` files were absent when planned.

**Command note:** For multiline `powershell` blocks, join wrapped lines into one
line and omit display-only trailing `\` characters. `bash` blocks use `\` as
normal shell continuation.

---

## Scope And File Map

| File | Responsibility |
|------|----------------|
| `server/database/storage_registry.py` | Process context, SQLite stores, init |
| `server/database/repositories/facade.py` | Late-bound repository proxy |
| `server/database/__init__.py` | Re-export facades instead of raw stores |
| `server/main.py` | Use registry context and SQLite initializer |
| `server/routers/learning.py` | Import facade aliases |
| `server/graph/nodes.py` | Import facades; remove direct SQL and phantom call |
| `server/graph/runner.py` | Import facades |
| `server/graph/regen.py` | Import facades |
| `server/graph/regen_stream.py` | Import facades |
| `server/services/generation_runtime.py` | Default injected stores to facades |
| `server/services/research_runner.py` | Use facade defaults |
| `server/services/concept_chat.py` | Use learning facade |
| `server/database/generation_jobs.py` | Resolve progress through facade |
| `server/tests/test_repository_facades.py` | Late binding and compatibility |
| `server/tests/generation_acceptance_harness.py` | Patch updated facade objects |

New `.py` files require mandatory `AGENTS.md` header. Existing files need header
refresh only if implementation changes more than 30 percent.

## Task 1: Late-Bound Repository Facade

**Files:**
- Create: `server/database/repositories/facade.py`
- Create: `server/tests/test_repository_facades.py`

- [ ] **Step 1: Write failing late-binding test**

Create test file with mandatory header:

```python
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from server.database.repositories.facade import RepositoryFacade


class RepositoryFacadeTests(unittest.TestCase):
    def test_resolves_current_target_for_every_attribute(self) -> None:
        first = MagicMock()
        second = MagicMock()
        first.read.return_value = "sqlite"
        second.read.return_value = "mongo"
        holder = SimpleNamespace(current=first)
        facade = RepositoryFacade(lambda: holder.current)

        self.assertEqual(facade.read(), "sqlite")
        holder.current = second
        self.assertEqual(facade.read(), "mongo")
        first.read.assert_called_once_with()
        second.read.assert_called_once_with()

    def test_patch_object_can_override_facade_method(self) -> None:
        target = MagicMock()
        facade = RepositoryFacade(lambda: target)
        facade.read = MagicMock(return_value="patched")

        self.assertEqual(facade.read(), "patched")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_repository_facades -v
```

Expected: FAIL because facade module does not exist.

- [ ] **Step 3: Implement proxy**

Create `server/database/repositories/facade.py` with mandatory header:

```python
from __future__ import annotations

from typing import Any, Callable


class RepositoryFacade:
    """Resolve active repository lazily while preserving import identity."""

    def __init__(self, resolver: Callable[[], Any]) -> None:
        object.__setattr__(self, "_resolver", resolver)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolver(), name)
```

Do not implement `__setattr__`; tests and existing `patch.object` must be able to
place a temporary method directly on facade instance.

- [ ] **Step 4: Run test and verify GREEN**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_repository_facades -v
```

Expected: two tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/database/repositories/facade.py \
  server/tests/test_repository_facades.py
git commit -m "feat(storage): add late-bound repository facade"
```

## Task 2: Process Storage Registry

**Files:**
- Create: `server/database/storage_registry.py`
- Modify: `server/database/__init__.py`
- Modify: `server/tests/test_repository_facades.py`

- [ ] **Step 1: Write failing registry identity test**

Append:

```python
def test_registry_facades_point_at_context_bundle(self) -> None:
    from server.database.storage_registry import (
        learning_repository,
        storage_context,
    )

    expected = MagicMock(return_value={"id": "s1"})
    original = storage_context._repositories
    fake = replace(original, learning=MagicMock())
    fake.learning.get_learning_session = expected
    try:
        storage_context._repositories = fake
        result = learning_repository.get_learning_session("s1")
    finally:
        storage_context._repositories = original

    self.assertEqual(result, {"id": "s1"})
    expected.assert_called_once_with("s1")
```

Add imports `from dataclasses import replace`. Private assignment exists only in
this focused test; production swaps use context methods in Phase 3.

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_repository_facades -v
```

Expected: FAIL because registry does not exist.

- [ ] **Step 3: Implement registry and facade aliases**

Create `server/database/storage_registry.py` with mandatory header:

```python
from __future__ import annotations

from typing import cast

from server.config import settings
from server.database.generation_artifacts import GenerationArtifactStore
from server.database.generation_jobs import GenerationJobStore
from server.database.generation_migrations import (
    initialize_generation_schema,
)
from server.database.learning_persistence import LearningManager
from server.database.persistence import DB_PATH
from server.database.progress_events import ProgressEventStore
from server.database.repositories.facade import RepositoryFacade
from server.database.repositories.protocols import (
    GenerationArtifactRepository,
    GenerationJobRepository,
    LearningRepository,
    ProgressEventRepository,
    ResearchRepository,
)
from server.database.repositories.sqlite import build_sqlite_bundle
from server.database.research_store import ResearchStore
from server.database.storage_mode import StorageContext

sqlite_learning_store = LearningManager(DB_PATH)
sqlite_job_store = GenerationJobStore(DB_PATH)
sqlite_artifact_store = GenerationArtifactStore(DB_PATH)
sqlite_research_store = ResearchStore(DB_PATH)
sqlite_progress_store = ProgressEventStore(DB_PATH)

sqlite_repositories = build_sqlite_bundle(
    learning=sqlite_learning_store,
    jobs=sqlite_job_store,
    artifacts=sqlite_artifact_store,
    research=sqlite_research_store,
    progress=sqlite_progress_store,
)

storage_context = StorageContext(
    deployment_mode=settings.deployment_mode,
    sqlite_path=DB_PATH,
    sqlite_repositories=sqlite_repositories,
)

learning_repository = cast(
    LearningRepository,
    RepositoryFacade(lambda: storage_context.learning),
)
generation_job_repository = cast(
    GenerationJobRepository,
    RepositoryFacade(lambda: storage_context.jobs),
)
generation_artifact_repository = cast(
    GenerationArtifactRepository,
    RepositoryFacade(lambda: storage_context.artifacts),
)
research_repository = cast(
    ResearchRepository,
    RepositoryFacade(lambda: storage_context.research),
)
progress_event_repository = cast(
    ProgressEventRepository,
    RepositoryFacade(lambda: storage_context.progress),
)


def initialize_sqlite_storage() -> None:
    """Initialize local backup regardless of active cloud target."""

    sqlite_learning_store.init_learning_tables()
    initialize_generation_schema(DB_PATH)
```

Remove duplicate singleton construction from `server/database/__init__.py`.
Re-export facade aliases under current public names:

```python
from server.database.storage_registry import (
    generation_artifact_repository as generation_artifact_store,
    generation_job_repository as generation_job_store,
    progress_event_repository as progress_event_store,
    research_repository as research_store,
    storage_context,
)
```

Keep store classes and `DB_PATH` exports for tests and migrations.

- [ ] **Step 4: Run test and verify GREEN**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_repository_facades -v
```

Expected: registry identity test PASS.

- [ ] **Step 5: Commit**

```bash
git add server/database/__init__.py \
  server/database/storage_registry.py \
  server/tests/test_repository_facades.py
git commit -m "feat(storage): add process repository registry"
```

## Task 3: Remove Graph Direct SQL Coupling

**Files:**
- Modify: `server/graph/nodes.py`
- Modify: `server/tests/test_staged_graph.py`
- Modify: `server/tests/test_generation_jobs.py`

- [ ] **Step 1: Add failing graph delegation tests**

In `test_staged_graph.py`, patch module facade and call current warning/count
helpers with same fixtures already used by tests:

```python
@patch("server.graph.nodes.generation_job_store")
def test_append_job_warning_uses_repository(self, jobs) -> None:
    warning = GenerationWarning(code="slow", message="Provider slow")
    nodes._append_job_warning("s1", warning)
    jobs.append_warning.assert_called_once_with("s1", warning)

@patch("server.graph.nodes.generation_job_store")
def test_bump_job_counts_uses_repository(self, jobs) -> None:
    nodes._bump_job_counts("s1", sources=2)
    jobs.bump_counts.assert_called_once_with("s1", sources=2)
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_staged_graph -v
```

Expected: FAIL because helpers still enter SQLite transactions directly.

- [ ] **Step 3: Replace helper bodies and dead fallback**

In `server/graph/nodes.py`, replace direct imports of
`optional_transaction`, JSON SQL, and `generation_job_store.db_path`:

```python
def _append_job_warning(
    session_id: str,
    warning: GenerationWarning,
) -> None:
    generation_job_store.append_warning(session_id, warning)


def _bump_job_counts(session_id: str, **increments: int) -> None:
    generation_job_store.bump_counts(session_id, **increments)
```

At current resolved-mode update, retain only real method:

```python
learning_manager.update_session_resolved_mode(
    session_id,
    resolved_mode,
)
```

Delete fallback call to nonexistent `update_learning_session`. Let repository
errors propagate through current runner failure handling.

- [ ] **Step 4: Run tests and verify GREEN**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_staged_graph \
  server.tests.test_generation_jobs -v
```

Expected: PASS and grep finds no `.db_path` in `server/graph`.

- [ ] **Step 5: Commit**

```bash
git add server/graph/nodes.py server/tests/test_staged_graph.py
git commit -m "refactor(storage): remove graph SQLite coupling"
```

## Task 4: Redirect All Production Imports Through Facades

**Files:**
- Modify: `server/main.py`
- Modify: `server/routers/learning.py`
- Modify: `server/graph/nodes.py`
- Modify: `server/graph/runner.py`
- Modify: `server/graph/regen.py`
- Modify: `server/graph/regen_stream.py`
- Modify: `server/services/generation_runtime.py`
- Modify: `server/services/research_runner.py`
- Modify: `server/services/concept_chat.py`
- Modify: `server/database/generation_jobs.py`
- Modify: `server/tests/generation_acceptance_harness.py`

- [ ] **Step 1: Add failing import-identity regression test**

Append to facade tests:

```python
def test_production_modules_import_repository_facades(self) -> None:
    from server.database.storage_registry import learning_repository
    from server.graph import nodes, regen, regen_stream, runner
    from server.routers import learning

    modules = (nodes, regen, regen_stream, runner, learning)
    for module in modules:
        with self.subTest(module=module.__name__):
            self.assertIs(module.learning_manager, learning_repository)
```

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_repository_facades -v
```

Expected: FAIL because modules still import raw singleton.

- [ ] **Step 3: Replace imports while preserving local names**

Use alias imports so current code and patch targets remain stable:

```python
from server.database.storage_registry import (
    generation_artifact_repository as generation_artifact_store,
    generation_job_repository as generation_job_store,
    learning_repository as learning_manager,
    progress_event_repository as progress_event_store,
    research_repository as research_store,
)
```

Apply only needed names per file. Exact production importer checklist:

| Consumer | Facades |
|----------|---------|
| `server/routers/learning.py` | learning, jobs, research, progress |
| `server/graph/nodes.py` | learning, jobs, artifacts, research, progress |
| `server/graph/runner.py` | learning, jobs, progress |
| `server/graph/regen.py` | learning, artifacts |
| `server/graph/regen_stream.py` | learning, artifacts |
| `server/services/generation_runtime.py` | jobs, research, progress |
| `server/services/research_runner.py` | jobs, research, progress |
| `server/services/concept_chat.py` | learning |
| `server/database/generation_jobs.py` | progress, lazy import |

Keep constructor injection in `GenerationRuntime`, `run_generation_job`, and
`ResearchRunner`. Only their defaults change to facades.

Update `generation_acceptance_harness.py` patch paths only if assertions depend
on raw store type. Existing patches such as
`server.graph.nodes.learning_manager` remain valid because aliases retain names.

- [ ] **Step 4: Wire main to registry context**

Replace Phase 1 context construction in `server/main.py`:

```python
from server.database.storage_registry import (
    initialize_sqlite_storage,
    storage_context,
)

# inside lifespan
initialize_sqlite_storage()
storage_context.jobs.mark_orphaned_jobs_paused(
    pause_all_nonterminal=True,
)
app.state.storage = storage_context
```

Do not disconnect process context before `GenerationRuntime.shutdown()`.

- [ ] **Step 5: Verify no production raw singleton imports remain**

Run searches:

```powershell
git grep -n -E \
  "from server\.database\.learning_persistence import learning_manager" \
  -- server
git grep -n -E \
  "generation_job_store\.db_path|optional_transaction" \
  -- server/graph
```

Expected: no output and exit status 1 for each search. Test fixtures may still
construct store classes.

- [ ] **Step 6: Run targeted and full server suites**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_repository_facades \
  server.tests.test_graph \
  server.tests.test_staged_graph \
  server.tests.test_generation_runtime \
  server.tests.test_learning_graph_router -v
server\.venv\Scripts\python.exe -m unittest
```

Expected: all tests PASS with SQLite as default.

- [ ] **Step 7: Commit**

```bash
git add server/main.py server/routers/learning.py \
  server/graph/nodes.py server/graph/runner.py server/graph/regen.py \
  server/graph/regen_stream.py server/services/generation_runtime.py \
  server/services/research_runner.py server/services/concept_chat.py \
  server/database/generation_jobs.py \
  server/tests/generation_acceptance_harness.py \
  server/tests/test_repository_facades.py
git commit -m "refactor(storage): route persistence through context facades"
```

## Phase 2B Exit Checkpoint

- [ ] Fresh process defaults to SQLite and all existing tests pass.
- [ ] Facade object identities stay constant across bundle changes.
- [ ] Routers, graph, runtime, research, chat, and lazy event lookup use facades.
- [ ] No graph code reaches `db_path`, raw SQL, or SQLite transaction helpers.
- [ ] Existing module-local patch names remain valid.
- [ ] Add phase note:

```bash
git notes add -m "Phase 2B complete: all consumers use repository facades"
```
