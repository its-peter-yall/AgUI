# Internet-Grounded Course Generation Implementation Plan — Phase 5: Async API, SSE, Research & Controls

> **Planning method:** I used writing-plans skill principles: TDD, bite-sized tasks, exact paths, and no placeholders.
>
> **For agentic workers:** REQUIRED: TDD via test-driven-development skill; execute via executing-plans or subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** Expose immediate `202` generation, poll-compatible session snapshots, replayable SSE, visible research, cooperative cancellation, resumable work, and explicit permanent deletion.

**Architecture:** Router validates ephemeral LLM/search headers, atomically creates shell/job, and delegates detached execution to a lifespan-scoped runtime that strongly references tasks. SQLite events remain source of truth; SSE replays then tails by cursor and never owns generation lifetime. Session polling joins job counts/warnings/skeletons/citations but never private briefs. Resume supplies fresh credentials; delete is the only permanent cleanup path.

**Tech Stack:** FastAPI, Pydantic v2, raw `StreamingResponse` SSE for compatibility with unpinned current FastAPI requirement, `asyncio`, SQLite focused stores, React-query-compatible JSON contracts.

**Depends on:** Phase 4.

**Deliverable:** Stable HTTP contract for progressive generation with secrets accepted only on generate/resume, `Last-Event-ID` replay, two-second polling compatibility, retained cancelled artifacts, and no disconnect-triggered cancellation.

## API Contract

| Method | Path | Status | Search credentials | Behavior |
|---|---|---:|---|---|
| `POST` | `/learning/generate` | `202` | Required only when `X-Web-Search: true` | Create shell/job and start detached graph. |
| `GET` | `/learning/sessions/{id}` | `200` | Never | Pollable shell, stage, counts, warnings, skeletons/cards/citations. |
| `GET` | `/learning/sessions/{id}/events?after=N` | `200` SSE | Never | Replay IDs greater than cursor, then tail. |
| `GET` | `/learning/sessions/{id}/research` | `200` | Never | Partial/final public report and normalized sources. |
| `POST` | `/learning/sessions/{id}/cancel` | `202` | Never | Set cooperative cancel flag; retain artifacts. |
| `POST` | `/learning/sessions/{id}/resume` | `202` | Fresh search keys only if research remains | Restore persisted stage and schedule same graph thread. |
| `DELETE` | `/learning/sessions/{id}` | `200` | Never | Stop local work, delete session artifacts and checkpoint. |

Search request headers:

```http
X-Web-Search: true|false
X-Web-Search-Providers: tavily,exa,brave,serpapi
X-Tavily-Key: value
X-Exa-Key: value
X-Brave-Key: value
X-SerpApi-Key: value
```

Keys never appear in response, log message, SQLite row, checkpoint, event, report, warning, or error detail.

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `server/schemas/search.py` | Strict FastAPI header dependency producing excluded runtime `SearchContext`. |
| Modify | `server/schemas/generation.py` | Public job, accepted response, control response, and event envelope models. |
| Modify | `server/schemas/research.py` | Public report response projection. |
| Modify | `server/schemas/learning.py` | Provisional-title, module generation status, citations, and generation snapshot fields. |
| Create | `server/services/generation_runtime.py` | Strong task registry, detached start/resume, shutdown pause, and delete coordination. |
| Create | `server/services/session_event_stream.py` | Replay-then-tail SSE framing and heartbeat. |
| Modify | `server/database/generation_jobs.py` | Public job projection and shell/status reads. |
| Modify | `server/database/research_store.py` | Public report and bulk citation projections. |
| Modify | `server/database/progress_events.py` | Replay API and terminal checks. |
| Modify | `server/routers/learning.py` | Replace blocking generation; add status/events/research/cancel/resume. |
| Modify | `server/main.py` | Construct/close `GenerationRuntime`; pause unfinished jobs at startup/shutdown. |
| Modify | `server/tests/test_learning_graph_router.py` | Remove temporary Phase 4 `201` compatibility tests. |
| Create | `server/tests/test_search_context.py` | Search header validation/redaction tests. |
| Create | `server/tests/test_generation_api.py` | `202`, research, validation, and secret-boundary tests. |
| Create | `server/tests/test_generation_runtime.py` | Detached task and lifecycle tests. |
| Create | `server/tests/test_generation_session_view.py` | Progressive polling projection tests. |
| Create | `server/tests/test_session_events.py` | SSE ordering, reconnect, heartbeat, terminal, disconnect tests. |
| Create | `server/tests/test_generation_controls.py` | Cancel/resume/duplicate/delete tests. |

## Tasks

### Task 5.1: Parse Runtime-Only Search Headers and Add Public API Models

**Files:**
- Modify: `server/schemas/search.py`
- Modify: `server/schemas/generation.py`
- Modify: `server/schemas/research.py`
- Modify: `server/schemas/learning.py`
- Create: `server/tests/test_search_context.py`

- [ ] **Step 1: Write failing search-header tests**

Create `server/tests/test_search_context.py`:

