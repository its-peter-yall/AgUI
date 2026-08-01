# Internet-Grounded Course Generation Implementation Plan - Phase 7: Integration Hardening, Security & Release Gates

> **Planning method:** I used writing-plans skill principles: TDD, bite-sized tasks, exact paths, and no placeholders.
>
> **For agentic workers:** REQUIRED: TDD via test-driven-development skill; execute via executing-plans or subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** Prove complete Internet-grounded generation flow across server, browser, persistence, recovery, and streaming boundaries; close stale-state and unsafe-logging gaps; enforce focused coverage; and document operation before release.

**Architecture:** Hardening adds deterministic acceptance harnesses around real SQLite stores, staged graph topology, runtime, router projections, and SSE service while replacing only external search/LLM calls with fakes. Security tests inject unique canary secrets and inspect every durable/public surface. Client integration tests exercise React Query, EventSource, repair polling, progressive rendering, and retained controls together. No live provider call, external queue, second persistence model, or broad `LearningManager` refactor is introduced.

**Tech Stack:** Python 3.10+, stdlib `unittest`, FastAPI `TestClient`, SQLite, LangGraph 1.2.4, React 19, React Query 5, Vitest 3, Testing Library, V8 coverage, TypeScript strict mode.

**Depends on:** Phases 1-6 complete.

**Deliverable:** Deterministic web-off, web-on, degraded, partial-failure, cancelled, restarted, resumed, SSE-reconnected, and browser-progressive acceptance coverage; canary-based secret audits; per-file >80% coverage gates for new client modules; passing full suites/lint/build; and operator/user documentation.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `server/tests/generation_acceptance_harness.py` | Test-only composition root using temporary SQLite, real focused stores/runtime/graph/SSE, and deterministic external fakes. |
| Create | `server/tests/test_internet_generation_acceptance.py` | Cross-layer web-off, grounded, degraded, 3/10 batching, citation, and partial-error scenarios. |
| Create | `server/tests/test_generation_security_acceptance.py` | Cancellation/restart/resume, SSE replay, duplicate-start, and canary-secret surface audit. |
| Create | `server/utils/safe_logging.py` | Fixed-shape logging helper that records exception type, never external exception text or traceback. |
| Modify | `server/graph/runner.py` | Route unexpected graph failures through safe logging. |
| Modify | `server/services/generation_runtime.py` | Consume detached task failures without logging secret-bearing exception strings. |
| Modify | `client/src/features/learning/generationEvents.ts` | Reconcile polling snapshots by monotonic event ID so stale HTTP responses cannot undo newer SSE state. |
| Modify | `client/src/features/learning/generationEvents.test.ts` | Add stale/newer snapshot reconciliation tests. |
| Modify | `client/src/features/learning/LearningPage.tsx` | Apply reconciliation before committing repair-poll responses to React Query. |
| Modify | `client/src/test/FakeEventSource.ts` | Expose deterministic instances/reset for integration tests without changing production behavior. |
| Create | `client/src/features/learning/__tests__/internetGroundedGeneration.test.tsx` | Browser-level progressive, degraded, stale-poll, cancel, resume, and delete flows. |
| Create | `client/vitest.generation.config.ts` | Focused V8 coverage include set and per-file >80% thresholds for new generation modules. |
| Modify | `client/package.json` | Add one-shot focused generation coverage command. |
| Create | `docs/internet-grounded-course-generation/operations.md` | Configuration, stage, recovery, security, limits, and troubleshooting runbook. |
| Modify | `README.md` | Document optional web grounding, progressive API/UI behavior, endpoints, and commands. |
| Create | `server/tests/test_internet_generation_docs.py` | Guard required user/operator documentation and provider links. |

## Acceptance Matrix

| Scenario | Required terminal state | Required proof |
|---|---|---|
| Web OFF, 30 topics | `COMPLETE` | Research skipped; batch windows `(0,3)`, `(3,10)`, `(13,10)`, `(23,7)`; all cards persisted. |
| Web ON, sources available | `COMPLETE` | Research sections/sources precede outline; briefs use approved IDs; public cards expose validated citations only. |
| All search providers unavailable | `COMPLETE_DEGRADED` | Warning persists; no grounded label; staged web-off generation continues. |
| One Generator/Quizzer failure | `COMPLETE` or `COMPLETE_DEGRADED` | Failed card remains `ERROR`; siblings and later batches complete. |
| Cancel after preview | `CANCELLED` | Report, TOC, first cards, cursor, and events remain; no later call starts. |
| Restart then resume | `COMPLETE` or `COMPLETE_DEGRADED` | Startup pauses orphan; fresh credentials required when research unfinished; same thread and node IDs; no duplicates. |
| SSE disconnect/reconnect | Unchanged job outcome | Work continues; reconnect replays IDs greater than cursor in order; polling snapshot agrees. |
| Duplicate start/resume | Existing job continues | Second worker receives conflict; one lock owner; no duplicate artifacts/events. |
| Browser progressive flow | Server terminal state mirrored | Research before TOC, skeletons before cards, first three first, later batches, warnings/sources/controls visible. |
| Canary secrets | Any outcome | No canary in DB, checkpoint, events, reports, public JSON, error detail, or captured logs. |

## Tasks

### Task 7.1: Add Deterministic Server Acceptance Harness and Scenario Matrix

**Files:**
- Create: `server/tests/generation_acceptance_harness.py`
- Create: `server/tests/test_internet_generation_acceptance.py`

- [ ] **Step 1: Write failing cross-layer acceptance tests**

Create `server/tests/test_internet_generation_acceptance.py`:

