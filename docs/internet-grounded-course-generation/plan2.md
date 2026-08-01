# Internet-Grounded Course Generation Implementation Plan — Phase 2: Durable Persistence

> **Planning method:** I used writing-plans skill principles: TDD, bite-sized tasks, exact paths, and no placeholders.
>
> **For agentic workers:** REQUIRED: TDD via test-driven-development skill; execute via executing-plans or subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** Persist generation jobs, research reports/sections/sources/provider states, private briefs, validated node-source links, and replayable progress events in SQLite for fresh and existing databases.

**Architecture:** Add one versioned startup migration and four focused stores. `GenerationJobStore` owns shell/job lifecycle and execution locks; `ResearchStore` owns report aggregates; `GenerationArtifactStore` owns TOC skeletons, private briefs, generated module artifacts, and citation links; `ProgressEventStore` owns monotonic replay. All stores accept an optional shared connection so stage, cursor, artifacts, and events can commit atomically. `LearningManager` remains unchanged.

**Tech Stack:** Python 3.10+, stdlib `sqlite3`, Pydantic v2, stdlib `unittest`.

**Depends on:** Phase 1.

**Deliverable:** Startup-safe schema evolution, focused repository APIs, idempotent writes, fenced per-session locks, transactional stage boundaries, and cascade cleanup with no secret-bearing column.

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `server/database/sqlite_utils.py` | Shared SQLite connection and `BEGIN IMMEDIATE` transaction contexts for new stores. |
| Create | `server/database/generation_migrations.py` | Versioned migration for generation, research, brief, citation, and event schema. |
| Create | `server/database/generation_jobs.py` | Session shell, job stage/cursor/counts/warnings, cancellation, and fenced execution locks. |
| Create | `server/database/research_store.py` | Reports, incremental sections, normalized sources, section links, and provider states. |
| Create | `server/database/generation_artifacts.py` | TOC skeletons, private briefs, generated content/quiz state, and node-source links. |
| Create | `server/database/progress_events.py` | Idempotent event append, monotonic replay, latest cursor, and retention. |
| Modify | `server/database/__init__.py` | Export focused stores and migration entry point. |
| Modify | `server/schemas/generation.py` | Add persisted job and lock record models. |
| Modify | `server/main.py` | Initialize new schema after legacy learning tables; fail startup on migration errors. |
| Create | `server/tests/test_generation_migrations.py` | Fresh/existing/rerun/rollback migration tests. |
| Create | `server/tests/test_generation_jobs.py` | Shell, stage, cursor, cancel, resume-stage, and lock tests. |
| Create | `server/tests/test_research_store.py` | Incremental report/source/provider persistence tests. |
| Create | `server/tests/test_generation_artifacts.py` | Idempotent skeleton, brief, module, and citation tests. |
| Create | `server/tests/test_progress_events.py` | Event ordering, dedupe, conflict, rollback, and retention tests. |
| Create | `server/tests/test_generation_persistence_integration.py` | Cross-store transaction and delete-cascade tests. |
| Do not modify | `server/database/learning_persistence.py` | Existing god class receives no generation/research methods. |

## Schema Contract

Migration version 1 creates these exact records:

| Table | Natural key and purpose |
|---|---|
| `generation_schema_migrations` | `version` primary key; records completed generation-schema migrations. |
| `generation_jobs` | Unique `session_id`; stage, resume stage, cursor, counts, warnings, web/degraded flags, cancel flag, stable thread, fenced lock. |
| `research_reports` | Unique `session_id`; status, summary, limitations, freshness. |
| `research_sources` | Unique `(session_id, canonical_url)` and `(session_id, content_hash)`; normalized citation evidence. |
| `research_sections` | Unique `(report_id, sequence_index)`; incremental theme report writes. |
| `research_section_sources` | Composite `(section_id, source_id)` primary key. |
| `research_provider_statuses` | Composite `(report_id, provider_id)` primary key; safe status only. |
| `generation_briefs` | Unique `node_id` and `(session_id, topic_index)`; private Planner artifact. |
| `node_sources` | Composite `(node_id, source_id)` primary key and unique `(node_id, citation_order)`. |
| `progress_events` | Monotonic integer `id`; unique `(session_id, dedupe_key)` for replay-safe writes. |

Migration also adds:

```text
learning_sessions.title_finalized INTEGER NOT NULL DEFAULT 1
concept_nodes.generation_status TEXT NOT NULL DEFAULT 'READY'
UNIQUE INDEX uq_concept_nodes_session_sequence
    ON concept_nodes(learning_session_id, sequence_index)
```

Existing sessions/nodes therefore remain finalized/ready. New generation shells use `title_finalized=0`; new TOC rows use `generation_status='SKELETON'`.

## Tasks

### Task 2.1: Add Transaction Helper and Versioned Migration

**Files:**
- Create: `server/database/sqlite_utils.py`
- Create: `server/database/generation_migrations.py`
- Create: `server/tests/test_generation_migrations.py`

- [ ] **Step 1: Write failing fresh/existing migration tests**

Create `server/tests/test_generation_migrations.py`:

```python
"""
============================================================================
FILE: test_generation_migrations.py
LOCATION: server/tests/test_generation_migrations.py
============================================================================
PURPOSE:
    Tests generation-schema creation and safe evolution of existing databases.
ROLE IN PROJECT:
    Guards startup migrations before focused generation stores use new tables.
KEY COMPONENTS:
    - GenerationMigrationTests: Fresh, existing, idempotent, and rollback tests
DEPENDENCIES:
    - External: sqlite3, tempfile, unittest
    - Internal: server.database generation migration and learning manager
USAGE:
    python -m unittest server.tests.test_generation_migrations -v
============================================================================
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.database.generation_migrations import (
    GenerationMigrationError,
    initialize_generation_schema,
)
from server.database.learning_persistence import LearningManager
from server.database.sqlite_utils import connect_database


EXPECTED_TABLES = {
    "generation_schema_migrations",
    "generation_jobs",
    "research_reports",
    "research_sources",
    "research_sections",
    "research_section_sources",
    "research_provider_statuses",
    "generation_briefs",
    "node_sources",
    "progress_events",
}


class GenerationMigrationTests(unittest.TestCase):
    """Tests fresh and existing SQLite generation schema migration."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        self.manager = LearningManager(db_path=self.db_path)
        self.manager.init_learning_tables()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_fresh_database_gets_all_tables_columns_and_indexes(self) -> None:
        initialize_generation_schema(self.db_path)
        conn = connect_database(self.db_path)
        try:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertTrue(EXPECTED_TABLES.issubset(tables))
            session_columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(learning_sessions)"
                ).fetchall()
            }
            node_columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(concept_nodes)"
                ).fetchall()
            }
            self.assertIn("title_finalized", session_columns)
            self.assertIn("generation_status", node_columns)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            conn.close()

    def test_existing_data_survives_idempotent_migration(self) -> None:
        session = self.manager.create_learning_session(
            query="Existing course",
            course_title="Existing Course",
        )
        initialize_generation_schema(self.db_path)
        initialize_generation_schema(self.db_path)

        loaded = self.manager.get_learning_session(session["id"])
        self.assertIsNotNone(loaded)
        conn = connect_database(self.db_path)
        try:
            versions = conn.execute(
                "SELECT version FROM generation_schema_migrations"
            ).fetchall()
            self.assertEqual([row["version"] for row in versions], [1])
        finally:
            conn.close()

    def test_duplicate_existing_sequence_stops_before_unique_index(self) -> None:
        session = self.manager.create_learning_session(
            query="Duplicate test",
            course_title="Duplicate Test",
        )
        conn = self.manager._get_connection()
        try:
            for node_id in ("node-a", "node-b"):
                conn.execute(
                    """
                    INSERT INTO concept_nodes (
                        id, learning_session_id, sequence_index, title,
                        content_markdown, status
                    ) VALUES (?, ?, 0, 'Topic', '', 'LOCKED')
                    """,
                    (node_id, session["id"]),
                )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(GenerationMigrationError):
            initialize_generation_schema(self.db_path)

    def test_failed_statement_rolls_back_migration_version(self) -> None:
        original_execute = sqlite3.Connection.execute

        def fail_on_jobs(connection, sql, parameters=()):
            if "CREATE TABLE generation_jobs" in sql:
                raise sqlite3.OperationalError("forced migration failure")
            return original_execute(connection, sql, parameters)

        with patch.object(sqlite3.Connection, "execute", fail_on_jobs):
            with self.assertRaises(sqlite3.OperationalError):
                initialize_generation_schema(self.db_path)

        conn = connect_database(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name = 'generation_schema_migrations'
                """
            ).fetchone()
            if row is not None:
                versions = conn.execute(
                    "SELECT version FROM generation_schema_migrations"
                ).fetchall()
                self.assertEqual(versions, [])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify red state**

Run from `D:\Peter\A2UI`:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_migrations -v
```

Expected: FAIL because migration modules do not exist.

- [ ] **Step 3: Implement connection and migration modules**

Create `server/database/sqlite_utils.py` with mandatory header and exact resource behavior:

```python
def connect_database(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(db_path),
        timeout=5.0,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def database_transaction(
    db_path: Path = DB_PATH,
) -> Iterator[sqlite3.Connection]:
    conn = connect_database(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def optional_transaction(
    db_path: Path,
    conn: Optional[sqlite3.Connection],
) -> Iterator[sqlite3.Connection]:
    if conn is not None:
        yield conn
        return
    with database_transaction(db_path) as owned_conn:
        yield owned_conn
```

Create `server/database/generation_migrations.py` with `GenerationMigrationError`, `CURRENT_GENERATION_SCHEMA_VERSION = 1`, and `initialize_generation_schema(db_path=DB_PATH)`. Required algorithm:

1. Open `database_transaction(db_path)`.
2. Create `generation_schema_migrations` if missing.
3. Return when version 1 already exists.
4. Query duplicate `(learning_session_id, sequence_index)` rows. Raise `GenerationMigrationError("Duplicate concept-node sequence rows block generation migration")` before creating unique index.
5. Add `title_finalized` and `generation_status` only when absent, using `PRAGMA table_info`.
6. Execute each DDL statement separately; do not use `executescript()`.
7. Create all tables and indexes listed in Schema Contract with foreign keys `ON DELETE CASCADE`.
8. Run `PRAGMA foreign_key_check`; raise `GenerationMigrationError` if rows are returned.
9. Insert migration version and UTC ISO timestamp last.

Use these exact JSON/text columns in `generation_jobs`:

```sql
id TEXT PRIMARY KEY,
session_id TEXT NOT NULL UNIQUE,
thread_id TEXT NOT NULL UNIQUE,
stage TEXT NOT NULL,
resume_stage TEXT,
web_search_requested INTEGER NOT NULL DEFAULT 0,
grounding_status TEXT NOT NULL DEFAULT 'DISABLED',
cursor_json TEXT NOT NULL,
counts_json TEXT NOT NULL,
warnings_json TEXT NOT NULL,
cancel_requested INTEGER NOT NULL DEFAULT 0,
lock_owner TEXT,
lock_version INTEGER NOT NULL DEFAULT 0,
lock_expires_at TEXT,
created_at TEXT NOT NULL,
updated_at TEXT NOT NULL,
FOREIGN KEY (session_id) REFERENCES learning_sessions(id) ON DELETE CASCADE
```

Use `payload_json TEXT NOT NULL` for briefs/events, canonical compact JSON (`sort_keys=True`, `separators=(",", ":")`), and no credential/header column.

- [ ] **Step 4: Run migration tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_migrations -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit migration foundation**

```powershell
git add server/database/sqlite_utils.py server/database/generation_migrations.py server/tests/test_generation_migrations.py
git commit -m "feat(database): add generation schema migrations"
```