```python
"""
============================================================================
FILE: test_search_context.py
LOCATION: server/tests/test_search_context.py
============================================================================
PURPOSE:
    Tests strict web-search header parsing and runtime secret exclusion.
ROLE IN PROJECT:
    Defines credential boundary used only by generate and resume endpoints.
KEY COMPONENTS:
    - SearchContextHeaderTests: Off, on, missing, unknown, duplicate tests
DEPENDENCIES:
    - External: fastapi, unittest
    - Internal: server.schemas.search
USAGE:
    python -m unittest server.tests.test_search_context -v
============================================================================
"""

from __future__ import annotations

import unittest
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from server.schemas.search import SearchContext, get_search_context
from server.search.types import SearchProviderId


app = FastAPI()


@app.get("/context")
async def read_context(
    context: Annotated[SearchContext, Depends(get_search_context)],
) -> dict[str, object]:
    return {
        "enabled": context.enabled,
        "provider_ids": [item.value for item in context.provider_ids],
        "dump": context.model_dump(mode="json"),
    }


class SearchContextHeaderTests(unittest.TestCase):
    """Tests request-scoped search header validation."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_default_and_explicit_off_return_no_credentials(self) -> None:
        for headers in ({}, {"X-Web-Search": "false", "X-Tavily-Key": "ignored"}):
            with self.subTest(headers=headers):
                response = self.client.get("/context", headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()["enabled"])
                self.assertEqual(response.json()["provider_ids"], [])
                self.assertNotIn("ignored", response.text)

    def test_enabled_context_deduplicates_and_excludes_keys(self) -> None:
        response = self.client.get(
            "/context",
            headers={
                "X-Web-Search": "true",
                "X-Web-Search-Providers": "tavily,exa,tavily",
                "X-Tavily-Key": "tvly-secret",
                "X-Exa-Key": "exa-secret",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["provider_ids"], ["tavily", "exa"])
        self.assertNotIn("tvly-secret", response.text)
        self.assertNotIn("exa-secret", response.text)
        self.assertNotIn("credentials", response.json()["dump"])

    def test_missing_selected_key_returns_safe_401(self) -> None:
        response = self.client.get(
            "/context",
            headers={
                "X-Web-Search": "true",
                "X-Web-Search-Providers": "brave",
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "X-Brave-Key header is missing.")

    def test_unknown_provider_and_invalid_flag_return_400(self) -> None:
        unknown = self.client.get(
            "/context",
            headers={
                "X-Web-Search": "true",
                "X-Web-Search-Providers": "unknown",
            },
        )
        invalid = self.client.get(
            "/context",
            headers={"X-Web-Search": "sometimes"},
        )
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(
            unknown.json()["detail"],
            "Unsupported web search provider: unknown",
        )
        self.assertEqual(invalid.status_code, 400)

    def test_context_returns_plain_key_only_through_explicit_method(self) -> None:
        context = SearchContext.from_plaintext_credentials(
            enabled=True,
            provider_ids=[SearchProviderId.SERPAPI],
            credentials={SearchProviderId.SERPAPI: "serp-secret"},
        )
        self.assertEqual(
            context.get_api_key(SearchProviderId.SERPAPI),
            "serp-secret",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify red state**

Run from `D:\Peter\A2UI`:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_search_context -v
```

Expected: FAIL because `get_search_context` does not exist.

- [ ] **Step 3: Implement dependency and public response contracts**

Add `get_search_context()` to `server/schemas/search.py` using `Header` aliases for all six search headers. Accept absent as false; accept case-insensitive exact `true`/`false`; reject other values with 400. When false, return empty context and ignore supplied key headers. When true, require nonempty CSV, reject unknown IDs, deduplicate preserving client order, require each selected key, trim keys, and construct `SearchContext.from_plaintext_credentials()`.

Add public models to `server/schemas/generation.py`:

```text
GenerationJobPublic(id, session_id, stage, web_search_requested,
                    grounding_status, counts, warnings, cancel_requested,
                    can_cancel, can_resume, last_event_id, created_at, updated_at)
GenerateCourseAcceptedResponse(session, generation)
GenerationControlResponse(generation)
GenerationEventEnvelope(id, session_id, event_type, payload,
                        generation, created_at)
```

`can_cancel` is true only for nonterminal/nonpaused stages. `can_resume` is true only for `PAUSED`/`CANCELLED`. No cursor, thread ID, lock, brief, report internals, or credential fields are public.

Add to learning schemas:

```python
class ModuleGenerationStatus(str, Enum):
    SKELETON = "SKELETON"
    GENERATING = "GENERATING"
    READY = "READY"
    ERROR = "ERROR"
```

`ConceptNodeResponse` gains `module_status` and `citations: list[PublicNodeCitation]`; `LearningSessionResponse` gains `title_finalized: bool`; router-local `LearningSessionWithNodes` gains `generation: Optional[GenerationJobPublic]`. Existing sessions without generation jobs serialize `generation=null`, `title_finalized=true`, and nodes `READY`.

Public research response uses existing `ResearchReport` fields but excludes canonical URL/content hash and exposes only normalized source metadata/excerpt, provider status, limitations, warnings, and timestamps.