```python
"""
============================================================================
FILE: test_internet_generation_acceptance.py
LOCATION: server/tests/test_internet_generation_acceptance.py
============================================================================
PURPOSE:
    Verifies complete staged generation outcomes with deterministic external
    services and real graph, persistence, runtime, and public projections.
ROLE IN PROJECT:
    Provides release-level acceptance coverage across Phases 1-5.
KEY COMPONENTS:
    - InternetGenerationAcceptanceTests: Main scenario matrix
DEPENDENCIES:
    - External: unittest
    - Internal: server.tests.generation_acceptance_harness
USAGE:
    python -m unittest server.tests.test_internet_generation_acceptance -v
============================================================================
"""

from __future__ import annotations

import unittest

from server.tests.generation_acceptance_harness import (
    AcceptanceScenario,
    GenerationAcceptanceHarness,
)


class InternetGenerationAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    """Tests durable generation as one composed system."""

    async def asyncSetUp(self) -> None:
        self.harness = await GenerationAcceptanceHarness.create()

    async def asyncTearDown(self) -> None:
        await self.harness.close()

    async def test_web_off_uses_exact_preview_and_later_batches(self) -> None:
        result = await self.harness.run(
            AcceptanceScenario(topic_count=30, web_search=False)
        )

        self.assertEqual(result.terminal_stage, "COMPLETE")
        self.assertEqual(result.research_calls, 0)
        self.assertEqual(
            result.batch_windows,
            [(0, 3), (3, 10), (13, 10), (23, 7)],
        )
        self.assertEqual(result.ready_indices, list(range(30)))
        self.assertEqual(result.error_indices, [])
        self.assertLess(
            result.stage_events.index("OUTLINING"),
            result.stage_events.index("PLANNING_PREVIEW"),
        )
        self.assertNotIn("RESEARCHING", result.stage_events)

    async def test_grounded_research_precedes_outline_and_citations_validate(
        self,
    ) -> None:
        result = await self.harness.run(
            AcceptanceScenario(topic_count=4, web_search=True)
        )

        self.assertEqual(result.terminal_stage, "COMPLETE")
        self.assertEqual(result.grounding_status, "GROUNDED")
        self.assertGreaterEqual(result.research_section_count, 1)
        self.assertGreaterEqual(result.source_count, 1)
        self.assertLess(
            result.event_types.index("research_section_ready"),
            result.event_types.index("outline_ready"),
        )
        self.assertEqual(
            set(result.public_citation_source_ids),
            set(result.persisted_source_ids),
        )
        self.assertNotIn("generation_briefs", result.public_session_json)
        self.assertNotIn("source_excerpts", result.public_session_json)
        self.assertNotIn("https://fabricated.example", result.public_session_json)

    async def test_provider_exhaustion_completes_degraded_without_false_label(
        self,
    ) -> None:
        result = await self.harness.run(
            AcceptanceScenario(
                topic_count=5,
                web_search=True,
                exhaust_providers=True,
            )
        )

        self.assertEqual(result.terminal_stage, "COMPLETE_DEGRADED")
        self.assertEqual(result.grounding_status, "DEGRADED")
        self.assertEqual(result.ready_indices, [0, 1, 2, 3, 4])
        self.assertIn("research_degraded", result.event_types)
        self.assertTrue(result.public_warnings)
        self.assertEqual(result.public_citation_source_ids, [])
        self.assertNotIn('"grounding_status":"GROUNDED"', result.public_session_json)

    async def test_one_topic_failure_does_not_block_siblings_or_next_batch(
        self,
    ) -> None:
        result = await self.harness.run(
            AcceptanceScenario(
                topic_count=14,
                web_search=False,
                fail_generator_indices=frozenset({1}),
                fail_quizzer_indices=frozenset({5}),
            )
        )

        self.assertEqual(result.terminal_stage, "COMPLETE")
        self.assertEqual(result.batch_windows, [(0, 3), (3, 10), (13, 1)])
        self.assertEqual(result.error_indices, [1, 5])
        self.assertEqual(
            result.ready_indices,
            [0, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13],
        )
        self.assertEqual(result.event_types.count("module_failed"), 2)
        self.assertEqual(result.event_types[-1], "generation_complete")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify red state**

Run from `D:\Peter\A2UI`:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_internet_generation_acceptance -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'server.tests.generation_acceptance_harness'`.

- [ ] **Step 3: Implement deterministic composition harness**

Create `server/tests/generation_acceptance_harness.py` with mandatory Python file header and these exact public records and method signatures:

```python
@dataclass(frozen=True)
class AcceptanceScenario:
    topic_count: int
    web_search: bool
    exhaust_providers: bool = False
    fail_generator_indices: frozenset[int] = frozenset()
    fail_quizzer_indices: frozenset[int] = frozenset()


@dataclass(frozen=True)
class AcceptanceResult:
    session_id: str
    thread_id: str
    terminal_stage: str
    grounding_status: str
    stage_events: list[str]
    event_types: list[str]
    batch_windows: list[tuple[int, int]]
    ready_indices: list[int]
    error_indices: list[int]
    research_calls: int
    research_section_count: int
    source_count: int
    persisted_source_ids: list[str]
    public_citation_source_ids: list[str]
    public_warnings: list[dict[str, object]]
    public_session_json: str
```

```text
GenerationAcceptanceHarness.create() -> GenerationAcceptanceHarness
GenerationAcceptanceHarness.run(AcceptanceScenario) -> AcceptanceResult
GenerationAcceptanceHarness.close() -> None
```

Implement `create()` as an async classmethod and `run()`/`close()` as async instance methods. Harness behavior is fixed:

1. `create()` owns `TemporaryDirectory`, initializes legacy learning tables, runs `initialize_generation_schema()`, creates a temporary LangGraph checkpoint file, and constructs real `GenerationJobStore`, `ResearchStore`, `GenerationArtifactStore`, `ProgressEventStore`, `GenerationRuntime`, and router projection dependencies against same DB path.
2. It compiles production `build_graph()` with test-only external seams. Do not replace stage selection, fan-out/barriers, cursor advancement, stores, runner, runtime, event serialization, citation validation, or public projections.
3. Fake Researcher returns one section and two normalized HTTPS sources when enabled. Exhaustion raises `AllProvidersUnavailable` after recording every configured provider unavailable. It never performs an HTTP request.
4. Fake Planner returns validated `CourseOutline` with exactly `scenario.topic_count` ordered topics and records every `plan_briefs(start_index, topic_count)` call. Briefs contain approved source IDs only when grounding succeeded.
5. Fake Generator and Quizzer return valid deterministic content and `QuizSet`; requested failing indices raise fixed exceptions containing no secret. Production nodes must convert failures to `ERROR` cards while siblings continue.
6. Invoke through `GenerationRuntime.start()`, then await a copied task list: `tasks = tuple(runtime.active_tasks); await asyncio.gather(*tasks)`. Never await mutable set after done callbacks remove entries.
7. Build result only from persisted job/report/nodes/events plus same public projection used by `GET /learning/sessions/{id}`. `batch_windows` comes from recorded Planner brief calls, not from expected constants in harness.
8. `close()` calls runtime shutdown, closes checkpointer, and cleans temporary directory even when scenario fails.

Use deterministic values from factories, never from external APIs:

```python
def make_outline(topic_count: int) -> CourseOutline:
    return CourseOutline(
        course_title="Deterministic Course",
        topics=[
            TopicNode(
                index=index,
                title=f"Topic {index}",
                summary_for_context=f"Summary {index}",
                key_terms=[f"term-{index}", "current"],
                complexity="Basic" if index < 3 else "Intermediate",
                quiz_count=1,
            )
            for index in range(topic_count)
        ],
    )
```

Factory also creates one valid four-option `QuizCard` per topic with stable IDs `topic-{index}-option-{label}`. Use production Pydantic models so schema drift fails acceptance tests.

- [ ] **Step 4: Run acceptance and focused regression tests**

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_internet_generation_acceptance server.tests.test_staged_graph server.tests.test_generation_persistence_integration server.tests.test_generation_api server.tests.test_generation_session_view -v
```

Expected: 4 acceptance tests plus focused regressions PASS; no network access.

- [ ] **Step 5: Commit server acceptance harness**

```powershell
git add server/tests/generation_acceptance_harness.py server/tests/test_internet_generation_acceptance.py
git commit -m "test(generation): add cross-layer acceptance matrix"
```

### Task 7.2: Harden Recovery, SSE Replay, and Secret Boundaries

**Files:**
- Modify: `server/tests/generation_acceptance_harness.py`
- Create: `server/tests/test_generation_security_acceptance.py`
- Create: `server/utils/safe_logging.py`
- Modify: `server/graph/runner.py`
- Modify: `server/services/generation_runtime.py`

- [ ] **Step 1: Write failing recovery and canary-secret tests**

Create `server/tests/test_generation_security_acceptance.py`:

```python
"""
============================================================================
FILE: test_generation_security_acceptance.py
LOCATION: server/tests/test_generation_security_acceptance.py
============================================================================
PURPOSE:
    Verifies retained recovery, SSE replay, duplicate fencing, and absence of
    request secrets from every persisted, public, and logged surface.
ROLE IN PROJECT:
    Supplies final security and durability acceptance gates for generation.
KEY COMPONENTS:
    - GenerationRecoverySecurityAcceptanceTests: Recovery and secret audits
    - SafeLoggingTests: External exception-message suppression
DEPENDENCIES:
    - External: unittest
    - Internal: acceptance harness, safe logging
USAGE:
    python -m unittest server.tests.test_generation_security_acceptance -v
============================================================================
"""

from __future__ import annotations

import logging
import unittest

from server.tests.generation_acceptance_harness import (
    GenerationAcceptanceHarness,
    RecoveryScenario,
)
from server.utils.safe_logging import log_external_failure


LLM_CANARY = "llm-canary-7d45f2"
SEARCH_CANARY = "search-canary-a91c0e"


