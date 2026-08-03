# MongoDB Atlas Storage Phase 3A: Mongo Learning Repository Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Mongo CRUD parity for learning sessions, nodes, quizzes,
attempts, and revisions, including application-level cascade deletion and all
equivalent indexes.

**Architecture:** One document per current SQLite row, same collection names,
existing string IDs as `_id`, native BSON for JSON payloads, and ISO timestamp
strings at API boundaries. Repository remains synchronous and implements Phase
2 `LearningRepository`; no Motor or async repository rewrite.

**Tech Stack:** PyMongo sync `Database`/`Collection`, Pydantic v2 domain models,
stdlib `unittest.mock`, current SQLite parity fixtures.

**Source references:** `docs/mongodb-atlas-storage/goal.md` and
`docs/mongodb-atlas-storage/research.md`, especially sections 5.3, 6.1, and
7.3. Follow root `AGENTS.md`; referenced `.planning/codebase/*` files were
absent when planned.

**Command note:** For multiline `powershell` blocks, join wrapped lines into one
line and omit display-only trailing `\` characters. `bash` blocks use `\` as
normal shell continuation.

---

## Scope And File Map

| File | Responsibility |
|------|----------------|
| `server/database/repositories/mongo_common.py` | ID/timestamp/model codecs |
| `server/database/repositories/mongo_indexes.py` | Idempotent app indexes |
| `server/database/repositories/mongo_learning.py` | Learning port |
| `server/tests/test_mongo_common.py` | Codec and index tests |
| `server/tests/test_mongo_learning.py` | Critical CRUD command/parity tests |

New Python files require mandatory `AGENTS.md` header. Keep public method names
and return shapes equal to `LearningManager`; HTTP contracts must not change.

## Task 1: Mongo Document Codecs And Learning Indexes

**Files:**
- Create: `server/database/repositories/mongo_common.py`
- Create: `server/database/repositories/mongo_indexes.py`
- Create: `server/tests/test_mongo_common.py`

- [ ] **Step 1: Write failing codec and index tests**

Create test file with mandatory header:

```python
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, call

from server.database.repositories.mongo_common import (
    document_to_row,
    model_payload,
    utc_iso,
)
from server.database.repositories.mongo_indexes import (
    ensure_learning_indexes,
)
from server.schemas.generation import GenerationCounts