### Task 2.2: Add Generation Job Store, State Machine, and Fenced Lock

**Files:**
- Create: `server/database/generation_jobs.py`
- Modify: `server/schemas/generation.py`
- Create: `server/tests/test_generation_jobs.py`

- [ ] **Step 1: Write failing job lifecycle tests**

Create `server/tests/test_generation_jobs.py`:

```python
"""
============================================================================
FILE: test_generation_jobs.py
LOCATION: server/tests/test_generation_jobs.py
============================================================================
PURPOSE:
    Tests durable generation job stages, cursors, cancellation, and locks.
ROLE IN PROJECT:
    Guards resumable single-worker generation lifecycle semantics.
KEY COMPONENTS:
    - GenerationJobStoreTests: Shell, transitions, lock fencing, cancel tests
DEPENDENCIES:
    - External: tempfile, unittest
    - Internal: server.database generation stores and schemas
USAGE:
    python -m unittest server.tests.test_generation_jobs -v
============================================================================
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from server.database.generation_jobs import (
    GenerationJobStore,
    GenerationLockConflict,
    InvalidGenerationTransition,
)
from server.database.generation_migrations import initialize_generation_schema
from server.database.learning_persistence import LearningManager
from server.schemas.generation import GenerationStage, GroundingStatus


class GenerationJobStoreTests(unittest.TestCase):
    """Tests durable generation job behavior."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        LearningManager(self.db_path).init_learning_tables()
        initialize_generation_schema(self.db_path)
        self.store = GenerationJobStore(self.db_path)
        self.now = datetime(2026, 8, 1, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_shell_and_job_are_created_atomically(self) -> None:
        session, job = self.store.create_session_shell_and_job(
            query="Modern Python packaging",
            user_id=None,
            mode="auto",
            web_search_requested=True,
            now=self.now,
        )
        self.assertEqual(session["course_title"], "Modern Python packaging")
        self.assertFalse(session["title_finalized"])
        self.assertIsNone(session["resolved_mode"])
        self.assertEqual(job.session_id, session["id"])
        self.assertEqual(job.thread_id, f"gen-{session['id']}")
        self.assertEqual(job.stage, GenerationStage.INITIALIZING)
        self.assertEqual(job.grounding_status, GroundingStatus.PENDING)

    def test_transition_matrix_rejects_skipped_stage(self) -> None:
        session, _ = self.store.create_session_shell_and_job(
            query="State machines",
            user_id=None,
            mode="lite",
            web_search_requested=False,
            now=self.now,
        )
        lock = self.store.try_acquire_lock(
            session_id=session["id"],
            owner="worker-a",
            ttl_seconds=120,
            now=self.now,
        )
        self.assertIsNotNone(lock)
        assert lock is not None
        with self.assertRaises(InvalidGenerationTransition):
            self.store.transition_stage(
                session_id=session["id"],
                target_stage=GenerationStage.COMPLETE,
                lock=lock,
                now=self.now,
            )

    def test_new_lock_fences_expired_worker(self) -> None:
        session, _ = self.store.create_session_shell_and_job(
            query="Fenced locks",
            user_id=None,
            mode="lite",
            web_search_requested=False,
            now=self.now,
        )
        first = self.store.try_acquire_lock(
            session_id=session["id"],
            owner="worker-a",
            ttl_seconds=60,
            now=self.now,
        )
        self.assertIsNotNone(first)
        second = self.store.try_acquire_lock(
            session_id=session["id"],
            owner="worker-b",
            ttl_seconds=60,
            now=self.now + timedelta(seconds=61),
        )
        self.assertIsNotNone(second)
        assert first is not None
        assert second is not None
        self.assertGreater(second.version, first.version)
        with self.assertRaises(GenerationLockConflict):
            self.store.transition_stage(
                session_id=session["id"],
                target_stage=GenerationStage.OUTLINING,
                lock=first,
                now=self.now + timedelta(seconds=62),
            )

    def test_cancel_retains_resume_stage_and_clears_on_resume(self) -> None:
        session, _ = self.store.create_session_shell_and_job(
            query="Cancellation",
            user_id=None,
            mode="full",
            web_search_requested=True,
            now=self.now,
        )
        lock = self.store.try_acquire_lock(
            session_id=session["id"],
            owner="worker-a",
            ttl_seconds=120,
            now=self.now,
        )
        assert lock is not None
        self.store.transition_stage(
            session_id=session["id"],
            target_stage=GenerationStage.RESEARCHING,
            lock=lock,
            now=self.now,
        )
        requested = self.store.request_cancel(session["id"], now=self.now)
        self.assertTrue(requested.cancel_requested)
        cancelled = self.store.mark_cancelled(
            session_id=session["id"],
            lock=lock,
            now=self.now,
        )
        self.assertEqual(cancelled.stage, GenerationStage.CANCELLED)
        self.assertEqual(cancelled.resume_stage, GenerationStage.RESEARCHING)
        resumed = self.store.prepare_resume(session["id"], now=self.now)
        self.assertEqual(resumed.stage, GenerationStage.RESEARCHING)
        self.assertFalse(resumed.cancel_requested)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_jobs -v
```

Expected: FAIL because `server.database.generation_jobs` does not exist.

- [ ] **Step 3: Implement job records and store**

Add `GenerationLock` and `GenerationJobRecord` to `server/schemas/generation.py`. `GenerationJobRecord` fields exactly mirror `generation_jobs`, parsing JSON into `GenerationCursor`, `GenerationCounts`, and `list[GenerationWarning]`. It contains no API key, credential, request header, provider response body, or LLM context field.

Create `server/database/generation_jobs.py` with mandatory header, module logger, `InvalidGenerationTransition`, `GenerationLockConflict`, `GenerationJobNotFound`, and `GenerationJobStore`. Public methods:

