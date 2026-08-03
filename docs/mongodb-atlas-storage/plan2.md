# MongoDB Atlas Storage Phase 2A: Repository Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define synchronous repository ports, wrap every existing SQLite store,
and make `StorageContext` return a complete SQLite repository bundle by default.

**Architecture:** Ports-and-adapters boundary around current sync persistence.
Protocols contain production call-graph methods, not private SQLite helpers or
`sqlite3.Connection` parameters. Thin SQLite adapters delegate to proven stores;
Phase 2B redirects consumers through stable facades and Phase 3 adds Mongo ports.

**Tech Stack:** Python typing `Protocol`, dataclasses, SQLite store classes,
stdlib `unittest`, Protocol fakes.

**Source references:** `docs/mongodb-atlas-storage/goal.md` and
`docs/mongodb-atlas-storage/research.md`, especially research sections 3.2,
3.3, 7.1, and 7.2. Follow root `AGENTS.md`; referenced
`.planning/codebase/*` files were absent when planned.

**Command note:** For multiline `powershell` blocks, join wrapped lines into one
line and omit display-only trailing `\` characters. `bash` blocks use `\` as
normal shell continuation.

---

## Scope And File Map

| File | Responsibility |
|------|----------------|
| `server/database/repositories/protocols.py` | Six repository ports |
| `server/database/repositories/sqlite.py` | Existing-store adapters |
| `server/database/repositories/bundle.py` | Typed aggregate bundle |
| `server/database/repositories/errors.py` | Backend-independent errors |
| `server/database/repositories/__init__.py` | Public repository exports |
| `server/database/storage_mode.py` | Hold active and SQLite bundles |
| `server/database/generation_jobs.py` | Add missing warning/count methods |
| `server/tests/test_repository_contracts.py` | Fakes and default-bundle tests |
| `server/tests/test_sqlite_repositories.py` | Adapter delegation tests |

All new `.py` files require mandatory `AGENTS.md` header before first code.

## Task 1: Repository Protocols

**Files:**
- Create: `server/database/repositories/protocols.py`
- Create: `server/database/repositories/errors.py`
- Create: `server/tests/test_repository_contracts.py`

- [ ] **Step 1: Write failing structural contract tests**

Create test file with mandatory header:

```python
from __future__ import annotations

import unittest

from server.database.repositories.protocols import (
    AppSettingsRepository,
    GenerationArtifactRepository,
    GenerationJobRepository,
    LearningRepository,
    ProgressEventRepository,
    ResearchRepository,
)