class GenerationRecoverySecurityAcceptanceTests(
    unittest.IsolatedAsyncioTestCase
):
    """Tests durable recovery and secret isolation across process boundaries."""

    async def asyncSetUp(self) -> None:
        self.harness = await GenerationAcceptanceHarness.create()

    async def asyncTearDown(self) -> None:
        await self.harness.close()

    async def test_cancel_restart_resume_keeps_ids_and_avoids_duplicates(
        self,
    ) -> None:
        result = await self.harness.run_recovery(
            RecoveryScenario(
                topic_count=14,
                web_search=True,
                cancel_after_ready=3,
                llm_key=LLM_CANARY,
                search_key=SEARCH_CANARY,
            )
        )

        self.assertEqual(result.cancelled_stage, "CANCELLED")
        self.assertEqual(result.stage_after_restart, "PAUSED")
        self.assertEqual(result.terminal_stage, "COMPLETE")
        self.assertEqual(result.thread_ids, [result.thread_ids[0]] * 3)
        self.assertEqual(result.node_ids_before, result.node_ids_after[:3])
        self.assertEqual(len(result.node_ids_after), 14)
        self.assertEqual(len(set(result.node_ids_after)), 14)
        self.assertEqual(len(result.event_dedupe_keys), len(set(result.event_dedupe_keys)))
        self.assertTrue(result.fresh_credentials_used_on_resume)

    async def test_sse_disconnect_does_not_cancel_and_reconnect_replays_gap(
        self,
    ) -> None:
        result = await self.harness.run_sse_reconnect(topic_count=13)

        self.assertTrue(result.task_running_after_disconnect)
        self.assertEqual(result.terminal_stage, "COMPLETE")
        self.assertTrue(result.replayed_event_ids)
        self.assertTrue(
            all(
                event_id > result.disconnect_cursor
                for event_id in result.replayed_event_ids
            )
        )
        self.assertEqual(
            result.replayed_event_ids,
            sorted(set(result.replayed_event_ids)),
        )
        self.assertEqual(
            result.polling_last_event_id,
            result.replayed_event_ids[-1],
        )

    async def test_duplicate_resume_is_fenced_without_duplicate_work(self) -> None:
        result = await self.harness.run_duplicate_resume(topic_count=4)

        self.assertEqual(result.accepted_resumes, 1)
        self.assertEqual(result.conflicting_resumes, 1)
        self.assertEqual(len(result.node_ids), len(set(result.node_ids)))
        self.assertEqual(len(result.event_dedupe_keys), len(set(result.event_dedupe_keys)))

    async def test_canary_secrets_are_absent_from_all_surfaces(self) -> None:
        surfaces = await self.harness.audit_secret_surfaces(
            llm_key=LLM_CANARY,
            search_key=SEARCH_CANARY,
            provider_error=f"transport failed for {SEARCH_CANARY}",
        )

        expected_names = {
            "database_dump",
            "checkpoint_bytes",
            "event_json",
            "research_json",
            "session_json",
            "sse_frames",
            "http_error_json",
            "captured_logs",
        }
        self.assertEqual(set(surfaces), expected_names)
        for name, value in surfaces.items():
            with self.subTest(surface=name):
                self.assertNotIn(LLM_CANARY, value)
                self.assertNotIn(SEARCH_CANARY, value)


class SafeLoggingTests(unittest.TestCase):
    """Tests fixed-shape logging for untrusted external exceptions."""

    def test_external_exception_message_and_traceback_are_not_logged(self) -> None:
        logger = logging.getLogger("generation-safe-log-test")
        with self.assertLogs(logger, level="ERROR") as captured:
            log_external_failure(
                logger,
                event="generation_failed",
                session_id="session-1",
                error=RuntimeError(f"{LLM_CANARY}:{SEARCH_CANARY}"),
            )

        rendered = "\n".join(captured.output)
        self.assertIn("error_type=RuntimeError", rendered)
        self.assertIn("session_id=session-1", rendered)
        self.assertNotIn(LLM_CANARY, rendered)
        self.assertNotIn(SEARCH_CANARY, rendered)
        self.assertNotIn("Traceback", rendered)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify red state**

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_security_acceptance -v
```

Expected: FAIL because `RecoveryScenario`, recovery/SSE harness methods, and `server.utils.safe_logging` do not exist.

- [ ] **Step 3: Implement recovery harness and fixed-shape logging**

Extend harness with immutable result records and these method signatures:

```python
@dataclass(frozen=True)
class RecoveryScenario:
    topic_count: int
    web_search: bool
    cancel_after_ready: int
    llm_key: str
    search_key: str
```

```text
GenerationAcceptanceHarness.run_recovery(RecoveryScenario) -> RecoveryResult
GenerationAcceptanceHarness.run_sse_reconnect(topic_count: int) -> SseReconnectResult
GenerationAcceptanceHarness.run_duplicate_resume(topic_count: int) -> DuplicateResumeResult
GenerationAcceptanceHarness.audit_secret_surfaces(
    llm_key: str,
    search_key: str,
    provider_error: str,
) -> dict[str, str]
```

Implement all four as async instance methods. Required behavior:

1. Recovery starts real runtime, blocks fake Planner before second batch, calls runtime cancel, waits for persisted `CANCELLED`, records node IDs/cursor, shuts down runtime/checkpointer, then opens new runtime/checkpointer against same files.
2. Simulate startup reconciliation with `mark_orphaned_jobs_paused()`. Resume uses same session/thread and newly constructed `LLMContext`/`SearchContext`; original context objects are deleted before restart.
3. SSE scenario consumes actual `iter_session_events()` until one module event, closes async iterator, verifies runtime task remains alive, records cursor, finishes job, then reconnects with that cursor and collects replay through terminal event.
4. Duplicate-resume scenario calls `asyncio.gather()` for two resume requests at same barrier and counts one success plus one `GenerationAlreadyRunning`; do not serialize calls in test.
5. Secret audit uses unique canaries as request credentials, forces one provider transport exception containing search canary, and returns exact eight surfaces from raw SQLite `iterdump()`, checkpoint file bytes decoded with `errors="replace"`, stored event/report/public JSON, SSE frames, HTTP error response, and captured logs.
6. Search/LLM canaries may exist only in live context objects while task runs. Harness itself must not put canaries into scenario result records, assertion messages, temp file names, persisted fake content, or snapshots.

Create `server/utils/safe_logging.py` with mandatory header and exact implementation:

```python
from __future__ import annotations

import logging


def log_external_failure(
    logger: logging.Logger,
    *,
    event: str,
    session_id: str,
    error: BaseException,
) -> None:
    """Log safe external-failure metadata without message or traceback."""
    logger.error(
        "%s session_id=%s error_type=%s",
        event,
        session_id,
        type(error).__name__,
    )
```

Use `log_external_failure()` in graph runner's unexpected exception branch and detached runtime task done callback. Keep provider failures represented by Phase 3 typed errors and user-facing warning/error strings selected from internal error classes. Never pass `str(error)`, `repr(error)`, `exc_info=True`, request headers, provider URL, or runtime context to logger.

`SearchSecretRedactionFilter` remains installed because low-level `httpx` request logs can include SerpAPI query credentials. Safe logging supplements that filter; it does not replace it.

- [ ] **Step 4: Run security, recovery, SSE, and full server suites**

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_security_acceptance server.tests.test_generation_recovery server.tests.test_generation_controls server.tests.test_session_events server.tests.test_source_safety -v
server\.venv\Scripts\python.exe -m unittest
```