- [ ] **Step 4: Run schema/header tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_search_context server.tests.test_generation_contracts server.tests.test_research_progress_contracts server.tests.test_learning_schemas -v
```

Expected: all targeted tests PASS.

- [ ] **Step 5: Commit API contracts**

```powershell
git add server/schemas/search.py server/schemas/generation.py server/schemas/research.py server/schemas/learning.py server/tests/test_search_context.py
git commit -m "feat(api): add progressive generation contracts"
```

### Task 5.2: Return `202` Shell and Run Detached Generation

**Files:**
- Create: `server/services/generation_runtime.py`
- Modify: `server/routers/learning.py`
- Modify: `server/main.py`
- Modify: `server/database/generation_jobs.py`
- Create: `server/tests/test_generation_api.py`
- Create: `server/tests/test_generation_runtime.py`
- Modify: `server/tests/test_learning_graph_router.py`

- [ ] **Step 1: Write failing `202` and detached-runtime tests**

Create `server/tests/test_generation_api.py`:

```python
"""
============================================================================
FILE: test_generation_api.py
LOCATION: server/tests/test_generation_api.py
============================================================================
PURPOSE:
    Tests immediate generation acceptance and research API contracts.
ROLE IN PROJECT:
    Replaces blocking generation HTTP behavior with durable shell creation.
KEY COMPONENTS:
    - GenerationApiTests: 202, validation, and secret-boundary tests
DEPENDENCIES:
    - External: fastapi, unittest
    - Internal: server.routers.learning
USAGE:
    python -m unittest server.tests.test_generation_api -v
============================================================================
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routers.learning import router
from server.schemas.llm import LLMContext, get_llm_context


def _accepted() -> dict[str, object]:
    return {
        "session": {
            "id": "session-1",
            "user_id": None,
            "query": "Modern CSS",
            "course_title": "Modern CSS",
            "title_finalized": False,
            "mode": "auto",
            "resolved_mode": None,
            "total_nodes": 0,
            "completed_nodes": 0,
            "last_active_node_id": None,
            "created_at": "2026-08-01T12:00:00+00:00",
            "updated_at": "2026-08-01T12:00:00+00:00",
            "nodes": [],
        },
        "generation": {
            "id": "job-1",
            "session_id": "session-1",
            "stage": "INITIALIZING",
            "web_search_requested": True,
            "grounding_status": "PENDING",
            "counts": {
                "topics_total": 0,
                "briefs_ready": 0,
                "topics_ready": 0,
                "topics_failed": 0,
                "research_sections": 0,
                "sources": 0,
            },
            "warnings": [],
            "cancel_requested": False,
            "can_cancel": True,
            "can_resume": False,
            "last_event_id": 1,
            "created_at": "2026-08-01T12:00:00+00:00",
            "updated_at": "2026-08-01T12:00:00+00:00",
        },
    }


class GenerationApiTests(unittest.TestCase):
    """Tests accepted-shell route and runtime context boundary."""

    def test_generate_returns_202_before_job_finishes_without_secrets(self) -> None:
        app = FastAPI()
        runtime = SimpleNamespace(start=AsyncMock(return_value=_accepted()))
        app.state.generation_runtime = runtime
        app.include_router(router)
        app.dependency_overrides[get_llm_context] = lambda: LLMContext(
            api_key="llm-secret",
            model="test/model",
        )
        with TestClient(app) as client:
            response = client.post(
                "/learning/generate",
                json={"query": "Modern CSS", "mode": "auto"},
                headers={
                    "X-Web-Search": "true",
                    "X-Web-Search-Providers": "tavily",
                    "X-Tavily-Key": "search-secret",
                },
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), _accepted())
        self.assertNotIn("llm-secret", response.text)
        self.assertNotIn("search-secret", response.text)
        call = runtime.start.await_args.kwargs
        self.assertEqual(call["llm_context"].api_key, "llm-secret")
        self.assertEqual(
            call["search_context"].get_api_key(call["search_context"].provider_ids[0]),
            "search-secret",
        )

    def test_invalid_mode_still_returns_422_without_starting_job(self) -> None:
        app = FastAPI()
        runtime = SimpleNamespace(start=AsyncMock())
        app.state.generation_runtime = runtime
        app.include_router(router)
        app.dependency_overrides[get_llm_context] = lambda: LLMContext(
            api_key="llm-key",
            model="test/model",
        )
        with TestClient(app) as client:
            response = client.post(
                "/learning/generate",
                json={"query": "Topic", "mode": "turbo"},
            )
        self.assertEqual(response.status_code, 422)
        runtime.start.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
```

Create `server/tests/test_generation_runtime.py`:

```python
"""
============================================================================
FILE: test_generation_runtime.py
LOCATION: server/tests/test_generation_runtime.py
============================================================================
PURPOSE:
    Tests detached generation task ownership and lifecycle reconciliation.
ROLE IN PROJECT:
    Ensures browser/SSE disconnect cannot own or cancel durable work.
KEY COMPONENTS:
    - GenerationRuntimeTests: Immediate start, task refs, shutdown tests
DEPENDENCIES:
    - External: asyncio, unittest, unittest.mock
    - Internal: server.services.generation_runtime
USAGE:
    python -m unittest server.tests.test_generation_runtime -v
============================================================================
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from server.schemas.llm import LLMContext
from server.schemas.search import SearchContext
from server.services.generation_runtime import GenerationRuntime