```python
create_session_shell_and_job(
    *, query: str, user_id: Optional[str], mode: str,
    web_search_requested: bool, now: Optional[datetime] = None,
) -> tuple[dict[str, Any], GenerationJobRecord]
get_by_session(session_id: str) -> Optional[GenerationJobRecord]
transition_stage(
    *, session_id: str, target_stage: GenerationStage,
    lock: GenerationLock, cursor: Optional[GenerationCursor] = None,
    counts: Optional[GenerationCounts] = None,
    warnings: Optional[list[GenerationWarning]] = None,
    grounding_status: Optional[GroundingStatus] = None,
    now: Optional[datetime] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> GenerationJobRecord
update_cursor(...same lock and optional connection...) -> GenerationJobRecord
request_cancel(session_id: str, now: Optional[datetime] = None) -> GenerationJobRecord
is_cancel_requested(session_id: str) -> bool
mark_paused(...lock...) -> GenerationJobRecord
mark_cancelled(...lock...) -> GenerationJobRecord
prepare_resume(session_id: str, now: Optional[datetime] = None) -> GenerationJobRecord
try_acquire_lock(...owner, ttl_seconds, now...) -> Optional[GenerationLock]
renew_lock(...lock, ttl_seconds, now...) -> GenerationLock
release_lock(...lock...) -> None
mark_orphaned_jobs_paused(now: Optional[datetime] = None) -> list[str]
```

Use one explicit `ALLOWED_STAGE_TRANSITIONS` mapping covering every enum member. Same-stage writes are idempotent. `PAUSED` and `CANCELLED` save prior stage in `resume_stage`; `prepare_resume()` accepts only those two stages, restores `resume_stage`, clears cancel flag, and leaves artifacts/cursor unchanged. `FAILED`, `COMPLETE`, and `COMPLETE_DEGRADED` are terminal.

Shell/job creation uses one transaction, UUID4 IDs, provisional title equal to trimmed query, `title_finalized=0`, `resolved_mode=NULL`, stable `thread_id=f"gen-{session_id}"`, and `GroundingStatus.PENDING` only when web was requested. It never calls `LearningManager`.

Lock acquisition uses conditional `UPDATE` in `BEGIN IMMEDIATE`, increments `lock_version`, and checks `(owner, version, expires_at)` on every worker mutation. Requesting cancellation does not require worker lock.

- [ ] **Step 4: Run job tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_jobs -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit job persistence**

```powershell
git add server/database/generation_jobs.py server/schemas/generation.py server/tests/test_generation_jobs.py
git commit -m "feat(database): persist generation job lifecycle"
```

### Task 2.3: Add Incremental Research Store

**Files:**
- Create: `server/database/research_store.py`
- Create: `server/tests/test_research_store.py`

- [ ] **Step 1: Write failing research persistence tests**

Create `server/tests/test_research_store.py`:

```python
"""
============================================================================
FILE: test_research_store.py
LOCATION: server/tests/test_research_store.py
============================================================================
PURPOSE:
    Tests incremental reports, source deduplication, sections, and providers.
ROLE IN PROJECT:
    Guards durable Researcher output before live search is implemented.
KEY COMPONENTS:
    - ResearchStoreTests: Report aggregate persistence tests
DEPENDENCIES:
    - External: tempfile, unittest
    - Internal: server.database research store and schemas
USAGE:
    python -m unittest server.tests.test_research_store -v
============================================================================
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from server.database.generation_jobs import GenerationJobStore
from server.database.generation_migrations import initialize_generation_schema
from server.database.learning_persistence import LearningManager
from server.database.research_store import ResearchSourceConflict, ResearchStore
from server.schemas.research import (
    ResearchProviderState,
    ResearchSource,
    ResearchStatus,
)
from server.search.types import SearchErrorClass, SearchProviderId


class ResearchStoreTests(unittest.TestCase):
    """Tests idempotent research aggregate writes."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        LearningManager(self.db_path).init_learning_tables()
        initialize_generation_schema(self.db_path)
        session, _ = GenerationJobStore(
            self.db_path
        ).create_session_shell_and_job(
            query="React 19",
            user_id=None,
            mode="full",
            web_search_requested=True,
        )
        self.session_id = session["id"]
        self.store = ResearchStore(self.db_path)
        self.report = self.store.create_report(self.session_id)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def make_source(self, content_hash: str = "a" * 64) -> ResearchSource:
        return ResearchSource(
            id="source-input-id",
            title="React v19",
            url="https://react.dev/blog/2024/12/05/react-19",
            publisher="React",
            published_at=datetime(2024, 12, 5, tzinfo=timezone.utc),
            retrieved_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            provider_id=SearchProviderId.TAVILY,
            snippet="React 19 release summary.",
            excerpt="React 19 is stable.",
            relevance_score=0.98,
        ).model_copy(update={"id": content_hash})

    def test_source_and_section_upserts_are_idempotent(self) -> None:
        first = self.store.upsert_source(
            session_id=self.session_id,
            source=self.make_source(),
            canonical_url="https://react.dev/blog/2024/12/05/react-19",
            content_hash="a" * 64,
        )
        second = self.store.upsert_source(
            session_id=self.session_id,
            source=self.make_source(),
            canonical_url="https://react.dev/blog/2024/12/05/react-19",
            content_hash="a" * 64,
        )
        self.assertEqual(first.id, second.id)

        section = self.store.upsert_section(
            report_id=self.report.id,
            sequence_index=0,
            theme="Current versions",
            markdown="React 19 is stable.",
            source_ids=[first.id],
        )
        updated = self.store.upsert_section(
            report_id=self.report.id,
            sequence_index=0,
            theme="Current versions",
            markdown="React 19 is stable and documents Actions.",
            source_ids=[first.id],
        )
        self.assertEqual(section.id, updated.id)
        self.assertIn("Actions", updated.markdown)

    def test_content_hash_collision_with_different_url_is_rejected(self) -> None:
        self.store.upsert_source(
            session_id=self.session_id,
            source=self.make_source(),
            canonical_url="https://react.dev/react-19",
            content_hash="a" * 64,
        )
        with self.assertRaises(ResearchSourceConflict):
            self.store.upsert_source(
                session_id=self.session_id,
                source=self.make_source(),
                canonical_url="https://example.com/copied-react-19",
                content_hash="a" * 64,
            )

    def test_provider_state_and_final_report_expose_safe_data(self) -> None:
        self.store.set_provider_status(
            report_id=self.report.id,
            provider_id=SearchProviderId.EXA,
            state=ResearchProviderState.AUTH_FAILED,
            search_calls=1,
            result_count=0,
            error_class=SearchErrorClass.AUTHENTICATION,
        )
        final = self.store.finalize_report(
            session_id=self.session_id,
            status=ResearchStatus.DEGRADED,
            summary="Research stopped after provider authentication failed.",
            limitations=["Current web evidence is incomplete."],
            freshness_note="Retrieved 2026-08-01.",
        )
        rendered = final.model_dump_json()
        self.assertIn("AUTH_FAILED", rendered)
        self.assertNotIn("api_key", rendered)
        self.assertNotIn("authorization", rendered.lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_research_store -v
```