Expected: targeted and full server suites PASS. No live HTTP request occurs.

- [ ] **Step 5: Commit recovery and security hardening**

```powershell
git add server/tests/generation_acceptance_harness.py server/tests/test_generation_security_acceptance.py server/utils/safe_logging.py server/graph/runner.py server/services/generation_runtime.py
git commit -m "test(generation): harden recovery and secret boundaries"
```

### Task 7.3: Add Browser Acceptance Flow and Prevent Stale Poll Regression

**Files:**
- Modify: `client/src/features/learning/generationEvents.ts`
- Modify: `client/src/features/learning/generationEvents.test.ts`
- Modify: `client/src/features/learning/LearningPage.tsx`
- Modify: `client/src/test/FakeEventSource.ts`
- Create: `client/src/features/learning/__tests__/internetGroundedGeneration.test.tsx`

- [ ] **Step 1: Write failing stale-snapshot and browser-flow tests**

Append to `client/src/features/learning/generationEvents.test.ts`:

```typescript
import { reconcileGenerationSession } from './generationEvents';

it('keeps newer SSE state when a delayed poll returns an older event ID', () => {
  const current = {
    ...session,
    generation: {
      ...session.generation,
      stage: 'OUTLINING',
      last_event_id: 8,
    },
  } as LearningSessionWithNodes;
  const delayedPoll = {
    ...current,
    generation: {
      ...current.generation,
      stage: 'RESEARCHING',
      last_event_id: 7,
    },
  } as LearningSessionWithNodes;

  expect(reconcileGenerationSession(current, delayedPoll)).toBe(current);
});

it('accepts a poll snapshot at the same or newer event ID', () => {
  const current = {
    ...session,
    generation: { ...session.generation, last_event_id: 8 },
  } as LearningSessionWithNodes;
  const repaired = {
    ...current,
    nodes: [
      {
        id: 'node-1',
        learning_session_id: 'session-1',
        sequence_index: 0,
        title: 'Ready topic',
        content_markdown: '# Ready topic',
        status: 'VIEWING_EXPLANATION',
        error_message: null,
        retry_available: false,
        complexity: 'Basic',
        total_quizzes: 1,
        quiz: null,
        quiz_set: null,
        quiz_hidden: null,
        quiz_set_hidden: null,
        created_at: '2026-08-01T00:00:00Z',
        updated_at: '2026-08-01T00:00:00Z',
        module_status: 'READY',
        citations: [],
      },
    ],
    generation: {
      ...current.generation,
      stage: 'GENERATING_PREVIEW',
      last_event_id: 9,
    },
  } as LearningSessionWithNodes;

  expect(reconcileGenerationSession(current, repaired)).toBe(repaired);
});
```

Create `client/src/features/learning/__tests__/internetGroundedGeneration.test.tsx`:

```tsx
/**
 * ============================================================================
 * FILE: internetGroundedGeneration.test.tsx
 * LOCATION: client/src/features/learning/__tests__/internetGroundedGeneration.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests progressive Internet-grounded course behavior across query cache,
 *    EventSource, polling repair, sources, and retained controls.
 *
 * ROLE IN PROJECT:
 *    Provides browser acceptance coverage for Phase 6 integration.
 *
 * KEY COMPONENTS:
 *    - Progressive generation browser scenarios
 *
 * DEPENDENCIES:
 *    - External: React Query, React Router, Testing Library, Vitest
 *    - Internal: LearningPage, generation events, FakeEventSource
 *
 * USAGE:
 *    npm run test -- --run src/features/learning/__tests__/internetGroundedGeneration.test.tsx
 * ============================================================================
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { LearningPage } from '@/features/learning/LearningPage';
import { FakeEventSource } from '@/test/FakeEventSource';
import type { GenerationEvent } from '@/types/generation';
import type { LearningSessionWithNodes } from '@/types/learning';

const api = vi.hoisted(() => ({
  cancelGeneration: vi.fn(),
  deleteSession: vi.fn(),
  getCourseResearch: vi.fn(),
  getLearningSession: vi.fn(),
  resumeGeneration: vi.fn(),
}));

vi.mock('@/lib/learningApi', () => api);

const shell = (stage: string, eventId: number): LearningSessionWithNodes => ({
  id: 'session-1',
  user_id: null,
  query: 'Modern React',
  course_title: 'Modern React',
  title_finalized: stage !== 'RESEARCHING',
  mode: 'full',
  resolved_mode: 'full',
  total_nodes: stage === 'RESEARCHING' ? 0 : 4,
  completed_nodes: 0,
  last_active_node_id: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  nodes: [],
  generation: {
    id: 'job-1',
    session_id: 'session-1',
    stage,
    web_search_requested: true,
    grounding_status: stage === 'COMPLETE_DEGRADED' ? 'DEGRADED' : 'PENDING',
    counts: {
      topics_total: stage === 'RESEARCHING' ? 0 : 4,
      briefs_ready: 0,
      topics_ready: 0,
      topics_failed: 0,
      research_sections: 1,
      sources: 2,
    },
    warnings: [],
    cancel_requested: false,
    can_cancel: true,
    can_resume: false,
    last_event_id: eventId,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
  },
});

const stageEvent = (
  id: number,
  stage: string,
  base: LearningSessionWithNodes,
): GenerationEvent => ({
  id,
  event_type: 'stage_changed',
  generation: {
    ...base.generation,
    stage,
    last_event_id: id,
  },
});

function renderPage(initial: LearningSessionWithNodes) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  queryClient.setQueryData(['learningSession', 'session-1'], initial);
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/learn/session-1']}>
        <Routes>
          <Route path="/learn/:sessionId" element={<LearningPage />} />
          <Route path="/learn" element={<div>Course dashboard</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return queryClient;
}

describe('Internet-grounded generation browser flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    FakeEventSource.reset();
    Object.defineProperty(globalThis, 'EventSource', {
      configurable: true,
      value: FakeEventSource,
    });
    api.getCourseResearch.mockResolvedValue({
      status: 'RESEARCHING',
      sections: [{ id: 'section-1', theme: 'Current versions', markdown: 'React 19.' }],
      sources: [],
      provider_statuses: [],
      limitations: [],
      warnings: [],
    });
  });

  it('renders research first and never regresses after a stale poll', async () => {
    const researching = shell('RESEARCHING', 4);
    const delayed = shell('RESEARCHING', 4);
    api.getLearningSession.mockImplementation(
      () => new Promise<LearningSessionWithNodes>((resolve) => {
        setTimeout(() => resolve(delayed), 25);
      }),
    );
    const client = renderPage(researching);

    expect(
      await screen.findByText(/researching current sources/i),
    ).toBeInTheDocument();
    const stream = FakeEventSource.instances[0];
    stream.emit(
      'stage_changed',
      stageEvent(5, 'OUTLINING', researching),
      '5',
    );
    await waitFor(() => {
      expect(
        client.getQueryData<LearningSessionWithNodes>([
          'learningSession',
          'session-1',
        ])?.generation.stage,
      ).toBe('OUTLINING');
    });
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(
      client.getQueryData<LearningSessionWithNodes>([
        'learningSession',
        'session-1',
      ])?.generation.stage,
    ).toBe('OUTLINING');
  });

  it('keeps partial artifacts on stop and resumes with fresh capability', async () => {
    const generating = shell('GENERATING_PREVIEW', 8);
    generating.nodes = [
      {
        id: 'node-1',
        learning_session_id: 'session-1',
        sequence_index: 0,
        title: 'React Actions',
        content_markdown: '# React Actions',
        status: 'VIEWING_EXPLANATION',
        error_message: null,
        retry_available: false,
        complexity: 'Basic',
        total_quizzes: 1,
        quiz: null,
        quiz_set: null,
        quiz_hidden: null,
        quiz_set_hidden: null,
        created_at: '2026-08-01T00:00:00Z',
        updated_at: '2026-08-01T00:00:00Z',
        module_status: 'READY',
        citations: [],
      },
    ];
    api.getLearningSession.mockResolvedValue(generating);
    api.cancelGeneration.mockResolvedValue({
      generation: {
        ...generating.generation,
        stage: 'CANCELLED',
        can_cancel: false,
        can_resume: true,
        last_event_id: 9,
      },
    });
    api.resumeGeneration.mockResolvedValue({
      generation: {
        ...generating.generation,
        stage: 'GENERATING_PREVIEW',
        last_event_id: 10,
      },
    });
    const client = renderPage(generating);

    fireEvent.click(await screen.findByRole('button', { name: /stop generation/i }));
    await waitFor(() => expect(api.cancelGeneration).toHaveBeenCalledWith('session-1'));
    expect(screen.getByText('React Actions')).toBeInTheDocument();
    expect(
      client.getQueryData<LearningSessionWithNodes>([
        'learningSession',
        'session-1',
      ])?.nodes,
    ).toHaveLength(1);
    fireEvent.click(await screen.findByRole('button', { name: /resume generation/i }));
    await waitFor(() => expect(api.resumeGeneration).toHaveBeenCalledOnce());
    expect(screen.getByText('React Actions')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests and verify red state**

Run from `D:\Peter\A2UI\client`:

```powershell
npm run test -- --run src/features/learning/generationEvents.test.ts src/features/learning/__tests__/internetGroundedGeneration.test.tsx
```

Expected: reconciliation test FAIL because `reconcileGenerationSession` does not exist; browser test then exposes stale poll overwriting event ID 5 with event ID 4.

- [ ] **Step 3: Implement monotonic poll reconciliation and deterministic EventSource access**

Add to `generationEvents.ts`:

```typescript
export const reconcileGenerationSession = (
  current: LearningSessionWithNodes | undefined,
  incoming: LearningSessionWithNodes,
): LearningSessionWithNodes => {
  if (!current?.generation || !incoming.generation) {
    return incoming;
  }
  if (
    incoming.generation.last_event_id <
    current.generation.last_event_id
  ) {
    return current;
  }
  return incoming;
};
```

In `LearningPage`, repair query fetches incoming session, reads current cache, reconciles, and returns reconciled value. Apply same helper before manual refetch result writes. Do not compare wall-clock timestamps; persisted monotonic event ID is authority.

Extend test double only:

```typescript
export class FakeEventSource {
  static instances: FakeEventSource[] = [];

  static reset(): void {
    FakeEventSource.instances = [];
  }