class MongoCommonTests(unittest.TestCase):
    def test_document_to_row_maps_id_without_mutating_source(self) -> None:
        source = {"_id": "s1", "query": "q"}
        self.assertEqual(
            document_to_row(source),
            {"id": "s1", "query": "q"},
        )
        self.assertEqual(source, {"_id": "s1", "query": "q"})

    def test_model_payload_returns_native_bson_shape(self) -> None:
        counts = GenerationCounts(sources=2)
        self.assertEqual(model_payload(counts)["sources"], 2)

    def test_utc_iso_is_timezone_aware(self) -> None:
        value = utc_iso(datetime(2026, 8, 3, tzinfo=timezone.utc))
        self.assertEqual(value, "2026-08-03T00:00:00+00:00")

    def test_learning_indexes_match_sqlite_constraints(self) -> None:
        database = MagicMock()
        ensure_learning_indexes(database)

        database["concept_nodes"].create_index.assert_has_calls(
            [
                call([("learning_session_id", 1)]),
                call(
                    [
                        ("learning_session_id", 1),
                        ("sequence_index", 1),
                    ],
                    unique=True,
                ),
            ]
        )
        database["revision_node_progress"].create_index.\
            assert_any_call(
                [("revision_session_id", 1), ("node_id", 1)],
                unique=True,
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_common -v
```

Expected: FAIL because codec/index modules do not exist.

- [ ] **Step 3: Implement codecs**

Create `mongo_common.py` with mandatory header:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel


def utc_iso(now: Optional[datetime] = None) -> str:
    """Return stable timezone-aware ISO timestamp."""

    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def document_to_row(
    document: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Map Mongo `_id` to existing API/store `id` key."""

    if document is None:
        return None
    row = dict(document)
    identifier = row.pop("_id", None)
    if identifier is not None:
        row["id"] = identifier
    return row


def model_payload(value: BaseModel) -> dict[str, Any]:
    """Convert Pydantic value to BSON-safe native dict/list primitives."""

    return value.model_dump(mode="json", exclude_none=True)
```

- [ ] **Step 4: Implement exact learning indexes**

Create `mongo_indexes.py` with mandatory header and an idempotent function:

```python
from __future__ import annotations

from typing import Any


def ensure_learning_indexes(database: Any) -> None:
    database["learning_sessions"].create_index([("user_id", 1)])
    database["learning_sessions"].create_index([("updated_at", -1)])
    database["concept_nodes"].create_index(
        [("learning_session_id", 1)]
    )
    database["concept_nodes"].create_index(
        [("learning_session_id", 1), ("sequence_index", 1)],
        unique=True,
    )
    database["quiz_data"].create_index([("node_id", 1)])
    database["quiz_attempts"].create_index([("node_id", 1)])
    database["quiz_attempts"].create_index(
        [("node_id", 1), ("attempt_number", 1)]
    )
    database["quiz_attempts"].create_index(
        [("revision_session_id", 1)]
    )
    database["revision_sessions"].create_index(
        [("original_session_id", 1)]
    )
    database["revision_node_progress"].create_index(
        [("revision_session_id", 1)]
    )
    database["revision_node_progress"].create_index(
        [("revision_session_id", 1), ("node_id", 1)],
        unique=True,
    )
```

Do not make `quiz_data.node_id` unique until production data audit proves no
legacy duplicates; existing SQLite has only non-unique index.

- [ ] **Step 5: Run test and verify GREEN**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_common -v
```

Expected: four tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/database/repositories/mongo_common.py \
  server/database/repositories/mongo_indexes.py \
  server/tests/test_mongo_common.py
git commit -m "feat(storage): add Mongo codecs and learning indexes"
```

## Task 2: Session And Concept Node CRUD

**Files:**
- Create: `server/database/repositories/mongo_learning.py`
- Create: `server/tests/test_mongo_learning.py`

- [ ] **Step 1: Write failing session and node tests**

Create test file with mandatory header. Use mocked collections, fixed UUID, and
fixed clock so no Atlas is required:

```python
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from pymongo import ReturnDocument

from server.database.repositories.mongo_learning import (
    MongoLearningRepository,
)
from server.schemas.learning import NodeStatus


NOW = datetime(2026, 8, 3, tzinfo=timezone.utc)


class MongoLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = MagicMock()
        self.repository = MongoLearningRepository(self.database)

    @patch("server.database.repositories.mongo_learning.uuid.uuid4")
    def test_create_session_uses_string_id_and_api_shape(
        self,
        uuid4,
    ) -> None:
        uuid4.return_value = "session-1"
        with patch(
            "server.database.repositories.mongo_learning.utc_iso",
            return_value="2026-08-03T00:00:00+00:00",
        ):
            result = self.repository.create_learning_session(
                "query",
                "Course",
                mode="auto",
            )

        inserted = self.database["learning_sessions"].\
            insert_one.call_args.args[0]
        self.assertEqual(inserted["_id"], "session-1")
        self.assertEqual(result["id"], "session-1")
        self.assertNotIn("_id", result)

    def test_get_sessions_list_uses_safe_sort_and_pagination(self) -> None:
        collection = self.database["learning_sessions"]
        collection.count_documents.return_value = 1
        cursor = collection.find.return_value
        cursor.sort.return_value.skip.return_value.limit.return_value = [
            {"_id": "s1", "query": "q"}
        ]

        sessions, total = self.repository.get_sessions_list(
            None,
            sort_by="unknown",
            sort_order="asc",
            limit=20,
            offset=2,
        )

        cursor.sort.assert_called_once_with("updated_at", 1)
        self.assertEqual(total, 1)
        self.assertEqual(sessions[0]["id"], "s1")

    def test_node_status_update_uses_current_status_compare(self) -> None:
        nodes = self.database["concept_nodes"]
        nodes.find_one.return_value = {
            "_id": "n1",
            "status": NodeStatus.LOCKED.value,
        }
        nodes.find_one_and_update.return_value = {
            "_id": "n1",
            "status": NodeStatus.VIEWING_EXPLANATION.value,
        }

        result = self.repository.update_node_status(
            "n1",
            NodeStatus.VIEWING_EXPLANATION,
        )

        query = nodes.find_one_and_update.call_args.args[0]
        self.assertEqual(
            query,
            {"_id": "n1", "status": NodeStatus.LOCKED.value},
        )
        self.assertEqual(
            nodes.find_one_and_update.call_args.kwargs["return_document"],
            ReturnDocument.AFTER,
        )
        self.assertEqual(result["id"], "n1")
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_learning -v
```

Expected: FAIL because repository does not exist.

- [ ] **Step 3: Implement constructor and session methods**

Start `mongo_learning.py` with mandatory header and explicit collection refs:

```python
from __future__ import annotations

import uuid
from typing import Any, Optional

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from server.database.repositories.mongo_common import (
    document_to_row,
    model_payload,
    utc_iso,
)
from server.schemas.learning import NodeStatus, QuizCard, QuizSet


class MongoLearningRepository:
    """Mongo implementation of learning, quiz, and revision persistence."""

    def __init__(self, database: Any) -> None:
        self._db = database
        self._sessions = database["learning_sessions"]
        self._nodes = database["concept_nodes"]
        self._quizzes = database["quiz_data"]
        self._attempts = database["quiz_attempts"]
        self._revisions = database["revision_sessions"]
        self._revision_nodes = database["revision_node_progress"]

    def create_learning_session(
        self,
        query: str,
        course_title: str,
        user_id: Optional[str] = None,
        mode: str = "auto",
        resolved_mode: Optional[str] = None,
    ) -> dict[str, Any]:
        now = utc_iso()
        document = {
            "_id": str(uuid.uuid4()),
            "user_id": user_id,
            "query": query,
            "course_title": course_title,
            "title_finalized": True,
            "mode": mode,
            "resolved_mode": resolved_mode,
            "status": "active",
            "progress_percent": 0,
            "completed_at": None,
            "last_active_node_id": None,
            "created_at": now,
            "updated_at": now,
        }
        self._sessions.insert_one(document)
        return document_to_row(document) or {}

    def get_learning_session(
        self,
        session_id: str,
    ) -> Optional[dict[str, Any]]:
        return document_to_row(self._sessions.find_one({"_id": session_id}))

    def get_sessions_list(
        self,
        user_id: Optional[str],
        status: str = "all",
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        query: dict[str, Any] = {}
        if user_id is not None:
            query["user_id"] = user_id
        if status != "all":
            query["status"] = status
        safe_sort = sort_by if sort_by in {
            "created_at",
            "updated_at",
            "course_title",
        } else "updated_at"
        direction = ASCENDING if sort_order == "asc" else DESCENDING
        cursor = self._sessions.find(query).sort(
            safe_sort,
            direction,
        ).skip(offset).limit(limit)
        rows = [document_to_row(item) or {} for item in cursor]
        return rows, self._sessions.count_documents(query)
```

Implement `get_session_progress`, `update_session_resolved_mode`, and
`update_last_active_node` with `_id` filters and `$set` `updated_at`. Preserve
current exceptions: invalid mode -> `ValueError`; missing session/node ->
`LookupError`.

- [ ] **Step 4: Implement node methods with exact state semantics**

Port `LearningManager._is_valid_transition` as a module-level immutable map.
`create_concept_node` stores `key_terms` as native list and `failed_step` as enum
value. Catch `DuplicateKeyError` and raise `ValueError` from it.

Use conditional update for state transitions:

```python
def update_node_status(
    self,
    node_id: str,
    status: NodeStatus,
) -> Optional[dict[str, Any]]:
    current = self._nodes.find_one({"_id": node_id})
    if current is None:
        return None
    current_status = NodeStatus(current["status"])
    if not self._is_valid_transition(current_status, status):
        raise ValueError(
            f"Invalid status transition: {current_status} -> {status}"
        )
    updated = self._nodes.find_one_and_update(
        {"_id": node_id, "status": current_status.value},
        {"$set": {"status": status.value, "updated_at": utc_iso()}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise ValueError("retry")
    self._update_session_progress(updated["learning_session_id"])
    return document_to_row(updated)
```

Implement all remaining node methods from Protocol:

| Method | Mongo operation |
|--------|-----------------|
| `create_concept_node` | `insert_one`, string UUID `_id` |
| `get_session_nodes` | find by `learning_session_id`, sort sequence asc |
| `get_concept_node` | find `_id` |
| `get_next_node` | find session with `sequence_index > current`, sort/limit 1 |
| `update_node_content` | conditional status/content/error `$set` |
| `replace_node_content` | unconditional content/status `$set`, `$unset` errors |
| `_update_session_progress` | count total/ready; update percent/status |

Return `document_to_row` shapes and use existing `NodeStatus` values exactly.

- [ ] **Step 5: Run session/node tests and verify GREEN**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_learning.MongoLearningTests -v
```

Expected: session and node tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/database/repositories/mongo_learning.py \
  server/tests/test_mongo_learning.py
git commit -m "feat(storage): add Mongo session and node persistence"
```

## Task 3: Quiz And Revision Parity

**Files:**
- Modify: `server/database/repositories/mongo_learning.py`
- Modify: `server/tests/test_mongo_learning.py`

- [ ] **Step 1: Add failing quiz/revision tests**

Append tests covering native payloads and revision relationships:

```python
def test_create_quiz_set_stores_native_payload(self) -> None:
    quiz_set = make_quiz_set()
    self.repository.create_quiz_set("n1", quiz_set, "seed")
    update = self.database["quiz_data"].\
        replace_one.call_args.args[1]
    self.assertIsInstance(update["payload"], dict)
    self.assertEqual(update["format_version"], 1)
    self.assertEqual(update["shuffle_seed"], "seed")

def test_create_attempt_uses_next_attempt_number(self) -> None:
    attempts = self.database["quiz_attempts"]
    attempts.count_documents.return_value = 2
    self.database["quiz_data"].find_one.return_value = {
        "node_id": "n1",
        "payload": make_quiz_set().model_dump(mode="json"),
    }
    result = self.repository.create_quiz_attempt(
        "n1",
        ["option-1"],
    )
    inserted = attempts.insert_one.call_args.args[0]
    self.assertEqual(inserted["attempt_number"], 3)
    self.assertEqual(inserted["selected_option_id"], ["option-1"])
    self.assertEqual(result["attempt_number"], 3)

def test_create_revision_clones_all_node_progress(self) -> None:
    self.database["learning_sessions"].find_one.return_value = {
        "_id": "s1",
        "status": "completed",
    }
    self.database["revision_sessions"].count_documents.return_value = 0
    self.database["concept_nodes"].find.return_value = [
        {"_id": "n1"},
        {"_id": "n2"},
    ]
    revision = self.repository.create_revision_session(
        "s1",
        "full_review",
    )
    inserts = self.database["revision_node_progress"].\
        insert_many.call_args.args[0]
    self.assertEqual(len(inserts), 2)
    self.assertEqual(revision["revision_number"], 1)
```

Reuse valid `make_quiz_set()` fixture from existing learning tests or define it
with actual `QuizSet`/question/option constructors used in this repository.

- [ ] **Step 2: Run tests and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_learning -v
```

Expected: FAIL because quiz/revision methods are absent.

- [ ] **Step 3: Implement quiz persistence**

Use one quiz document per node and native Pydantic payload:

```python
def create_quiz_set(
    self,
    node_id: str,
    quiz_set: QuizSet,
    shuffle_seed: Optional[str] = None,
) -> dict[str, Any]:
    now = utc_iso()
    document = {
        "_id": str(uuid.uuid4()),
        "node_id": node_id,
        "payload": model_payload(quiz_set),
        "format_version": 1,
        "shuffle_seed": shuffle_seed,
        "current_index": 0,
        "created_at": now,
        "updated_at": now,
    }
    self._quizzes.replace_one(
        {"node_id": node_id},
        document,
        upsert=True,
    )
    return document_to_row(document) or {}
```

Implement `get_quiz_set_for_node`, legacy `get_quiz_for_node`, shuffle seed,
increment/decrement progress, attempts, and mastery using existing conversion
helper `convert_legacy_quiz_card`. Store `selected_option_id` as native list,
but return exact current API key and score/mastery fields. Validate answers using
Pydantic quiz payload, not Mongo positional assumptions.

- [ ] **Step 4: Implement revisions**

Use these operations:

| Method | Mongo behavior |
|--------|----------------|
| `create_revision_session` | validate completed original; insert session; insert progress docs |
| `get_revisions_for_session` | query original, sort revision desc, paginate/count |
| `get_revision_session` | find revision plus sorted progress list |
| `delete_revision_session` | delete attempts by revision, progress, then revision |
| `mark_revision_node_reviewed` | conditional progress update; recalc revision |
| `submit_revision_quiz` | create linked attempt; set pass/fail; recalc |
| `get_revision_summary` | aggregate progress and attempts in Python |

Revision progress recalculation must use one aggregation result and update:

```python
self._revisions.update_one(
    {"_id": revision_id},
    {
        "$set": {
            "progress_percent": progress_percent,
            "status": next_status,
            "completed_at": completed_at,
        }
    },
)
```

Match current rules: `full_review` permits reviewed status; `quiz_only` advances
through quiz results; missing revision/node raises `LookupError`.

- [ ] **Step 5: Run Mongo and SQLite learning tests**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_learning \
  server.tests.test_majors_m1_m8 \
  server.tests.test_generation_persistence_integration -v
```

Expected: PASS. Existing SQLite behavior remains unchanged.

- [ ] **Step 6: Commit**

```bash
git add server/database/repositories/mongo_learning.py \
  server/tests/test_mongo_learning.py
git commit -m "feat(storage): add Mongo quiz and revision persistence"
```

## Task 4: Application-Level Cascade Delete

**Files:**
- Modify: `server/database/repositories/mongo_learning.py`
- Modify: `server/tests/test_mongo_learning.py`

- [ ] **Step 1: Write failing cascade-order test**

Append:

```python
def test_delete_session_removes_all_dependent_documents(self) -> None:
    self.database["concept_nodes"].find.return_value = [
        {"_id": "n1"},
        {"_id": "n2"},
    ]
    self.database["revision_sessions"].find.return_value = [
        {"_id": "r1"}
    ]
    self.database["research_reports"].find.return_value = [
        {"_id": "report-1"}
    ]
    self.database["research_sections"].find.return_value = [
        {"_id": "section-1"}
    ]
    self.database["learning_sessions"].delete_one.return_value.\
        deleted_count = 1

    deleted = self.repository.delete_learning_session("s1")

    self.assertTrue(deleted)
    self.database["quiz_data"].delete_many.assert_called_once_with(
        {"node_id": {"$in": ["n1", "n2"]}}
    )
    self.database["research_section_sources"].delete_many.\
        assert_called_once_with(
            {"section_id": {"$in": ["section-1"]}}
        )
    self.database["progress_events"].delete_many.assert_called_once_with(
        {"session_id": "s1"}
    )
```

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_learning.\
MongoLearningTests.test_delete_session_removes_all_dependent_documents -v
```

Expected: FAIL because cascade is absent/incomplete.

- [ ] **Step 3: Implement idempotent child-first cascade**

Implement exact child-first sequence. Every `delete_many` is retry-safe; no
giant transaction is required:

```python
def delete_learning_session(self, session_id: str) -> bool:
    node_ids = [
        item["_id"]
        for item in self._nodes.find(
            {"learning_session_id": session_id},
            {"_id": 1},
        )
    ]
    revision_ids = [
        item["_id"]
        for item in self._revisions.find(
            {"original_session_id": session_id},
            {"_id": 1},
        )
    ]
    reports = self._db["research_reports"]
    report_ids = [
        item["_id"]
        for item in reports.find({"session_id": session_id}, {"_id": 1})
    ]
    sections = self._db["research_sections"]
    section_ids = [
        item["_id"]
        for item in sections.find(
            {"report_id": {"$in": report_ids}},
            {"_id": 1},
        )
    ] if report_ids else []

    if section_ids:
        self._db["research_section_sources"].delete_many(
            {"section_id": {"$in": section_ids}}
        )
    if report_ids:
        self._db["research_provider_statuses"].delete_many(
            {"report_id": {"$in": report_ids}}
        )
        sections.delete_many({"report_id": {"$in": report_ids}})
    self._db["research_sources"].delete_many({"session_id": session_id})
    reports.delete_many({"session_id": session_id})

    if revision_ids:
        self._attempts.delete_many(
            {"revision_session_id": {"$in": revision_ids}}
        )
        self._revision_nodes.delete_many(
            {"revision_session_id": {"$in": revision_ids}}
        )
        self._revisions.delete_many({"_id": {"$in": revision_ids}})
    if node_ids:
        self._attempts.delete_many({"node_id": {"$in": node_ids}})
        self._quizzes.delete_many({"node_id": {"$in": node_ids}})
        self._db["node_sources"].delete_many(
            {"node_id": {"$in": node_ids}}
        )
        self._db["generation_briefs"].delete_many(
            {"node_id": {"$in": node_ids}}
        )
        self._nodes.delete_many({"_id": {"$in": node_ids}})

    self._db["generation_jobs"].delete_many({"session_id": session_id})
    self._db["progress_events"].delete_many({"session_id": session_id})
    result = self._sessions.delete_one({"_id": session_id})
    return result.deleted_count > 0
```

Also delete `generation_briefs` by `session_id` after node branch so malformed
or legacy orphan briefs are removed.

- [ ] **Step 4: Run Phase 3A tests and regressions**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_common \
  server.tests.test_mongo_learning \
  server.tests.test_learning_graph_router \
  server.tests.test_generation_persistence_integration -v
```

Expected: PASS without network.

- [ ] **Step 5: Commit**

```bash
git add server/database/repositories/mongo_learning.py \
  server/tests/test_mongo_learning.py
git commit -m "feat(storage): cascade Mongo learning session deletes"
```

## Phase 3A Exit Checkpoint

- [ ] `MongoLearningRepository` satisfies `LearningRepository` at runtime.
- [ ] All six learning collections use current string IDs and API shapes.
- [ ] JSON quiz/key-term fields are native BSON, not JSON strings.
- [ ] State updates use compare predicates where SQLite used transitions.
- [ ] Cascade covers generation, research, revision, quiz, and progress children.
- [ ] Add phase note:

```bash
git notes add -m "Phase 3A complete: Mongo learning repository and cascade"
```