Expected: FAIL because `ResearchStore` does not exist.

- [ ] **Step 3: Implement focused research aggregate store**

Create `server/database/research_store.py` with mandatory header, `ResearchSourceConflict`, `ResearchRelationshipError`, and these methods:

```python
create_report(session_id, now=None, conn=None) -> ResearchReport
get_report(session_id) -> Optional[ResearchReport]
upsert_source(
    *, session_id, source, canonical_url, content_hash, conn=None
) -> ResearchSource
upsert_section(
    *, report_id, sequence_index, theme, markdown, source_ids, conn=None
) -> ResearchSection
set_provider_status(
    *, report_id, provider_id, state, search_calls, result_count,
    error_class=None, conn=None
) -> ResearchProviderStatus
finalize_report(
    *, session_id, status, summary, limitations, freshness_note,
    conn=None
) -> ResearchReport
mark_degraded(
    *, session_id, warning, conn=None
) -> ResearchReport
get_planner_context(session_id, max_excerpt_chars) -> dict[str, Any]
get_sources_by_ids(session_id, source_ids) -> list[ResearchSource]
```

Generate server-owned UUID4 IDs; ignore caller-supplied `ResearchSource.id` on first insert. Canonical URL match returns existing row and updates only richer non-secret metadata. Content-hash match with a different canonical URL raises `ResearchSourceConflict` so copied evidence is not silently attributed to another URL. Validate all section source IDs belong to report session before deleting/replacing links. Section upsert and link replacement share one transaction. Provider persistence accepts only enum state/count/error class; no arbitrary provider message parameter exists.

`get_planner_context()` returns ordered sections and capped excerpts with source IDs. It omits canonical URL, content hash, provider raw data, and credentials.

- [ ] **Step 4: Run research store tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_research_store -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit research persistence**

```powershell
git add server/database/research_store.py server/tests/test_research_store.py
git commit -m "feat(database): persist incremental research reports"
```

### Task 2.4: Add TOC, Brief, Module, and Citation Artifact Store

**Files:**
- Create: `server/database/generation_artifacts.py`
- Create: `server/tests/test_generation_artifacts.py`

- [ ] **Step 1: Write failing artifact tests**

Create `server/tests/test_generation_artifacts.py` with one complete integration-style test class:

```python
"""
============================================================================
FILE: test_generation_artifacts.py
LOCATION: server/tests/test_generation_artifacts.py
============================================================================
PURPOSE:
    Tests idempotent TOC, private brief, module, and citation persistence.
ROLE IN PROJECT:
    Guards Planner-to-Generator durable artifacts without growing LearningManager.
KEY COMPONENTS:
    - GenerationArtifactStoreTests: Outline, brief, content, citation tests
DEPENDENCIES:
    - External: tempfile, unittest
    - Internal: server.database stores and learning schemas
USAGE:
    python -m unittest server.tests.test_generation_artifacts -v
============================================================================
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from server.database.generation_artifacts import (
    GenerationArtifactStore,
    UnsupportedCitationError,
)
from server.database.generation_jobs import GenerationJobStore
from server.database.generation_migrations import initialize_generation_schema
from server.database.learning_persistence import LearningManager
from server.database.research_store import ResearchStore
from server.schemas.generation import (
    BriefSourceExcerpt,
    GenerationBrief,
    GenerationBriefBatch,
    GroundingStatus,
    SourceCitation,
)
from server.schemas.learning import CourseOutline, TopicNode
from server.schemas.research import ResearchSource
from server.search.types import SearchProviderId


class GenerationArtifactStoreTests(unittest.TestCase):
    """Tests durable generation artifacts and citation allowlists."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        self.learning = LearningManager(self.db_path)
        self.learning.init_learning_tables()
        initialize_generation_schema(self.db_path)
        session, _ = GenerationJobStore(
            self.db_path
        ).create_session_shell_and_job(
            query="Modern packaging",
            user_id=None,
            mode="lite",
            web_search_requested=True,
        )
        self.session_id = session["id"]
        self.store = GenerationArtifactStore(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_outline_brief_and_citations_are_idempotent_and_private(self) -> None:
        topics = [
            TopicNode(
                index=index,
                title=f"Topic {index}",
                summary_for_context=f"Summary {index}",
                key_terms=["packaging", "standards"],
                complexity="Intermediate",
                quiz_count=2,
            )
            for index in range(3)
        ]
        outline = CourseOutline(
            course_title="Modern Python Packaging",
            topics=topics,
        )
        first_nodes = self.store.persist_outline(self.session_id, outline)
        second_nodes = self.store.persist_outline(self.session_id, outline)
        self.assertEqual(
            [node["id"] for node in first_nodes],
            [node["id"] for node in second_nodes],
        )
        self.assertTrue(all(node["generation_status"] == "SKELETON" for node in first_nodes))

        research = ResearchStore(self.db_path)
        research.create_report(self.session_id)
        source = research.upsert_source(
            session_id=self.session_id,
            source=ResearchSource(
                id="input-id",
                title="Python Packaging User Guide",
                url="https://packaging.python.org/en/latest/",
                publisher="Python Packaging Authority",
                published_at=None,
                retrieved_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                provider_id=SearchProviderId.EXA,
                snippet="Current packaging guidance.",
                excerpt="Use pyproject.toml for build configuration.",
                relevance_score=0.95,
            ),
            canonical_url="https://packaging.python.org/en/latest/",
            content_hash="b" * 64,
        )
        brief = GenerationBrief(
            topic_index=0,
            topic_scope="Standards-based build configuration.",
            learning_objectives=["Explain pyproject.toml build metadata."],
            prerequisites=["Python module structure."],
            assumed_knowledge=["Virtual environments."],
            current_facts=["PEP 517 build isolation is current."],
            methodologies=["Use a standards-based build frontend."],
            conventions=["Store metadata in pyproject.toml."],
            deprecated_approaches=["Direct setup.py invocation."],
            migration_notes=["Move legacy metadata incrementally."],
            caveats=["Backend-specific options differ."],
            research_report_id=research.get_report(self.session_id).id,
            source_excerpts=[
                BriefSourceExcerpt(
                    source_id=source.id,
                    excerpt="Use pyproject.toml for build configuration.",
                )
            ],
            required_examples=["Build a wheel with python -m build."],
            common_misconceptions=["pip is not a build backend."],
            failure_modes=["Missing build-system requirements."],
            pedagogical_guidance="Contrast frontend and backend roles.",
            expected_depth="lite",
            boundaries_with_adjacent_topics="Lock files belong later.",
            quiz_learning_targets=["Identify valid build configuration."],
            expected_learner_evidence=["Choose a standards-based command."],
            grounding_status=GroundingStatus.GROUNDED,
        )
        batch = GenerationBriefBatch(start_index=0, briefs=[brief])
        self.store.upsert_brief_batch(self.session_id, batch)
        self.store.upsert_brief_batch(self.session_id, batch)
        self.assertEqual(self.store.get_brief(first_nodes[0]["id"]), brief)

        links = self.store.replace_node_sources(
            node_id=first_nodes[0]["id"],
            citations=[
                SourceCitation(
                    source_id=source.id,
                    claim="pyproject.toml stores build configuration.",
                )
            ],
        )
        self.assertEqual([link["source_id"] for link in links], [source.id])

        public_node = self.learning.get_concept_node(first_nodes[0]["id"])
        self.assertNotIn("brief", public_node)
        self.assertNotIn("source_excerpts", public_node)

    def test_unsupported_citation_preserves_existing_links(self) -> None:
        topics = [
            TopicNode(
                index=index,
                title=f"Topic {index}",
                summary_for_context=f"Summary {index}",
                key_terms=["term-a", "term-b"],
                complexity="Basic",
                quiz_count=1,
            )
            for index in range(3)
        ]
        node = self.store.persist_outline(
            self.session_id,
            CourseOutline(course_title="Course", topics=topics),
        )[0]
        with self.assertRaises(UnsupportedCitationError):
            self.store.replace_node_sources(
                node_id=node["id"],
                citations=[
                    SourceCitation(
                        source_id="fabricated-source",
                        claim="Fabricated claim.",
                    )
                ],
            )
        self.assertEqual(self.store.list_node_sources(node["id"]), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_artifacts -v
```

Expected: FAIL because `GenerationArtifactStore` does not exist.

- [ ] **Step 3: Implement focused artifact store**

Create `server/database/generation_artifacts.py` with mandatory header and methods:

```python
persist_outline(session_id, outline, conn=None) -> list[dict[str, Any]]
upsert_brief_batch(session_id, batch, conn=None) -> list[GenerationBrief]
get_brief(node_id) -> Optional[GenerationBrief]
get_briefs(session_id, start_index, limit) -> list[GenerationBrief]
get_topic(session_id, topic_index) -> TopicNode
persist_generated_content(node_id, content_markdown, conn=None) -> dict[str, Any]
persist_topic_success(node_id, quiz_set, citations, conn=None) -> dict[str, Any]
persist_topic_error(
    node_id, failed_step, safe_error_message, content_markdown, conn=None
) -> dict[str, Any]
replace_node_sources(node_id, citations, conn=None) -> list[dict[str, Any]]
list_node_sources(node_id) -> list[dict[str, Any]]
get_citations_by_session(session_id) -> dict[str, list[dict[str, Any]]]
```

`persist_outline()` updates session title and `title_finalized=1`, then upserts every topic in one transaction. Node ID is deterministic UUID5 from `f"a2ui:{session_id}:{topic.index}"`. Every new skeleton has empty content, `NodeStatus.LOCKED`, `generation_status='SKELETON'`, and Planner metadata. Repeated identical writes return same IDs; conflicting title/index metadata raises `GenerationArtifactConflict`.

Brief upsert validates node/session/index alignment and stores compact `brief.model_dump_json(exclude_none=True)` only in `generation_briefs`. No `LearningManager` response query joins that table.

`persist_generated_content()` sets content and `generation_status='GENERATING'` but does not expose it as ready. Success writes quiz payload, sets `generation_status='READY'`, clears errors, and sets learner status to `VIEWING_EXPLANATION` for index 0 or `LOCKED` otherwise. Failure sets `generation_status='ERROR'`, `NodeStatus.ERROR`, `retry_available=1`, preserves available generated content, and stores only safe caller-supplied error text.

Citation replacement first loads brief approved IDs and verifies each source belongs to same session. It validates complete new set before deleting old links; then inserts ordered links with claim text. Fabricated URL input is impossible because `SourceCitation` accepts source ID and claim only.