class GenerationRuntimeTests(unittest.IsolatedAsyncioTestCase):
    """Tests detached job ownership independent of HTTP connections."""

    async def test_start_returns_shell_while_runner_is_blocked(self) -> None:
        gate = asyncio.Event()

        async def blocked_runner(**kwargs):
            await gate.wait()

        jobs = MagicMock()
        jobs.create_session_shell_and_job.return_value = (
            {"id": "session-1", "nodes": []},
            SimpleNamespace(id="job-1", session_id="session-1"),
        )
        jobs.to_public.return_value = {"id": "job-1"}
        runtime = GenerationRuntime(
            app_state=SimpleNamespace(),
            job_store=jobs,
            runner=blocked_runner,
        )
        accepted = await runtime.start(
            request_body=SimpleNamespace(
                query="Topic",
                user_id=None,
                mode="auto",
            ),
            llm_context=LLMContext(api_key="llm-key", model="test/model"),
            search_context=SearchContext(),
        )
        self.assertEqual(accepted["session"]["id"], "session-1")
        self.assertEqual(len(runtime.active_tasks), 1)
        self.assertFalse(next(iter(runtime.active_tasks)).done())
        gate.set()
        await asyncio.gather(*runtime.active_tasks)

    async def test_shutdown_does_not_store_contexts_and_marks_jobs_paused(self) -> None:
        jobs = MagicMock()
        runtime = GenerationRuntime(
            app_state=SimpleNamespace(),
            job_store=jobs,
            runner=AsyncMock(),
        )
        await runtime.shutdown()
        jobs.mark_orphaned_jobs_paused.assert_called_once()
        self.assertNotIn("llm_context", runtime.__dict__)
        self.assertNotIn("search_context", runtime.__dict__)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_api.GenerationApiTests server.tests.test_generation_runtime -v
```

Expected: FAIL because route still returns `201`/blocks and runtime does not exist.

- [ ] **Step 3: Implement accepted route and strong task registry**

`GenerationRuntime` keeps only `set[asyncio.Task[None]] active_tasks`, app state, stores, and runner function. `start()`:

1. Atomically calls `create_session_shell_and_job()`.
2. Appends initial `stage_changed` event in same transaction or uses store method that does both.
3. Calls `asyncio.create_task(run_generation_job(...))`.
4. Adds task to set and removes it in done callback after consuming exception.
5. Returns shell and public generation immediately; it never awaits depth routing, research, Planner, Generator, or Quizzer.

Runtime does not retain contexts after passing them into task closure. Task closure lifetime is allowed to hold them ephemerally. `shutdown()` marks unfinished jobs paused, cancels only local process tasks during application shutdown, awaits them with `return_exceptions=True`, and clears set.

Replace `/learning/generate` decorator with `status_code=202`, response model `GenerateCourseAcceptedResponse`, dependencies `get_llm_context` and `get_search_context`, and `request.app.state.generation_runtime.start()`. Remove `_generate_course_with_graph` temporary wrapper and all `Request.is_disconnected` behavior. Query max length becomes 500.

In `main.py`, construct runtime after graph/stores are available and call `await runtime.shutdown()` before checkpointer context closes. Startup marks incomplete prior-process jobs `PAUSED`; it never auto-resumes without fresh secrets.

- [ ] **Step 4: Run generation API/runtime tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_api.GenerationApiTests server.tests.test_generation_runtime server.tests.test_learning_graph_router -v
```

Expected: tests PASS with `202`; no old `201` expectation remains.

- [ ] **Step 5: Commit detached generation API**

```powershell
git add server/services/generation_runtime.py server/routers/learning.py server/main.py server/database/generation_jobs.py server/tests/test_generation_api.py server/tests/test_generation_runtime.py server/tests/test_learning_graph_router.py
git commit -m "feat(api): accept generation as detached job"
```

### Task 5.3: Project Poll-Compatible Progressive Session State

**Files:**
- Modify: `server/routers/learning.py`
- Modify: `server/database/generation_jobs.py`
- Modify: `server/database/research_store.py`
- Create: `server/tests/test_generation_session_view.py`

- [ ] **Step 1: Write failing progressive session projection tests**

Create `server/tests/test_generation_session_view.py`:

```python
"""
============================================================================
FILE: test_generation_session_view.py
LOCATION: server/tests/test_generation_session_view.py
============================================================================
PURPOSE:
    Tests polling snapshots across shell, TOC, preview, batch, and degraded stages.
ROLE IN PROJECT:
    Makes two-second polling a complete repair/fallback channel for SSE clients.
KEY COMPONENTS:
    - GenerationSessionViewTests: Session and node public projection tests
DEPENDENCIES:
    - External: fastapi, unittest, unittest.mock
    - Internal: server.routers.learning
USAGE:
    python -m unittest server.tests.test_generation_session_view -v
============================================================================
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from server.routers.learning import get_learning_session


class GenerationSessionViewTests(unittest.TestCase):
    """Tests progressive session polling projection."""

    def test_shell_and_skeletons_include_generation_but_not_briefs(self) -> None:
        manager = MagicMock()
        manager.get_learning_session.return_value = {
            "id": "session-1",
            "user_id": None,
            "query": "Topic",
            "course_title": "Generated Course",
            "title_finalized": True,
            "mode": "full",
            "resolved_mode": "full",
            "last_active_node_id": None,
            "created_at": "2026-08-01T00:00:00+00:00",
            "updated_at": "2026-08-01T00:00:00+00:00",
            "total_nodes": 2,
            "completed_nodes": 0,
        }
        manager.get_session_nodes.return_value = [
            {
                "id": "node-1",
                "learning_session_id": "session-1",
                "sequence_index": 0,
                "title": "Topic 0",
                "content_markdown": "stored but not ready",
                "status": "LOCKED",
                "generation_status": "GENERATING",
                "error_message": None,
                "retry_available": False,
                "failed_step": None,
                "complexity": "Basic",
                "created_at": "2026-08-01T00:00:00+00:00",
                "updated_at": "2026-08-01T00:00:00+00:00",
                "quiz": None,
            },
            {
                "id": "node-2",
                "learning_session_id": "session-1",
                "sequence_index": 1,
                "title": "Topic 1",
                "content_markdown": "",
                "status": "LOCKED",
                "generation_status": "SKELETON",
                "error_message": None,
                "retry_available": False,
                "failed_step": None,
                "complexity": "Intermediate",
                "created_at": "2026-08-01T00:00:00+00:00",
                "updated_at": "2026-08-01T00:00:00+00:00",
                "quiz": None,
            },
        ]
        jobs = MagicMock()
        jobs.to_public_by_session.return_value = {
            "id": "job-1",
            "session_id": "session-1",
            "stage": "GENERATING_PREVIEW",
            "web_search_requested": False,
            "grounding_status": "DISABLED",
            "counts": {
                "topics_total": 2,
                "briefs_ready": 2,
                "topics_ready": 0,
                "topics_failed": 0,
                "research_sections": 0,
                "sources": 0,
            },
            "warnings": [],
            "cancel_requested": False,
            "can_cancel": True,
            "can_resume": False,
            "last_event_id": 3,
            "created_at": "2026-08-01T00:00:00+00:00",
            "updated_at": "2026-08-01T00:00:00+00:00",
        }
        research = MagicMock()
        research.get_citations_by_session.return_value = {}
        with (
            patch("server.routers.learning.learning_manager", manager),
            patch("server.routers.learning.generation_job_store", jobs),
            patch("server.routers.learning.research_store", research),
        ):
            response = get_learning_session("session-1")
        payload = response.model_dump(mode="json")
        self.assertEqual(payload["generation"]["stage"], "GENERATING_PREVIEW")
        self.assertEqual(payload["nodes"][0]["module_status"], "GENERATING")
        self.assertEqual(payload["nodes"][0]["content_markdown"], "")
        self.assertNotIn("brief", repr(payload))
        self.assertNotIn("source_excerpts", repr(payload))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_session_view -v
```

Expected: FAIL because current session response lacks generation/module status/citations.

- [ ] **Step 3: Implement public projections**

Add `GenerationJobStore.to_public_by_session(session_id)` that derives booleans and last event ID without exposing cursor/thread/lock. Add `ResearchStore.get_citations_by_session(session_id)` as one bulk query joining `node_sources` and `research_sources`, ordered by citation order.

Update session endpoint:

1. Fetch session and nodes as today.
2. Fetch job public status and all citations in two additional queries, not one query per node.
3. Map DB `generation_status` to API `module_status`.
4. For `SKELETON`/`GENERATING`, blank content and all quiz fields regardless of learner status.
5. For `READY`/`ERROR`, retain existing learner visibility/secure quiz behavior.
6. Attach only validated normalized citation metadata.
7. Attach generation status; `null` for old sessions without job.

Extend session-list projection with optional `generation_stage` and `grounding_status` using one bulk job lookup. Do not expose report excerpts or briefs in session/list endpoints.