  constructor(url: string | URL) {
    this.url = String(url);
    FakeEventSource.instances.push(this);
  }
}
```

Keep Phase 6 `addEventListener`, `removeEventListener`, `emit`, and `close` behavior. `emit()` accepts typed object payload and JSON-stringifies it exactly once. No production code imports `FakeEventSource`.

- [ ] **Step 4: Run browser suite, lint, and build**

```powershell
npm run test -- --run src/features/learning/generationEvents.test.ts src/features/learning/useSessionEvents.test.tsx src/features/learning/LearningPage.test.tsx src/features/learning/__tests__/internetGroundedGeneration.test.tsx
npm run lint
npm run build
```

Expected: targeted Vitest tests, ESLint, TypeScript, and Vite build PASS.

- [ ] **Step 5: Commit browser hardening**

```powershell
git add client/src/features/learning/generationEvents.ts client/src/features/learning/generationEvents.test.ts client/src/features/learning/LearningPage.tsx client/src/test/FakeEventSource.ts client/src/features/learning/__tests__/internetGroundedGeneration.test.tsx
git commit -m "test(learning): harden progressive generation flow"
```

### Task 7.4: Enforce Focused Coverage and Run Full Quality Gates

**Files:**
- Create: `client/vitest.generation.config.ts`
- Modify: `client/package.json`

- [ ] **Step 1: Add failing focused coverage command**

Add this script to `client/package.json` before creating config:

```json
"test:generation:coverage": "vitest run --config vitest.generation.config.ts --coverage"
```

- [ ] **Step 2: Run command and verify red state**

Run from `D:\Peter\A2UI\client`:

```powershell
npm run test:generation:coverage
```

Expected: FAIL because `vitest.generation.config.ts` does not exist.

- [ ] **Step 3: Add per-file >80% generation coverage config**

Create `client/vitest.generation.config.ts`:

```typescript
/**
 * ============================================================================
 * FILE: vitest.generation.config.ts
 * LOCATION: client/vitest.generation.config.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Enforces focused per-file coverage for new progressive generation modules.
 *
 * ROLE IN PROJECT:
 *    Supplements full Vitest execution with Phase 7 release thresholds.
 *
 * KEY COMPONENTS:
 *    - V8 include list and per-file thresholds
 *
 * DEPENDENCIES:
 *    - External: vitest/config
 *    - Internal: vite.config.ts
 *
 * USAGE:
 *    npm run test:generation:coverage
 * ============================================================================
 */

import { defineConfig, mergeConfig } from 'vitest/config';

import baseConfig from './vite.config';

export default mergeConfig(
  baseConfig,
  defineConfig({
    test: {
      coverage: {
        provider: 'v8',
        include: [
          'src/lib/webSearchProviders.ts',
          'src/lib/webSearchHeaders.ts',
          'src/features/settings/WebSearchSettingsPanel.tsx',
          'src/features/learning/generationEvents.ts',
          'src/features/learning/useSessionEvents.ts',
          'src/features/learning/GenerationStatusPanel.tsx',
          'src/features/learning/CourseSourcesPanel.tsx',
          'src/features/learning/SourceCitations.tsx',
        ],
        thresholds: {
          perFile: true,
          branches: 81,
          functions: 81,
          lines: 81,
          statements: 81,
        },
      },
    },
  }),
);
```

Threshold is `81`, not `80`, because goal requires more than 80%. Dedicated Phase 1/6 modules are measured per file. Modified legacy files (`providerSettings.ts`, `learningApi.ts`, `LearningPage.tsx`, `ConceptCard.tsx`) remain covered by focused unit/integration tests but are excluded from per-file threshold because V8 cannot distinguish new lines from pre-existing lines without a baseline service.

If one listed file falls below threshold, add behavior-focused tests for uncovered branches. Do not exclude file, add `/* istanbul ignore */`, lower threshold, or test implementation details.

- [ ] **Step 4: Run all release gates**

Run server commands from `D:\Peter\A2UI`:

```powershell
server\.venv\Scripts\python.exe -m unittest
```

Run client commands from `D:\Peter\A2UI\client`:

```powershell
npm run test -- --run
npm run test:generation:coverage
npm run lint
npm run build
```

Expected: full server suite PASS; full client suite PASS; each focused file exceeds 80% for branches/functions/lines/statements; ESLint PASS; TypeScript and production build PASS.

- [ ] **Step 5: Commit coverage gate**

```powershell
git add client/vitest.generation.config.ts client/package.json
git commit -m "test(client): enforce generation coverage gates"
```

### Task 7.5: Document Operation and Complete Release Audit

**Files:**
- Create: `docs/internet-grounded-course-generation/operations.md`
- Modify: `README.md`
- Create: `server/tests/test_internet_generation_docs.py`

- [ ] **Step 1: Write failing documentation contract test**

Create `server/tests/test_internet_generation_docs.py`:

```python
"""
============================================================================
FILE: test_internet_generation_docs.py
LOCATION: server/tests/test_internet_generation_docs.py
============================================================================
PURPOSE:
    Guards user and operator documentation for optional Internet grounding.
ROLE IN PROJECT:
    Prevents release without setup, security, recovery, and limit guidance.
KEY COMPONENTS:
    - InternetGenerationDocumentationTests: Required documentation contract
DEPENDENCIES:
    - External: pathlib, unittest
    - Internal: README and operations runbook
USAGE:
    python -m unittest server.tests.test_internet_generation_docs -v
============================================================================
"""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
OPERATIONS = (
    ROOT
    / "docs"
    / "internet-grounded-course-generation"
    / "operations.md"
)