- [ ] **Step 4: Run artifact tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_artifacts -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit generation artifacts**

```powershell
git add server/database/generation_artifacts.py server/tests/test_generation_artifacts.py
git commit -m "feat(database): persist generation briefs and citations"
```

### Task 2.5: Add Monotonic Replayable Progress Event Store

**Files:**
- Create: `server/database/progress_events.py`
- Create: `server/tests/test_progress_events.py`

- [ ] **Step 1: Write failing event store tests**

Create `server/tests/test_progress_events.py`:

```python
"""
============================================================================
FILE: test_progress_events.py
LOCATION: server/tests/test_progress_events.py
============================================================================
PURPOSE:
    Tests monotonic, replayable, idempotent, secret-safe generation events.
ROLE IN PROJECT:
    Establishes durable event source used by Phase 5 SSE and client polling repair.
KEY COMPONENTS:
    - ProgressEventStoreTests: Append, replay, conflict, rollback tests
DEPENDENCIES:
    - External: tempfile, unittest
    - Internal: server.database stores and progress schemas
USAGE:
    python -m unittest server.tests.test_progress_events -v
============================================================================
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.database.generation_jobs import GenerationJobStore
from server.database.generation_migrations import initialize_generation_schema
from server.database.learning_persistence import LearningManager
from server.database.progress_events import (
    ProgressEventConflict,
    ProgressEventStore,
)
from server.database.sqlite_utils import database_transaction
from server.schemas.generation import GenerationStage
from server.schemas.progress import ProgressEventType, StageChangedPayload


class ProgressEventStoreTests(unittest.TestCase):
    """Tests durable progress event ordering and atomicity."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        LearningManager(self.db_path).init_learning_tables()
        initialize_generation_schema(self.db_path)
        session, _ = GenerationJobStore(
            self.db_path
        ).create_session_shell_and_job(
            query="Events",
            user_id=None,
            mode="lite",
            web_search_requested=False,
        )
        self.session_id = session["id"]
        self.store = ProgressEventStore(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_append_once_and_list_after_use_monotonic_ids(self) -> None:
        payload = StageChangedPayload(
            previous_stage=GenerationStage.INITIALIZING,
            stage=GenerationStage.OUTLINING,
        )
        first = self.store.append_once(
            session_id=self.session_id,
            event_type=ProgressEventType.STAGE_CHANGED,
            payload=payload,
            dedupe_key="stage:OUTLINING:0",
        )
        repeated = self.store.append_once(
            session_id=self.session_id,
            event_type=ProgressEventType.STAGE_CHANGED,
            payload=payload,
            dedupe_key="stage:OUTLINING:0",
        )
        second = self.store.append_once(
            session_id=self.session_id,
            event_type=ProgressEventType.STAGE_CHANGED,
            payload=StageChangedPayload(
                previous_stage=GenerationStage.OUTLINING,
                stage=GenerationStage.PLANNING_PREVIEW,
            ),
            dedupe_key="stage:PLANNING_PREVIEW:0",
        )
        self.assertEqual(first.id, repeated.id)
        self.assertGreater(second.id, first.id)
        self.assertEqual(
            [event.id for event in self.store.list_after(self.session_id, first.id)],
            [second.id],
        )

    def test_same_dedupe_key_with_changed_payload_conflicts(self) -> None:
        self.store.append_once(
            session_id=self.session_id,
            event_type=ProgressEventType.STAGE_CHANGED,
            payload=StageChangedPayload(
                previous_stage=GenerationStage.INITIALIZING,
                stage=GenerationStage.OUTLINING,
            ),
            dedupe_key="stage:one",
        )
        with self.assertRaises(ProgressEventConflict):
            self.store.append_once(
                session_id=self.session_id,
                event_type=ProgressEventType.STAGE_CHANGED,
                payload=StageChangedPayload(
                    previous_stage=GenerationStage.INITIALIZING,
                    stage=GenerationStage.RESEARCHING,
                ),
                dedupe_key="stage:one",
            )

    def test_caller_transaction_rolls_event_back(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "forced rollback"):
            with database_transaction(self.db_path) as conn:
                self.store.append_once(
                    session_id=self.session_id,
                    event_type=ProgressEventType.STAGE_CHANGED,
                    payload=StageChangedPayload(
                        previous_stage=GenerationStage.INITIALIZING,
                        stage=GenerationStage.OUTLINING,
                    ),
                    dedupe_key="rolled-back",
                    conn=conn,
                )
                raise RuntimeError("forced rollback")
        self.assertEqual(self.store.list_after(self.session_id, 0), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_progress_events -v
```

Expected: FAIL because `ProgressEventStore` does not exist.

- [ ] **Step 3: Implement event store**

Create `server/database/progress_events.py` with mandatory header and:

```python
append_once(
    *, session_id: str, event_type: ProgressEventType,
    payload: ProgressPayload, dedupe_key: str,
    now: Optional[datetime] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> ProgressEvent
list_after(session_id: str, after_event_id: int, limit: int = 100) -> list[ProgressEvent]
latest_id(session_id: str) -> int
compact_completed(session_id: str, keep_last: int = 200) -> int
```

Serialize the already validated payload using canonical JSON. On unique-key collision, load existing row: return it only when event type and canonical payload match; otherwise raise `ProgressEventConflict`. `list_after()` validates `after_event_id >= 0`, clamps `limit` to 100, orders ascending, and parses every row through `ProgressEvent`. `compact_completed()` deletes oldest nonterminal events only after job stage is `COMPLETE`, `COMPLETE_DEGRADED`, `CANCELLED`, or `FAILED`; retain all terminal event rows and newest `keep_last` rows.

- [ ] **Step 4: Run event tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_progress_events -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit event persistence**

```powershell
git add server/database/progress_events.py server/tests/test_progress_events.py
git commit -m "feat(database): add replayable generation events"
```

### Task 2.6: Wire Startup and Verify Cross-Store Atomicity and Cleanup