- [ ] **Step 4: Run session and existing lifecycle tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_session_view server.tests.test_session_lifecycle server.tests.test_learning_router -v
```

Expected: tests PASS.

- [ ] **Step 5: Commit polling projection**

```powershell
git add server/routers/learning.py server/database/generation_jobs.py server/database/research_store.py server/tests/test_generation_session_view.py
git commit -m "feat(api): expose progressive session snapshots"
```

### Task 5.4: Add Replay-Then-Tail SSE Events

**Files:**
- Create: `server/services/session_event_stream.py`
- Modify: `server/routers/learning.py`
- Modify: `server/database/progress_events.py`
- Create: `server/tests/test_session_events.py`

- [ ] **Step 1: Write failing SSE stream tests**

Create `server/tests/test_session_events.py`:

```python
"""
============================================================================
FILE: test_session_events.py
LOCATION: server/tests/test_session_events.py
============================================================================
PURPOSE:
    Tests SSE replay, cursor precedence, heartbeat, terminal close, and isolation.
ROLE IN PROJECT:
    Ensures reconnecting clients observe durable events without owning jobs.
KEY COMPONENTS:
    - SessionEventStreamTests: Async stream behavior
    - SessionEventRouterTests: Header/query cursor contract
DEPENDENCIES:
    - External: fastapi, unittest, unittest.mock
    - Internal: server.services.session_event_stream and learning router
USAGE:
    python -m unittest server.tests.test_session_events -v
============================================================================
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from server.services.session_event_stream import stream_session_events


class SessionEventStreamTests(unittest.IsolatedAsyncioTestCase):
    """Tests replay-then-tail SSE generator."""

    async def test_replays_after_cursor_in_order_and_closes_on_terminal(self) -> None:
        events = MagicMock()
        events.list_after.return_value = [
            SimpleNamespace(
                id=8,
                session_id="session-1",
                event_type=SimpleNamespace(value="module_ready"),
                payload=SimpleNamespace(model_dump=lambda mode: {"node_id": "node-1"}),
                created_at="2026-08-01T00:00:00+00:00",
            ),
            SimpleNamespace(
                id=9,
                session_id="session-1",
                event_type=SimpleNamespace(value="generation_complete"),
                payload=SimpleNamespace(model_dump=lambda mode: {"stage": "COMPLETE"}),
                created_at="2026-08-01T00:00:01+00:00",
            ),
        ]
        jobs = MagicMock()
        jobs.to_public_by_session.return_value = {"stage": "COMPLETE"}
        frames = []
        async for frame in stream_session_events(
            session_id="session-1",
            cursor=7,
            event_store=events,
            job_store=jobs,
            sleep=AsyncMock(),
        ):
            frames.append(frame)
        rendered = "".join(frames)
        self.assertIn("id: 8\n", rendered)
        self.assertIn("event: module_ready\n", rendered)
        self.assertIn("id: 9\n", rendered)
        self.assertIn("event: generation_complete\n", rendered)
        events.list_after.assert_called_once_with("session-1", 7, limit=100)

    async def test_empty_running_stream_emits_heartbeat_without_cancel(self) -> None:
        events = MagicMock()
        events.list_after.return_value = []
        jobs = MagicMock()
        jobs.to_public_by_session.return_value = {"stage": "RESEARCHING"}
        sleep = AsyncMock(side_effect=[None, RuntimeError("stop test")])
        generator = stream_session_events(
            session_id="session-1",
            cursor=0,
            event_store=events,
            job_store=jobs,
            sleep=sleep,
            heartbeat_seconds=0,
        )
        frame = await anext(generator)
        self.assertEqual(frame, ": keepalive\n\n")
        await generator.aclose()
        self.assertFalse(hasattr(jobs, "request_cancel") and jobs.request_cancel.called)

    def test_frame_data_is_valid_json(self) -> None:
        payload = {
            "id": 1,
            "session_id": "session-1",
            "event_type": "stage_changed",
            "payload": {"stage": "OUTLINING"},
        }
        encoded = json.dumps(payload, separators=(",", ":"))
        self.assertEqual(json.loads(encoded), payload)


if __name__ == "__main__":
    unittest.main()
```

Add router-level tests in same file using a small FastAPI app: `after=5` plus `Last-Event-ID: 7` must pass cursor 7 to service; invalid/negative cursor returns 400; unknown session returns 404. Patch stream service to a finite async iterator.

- [ ] **Step 2: Run tests and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_session_events -v
```

Expected: FAIL because event stream service/endpoint do not exist.

- [ ] **Step 3: Implement durable SSE stream**

`stream_session_events()` uses cursor, fetches 100 rows ascending, and emits:

```text
id: 42
event: module_ready
retry: 2000
data: {compact JSON GenerationEventEnvelope}

```

After each event, advance cursor. Close after `generation_complete` or `generation_cancelled`; also close when no rows and persisted stage is `COMPLETE`, `COMPLETE_DEGRADED`, `CANCELLED`, or `FAILED`. When no rows, sleep 0.5 seconds and emit `: keepalive\n\n` at least every 15 seconds. Catch only generator cancellation for cleanup and return; never call graph task cancel, `request_cancel`, or session delete.

Endpoint accepts optional integer query `after` and `Last-Event-ID` header string. Validate nonnegative integers and use `max(after or 0, parsed_header or 0)`. Return raw `StreamingResponse` with media type `text/event-stream` and headers:

```python
{
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}
```

Do not emit `[DONE]` and do not set hop-by-hop `Connection` header.

- [ ] **Step 4: Run SSE tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_session_events -v
```

Expected: all SSE tests PASS.

- [ ] **Step 5: Commit SSE API**

```powershell
git add server/services/session_event_stream.py server/routers/learning.py server/database/progress_events.py server/tests/test_session_events.py
git commit -m "feat(api): stream replayable generation events"
```

### Task 5.5: Add Public Research Report Endpoint

**Files:**
- Modify: `server/routers/learning.py`
- Modify: `server/database/research_store.py`
- Modify: `server/tests/test_generation_api.py`

- [ ] **Step 1: Append complete research endpoint tests**

Append to `server/tests/test_generation_api.py`:

```python
class ResearchApiTests(unittest.TestCase):
    """Tests public research report projection."""

    def test_web_off_returns_not_requested_report(self) -> None:
        app = FastAPI()
        app.include_router(router)
        app.state.generation_runtime = SimpleNamespace()
        with (
            patch(
                "server.routers.learning.learning_manager.get_learning_session",
                return_value={"id": "session-1"},
            ),
            patch(
                "server.routers.learning.generation_job_store.get_by_session",
                return_value=SimpleNamespace(web_search_requested=False),
            ),
        ):
            with TestClient(app) as client:
                response = client.get(
                    "/learning/sessions/session-1/research"
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "NOT_REQUESTED")
        self.assertEqual(response.json()["sections"], [])
        self.assertEqual(response.json()["sources"], [])

    def test_report_response_omits_private_and_secret_fields(self) -> None:
        public_report = {
            "id": "report-1",
            "session_id": "session-1",
            "status": "DEGRADED",
            "summary": "Partial current research.",
            "limitations": ["Provider unavailable."],
            "freshness_note": "Retrieved 2026-08-01.",
            "sections": [],
            "sources": [
                {
                    "id": "source-1",
                    "title": "Current docs",
                    "url": "https://example.com/docs",
                    "publisher": "Example",
                    "published_at": None,
                    "retrieved_at": "2026-08-01T00:00:00+00:00",
                    "provider_id": "tavily",
                    "snippet": "Current docs.",
                    "excerpt": "Current evidence.",
                    "relevance_score": 0.9,
                }
            ],
            "provider_statuses": [],
            "warnings": [],
            "created_at": "2026-08-01T00:00:00+00:00",
            "updated_at": "2026-08-01T00:00:00+00:00",
        }
        app = FastAPI()
        app.include_router(router)
        with (
            patch(
                "server.routers.learning.learning_manager.get_learning_session",
                return_value={"id": "session-1"},
            ),
            patch(
                "server.routers.learning.generation_job_store.get_by_session",
                return_value=SimpleNamespace(web_search_requested=True),
            ),
            patch(
                "server.routers.learning.research_store.get_public_report",
                return_value=public_report,
            ),
        ):
            with TestClient(app) as client:
                response = client.get(
                    "/learning/sessions/session-1/research"
                )
        self.assertEqual(response.status_code, 200)
        rendered = response.text.lower()
        self.assertNotIn("canonical_url", rendered)
        self.assertNotIn("content_hash", rendered)
        self.assertNotIn("brief", rendered)
        self.assertNotIn("api_key", rendered)
```

- [ ] **Step 2: Run research API tests and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_api.ResearchApiTests -v
```

Expected: FAIL with 404 because research endpoint does not exist.

- [ ] **Step 3: Implement public research projection**

Add `GET /sessions/{session_id}/research` with response model `ResearchReport`. Return 404 for missing session. For legacy/web-off job, return deterministic `NOT_REQUESTED` empty report using session timestamps. If web requested but report row not created yet, return `PENDING` empty report. Otherwise `ResearchStore.get_public_report()` joins ordered sections, section source IDs, normalized sources, provider statuses, warnings, and timestamps.

Omit canonical URL, content hash, raw search body, query plan, pending queries, budget cursor, private brief excerpts, and credentials. Allow partial sections/sources while status is `RESEARCHING`, `CANCELLED`, or `DEGRADED`.

- [ ] **Step 4: Run research API tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_api.ResearchApiTests -v
```

Expected: tests PASS.

- [ ] **Step 5: Commit research endpoint**

```powershell
git add server/routers/learning.py server/database/research_store.py server/tests/test_generation_api.py
git commit -m "feat(api): expose course research reports"
```

### Task 5.6: Add Cancel, Resume, and Permanent Delete Controls

**Files:**
- Modify: `server/services/generation_runtime.py`
- Modify: `server/routers/learning.py`
- Modify: `server/database/generation_jobs.py`
- Create: `server/tests/test_generation_controls.py`

- [ ] **Step 1: Write failing lifecycle control tests**

Create `server/tests/test_generation_controls.py`:

```python
"""
============================================================================
FILE: test_generation_controls.py
LOCATION: server/tests/test_generation_controls.py
============================================================================
PURPOSE:
    Tests retained cancellation, fresh-credential resume, and permanent delete.