class InternetGenerationDocumentationTests(unittest.TestCase):
    """Tests required web-grounding documentation content."""

    def test_readme_documents_optional_progressive_generation(self) -> None:
        text = README.read_text(encoding="utf-8")
        required = [
            "Optional Internet Grounding",
            "defaults OFF",
            "Tavily",
            "Exa",
            "Brave Search",
            "SerpAPI",
            "POST /learning/generate",
            "202",
            "GET /learning/sessions/{id}/events",
            "POST /learning/sessions/{id}/resume",
        ]
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, text)

    def test_operations_runbook_covers_security_recovery_and_limits(self) -> None:
        text = OPERATIONS.read_text(encoding="utf-8")
        required_headings = [
            "## Provider Configuration",
            "## Generation Stages",
            "## Secret Boundary",
            "## Cancellation and Resume",
            "## Restart Recovery",
            "## SSE and Polling",
            "## Research Limits",
            "## Troubleshooting",
            "## Verification Commands",
        ]
        for heading in required_headings:
            with self.subTest(heading=heading):
                self.assertIn(heading, text)
        self.assertIn("Keys are stored only in browser localStorage", text)
        self.assertIn("Keys are sent only on generate and resume", text)
        self.assertIn("Cancelled work remains available", text)
        self.assertIn("server\\.venv\\Scripts\\python.exe -m unittest", text)
        self.assertIn("npm run test:generation:coverage", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify red state**

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_internet_generation_docs -v
```

Expected: FAIL because `operations.md` does not exist and README lacks required section.

- [ ] **Step 3: Write user and operator documentation**

Add `## Optional Internet Grounding` to README. State:

1. Master capability defaults OFF and each new course opt-in also starts OFF.
2. Registry contains Tavily, Exa, Brave Search, and SerpAPI with links to provider signup/docs from `WEB_SEARCH_PROVIDERS`; users must verify current provider terms.
3. Keys remain in browser localStorage at rest and are sent only on generate/resume requests that need them.
4. `POST /learning/generate` returns `202`; UI then uses credential-free SSE plus two-second polling repair.
5. Add events/research/cancel/resume endpoints to endpoint table and explain delete as permanent cleanup.
6. Research degradation continues useful generation but never shows grounded label.
7. Add `npm run test:generation:coverage` to development commands.

Create `operations.md` with exact headings asserted by test and concrete content:

- Provider Configuration: four IDs, signup/docs links, browser storage, capability and per-course switches.
- Generation Stages: full ordered state diagram from `INITIALIZING` through terminal states, including `PAUSED` and retained `CANCELLED`.
- Secret Boundary: allowed runtime locations and forbidden DB/checkpoint/event/report/log/error locations; generate/resume-only headers.
- Cancellation and Resume: cooperative boundaries, retained artifacts, fresh credentials when research unfinished, duplicate-resume `409`, delete distinction.
- Restart Recovery: startup marks incomplete jobs paused; no automatic secret recovery; stable `thread_id=gen-{session_id}`.
- SSE and Polling: `Last-Event-ID`/`?after=`, replay-then-tail, disconnect independence, two-second repair polling.
- Research Limits: depth/concept adaptive budgets, hard calls/time/results/bytes/context limits, approved provider rotation classes, degraded fallback.
- Troubleshooting: missing icon, `401` missing key, `409` already running/not resumable, degraded providers, stream fallback, retained cancellation.
- Verification Commands: exact root/client commands from Task 7.4 and statement that automated tests mock all external APIs.

Do not publish example real keys, live-provider smoke-test commands, unverified quota numbers, or claim server-side encryption/vaulting.

- [ ] **Step 4: Run docs test and final release audit**

Run from `D:\Peter\A2UI`:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_internet_generation_docs -v
server\.venv\Scripts\python.exe -m unittest
rg "_generate_remaining_nodes_bg|_generate_single_node_bg|is_disconnected|BackgroundTasks" server/routers/learning.py server/graph server/services
rg "api_key|credentials|llm_context|search_context" server/graph/state.py
rg "X-Tavily-Key|X-Exa-Key|X-Brave-Key|X-SerpApi-Key" client/src
git diff --check
```

Expected:

- Documentation and full server tests PASS.
- Legacy background/disconnect search returns no matches.
- Graph-state search finds runtime context fields only in `CourseGraphContext`, never `CourseState`.
- Client key-header search finds metadata/header builder/tests plus generate/resume call sites only.
- `git diff --check` prints nothing.

Run from `D:\Peter\A2UI\client`:

```powershell
npm run test -- --run
npm run test:generation:coverage
npm run lint
npm run build
```

Expected: all client gates PASS.

- [ ] **Step 5: Commit documentation and record phase checkpoint**

```powershell
git add README.md docs/internet-grounded-course-generation/operations.md server/tests/test_internet_generation_docs.py
git commit -m "docs: add Internet grounding operations guide"
git notes add -m "Phase 7 complete: integration, security, coverage, and documentation gates verified"
```

## Phase Checkpoint

- [ ] Confirm all acceptance matrix rows have automated assertions.
- [ ] Confirm no default automated test performs real Tavily, Exa, Brave, SerpAPI, OpenRouter, or General Compute calls.
- [ ] Confirm `server/database/learning_persistence.py` did not gain generation/research methods.
- [ ] Confirm migration works for fresh and existing databases and `PRAGMA foreign_key_check` is empty.
- [ ] Confirm 30-topic sequence is exactly `(0,3)`, `(3,10)`, `(13,10)`, `(23,7)`.
- [ ] Confirm web OFF never enters `RESEARCHING`; provider exhaustion ends `COMPLETE_DEGRADED`.
- [ ] Confirm SSE disconnect never calls cancel/delete and replay IDs are ordered/unique.
- [ ] Confirm cancellation preserves report, outline, completed cards, cursor, and events.
- [ ] Confirm restart/resume uses fresh credentials, same thread/node IDs, and no duplicate events/artifacts.
- [ ] Confirm canary secrets are absent from all eight audited surfaces.
- [ ] Confirm browser starts both capability and per-course search OFF, repairs through polling, and cannot regress from stale poll data.
- [ ] Confirm each focused new client module exceeds 80% branches/functions/lines/statements.
- [ ] Confirm full server tests, full client tests, ESLint, TypeScript, Vite build, and `git diff --check` pass.

## Definition of Done

Phase 7 is complete only when every checkbox above is satisfied, every external service remains mocked in automated tests, all quality commands pass from documented directories, no key canary reaches a durable/public/logged surface, and README plus operations runbook match shipped behavior.