**Files:**
- Modify: `server/database/__init__.py`
- Modify: `server/main.py`
- Create: `server/tests/test_generation_persistence_integration.py`

- [ ] **Step 1: Write failing cross-store transaction and cascade tests**

Create `server/tests/test_generation_persistence_integration.py`:

```python
"""
============================================================================
FILE: test_generation_persistence_integration.py
LOCATION: server/tests/test_generation_persistence_integration.py
============================================================================
PURPOSE:
    Tests atomic generation boundaries and explicit session cleanup cascades.
ROLE IN PROJECT:
    Verifies focused stores cooperate without adding methods to LearningManager.
KEY COMPONENTS:
    - GenerationPersistenceIntegrationTests: Transaction and cascade tests
DEPENDENCIES:
    - External: tempfile, unittest
    - Internal: server.database focused stores
USAGE:
    python -m unittest server.tests.test_generation_persistence_integration -v
============================================================================
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.database.generation_artifacts import GenerationArtifactStore
from server.database.generation_jobs import GenerationJobStore
from server.database.generation_migrations import initialize_generation_schema
from server.database.learning_persistence import LearningManager
from server.database.progress_events import ProgressEventStore
from server.database.sqlite_utils import connect_database, database_transaction
from server.schemas.generation import GenerationStage
from server.schemas.learning import CourseOutline, TopicNode
from server.schemas.progress import OutlineReadyPayload, ProgressEventType


class GenerationPersistenceIntegrationTests(unittest.TestCase):
    """Tests transaction sharing and cascade cleanup."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        self.learning = LearningManager(self.db_path)
        self.learning.init_learning_tables()
        initialize_generation_schema(self.db_path)
        self.jobs = GenerationJobStore(self.db_path)
        self.artifacts = GenerationArtifactStore(self.db_path)
        self.events = ProgressEventStore(self.db_path)
        self.session, _ = self.jobs.create_session_shell_and_job(
            query="Atomic boundaries",
            user_id=None,
            mode="lite",
            web_search_requested=False,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def outline(self) -> CourseOutline:
        return CourseOutline(
            course_title="Atomic Boundaries",
            topics=[
                TopicNode(
                    index=index,
                    title=f"Topic {index}",
                    summary_for_context=f"Summary {index}",
                    key_terms=["atomic", "transaction"],
                    complexity="Basic",
                    quiz_count=1,
                )
                for index in range(3)
            ],
        )

    def test_outline_and_event_roll_back_together(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "forced rollback"):
            with database_transaction(self.db_path) as conn:
                self.artifacts.persist_outline(
                    self.session["id"],
                    self.outline(),
                    conn=conn,
                )
                self.events.append_once(
                    session_id=self.session["id"],
                    event_type=ProgressEventType.OUTLINE_READY,
                    payload=OutlineReadyPayload(
                        course_title="Atomic Boundaries",
                        topic_count=3,
                    ),
                    dedupe_key="outline:ready",
                    conn=conn,
                )
                raise RuntimeError("forced rollback")
        self.assertEqual(self.learning.get_session_nodes(self.session["id"]), [])
        self.assertEqual(self.events.list_after(self.session["id"], 0), [])

    def test_explicit_session_delete_cascades_new_records(self) -> None:
        self.artifacts.persist_outline(self.session["id"], self.outline())
        self.assertTrue(self.learning.delete_learning_session(self.session["id"]))
        conn = connect_database(self.db_path)
        try:
            for table in (
                "generation_jobs",
                "research_reports",
                "generation_briefs",
                "progress_events",
            ):
                count = conn.execute(
                    f"SELECT COUNT(*) AS count FROM {table}"
                ).fetchone()["count"]
                self.assertEqual(count, 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run integration test and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_persistence_integration -v
```

Expected: first test FAIL until stores consistently honor caller-owned connections.

- [ ] **Step 3: Wire startup and finish shared-transaction behavior**

Ensure every store method with `conn` uses `optional_transaction()` and never commits/closes caller connection. Update `server/database/__init__.py` to export store classes, module-level stores using `DB_PATH`, and `initialize_generation_schema`.

Edit `server/main.py` startup in this exact order:

```python
learning_manager.init_learning_tables()
initialize_generation_schema()
generation_job_store.mark_orphaned_jobs_paused()
```

Remove the current behavior that logs database initialization failure and continues. Log with `logger.exception("Database initialization failed")` and re-raise so server cannot run against partial schema. Do not initialize a queue or retain credentials at startup.

Keep `server/database/learning_persistence.py` byte-for-byte unchanged in this phase. Cascade succeeds because focused tables reference `learning_sessions` and every focused connection enables foreign keys.

- [ ] **Step 4: Run Phase 2 integration and regression tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_persistence_integration server.tests.test_generation_migrations server.tests.test_generation_jobs server.tests.test_research_store server.tests.test_generation_artifacts server.tests.test_progress_events -v
```

Expected: all Phase 2 tests PASS.

- [ ] **Step 5: Commit startup integration**

```powershell
git add server/database/__init__.py server/main.py server/tests/test_generation_persistence_integration.py
git commit -m "feat(database): wire durable generation stores"
```

## Phase Checkpoint

- [ ] Run full server suite:

```powershell
server\.venv\Scripts\python.exe -m unittest
```

Expected: full suite PASS.

- [ ] Confirm focused schema has no secret-bearing column names:

```powershell
rg -i "api_key|authorization|credential|secret" server/database/generation_migrations.py server/database/generation_jobs.py server/database/research_store.py server/database/generation_artifacts.py server/database/progress_events.py
```

Expected: no schema or persistence field match; comments/docstrings explaining exclusion are acceptable.

- [ ] Confirm `LearningManager` did not grow:

```powershell
git diff HEAD~6 -- server/database/learning_persistence.py
```

Expected: empty diff.

- [ ] Record checkpoint:

```powershell
git notes add -m "Phase 2 complete: durable focused generation persistence verified"
```