ROLE IN PROJECT:
    Separates cooperative stop from explicit irreversible cleanup.
KEY COMPONENTS:
    - GenerationControlTests: Cancel, resume conflict, credential, delete tests
DEPENDENCIES:
    - External: fastapi, unittest, unittest.mock
    - Internal: server.routers.learning and generation runtime
USAGE:
    python -m unittest server.tests.test_generation_controls -v
============================================================================
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routers.learning import router
from server.schemas.llm import LLMContext, get_llm_context


def _client(runtime) -> TestClient:
    app = FastAPI()
    app.state.generation_runtime = runtime
    app.state.checkpointer = SimpleNamespace(adelete_thread=AsyncMock())
    app.include_router(router)
    app.dependency_overrides[get_llm_context] = lambda: LLMContext(
        api_key="fresh-llm-key",
        model="test/model",
    )
    return TestClient(app)


class GenerationControlTests(unittest.TestCase):
    """Tests cancel/resume/delete HTTP semantics."""

    def test_cancel_returns_202_and_does_not_delete_partial_artifacts(self) -> None:
        runtime = SimpleNamespace(
            cancel=AsyncMock(return_value={"generation": {"stage": "RESEARCHING"}})
        )
        with (
            patch(
                "server.routers.learning.learning_manager.get_learning_session",
                return_value={"id": "session-1"},
            ),
            patch(
                "server.routers.learning.learning_manager.delete_learning_session"
            ) as delete,
        ):
            with _client(runtime) as client:
                response = client.post(
                    "/learning/sessions/session-1/cancel"
                )
        self.assertEqual(response.status_code, 202)
        runtime.cancel.assert_awaited_once_with("session-1")
        delete.assert_not_called()

    def test_resume_passes_fresh_context_and_returns_202(self) -> None:
        runtime = SimpleNamespace(
            resume=AsyncMock(
                return_value={"generation": {"stage": "RESEARCHING"}}
            )
        )
        with patch(
            "server.routers.learning.learning_manager.get_learning_session",
            return_value={"id": "session-1"},
        ):
            with _client(runtime) as client:
                response = client.post(
                    "/learning/sessions/session-1/resume",
                    headers={
                        "X-Web-Search": "true",
                        "X-Web-Search-Providers": "exa",
                        "X-Exa-Key": "fresh-search-key",
                    },
                )
        self.assertEqual(response.status_code, 202)
        call = runtime.resume.await_args.kwargs
        self.assertEqual(call["llm_context"].api_key, "fresh-llm-key")
        self.assertEqual(
            call["search_context"].get_api_key(
                call["search_context"].provider_ids[0]
            ),
            "fresh-search-key",
        )

    def test_duplicate_resume_maps_to_409(self) -> None:
        from server.graph.runner import GenerationAlreadyRunning

        runtime = SimpleNamespace(
            resume=AsyncMock(side_effect=GenerationAlreadyRunning("session-1"))
        )
        with patch(
            "server.routers.learning.learning_manager.get_learning_session",
            return_value={"id": "session-1"},
        ):
            with _client(runtime) as client:
                response = client.post(
                    "/learning/sessions/session-1/resume"
                )
        self.assertEqual(response.status_code, 409)

    def test_delete_is_only_endpoint_that_removes_session(self) -> None:
        runtime = SimpleNamespace(stop_for_delete=AsyncMock())
        with (
            patch(
                "server.routers.learning.learning_manager.get_learning_session",
                return_value={"id": "session-1"},
            ),
            patch(
                "server.routers.learning.learning_manager.delete_learning_session",
                return_value=True,
            ) as delete,
        ):
            with _client(runtime) as client:
                response = client.delete(
                    "/learning/sessions/session-1"
                )
        self.assertEqual(response.status_code, 200)
        runtime.stop_for_delete.assert_awaited_once_with("session-1")
        delete.assert_called_once_with("session-1")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run control tests and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_controls -v