class RepositoryContractTests(unittest.TestCase):
    def test_protocols_expose_required_call_graph_methods(self) -> None:
        required = {
            LearningRepository: {
                "create_learning_session",
                "get_learning_session",
                "create_quiz_attempt",
                "create_revision_session",
            },
            GenerationJobRepository: {
                "create_session_shell_and_job",
                "transition_stage",
                "try_acquire_lock",
                "mark_orphaned_jobs_paused",
            },
            GenerationArtifactRepository: {
                "persist_outline",
                "persist_briefs",
                "persist_topic_success",
            },
            ResearchRepository: {
                "create_report",
                "upsert_source",
                "get_public_report",
            },
            ProgressEventRepository: {
                "append_once",
                "list_after",
                "latest_id",
            },
            AppSettingsRepository: {
                "get_provider_settings",
                "put_web_search_settings",
            },
        }
        for contract, methods in required.items():
            with self.subTest(contract=contract.__name__):
                self.assertTrue(methods.issubset(vars(contract)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_repository_contracts -v
```

Expected: FAIL because repository package does not exist.

- [ ] **Step 3: Define backend-independent errors**

Create `server/database/repositories/errors.py` with mandatory header:

```python
class RepositoryUnavailableError(RuntimeError):
    """Requested repository has no implementation for active backend."""


class RepositoryConflictError(RuntimeError):
    """Unique, transition, or optimistic-lock constraint failed."""
```

- [ ] **Step 4: Define exact synchronous Protocol surfaces**

Create `server/database/repositories/protocols.py` with mandatory header. Use
existing schema types in signatures. Protocol methods have `...` bodies because
they are contracts, not incomplete implementation.

```python
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel

from server.schemas.generation import (
    GenerationBrief,
    GenerationBriefBatch,
    GenerationCounts,
    GenerationJobPublic,
    GenerationJobRecord,
    GenerationLock,
    GenerationStage,
    GenerationWarning,
    SourceCitation,
)
from server.schemas.learning import (
    CourseOutline,
    FailedStep,
    NodeStatus,
    QuizCard,
    QuizSet,
    TopicNode,
)
from server.schemas.progress import ProgressEvent, ProgressEventType
from server.schemas.research import (
    ResearchProviderStatus,
    ResearchReport,
    ResearchSection,
    ResearchSource,
    ResearchStatus,
)


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

    def get_learning_session(
        self,
        session_id: str,
    ) -> Optional[dict[str, Any]]: ...

    def get_session_progress(
        self,
        session_id: str,
    ) -> Optional[dict[str, Any]]: ...

    def get_sessions_list(
        self,
        user_id: Optional[str],
        status: str = "all",
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]: ...

    def update_session_resolved_mode(
        self,
        session_id: str,
        resolved_mode: str,
    ) -> None: ...

    def update_last_active_node(
        self,
        session_id: str,
        node_id: str,
    ) -> None: ...

    def delete_learning_session(self, session_id: str) -> bool: ...
    def create_concept_node(self, *args: Any, **kwargs: Any) -> dict: ...
    def get_session_nodes(self, session_id: str) -> list[dict]: ...
    def get_concept_node(self, node_id: str) -> Optional[dict]: ...
    def get_next_node(
        self,
        session_id: str,
        sequence_index: int,
    ) -> Optional[dict]: ...
    def update_node_status(
        self,
        node_id: str,
        status: NodeStatus,
    ) -> Optional[dict]: ...
    def update_node_content(
        self,
        node_id: str,
        content_markdown: str,
        status: NodeStatus,
        quiz: Optional[QuizCard] = None,
        quiz_set: Optional[QuizSet] = None,
        error_message: Optional[str] = None,
        retry_available: bool = False,
        failed_step: Optional[FailedStep] = None,
    ) -> Optional[dict]: ...
    def replace_node_content(
        self,
        node_id: str,
        content_markdown: str,
        status: NodeStatus,
        quiz_set: Optional[QuizSet] = None,
    ) -> Optional[dict]: ...
    def get_quiz_for_node(self, node_id: str) -> Optional[QuizCard]: ...
    def create_quiz_set(
        self,
        node_id: str,
        quiz_set: QuizSet,
        shuffle_seed: Optional[str] = None,
    ) -> dict: ...
    def get_quiz_set_for_node(
        self,
        node_id: str,
    ) -> Optional[dict]: ...
    def update_quiz_shuffle_seed(
        self,
        node_id: str,
        shuffle_seed: str,
    ) -> bool: ...
    def decrement_quiz_set_progress(
        self,
        node_id: str,
    ) -> Optional[dict]: ...
    def update_quiz_set_progress(
        self,
        node_id: str,
        current_index: int,
    ) -> Optional[dict]: ...
    def create_quiz_attempt(
        self,
        node_id: str,
        selected_option_ids: list[str],
        quiz_index: int = 0,
        revision_session_id: Optional[str] = None,
    ) -> dict: ...
    def get_quiz_attempts(self, node_id: str) -> dict: ...
    def check_mastery(self, node_id: str) -> bool: ...
    def create_revision_session(
        self,
        original_session_id: str,
        mode: str,
    ) -> dict: ...
    def get_revisions_for_session(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]: ...
    def get_revision_session(
        self,
        revision_id: str,
    ) -> Optional[dict]: ...
    def delete_revision_session(self, revision_id: str) -> bool: ...
    def mark_revision_node_reviewed(
        self,
        revision_id: str,
        node_id: str,
    ) -> dict: ...
    def submit_revision_quiz(
        self,
        revision_id: str,
        node_id: str,
        selected_option_ids: list[str],
        quiz_index: int = 0,
    ) -> dict: ...
    def get_revision_summary(self, revision_id: str) -> dict: ...


@runtime_checkable
class GenerationJobRepository(Protocol):
    def create_session_shell_and_job(
        self,
        *,
        query: str,
        user_id: Optional[str],
        mode: str,
        web_search_requested: bool,
        now: Optional[datetime] = None,
    ) -> tuple[dict, GenerationJobRecord]: ...
    def get_by_session(
        self,
        session_id: str,
    ) -> Optional[GenerationJobRecord]: ...
    def to_public(
        self,
        job: GenerationJobRecord,
        *,
        last_event_id: Optional[int] = None,
    ) -> GenerationJobPublic: ...
    def to_public_by_session(
        self,
        session_id: str,
    ) -> Optional[GenerationJobPublic]: ...
    def get_public_by_sessions(
        self,
        session_ids: list[str],
    ) -> dict[str, GenerationJobPublic]: ...
    def transition_stage(self, **kwargs: Any) -> GenerationJobRecord: ...
    def update_cursor(self, **kwargs: Any) -> GenerationJobRecord: ...
    def request_cancel(self, session_id: str) -> GenerationJobRecord: ...
    def is_cancel_requested(self, session_id: str) -> bool: ...
    def mark_paused(self, **kwargs: Any) -> GenerationJobRecord: ...
    def mark_cancelled(self, **kwargs: Any) -> GenerationJobRecord: ...
    def prepare_resume(self, session_id: str) -> GenerationJobRecord: ...
    def try_acquire_lock(
        self,
        *,
        session_id: str,
        owner: str,
        ttl_seconds: int,
        now: Optional[datetime] = None,
    ) -> Optional[GenerationLock]: ...
    def renew_lock(
        self,
        *,
        lock: GenerationLock,
        ttl_seconds: int,
        now: Optional[datetime] = None,
    ) -> GenerationLock: ...
    def release_lock(self, *, lock: GenerationLock) -> None: ...
    def mark_orphaned_jobs_paused(
        self,
        now: Optional[datetime] = None,
        *,
        pause_all_nonterminal: bool = False,
    ) -> list[str]: ...
    def update_stage(
        self,
        session_id: str,
        stage: GenerationStage,
        *,
        lock: Optional[GenerationLock] = None,
    ) -> None: ...
    def update_progress(
        self,
        session_id: str,
        completed_topics: int,
        *,
        lock: Optional[GenerationLock] = None,
        topics_ready: Optional[int] = None,
        topics_failed: Optional[int] = None,
    ) -> None: ...
    def append_warning(
        self,
        session_id: str,
        warning: GenerationWarning,
    ) -> None: ...
    def bump_counts(
        self,
        session_id: str,
        **increments: int,
    ) -> GenerationCounts: ...
    def mark_failed(
        self,
        session_id: str,
        safe_message: str = "Generation failed",
    ) -> None: ...


@runtime_checkable
class GenerationArtifactRepository(Protocol):
    def persist_outline(
        self,
        session_id: str,
        outline: CourseOutline,
    ) -> list[dict]: ...
    def upsert_brief_batch(
        self,
        session_id: str,
        batch: GenerationBriefBatch,
    ) -> list[GenerationBrief]: ...
    def persist_briefs(
        self,
        session_id: str,
        batch: GenerationBriefBatch,
    ) -> list[GenerationBrief]: ...
    def get_brief(self, node_id: str) -> Optional[GenerationBrief]: ...
    def get_briefs(
        self,
        session_id: str,
        start_index: int,
        limit: int,
    ) -> list[GenerationBrief]: ...
    def get_topic(self, session_id: str, topic_index: int) -> TopicNode: ...
    def count_topics(self, session_id: str) -> int: ...
    def get_outline(self, session_id: str) -> CourseOutline: ...
    def get_adjacent_summaries(
        self,
        session_id: str,
        topic_index: int,
    ) -> tuple[Optional[str], Optional[str]]: ...
    def node_id_for_topic(
        self,
        session_id: str,
        topic_index: int,
    ) -> str: ...
    def persist_generated_content(
        self,
        node_id: str,
        content_markdown: str,
    ) -> dict: ...
    def has_durable_content(self, node_id: str) -> bool: ...
    def persist_content_with_citations(
        self,
        *,
        node_id: str,
        content_markdown: str,
        citations: list[SourceCitation],
    ) -> dict: ...
    def persist_topic_success(
        self,
        node_id: str,
        quiz_set: QuizSet,
        citations: list[SourceCitation],
    ) -> dict: ...
    def persist_topic_error(
        self,
        node_id: str,
        failed_step: FailedStep,
        safe_error_message: str,
        content_markdown: str,
    ) -> dict: ...
    def replace_node_sources(
        self,
        node_id: str,
        citations: list[SourceCitation],
    ) -> list[dict]: ...
    def list_node_sources(self, node_id: str) -> list[dict]: ...
    def get_citations_by_session(
        self,
        session_id: str,
    ) -> dict[str, list[dict]]: ...


@runtime_checkable
class ResearchRepository(Protocol):
    def create_report(
        self,
        session_id: str,
        now: Optional[datetime] = None,
    ) -> ResearchReport: ...
    def get_report(self, session_id: str) -> Optional[ResearchReport]: ...
    def upsert_source(self, **kwargs: Any) -> ResearchSource: ...
    def upsert_section(self, **kwargs: Any) -> ResearchSection: ...
    def set_provider_status(
        self,
        **kwargs: Any,
    ) -> ResearchProviderStatus: ...
    def finalize_report(
        self,
        *,
        session_id: str,
        status: ResearchStatus,
        summary: str,
        limitations: list[str],
        freshness_note: Optional[str],
    ) -> ResearchReport: ...
    def mark_degraded(self, **kwargs: Any) -> ResearchReport: ...
    def get_planner_context(
        self,
        session_id: str,
        max_excerpt_chars: int,
    ) -> dict: ...
    def get_report_context(
        self,
        report_id_or_session_id: str,
        max_bytes: int = 8000,
    ) -> Optional[str]: ...
    def get_sources_by_ids(
        self,
        session_id: str,
        source_ids: list[str],
    ) -> list[ResearchSource]: ...
    def get_citations_by_session(
        self,
        session_id: str,
    ) -> dict[str, list[dict]]: ...
    def get_public_report(
        self,
        session_id: str,
    ) -> Optional[ResearchReport]: ...


@runtime_checkable
class ProgressEventRepository(Protocol):
    def append_once(
        self,
        *,
        session_id: str,
        event_type: ProgressEventType,
        payload: BaseModel,
        dedupe_key: str,
        now: Optional[datetime] = None,
    ) -> ProgressEvent: ...
    def list_after(
        self,
        session_id: str,
        after_event_id: int,
        limit: int = 100,
    ) -> list[ProgressEvent]: ...
    def latest_id(self, session_id: str) -> int: ...
    def compact_completed(
        self,
        session_id: str,
        keep_last: int = 200,
    ) -> int: ...


@runtime_checkable
class AppSettingsRepository(Protocol):
    def get_provider_settings(self) -> Optional[dict[str, Any]]: ...
    def put_provider_settings(self, payload: dict[str, Any]) -> None: ...
    def get_web_search_settings(self) -> Optional[dict[str, Any]]: ...
    def put_web_search_settings(self, payload: dict[str, Any]) -> None: ...
```

Before committing, compare protocol names against current `grep` call graph.
Do not include phantom `LearningManager.update_learning_session`; remove its
dead fallback in Phase 2B.

- [ ] **Step 5: Run tests and verify GREEN**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_repository_contracts -v
```

Expected: protocol surface test PASS.

- [ ] **Step 6: Commit**

```bash
git add server/database/repositories/errors.py \
  server/database/repositories/protocols.py \
  server/tests/test_repository_contracts.py
git commit -m "feat(storage): define repository protocols"
```

## Task 2: Missing Job Repository Operations

**Files:**
- Modify: `server/database/generation_jobs.py`
- Modify: `server/tests/test_generation_jobs.py`

- [ ] **Step 1: Write failing tests for warning and count updates**

Use existing temporary database setup in `test_generation_jobs.py`. Add:

```python
def test_append_warning_is_idempotent_by_warning_payload(self) -> None:
    _, job = self.store.create_session_shell_and_job(
        query="q",
        user_id=None,
        mode="auto",
        web_search_requested=False,
    )
    warning = GenerationWarning(code="slow", message="Provider slow")
    self.store.append_warning(job.session_id, warning)
    self.store.append_warning(job.session_id, warning)

    updated = self.store.get_by_session(job.session_id)
    self.assertIsNotNone(updated)
    self.assertEqual(updated.warnings, [warning])

def test_bump_counts_updates_requested_nonnegative_fields(self) -> None:
    _, job = self.store.create_session_shell_and_job(
        query="q",
        user_id=None,
        mode="auto",
        web_search_requested=False,
    )
    counts = self.store.bump_counts(
        job.session_id,
        sources=2,
        research_sections=1,
    )
    self.assertEqual(counts.sources, 2)
    self.assertEqual(counts.research_sections, 1)
```

- [ ] **Step 2: Run two tests and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_generation_jobs.GenerationJobStoreTests.\
test_append_warning_is_idempotent_by_warning_payload \
  server.tests.test_generation_jobs.GenerationJobStoreTests.\
test_bump_counts_updates_requested_nonnegative_fields -v
```

Expected: FAIL because methods do not exist.

- [ ] **Step 3: Add store-owned operations**

Add public methods to `GenerationJobStore`. Reuse `optional_transaction`,
`canonical_json`, and `_row_to_record`; never expose `db_path` to graph code.

```python
def append_warning(
    self,
    session_id: str,
    warning: GenerationWarning,
) -> None:
    """Append warning once using canonical payload equality."""
    with optional_transaction(self.db_path, None) as conn:
        job = self.get_by_session(session_id, conn=conn)
        if job is None:
            raise GenerationJobNotFound(session_id)
        if warning in job.warnings:
            return
        warnings = [*job.warnings, warning]
        conn.execute(
            "UPDATE generation_jobs SET warnings_json = ?, "
            "updated_at = ? WHERE session_id = ?",
            (
                canonical_json(
                    [item.model_dump(mode="json") for item in warnings]
                ),
                _utc_now(None).isoformat(),
                session_id,
            ),
        )

def bump_counts(
    self,
    session_id: str,
    **increments: int,
) -> GenerationCounts:
    """Increment selected generation counters in one transaction."""
    allowed = set(GenerationCounts.model_fields)
    if set(increments) - allowed or any(
        value < 0 for value in increments.values()
    ):
        raise ValueError("Invalid generation count increment")
    with optional_transaction(self.db_path, None) as conn:
        job = self.get_by_session(session_id, conn=conn)
        if job is None:
            raise GenerationJobNotFound(session_id)
        values = job.counts.model_dump()
        for name, value in increments.items():
            values[name] += value
        counts = GenerationCounts.model_validate(values)
        conn.execute(
            "UPDATE generation_jobs SET counts_json = ?, updated_at = ? "
            "WHERE session_id = ?",
            (
                counts.model_dump_json(),
                _utc_now(None).isoformat(),
                session_id,
            ),
        )
    return counts
```

- [ ] **Step 4: Run job tests and verify GREEN**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_generation_jobs -v
```

Expected: all job tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/database/generation_jobs.py \
  server/tests/test_generation_jobs.py
git commit -m "refactor(storage): move job mutations into store"
```

## Task 3: SQLite Adapters And Repository Bundle

**Files:**
- Create: `server/database/repositories/sqlite.py`
- Create: `server/database/repositories/bundle.py`
- Create: `server/database/repositories/__init__.py`
- Create: `server/tests/test_sqlite_repositories.py`

- [ ] **Step 1: Write failing delegation and local-settings tests**

Create test file with mandatory header:

```python
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from server.database.repositories.errors import (
    RepositoryUnavailableError,
)
from server.database.repositories.sqlite import (
    LocalAppSettingsRepository,
    SqliteGenerationArtifactRepository,
    SqliteGenerationJobRepository,
    SqliteLearningRepository,
    SqliteProgressEventRepository,
    SqliteResearchRepository,
)


class SqliteRepositoryTests(unittest.TestCase):
    def test_each_adapter_delegates_to_wrapped_store(self) -> None:
        cases = (
            (SqliteLearningRepository, "get_learning_session", ("s1",)),
            (SqliteGenerationJobRepository, "get_by_session", ("s1",)),
            (SqliteGenerationArtifactRepository, "get_brief", ("n1",)),
            (SqliteResearchRepository, "get_report", ("s1",)),
            (SqliteProgressEventRepository, "latest_id", ("s1",)),
        )
        for adapter_type, method_name, args in cases:
            store = MagicMock()
            getattr(store, method_name).return_value = "sentinel"
            adapter = adapter_type(store)
            with self.subTest(adapter=adapter_type.__name__):
                result = getattr(adapter, method_name)(*args)
                self.assertEqual(result, "sentinel")
                getattr(store, method_name).assert_called_once_with(*args)

    def test_local_app_settings_is_explicitly_unavailable(self) -> None:
        repository = LocalAppSettingsRepository()
        with self.assertRaises(RepositoryUnavailableError):
            repository.get_provider_settings()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_sqlite_repositories -v
```

Expected: FAIL because adapters do not exist.

- [ ] **Step 3: Implement thin adapters**

Create `server/database/repositories/sqlite.py` with mandatory header:

```python
from __future__ import annotations

from typing import Any

from server.database.repositories.errors import (
    RepositoryUnavailableError,
)


class _DelegatingRepository:
    """Forward public calls to one proven SQLite store."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


class SqliteLearningRepository(_DelegatingRepository):
    """Learning port backed by `LearningManager`."""


class SqliteGenerationJobRepository(_DelegatingRepository):
    """Generation-job port backed by `GenerationJobStore`."""


class SqliteGenerationArtifactRepository(_DelegatingRepository):
    """Artifact port backed by `GenerationArtifactStore`."""


class SqliteResearchRepository(_DelegatingRepository):
    """Research port backed by `ResearchStore`."""


class SqliteProgressEventRepository(_DelegatingRepository):
    """Progress port backed by `ProgressEventStore`."""


class LocalAppSettingsRepository:
    """Keep local-mode credentials browser-only by product contract."""

    @staticmethod
    def _unavailable() -> None:
        raise RepositoryUnavailableError(
            "App settings are browser-owned while SQLite is active"
        )

    def get_provider_settings(self) -> None:
        self._unavailable()

    def put_provider_settings(self, payload: dict[str, Any]) -> None:
        self._unavailable()

    def get_web_search_settings(self) -> None:
        self._unavailable()

    def put_web_search_settings(self, payload: dict[str, Any]) -> None:
        self._unavailable()
```

Dynamic delegation is deliberate: it keeps this phase small and preserves all
current exception behavior. Runtime Protocol tests exercise methods through
`__getattr__`; Phase 3 Mongo implementations are explicit.

- [ ] **Step 4: Add typed bundle**

Create `server/database/repositories/bundle.py` with mandatory header:

```python
from __future__ import annotations

from dataclasses import dataclass

from server.database.repositories.protocols import (
    AppSettingsRepository,
    GenerationArtifactRepository,
    GenerationJobRepository,
    LearningRepository,
    ProgressEventRepository,
    ResearchRepository,
)


@dataclass(frozen=True)
class RepositoryBundle:
    """Complete backend implementation swapped as one value."""

    learning: LearningRepository
    jobs: GenerationJobRepository
    artifacts: GenerationArtifactRepository
    research: ResearchRepository
    progress: ProgressEventRepository
    app_settings: AppSettingsRepository
```

Export protocols, bundle, and adapters from repository `__init__.py`.

- [ ] **Step 5: Run adapter tests and verify GREEN**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_sqlite_repositories -v
```

Expected: all adapter tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/database/repositories \
  server/tests/test_sqlite_repositories.py
git commit -m "feat(storage): wrap SQLite stores as repositories"
```

## Task 4: Default SQLite Bundle In StorageContext

**Files:**
- Modify: `server/database/storage_mode.py`
- Modify: `server/tests/test_repository_contracts.py`

- [ ] **Step 1: Write failing default-bundle test**

Append a test using temporary stores rather than process singletons:

```python
def test_context_exposes_sqlite_bundle_by_default(self) -> None:
    stores = {
        "learning": MagicMock(),
        "jobs": MagicMock(),
        "artifacts": MagicMock(),
        "research": MagicMock(),
        "progress": MagicMock(),
    }
    bundle = build_sqlite_bundle(**stores)
    context = StorageContext(
        deployment_mode=DeploymentMode.LOCAL,
        sqlite_path=Path("unused.db"),
        sqlite_repositories=bundle,
    )

    self.assertIs(context.learning, bundle.learning)
    self.assertIs(context.jobs, bundle.jobs)
    self.assertIs(context.artifacts, bundle.artifacts)
    self.assertIs(context.research, bundle.research)
    self.assertIs(context.progress, bundle.progress)
```

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_repository_contracts -v
```

Expected: FAIL because context has no repository properties.

- [ ] **Step 3: Add bundle builder and context properties**

Add to `repositories/sqlite.py`:

```python
def build_sqlite_bundle(
    *,
    learning: Any,
    jobs: Any,
    artifacts: Any,
    research: Any,
    progress: Any,
) -> RepositoryBundle:
    return RepositoryBundle(
        learning=SqliteLearningRepository(learning),
        jobs=SqliteGenerationJobRepository(jobs),
        artifacts=SqliteGenerationArtifactRepository(artifacts),
        research=SqliteResearchRepository(research),
        progress=SqliteProgressEventRepository(progress),
        app_settings=LocalAppSettingsRepository(),
    )
```

Extend `StorageContext.__init__` with required `sqlite_repositories` in tests and
one production default built from current singletons. Store:

```python
self._sqlite_repositories = sqlite_repositories
self._repositories = sqlite_repositories
```

Add typed properties for all six bundle fields. `disconnect()` must set
`self._repositories = self._sqlite_repositories` inside same lock as backend
change. `connect()` does not swap bundle until Phase 3.

- [ ] **Step 4: Run Phase 2A tests and regressions**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_repository_contracts \
  server.tests.test_sqlite_repositories \
  server.tests.test_generation_jobs \
  server.tests.test_storage_mode -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/database/storage_mode.py \
  server/database/repositories/sqlite.py \
  server/tests/test_repository_contracts.py
git commit -m "feat(storage): expose default SQLite repository bundle"
```

## Phase 2A Exit Checkpoint

- [ ] Protocol names match all production call sites.
- [ ] No Protocol exposes `sqlite3.Connection` or `db_path`.
- [ ] Local app settings remain unavailable on server.
- [ ] `StorageContext` swaps complete bundles, never individual repositories.
- [ ] Add phase note:

```bash
git notes add -m "Phase 2A complete: protocols and SQLite adapters"
```