```

Expected: FAIL because cancel/resume routes and runtime methods do not exist.

- [ ] **Step 3: Implement retained controls**

`GenerationRuntime.cancel(session_id)` validates nonterminal job, calls `request_cancel`, and returns public state. It does not cancel active LLM task; runner checks flag at next cooperative boundary and marks retained `CANCELLED`.

`resume()` validates stage is `PAUSED` or `CANCELLED`, checks whether report remains `PENDING`/`RESEARCHING`, and requires `SearchContext.enabled` with credentials only in that case. If research is already `COMPLETE`/`DEGRADED`, ignore absent search credentials. It calls `prepare_resume`, schedules same stable thread with `resume=True`, and maps lock conflict to 409. `COMPLETE`, `COMPLETE_DEGRADED`, `FAILED`, and running stages return 409.

`stop_for_delete()` sets cancel, waits up to two seconds for cooperative boundary, then cancels only this process's matching task if still active and awaits it. Delete endpoint then calls existing session delete; foreign keys cascade focused artifacts. Finally call `await checkpointer.adelete_thread(f"gen-{session_id}")`. Return 404 for absent session.

Convert existing delete endpoint to async. Keep user-facing error details generic and log internals without contexts/headers. SSE disconnect and browser navigation never invoke any control method.

- [ ] **Step 4: Run API/control and full server tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_controls server.tests.test_generation_api server.tests.test_generation_runtime server.tests.test_generation_session_view server.tests.test_session_events -v
server\.venv\Scripts\python.exe -m unittest
```

Expected: targeted and full suites PASS.

- [ ] **Step 5: Commit controls**

```powershell
git add server/services/generation_runtime.py server/routers/learning.py server/database/generation_jobs.py server/tests/test_generation_controls.py
git commit -m "feat(api): add retained generation controls"
```

## Phase Checkpoint

- [ ] Verify route table and statuses:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_api server.tests.test_generation_session_view server.tests.test_session_events server.tests.test_generation_controls -v
```

- [ ] Verify old blocking helper, background tail, and disconnect checks are absent:

```powershell
rg "_generate_course_with_graph|_generate_remaining_nodes_bg|is_disconnected|delete_learning_session\(session_id\).*disconnect" server/routers/learning.py
```

Expected: no matches.

- [ ] Verify search header dependency appears only on generate/resume routes:

```powershell
rg "get_search_context" server/routers/learning.py
```

Expected: two dependency uses: `generate_course` and `resume_generation`.

- [ ] Record checkpoint:

```powershell
git notes add -m "Phase 5 complete: 202 API, SSE, research, cancel, and resume verified"
```
