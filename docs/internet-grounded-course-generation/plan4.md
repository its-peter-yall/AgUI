# Internet-Grounded Course Generation Implementation Plan — Phase 4: Durable Staged LangGraph

> **Planning method:** I used writing-plans skill principles: TDD, bite-sized tasks, exact paths, and no placeholders.
>
> **For agentic workers:** REQUIRED: TDD via test-driven-development skill; execute via executing-plans or subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** Rewire course generation into one durable optional-research workflow that persists TOC first, plans briefs in batches of 3 then at most 10, completes Generator/Quizzer fan-out per batch, and resumes safely from checkpoints/cursors.

**Architecture:** Session/job exist before graph invocation and use stable `thread_id=gen-{session_id}`. Checkpoint state contains IDs, cursors, stages, and small keyed worker results; LLM/search secrets stay in `CourseGraphContext`. Graph reads/writes durable stores at every boundary. Cancellation is a persisted cooperative flag checked before search calls, Planner calls, and fan-out batches. Existing first-three plus router-background remainder path is removed; Phase 4 keeps only a temporary synchronous HTTP compatibility wrapper over the full staged job, which Phase 5 replaces with `202` detached execution.

**Tech Stack:** LangGraph 1.2.4 `StateGraph`, `Runtime`, `Send`, `AsyncSqliteSaver`; existing Instructor agents; SQLite stores from Phase 2; stdlib `unittest`.

**Depends on:** Phase 3.

**Deliverable:** Web-on, web-off, degraded, paused, cancelled, resumed, and partial-error graph behavior with exact preview/later batch ordering and no secret-bearing checkpoint channel.

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `server/agents/base.py` | Safe explicit system-prompt override; remove Planner monkeypatch need. |
| Modify | `server/agents/planner.py` | TOC-only first turn plus exact contiguous brief-batch turns. |
| Modify | `server/agents/generator.py` | Brief-aware content, scoped excerpts, citation correction, no fabricated links. |
| Modify | `server/agents/quizzer.py` | Persisted brief quiz targets and expected learner evidence. |
| Create | `server/services/citation_validation.py` | Approved source-ID validation and web-enabled URL stripping. |
| Modify | `server/graph/state.py` | Secret-free state, worker states, and idempotent keyed reducers. |
| Rewrite | `server/graph/nodes.py` | Research, TOC, brief batch, Generator, Quizzer, advancement, finalization nodes. |
| Rewrite | `server/graph/build.py` | Optional research and repeated staged batch topology. |
| Create | `server/graph/runner.py` | Stable thread, lock heartbeat, new/resume invoke, pause/cancel/failure handling. |
| Modify | `server/graph/regen.py` | Reuse persisted brief and citation allowlist when available. |
| Modify | `server/graph/regen_stream.py` | Reuse persisted brief/citation contract for streaming regeneration. |
| Modify | `server/routers/learning.py` | Remove disconnect deletion and fixed background tail; use full staged compatibility wrapper. |
| Modify | `server/tests/test_graph.py` | Replace old preview-only node/topology expectations. |
| Modify | `server/tests/test_learning_graph_router.py` | Replace cancellation-delete and old background expectations. |
| Modify | `server/tests/test_regen.py` | Grounded regeneration coverage. |
| Modify | `server/tests/test_regen_stream.py` | Grounded streaming regeneration coverage. |
| Create | `server/tests/test_planner_briefs.py` | TOC/report and exact brief-batch contract tests. |
| Create | `server/tests/test_grounded_generation.py` | Brief scope, citation correction, quiz targets, and ERROR-card tests. |
| Create | `server/tests/test_staged_graph.py` | Optional research, TOC-first, exact 3/10 batches, and barriers. |
| Create | `server/tests/test_generation_recovery.py` | Locks, cancellation, pause, restart, resume, idempotency, and secret tests. |

## Stable Graph Contract

```text
START
  -> initialize_generation_node
  -> researcher_node?             # only when requested and report incomplete
  -> outline_planner_node
  -> plan_brief_batch_node         # 3 at cursor 0; then <=10
  -> generator_node[]              # Send, max concurrency 3
  -> prepare_quiz_batch_node       # fan-in barrier
  -> quizzer_node[]                # Send, max concurrency 3
  -> advance_batch_node            # fan-in barrier and persisted cursor
  -> plan_brief_batch_node | finalize_generation_node
  -> END
```

Constants:

```python
PREVIEW_BATCH_SIZE = 3
STANDARD_BATCH_SIZE = 10
GENERATION_MAX_CONCURRENCY = 3
GENERATION_LOCK_TTL_SECONDS = 120
GENERATION_LOCK_HEARTBEAT_SECONDS = 30
```

Thirty topics produce exactly `(0, 3)`, `(3, 10)`, `(13, 10)`, `(23, 7)`.

## Tasks

### Task 4.1: Split Planner into TOC and Exact Brief-Batch Turns

**Files:**
- Modify: `server/agents/base.py`
- Modify: `server/agents/planner.py`
- Create: `server/tests/test_planner_briefs.py`

- [ ] **Step 1: Write failing Planner turn tests**

Create `server/tests/test_planner_briefs.py`:

```python
"""
============================================================================
FILE: test_planner_briefs.py
LOCATION: server/tests/test_planner_briefs.py
============================================================================
PURPOSE:
    Tests TOC-first planning and exact contiguous generation brief batches.
ROLE IN PROJECT:
    Freezes Planner knowledge-transfer behavior for staged graph generation.
KEY COMPONENTS:
    - PlannerBriefTests: Report context, 3/10 batching, and web-off tests
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.agents.planner and generation schemas
USAGE:
    python -m unittest server.tests.test_planner_briefs -v
============================================================================
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from server.agents.planner import PlannerAgent
from server.schemas.generation import (
    GenerationBrief,
    GenerationBriefBatch,
    GroundingStatus,
)
from server.schemas.learning import CourseOutline, TopicNode
from server.schemas.llm import LLMContext


def _topics(count: int) -> list[TopicNode]:
    return [
        TopicNode(
            index=index,
            title=f"Topic {index}",
            summary_for_context=f"Summary {index}",
            key_terms=["term-a", "term-b"],
            complexity="Basic" if index == 0 else "Intermediate",
            quiz_count=1 if index == 0 else 2,
        )
        for index in range(count)
    ]


def _brief(index: int) -> GenerationBrief:
    return GenerationBrief(
        topic_index=index,
        topic_scope=f"Scope {index}",
        learning_objectives=[f"Objective {index}"],
        prerequisites=[],
        assumed_knowledge=[],
        current_facts=[],
        methodologies=[],
        conventions=[],
        deprecated_approaches=[],
        migration_notes=[],
        caveats=[],
        source_excerpts=None,
        required_examples=["Example"],
        common_misconceptions=["Misconception"],
        failure_modes=["Failure mode"],
        pedagogical_guidance="Explain clearly.",
        expected_depth="full",
        boundaries_with_adjacent_topics="Keep scope atomic.",
        quiz_learning_targets=["Recall target"],
        expected_learner_evidence=["Explain target"],
        grounding_status=GroundingStatus.DISABLED,
    )


class PlannerBriefTests(unittest.IsolatedAsyncioTestCase):
    """Tests separate Planner TOC and brief calls."""

    async def test_outline_receives_completed_report_context(self) -> None:
        agent = PlannerAgent()
        outline = CourseOutline(course_title="Course", topics=_topics(3))
        with patch.object(
            agent,
            "generate",
            new=AsyncMock(return_value=outline),
        ) as generate:
            result = await agent.plan(
                "Current topic",
                research_context="Current fact [source-1].",
                llm_context=LLMContext(
                    api_key="llm-key",
                    model="test/model",
                ),
                mode="lite",
            )
        self.assertEqual(result, outline)
        prompt = generate.await_args.kwargs["user_message"]
        self.assertIn("Current fact [source-1]", prompt)
        self.assertIn("table of contents", prompt.lower())
        self.assertNotIn("generation brief", prompt.lower())

    async def test_preview_and_later_calls_request_exact_indices(self) -> None:
        agent = PlannerAgent()
        outline = CourseOutline(course_title="Course", topics=_topics(15))
        generated = [
            GenerationBriefBatch(
                start_index=0,
                briefs=[_brief(0), _brief(1), _brief(2)],
            ),
            GenerationBriefBatch(
                start_index=3,
                briefs=[_brief(index) for index in range(3, 13)],
            ),
        ]
        with patch.object(
            agent,
            "generate",
            new=AsyncMock(side_effect=generated),
        ) as generate:
            preview = await agent.plan_briefs(
                outline=outline,
                start_index=0,
                batch_size=3,
                research_context=None,
                grounding_status=GroundingStatus.DISABLED,
                llm_context=LLMContext(
                    api_key="llm-key",
                    model="test/model",
                ),
                mode="full",
            )
            later = await agent.plan_briefs(
                outline=outline,
                start_index=3,
                batch_size=10,
                research_context=None,
                grounding_status=GroundingStatus.DISABLED,
                llm_context=LLMContext(
                    api_key="llm-key",
                    model="test/model",
                ),
                mode="full",
            )
        self.assertEqual([item.topic_index for item in preview.briefs], [0, 1, 2])
        self.assertEqual(
            [item.topic_index for item in later.briefs],
            list(range(3, 13)),
        )
        self.assertIn("0, 1, 2", generate.await_args_list[0].kwargs["user_message"])
        self.assertIn(
            "3, 4, 5, 6, 7, 8, 9, 10, 11, 12",
            generate.await_args_list[1].kwargs["user_message"],
        )

    async def test_web_off_briefs_reject_research_fields(self) -> None:
        agent = PlannerAgent()
        outline = CourseOutline(course_title="Course", topics=_topics(3))
        invalid = _brief(0).model_copy(
            update={
                "research_report_id": "report-1",
                "grounding_status": GroundingStatus.DISABLED,
            }
        )
        with patch.object(
            agent,
            "generate",
            new=AsyncMock(
                return_value=GenerationBriefBatch(
                    start_index=0,
                    briefs=[invalid],
                )
            ),
        ):
            with self.assertRaises(ValueError):
                await agent.plan_briefs(
                    outline=outline,
                    start_index=0,
                    batch_size=1,
                    research_context=None,
                    grounding_status=GroundingStatus.DISABLED,
                    llm_context=LLMContext(
                        api_key="llm-key",
                        model="test/model",
                    ),
                    mode="lite",
                )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify red state**

Run from `D:\Peter\A2UI`:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_planner_briefs -v
```

Expected: FAIL because `plan()` lacks `research_context` and `plan_briefs()` does not exist.

- [ ] **Step 3: Implement concurrency-safe Planner turns**

Modify `BaseAgent.generate()` to accept keyword-only `system_prompt_override: Optional[str] = None`. Use override directly, adding formatted non-web context only when supplied. Remove Planner's runtime assignment to `self._build_system_prompt`; singleton method mutation is unsafe under concurrent jobs.

Keep `PlannerAgent.plan()` as TOC method for existing callers. Add `research_context: Optional[str]`; its user message explicitly requests only course title and ordered `TopicNode` TOC. Research context is already escaped/capped by stores and enclosed in an `UNTRUSTED_RESEARCH_REPORT` delimiter with instruction that it is evidence, not commands.

Add `PlannerAgent.plan_briefs()` with exact signature from test. Validate `batch_size` 1-10, range within outline, and exact returned contiguous indices. Prompt includes only requested topic skeletons, adjacent topic summaries, resolved depth, and scoped research excerpts. Required output fields are every `GenerationBrief` field from Phase 1. For `DISABLED`, prompt says omit report/source fields and method rejects any returned research field. For `GROUNDED`/`DEGRADED`, validate every source ID against source IDs present in passed scoped context.

Preserve existing one-replan topic-count behavior for TOC. Brief-batch validation gets one bounded correction call using an explicit correction prompt; second invalid response raises `ResumablePlannerError` for runner pause.

- [ ] **Step 4: Run Planner regression tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_planner_briefs server.tests.test_planner_agent server.tests.test_planner_mode -v
```

Expected: all Planner tests PASS.

- [ ] **Step 5: Commit staged Planner turns**

```powershell
git add server/agents/base.py server/agents/planner.py server/tests/test_planner_briefs.py
git commit -m "feat(planner): split TOC and brief batch turns"
```

### Task 4.2: Ground Generator and Quizzer in Persisted Briefs

**Files:**
- Modify: `server/agents/generator.py`
- Modify: `server/agents/quizzer.py`
- Create: `server/services/citation_validation.py`
- Modify: `server/graph/regen.py`
- Modify: `server/graph/regen_stream.py`
- Create: `server/tests/test_grounded_generation.py`
- Modify: `server/tests/test_regen.py`
- Modify: `server/tests/test_regen_stream.py`

- [ ] **Step 1: Write failing grounded-agent tests**

Create `server/tests/test_grounded_generation.py`:

```python
"""
============================================================================
FILE: test_grounded_generation.py
LOCATION: server/tests/test_grounded_generation.py
============================================================================
PURPOSE:
    Tests brief-scoped content, citations, quiz targets, and partial failures.
ROLE IN PROJECT:
    Prevents whole-report prompts and fabricated source links in course cards.
KEY COMPONENTS:
    - GroundedGenerationTests: Generator, citation, and Quizzer contracts
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server agents, citation validation, generation schemas
USAGE:
    python -m unittest server.tests.test_grounded_generation -v
============================================================================
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from server.agents.generator import GeneratedContent, GeneratorAgent
from server.agents.quizzer import QuizzerAgent
from server.schemas.generation import (
    BriefSourceExcerpt,
    GenerationBrief,
    GroundingStatus,
    SourceCitation,
)
from server.schemas.learning import TopicNode
from server.schemas.llm import LLMContext
from server.services.citation_validation import sanitize_grounded_content


def _topic() -> TopicNode:
    return TopicNode(
        index=0,
        title="Current Packaging",
        summary_for_context="Current standards-based packaging.",
        key_terms=["pyproject.toml", "build backend"],
        complexity="Intermediate",
        quiz_count=2,
    )


def _brief() -> GenerationBrief:
    return GenerationBrief(
        topic_index=0,
        topic_scope="Current Python build configuration.",
        learning_objectives=["Explain current build metadata."],
        prerequisites=["Python modules."],
        assumed_knowledge=["Virtual environments."],
        current_facts=["PEP 517 build isolation is current."],
        methodologies=["Use a standards-based frontend."],
        conventions=["Use pyproject.toml."],
        deprecated_approaches=["Direct setup.py invocation."],
        migration_notes=["Move metadata incrementally."],
        caveats=["Backend options vary."],
        research_report_id="report-1",
        source_excerpts=[
            BriefSourceExcerpt(
                source_id="source-1",
                excerpt="Use pyproject.toml for build configuration.",
            )
        ],
        required_examples=["Run python -m build."],
        common_misconceptions=["pip is a build backend."],
        failure_modes=["Missing build requirements."],
        pedagogical_guidance="Contrast frontend and backend roles.",
        expected_depth="full",
        boundaries_with_adjacent_topics="Do not cover lock files.",
        quiz_learning_targets=["Identify current build configuration."],
        expected_learner_evidence=["Reject direct setup.py invocation."],
        grounding_status=GroundingStatus.GROUNDED,
    )


class GroundedGenerationTests(unittest.IsolatedAsyncioTestCase):
    """Tests grounded Generator and Quizzer behavior."""

    async def test_generator_prompt_contains_only_brief_approved_source(self) -> None:
        agent = GeneratorAgent()
        content = GeneratedContent(
            content_markdown="# Current Packaging\n" + "Evidence. " * 50,
            key_takeaways=["One", "Two", "Three"],
            citations=[
                SourceCitation(source_id="source-1", claim="Current standard.")
            ],
        )
        with patch.object(
            agent,
            "generate",
            new=AsyncMock(return_value=content),
        ) as generate:
            result = await agent.generate_explanation(
                topic=_topic(),
                brief=_brief(),
                prev_summary=None,
                next_summary="Next topic.",
                llm_context=LLMContext(
                    api_key="llm-key",
                    model="test/model",
                ),
            )
        prompt = generate.await_args.kwargs["user_message"]
        self.assertIn("source-1", prompt)
        self.assertIn("Use pyproject.toml", prompt)
        self.assertNotIn("entire research report", prompt.lower())
        self.assertEqual(result.citations[0].source_id, "source-1")

    async def test_unsupported_citation_gets_one_correction_then_is_removed(
        self,
    ) -> None:
        agent = GeneratorAgent()
        invalid = GeneratedContent(
            content_markdown=(
                "# Current Packaging\n"
                "See [fabricated](https://fabricated.invalid). "
                + "Evidence. " * 40
            ),
            key_takeaways=["One", "Two", "Three"],
            citations=[
                SourceCitation(source_id="fake-source", claim="Fabricated.")
            ],
        )
        with patch.object(
            agent,
            "generate",
            new=AsyncMock(side_effect=[invalid, invalid]),
        ) as generate:
            result = await agent.generate_explanation(
                topic=_topic(),
                brief=_brief(),
                llm_context=LLMContext(
                    api_key="llm-key",
                    model="test/model",
                ),
            )
        self.assertEqual(generate.await_count, 2)
        self.assertEqual(result.citations, [])
        self.assertNotIn("fabricated.invalid", result.content_markdown)
        self.assertIn("removed_unsupported_citations", result.warnings)

    async def test_quizzer_context_contains_brief_targets(self) -> None:
        agent = QuizzerAgent()
        with patch.object(agent, "generate", new=AsyncMock()) as generate:
            generate.side_effect = RuntimeError("stop after prompt capture")
            with self.assertRaises(RuntimeError):
                await agent.generate_quiz_set(
                    topic=_topic(),
                    content="# Content\n" + "Current facts. " * 30,
                    quiz_count=2,
                    brief=_brief(),
                    llm_context=LLMContext(
                        api_key="llm-key",
                        model="test/model",
                    ),
                )
        message = generate.await_args.kwargs["user_message"]
        self.assertIn("Identify current build configuration", message)
        self.assertIn("Reject direct setup.py invocation", message)

    def test_sanitizer_keeps_only_approved_source_ids_and_no_urls(self) -> None:
        cleaned, citations, warnings = sanitize_grounded_content(
            markdown="Use [guide](https://fake.invalid) and current evidence.",
            citations=[
                SourceCitation(source_id="source-1", claim="Current evidence."),
                SourceCitation(source_id="source-2", claim="Unsupported."),
            ],
            approved_source_ids={"source-1"},
        )
        self.assertNotIn("https://fake.invalid", cleaned)
        self.assertEqual([item.source_id for item in citations], ["source-1"])
        self.assertEqual(warnings, ["removed_unsupported_citations"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_grounded_generation -v
```

Expected: FAIL because agent signatures and citation validator do not exist.

- [ ] **Step 3: Implement brief-scoped generation and citation correction**

Add to `GeneratedContent`:

```python
citations: list[SourceCitation] = Field(default_factory=list, max_length=20)
warnings: list[str] = Field(default_factory=list, max_length=20)
```

`GeneratorAgent.generate_explanation()` accepts optional `brief`; graph always supplies it, while legacy courses/regeneration may omit it. Grounded prompt contains brief fields, adjacent summaries, and only `brief.source_excerpts`, using untrusted-source fences. Prompt forbids arbitrary links and says citations must be returned as `SourceCitation` IDs, never URLs.

After first result, compare citation IDs to `brief.approved_source_ids` and detect Markdown/raw HTTP(S) URLs. If invalid, make one correction call with exact allowed IDs and instruction to remove links. After second invalid result, `sanitize_grounded_content()` removes unsupported citations and link destinations, retaining visible link text, and appends `removed_unsupported_citations`. No fabricated URL reaches persistence/UI.

`QuizzerAgent.generate_quiz()` and `generate_quiz_set()` accept optional `brief`. Add quiz targets, misconceptions, and expected learner evidence to prompt; do not add source excerpts or whole report.

Update `regen.py` and `regen_stream.py` to load `GenerationArtifactStore.get_brief(node_id)`. If present, pass it to Generator/Quizzer and replace validated node-source links. If absent, preserve current legacy ungrounded regeneration behavior. Add tests proving grounded regeneration cannot replace links with unsupported IDs and legacy course still regenerates.

- [ ] **Step 4: Run grounded and regeneration tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_grounded_generation server.tests.test_generator_agent server.tests.test_quizzer_agent server.tests.test_regen server.tests.test_regen_stream -v
```

Expected: all targeted tests PASS.

- [ ] **Step 5: Commit grounded generation**

```powershell
git add server/agents/generator.py server/agents/quizzer.py server/services/citation_validation.py server/graph/regen.py server/graph/regen_stream.py server/tests/test_grounded_generation.py server/tests/test_regen.py server/tests/test_regen_stream.py
git commit -m "feat(generation): ground cards in approved briefs"
```

### Task 4.3: Replace Graph State with Secret-Free Keyed Reducers

**Files:**
- Rewrite: `server/graph/state.py`
- Modify: `server/tests/test_graph.py`

- [ ] **Step 1: Replace state tests with exact reducer and secret checks**

In `server/tests/test_graph.py`, replace old `StateSchemaTests` and preview-only fan-out assumptions with:

```python
class StagedStateTests(unittest.TestCase):
    """Tests staged graph state, reducers, and batch sizing."""

    def test_batches_are_three_then_ten_then_remainder(self) -> None:
        from server.graph.nodes import select_topic_batch

        cursor = 0
        batches: list[tuple[int, int]] = []
        while cursor < 30:
            batch = select_topic_batch(cursor, 30)
            batches.append((batch.start, batch.size))
            cursor = batch.start + batch.size
        self.assertEqual(
            batches,
            [(0, 3), (3, 10), (13, 10), (23, 7)],
        )

    def test_keyed_reducer_replaces_resumed_topic_result(self) -> None:
        from server.graph.state import merge_generator_results

        current = [
            {
                "batch_start": 0,
                "sequence_index": 1,
                "content_ready": False,
                "error_message": "first failure",
            }
        ]
        update = [
            {
                "batch_start": 0,
                "sequence_index": 1,
                "content_ready": True,
                "error_message": None,
            }
        ]
        merged = merge_generator_results(current, update)
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0]["content_ready"])

    def test_checkpoint_state_excludes_runtime_secrets_and_large_artifacts(
        self,
    ) -> None:
        from server.graph.state import CourseGraphContext, CourseState

        forbidden = {
            "api_key",
            "llm_context",
            "search_context",
            "search_credentials",
            "authorization",
            "session_ref",
            "cancel_event",
            "content_markdown",
            "source_excerpts",
            "generation_brief",
        }
        state_fields = {name.lower() for name in CourseState.__annotations__}
        context_fields = {
            name.lower() for name in CourseGraphContext.__annotations__
        }
        self.assertTrue(forbidden.isdisjoint(state_fields))
        self.assertIn("llm_context", context_fields)
        self.assertIn("search_context", context_fields)
```

- [ ] **Step 2: Run state tests and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_graph.StagedStateTests -v
```

Expected: FAIL because staged batch selector and keyed reducer do not exist.

- [ ] **Step 3: Define small persisted state and worker states**

Rewrite `server/graph/state.py` with updated mandatory header. Define:

```text
GeneratorResult(batch_start, sequence_index, content_ready, error_message)
TopicResult(batch_start, sequence_index, terminal_status, error_message)
CourseMetrics(cards_ready, cards_failed)
CourseGraphContext(llm_context, search_context, worker_id)
CourseState(job_id, session_id, query, user_id, mode, resolved_mode,
            web_search_enabled, research_report_id, topic_count,
            next_topic_index, active_batch_start, active_batch_size,
            generator_results, topic_results, degraded)
GeneratorWorkerState(job_id, session_id, batch_start, sequence_index)
QuizzerWorkerState(job_id, session_id, batch_start, sequence_index)
```

Use `Annotated[list[GeneratorResult], merge_generator_results]` and equivalent topic reducer keyed by `(batch_start, sequence_index)`. New update replaces same key and sort order is batch then sequence. State stores no Pydantic artifact dumps, content Markdown, excerpts, brief payloads, credentials, request objects, task objects, or wall-clock timers.

`CourseGraphContext` imports `LLMContext` and `SearchContext`; LangGraph runtime context is not a checkpoint channel. Remove `session_ref`.

- [ ] **Step 4: Run state tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_graph.StagedStateTests -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit state contracts**

```powershell
git add server/graph/state.py server/tests/test_graph.py
git commit -m "refactor(graph): use secret-free staged state"
```

### Task 4.4: Build Optional-Research 3/10 Graph with Fan-In Barriers

**Files:**
- Rewrite: `server/graph/nodes.py`
- Rewrite: `server/graph/build.py`
- Create: `server/tests/test_staged_graph.py`
- Modify: `server/tests/test_graph.py`

- [ ] **Step 1: Write failing staged graph tests**

Create `server/tests/test_staged_graph.py`:

```python
"""
============================================================================
FILE: test_staged_graph.py
LOCATION: server/tests/test_staged_graph.py
============================================================================
PURPOSE:
    Tests optional research, TOC-first persistence, exact batches, and barriers.
ROLE IN PROJECT:
    Guards permanent staged LangGraph topology and preview priority.
KEY COMPONENTS:
    - StagedGraphTests: Web routing, batch order, fan-out barrier tests
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.graph build and nodes
USAGE:
    python -m unittest server.tests.test_staged_graph -v
============================================================================
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from server.graph.build import build_graph
from server.graph.nodes import fan_out_generators, select_topic_batch
from server.schemas.generation import GenerationStage
from server.schemas.llm import LLMContext
from server.schemas.search import SearchContext


class StagedGraphTests(unittest.IsolatedAsyncioTestCase):
    """Tests staged graph route and batch orchestration."""

    async def test_web_off_skips_research_and_runs_three_then_ten(self) -> None:
        calls: list[str] = []
        jobs = MagicMock()
        jobs.is_cancel_requested.return_value = False
        artifacts = MagicMock()
        artifacts.count_topics.return_value = 13

        async def initialize(state, runtime):
            calls.append("initialize")
            return {"resolved_mode": "full", "web_search_enabled": False}

        async def outline(state, runtime):
            calls.append("outline")
            return {"topic_count": 13, "next_topic_index": 0}

        async def plan_batch(state, runtime):
            batch = select_topic_batch(state["next_topic_index"], 13)
            calls.append(f"plan:{batch.start}:{batch.size}")
            return {
                "active_batch_start": batch.start,
                "active_batch_size": batch.size,
            }

        async def generator(state, runtime):
            return {
                "generator_results": [
                    {
                        "batch_start": state["batch_start"],
                        "sequence_index": state["sequence_index"],
                        "content_ready": True,
                        "error_message": None,
                    }
                ]
            }

        async def quizzer(state, runtime):
            return {
                "topic_results": [
                    {
                        "batch_start": state["batch_start"],
                        "sequence_index": state["sequence_index"],
                        "terminal_status": "READY",
                        "error_message": None,
                    }
                ]
            }

        async def advance(state, runtime):
            start = state["active_batch_start"]
            size = state["active_batch_size"]
            calls.append(f"advance:{start}:{size}")
            return {"next_topic_index": start + size}

        graph = build_graph(
            node_overrides={
                "initialize_generation_node": initialize,
                "outline_planner_node": outline,
                "plan_brief_batch_node": plan_batch,
                "generator_node": generator,
                "quizzer_node": quizzer,
                "advance_batch_node": advance,
            }
        )
        with patch("server.graph.nodes.generation_artifact_store", artifacts):
            result = await graph.ainvoke(
                {
                    "job_id": "job-1",
                    "session_id": "session-1",
                    "query": "Topic",
                    "user_id": None,
                    "mode": "full",
                    "next_topic_index": 0,
                    "generator_results": [],
                    "topic_results": [],
                    "degraded": False,
                },
                config={"max_concurrency": 3},
                context={
                    "llm_context": LLMContext(
                        api_key="llm-key",
                        model="test/model",
                    ),
                    "search_context": SearchContext(),
                    "worker_id": "worker-1",
                },
            )
        self.assertEqual(result["next_topic_index"], 13)
        self.assertNotIn("research", calls)
        self.assertEqual(
            [call for call in calls if call.startswith("plan:")],
            ["plan:0:3", "plan:3:10"],
        )
        self.assertEqual(
            [call for call in calls if call.startswith("advance:")],
            ["advance:0:3", "advance:3:10"],
        )

    def test_generator_send_payload_contains_only_artifact_references(self) -> None:
        state = {
            "job_id": "job-1",
            "session_id": "session-1",
            "active_batch_start": 3,
            "active_batch_size": 2,
        }
        sends = fan_out_generators(state)
        self.assertEqual(len(sends), 2)
        self.assertEqual(
            set(sends[0].arg),
            {"job_id", "session_id", "batch_start", "sequence_index"},
        )
        self.assertNotIn("content_markdown", repr(sends))
        self.assertNotIn("source_excerpts", repr(sends))

    async def test_web_on_runs_research_before_outline(self) -> None:
        calls: list[str] = []
        graph = build_graph()
        with (
            patch(
                "server.graph.nodes.run_research",
                new=AsyncMock(side_effect=lambda **kwargs: calls.append("research")),
            ),
            patch(
                "server.graph.nodes.run_outline",
                new=AsyncMock(side_effect=lambda **kwargs: calls.append("outline")),
            ),
        ):
            await graph.ainvoke(
                {
                    "job_id": "job-1",
                    "session_id": "session-1",
                    "query": "Topic",
                    "user_id": None,
                    "mode": "lite",
                    "web_search_enabled": True,
                    "next_topic_index": 0,
                    "generator_results": [],
                    "topic_results": [],
                    "degraded": False,
                },
                context={
                    "llm_context": LLMContext(
                        api_key="llm-key",
                        model="test/model",
                    ),
                    "search_context": SearchContext(),
                    "worker_id": "worker-1",
                },
            )
        self.assertLess(calls.index("research"), calls.index("outline"))


if __name__ == "__main__":
    unittest.main()
```

The first and third tests may use a small `node_overrides` seam only in graph construction; production calls `build_graph()` without overrides.

- [ ] **Step 2: Run graph tests and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_staged_graph -v
```

Expected: FAIL because staged nodes/topology and override seam do not exist.

- [ ] **Step 3: Implement nodes and exact topology**

Rewrite `nodes.py` around focused stores. Required public functions:

```text
initialize_generation_node
route_optional_research
researcher_node
outline_planner_node
select_topic_batch
plan_brief_batch_node
fan_out_generators
generator_node
prepare_quiz_batch_node
fan_out_quizzers
quizzer_node
advance_batch_node
route_next_batch
finalize_generation_node
```

Every node starts with `raise_if_cancel_requested(session_id)`. Research runner additionally checks between internal calls. `initialize_generation_node` resolves `auto` depth inside background graph, not HTTP request, then transitions to `RESEARCHING` or `OUTLINING` with stage event. `researcher_node` persists report outcome; degraded continues to outline with `GroundingStatus.DEGRADED`.

`outline_planner_node` loads capped report context, calls TOC Planner, and in one transaction persists title/skeletons, counts/cursor, `PLANNING_PREVIEW`, and `outline_ready`. Retry structured outline once; second invalid result raises `ResumablePlannerError` before duplicate skeletons.

`plan_brief_batch_node` chooses 3 at cursor 0 and `min(10, remaining)` later, transitions to planning stage, gets topic-scoped source excerpts, upserts exact brief batch, then transitions to generating stage. Its fan-out payload contains IDs/indices only.

`generator_node` loads topic/brief/adjacent summaries from SQLite, calls Generator, persists content, and returns small keyed result. On exception except `CancelledError`, persist ERROR with `FailedStep.GENERATOR`, emit `module_failed`, and return terminal error result so siblings continue.

`prepare_quiz_batch_node` is fan-in after all Generator sends. `fan_out_quizzers` sends only indices with persisted content; if none, route directly to `advance_batch_node`. `quizzer_node` loads persisted content/brief, creates quiz, validates citations, persists success/links/event. Quizzer error preserves content, writes `FailedStep.QUIZZER`, emits `module_failed`, and does not fail siblings.

`advance_batch_node` queries durable generation status for every index in active batch. It advances only when each is `READY` or `ERROR`, atomically updates cursor/counts/event, then routes next Planner batch or finalization. This barrier ensures no later brief call starts before current Generator and Quizzer fan-out completes.

`finalize_generation_node` writes `COMPLETE` or `COMPLETE_DEGRADED` and terminal event once.

Build exact topology:

```python
workflow.add_edge(START, "initialize_generation_node")
workflow.add_conditional_edges("initialize_generation_node", route_optional_research)
workflow.add_edge("researcher_node", "outline_planner_node")
workflow.add_edge("outline_planner_node", "plan_brief_batch_node")
workflow.add_conditional_edges("plan_brief_batch_node", fan_out_generators)
workflow.add_edge("generator_node", "prepare_quiz_batch_node")
workflow.add_conditional_edges("prepare_quiz_batch_node", fan_out_quizzers)
workflow.add_edge("quizzer_node", "advance_batch_node")
workflow.add_conditional_edges(
    "advance_batch_node",
    route_next_batch,
    {
        "plan_next": "plan_brief_batch_node",
        "finalize": "finalize_generation_node",
    },
)
workflow.add_edge("finalize_generation_node", END)
```

Use LangGraph fan-in behavior: every `Send` worker edge converges before shared downstream node, with keyed reducers preventing resume duplicates. Compile with existing optional checkpointer.

- [ ] **Step 4: Run graph tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_staged_graph server.tests.test_graph -v
```

Expected: staged and rewritten graph tests PASS.

- [ ] **Step 5: Commit staged graph**

```powershell
git add server/graph/nodes.py server/graph/build.py server/tests/test_staged_graph.py server/tests/test_graph.py
git commit -m "feat(graph): add durable three-ten course workflow"
```

### Task 4.5: Add Locked Runner, Cooperative Cancel, Pause, and Resume

**Files:**
- Create: `server/graph/runner.py`
- Create: `server/tests/test_generation_recovery.py`

- [ ] **Step 1: Write failing recovery tests**

Create `server/tests/test_generation_recovery.py`:

```python
"""
============================================================================
FILE: test_generation_recovery.py
LOCATION: server/tests/test_generation_recovery.py
============================================================================
PURPOSE:
    Tests stable threads, execution locks, cancellation, pause, and resume.
ROLE IN PROJECT:
    Protects durable generation against duplicate workers and lost credentials.
KEY COMPONENTS:
    - GenerationRunnerTests: New/resume invoke and secret-boundary tests
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.graph.runner and runtime schemas
USAGE:
    python -m unittest server.tests.test_generation_recovery -v
============================================================================
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from server.graph.runner import (
    GenerationAlreadyRunning,
    GenerationCancelled,
    ResumableGenerationError,
    run_generation_job,
)
from server.schemas.generation import GenerationStage
from server.schemas.llm import LLMContext
from server.schemas.search import SearchContext
from server.search.types import SearchProviderId


class GenerationRunnerTests(unittest.IsolatedAsyncioTestCase):
    """Tests graph runner lock and resume behavior."""

    async def test_resume_uses_none_input_same_thread_and_fresh_context(self) -> None:
        graph = AsyncMock()
        graph.ainvoke.return_value = {"session_id": "session-1"}
        jobs = MagicMock()
        jobs.get_by_session.return_value = SimpleNamespace(
            id="job-1",
            session_id="session-1",
            thread_id="gen-session-1",
            stage=GenerationStage.PAUSED,
        )
        jobs.try_acquire_lock.return_value = SimpleNamespace(
            owner="worker-1",
            version=2,
        )
        jobs.renew_lock.return_value = jobs.try_acquire_lock.return_value
        llm = LLMContext(api_key="llm-secret", model="test/model")
        search = SearchContext.from_plaintext_credentials(
            enabled=True,
            provider_ids=[SearchProviderId.TAVILY],
            credentials={SearchProviderId.TAVILY: "search-secret"},
        )
        await run_generation_job(
            app_state=SimpleNamespace(course_graph=graph),
            session_id="session-1",
            llm_context=llm,
            search_context=search,
            resume=True,
            worker_id="worker-1",
            job_store=jobs,
            event_store=MagicMock(),
        )
        call = graph.ainvoke.await_args
        self.assertIsNone(call.args[0])
        self.assertEqual(
            call.kwargs["config"]["configurable"]["thread_id"],
            "gen-session-1",
        )
        self.assertEqual(call.kwargs["context"]["llm_context"], llm)
        self.assertEqual(call.kwargs["context"]["search_context"], search)
        persisted_calls = repr(jobs.method_calls)
        self.assertNotIn("llm-secret", persisted_calls)
        self.assertNotIn("search-secret", persisted_calls)

    async def test_second_worker_is_rejected(self) -> None:
        jobs = MagicMock()
        jobs.get_by_session.return_value = SimpleNamespace(
            id="job-1",
            session_id="session-1",
            thread_id="gen-session-1",
            stage=GenerationStage.OUTLINING,
        )
        jobs.try_acquire_lock.return_value = None
        with self.assertRaises(GenerationAlreadyRunning):
            await run_generation_job(
                app_state=SimpleNamespace(course_graph=AsyncMock()),
                session_id="session-1",
                llm_context=LLMContext(
                    api_key="llm-key",
                    model="test/model",
                ),
                search_context=SearchContext(),
                resume=False,
                worker_id="worker-2",
                job_store=jobs,
                event_store=MagicMock(),
            )

    async def test_cancel_marks_retained_cancelled_state(self) -> None:
        graph = AsyncMock()
        graph.ainvoke.side_effect = GenerationCancelled("session-1")
        jobs = MagicMock()
        jobs.get_by_session.return_value = SimpleNamespace(
            id="job-1",
            session_id="session-1",
            thread_id="gen-session-1",
            stage=GenerationStage.GENERATING_PREVIEW,
        )
        lock = SimpleNamespace(owner="worker-1", version=1)
        jobs.try_acquire_lock.return_value = lock
        jobs.renew_lock.return_value = lock
        events = MagicMock()
        await run_generation_job(
            app_state=SimpleNamespace(course_graph=graph),
            session_id="session-1",
            llm_context=LLMContext(api_key="llm-key", model="test/model"),
            search_context=SearchContext(),
            resume=False,
            worker_id="worker-1",
            job_store=jobs,
            event_store=events,
        )
        jobs.mark_cancelled.assert_called_once()
        events.append_once.assert_called_once()
        jobs.release_lock.assert_called_once()

    async def test_resumable_error_marks_paused_not_failed(self) -> None:
        graph = AsyncMock()
        graph.ainvoke.side_effect = ResumableGenerationError(
            "Planner brief validation failed"
        )
        jobs = MagicMock()
        jobs.get_by_session.return_value = SimpleNamespace(
            id="job-1",
            session_id="session-1",
            thread_id="gen-session-1",
            stage=GenerationStage.PLANNING_BATCH,
        )
        lock = SimpleNamespace(owner="worker-1", version=1)
        jobs.try_acquire_lock.return_value = lock
        jobs.renew_lock.return_value = lock
        await run_generation_job(
            app_state=SimpleNamespace(course_graph=graph),
            session_id="session-1",
            llm_context=LLMContext(api_key="llm-key", model="test/model"),
            search_context=SearchContext(),
            resume=False,
            worker_id="worker-1",
            job_store=jobs,
            event_store=MagicMock(),
        )
        jobs.mark_paused.assert_called_once()
        jobs.mark_failed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run recovery tests and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_recovery -v
```

Expected: FAIL because runner module does not exist.

- [ ] **Step 3: Implement durable runner**

`run_generation_job()` exact behavior:

1. Load job and acquire fenced lock; raise `GenerationAlreadyRunning` on conflict.
2. Start heartbeat task that renews lock every 30 seconds for 120-second TTL.
3. Build config with `{"configurable": {"thread_id": job.thread_id}, "max_concurrency": 3}`.
4. New run input contains only secret-free `CourseState` fields loaded from session/job. Resume input is `None`, following LangGraph checkpoint resume contract.
5. Pass `LLMContext`, `SearchContext`, and worker ID only through `context=`.
6. Catch `GenerationCancelled`/`ResearchCancelled`: mark `CANCELLED`, retain resume stage/artifacts, append terminal cancel event once.
7. Catch `ResumableGenerationError`, missing fresh runtime credentials, and bounded Planner exhaustion: mark `PAUSED`, append safe pause event once.
8. Catch invariant/schema/persistence corruption: log traceback without contexts, mark `FAILED`, append safe failed warning through `generation_paused` is forbidden; terminal failure is represented in polling stage and a final `stage_changed` event.
9. On normal return, verify persisted job is `COMPLETE` or `COMPLETE_DEGRADED`.
10. Cancel heartbeat and release lock in `finally`.

`raise_if_cancel_requested()` reads DB at every graph boundary and raises `GenerationCancelled`; it does not use `asyncio.Event`. Server restart calls Phase 2 `mark_orphaned_jobs_paused()`; resume requires fresh contexts and uses same checkpoint thread. All artifact/event writes are idempotent, so rerunning checkpointed node cannot duplicate TOC, briefs, cards, source links, or events.

- [ ] **Step 4: Run recovery tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_recovery -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit runner**

```powershell
git add server/graph/runner.py server/tests/test_generation_recovery.py
git commit -m "feat(graph): add durable cancel and resume runner"
```

### Task 4.6: Remove Old Background Remainder and Disconnect Deletion

**Files:**
- Modify: `server/routers/learning.py`
- Modify: `server/tests/test_learning_graph_router.py`

- [ ] **Step 1: Replace old router lifecycle tests**

In `server/tests/test_learning_graph_router.py`, delete `test_graph_cancellation_clears_session_ref` and old tests expecting only three ready nodes. Add:

```python
class StagedCompatibilityRouterTests(unittest.IsolatedAsyncioTestCase):
    """Tests temporary Phase 4 HTTP wrapper over complete staged graph."""

    async def test_disconnect_check_never_cancels_or_deletes_session(self) -> None:
        class RequestStub:
            def __init__(self) -> None:
                self.app = SimpleNamespace(state=SimpleNamespace())
                self.disconnect_checks = 0

            async def is_disconnected(self) -> bool:
                self.disconnect_checks += 1
                return True

        request = RequestStub()
        completed = {
            "id": "session-1",
            "user_id": None,
            "query": "test query",
            "course_title": "Test Course",
            "mode": "lite",
            "resolved_mode": "lite",
            "created_at": "2026-08-01T00:00:00+00:00",
            "updated_at": "2026-08-01T00:00:00+00:00",
            "total_nodes": 3,
            "completed_nodes": 0,
            "last_active_node_id": None,
        }
        with (
            patch(
                "server.routers.learning.generation_job_store"
                ".create_session_shell_and_job",
                return_value=(completed, SimpleNamespace(id="job-1")),
            ),
            patch(
                "server.routers.learning.run_generation_job",
                new=AsyncMock(),
            ) as run,
            patch(
                "server.routers.learning.learning_manager"
                ".get_learning_session",
                return_value=completed,
            ),
            patch(
                "server.routers.learning.learning_manager.get_session_nodes",
                return_value=[],
            ),
            patch(
                "server.routers.learning.learning_manager"
                ".delete_learning_session"
            ) as delete,
        ):
            await _generate_course_with_graph(
                GenerateCourseRequest(query="test query", mode="lite"),
                request,
                LLMContext(api_key="llm-key", model="test/model"),
            )
        run.assert_awaited_once()
        delete.assert_not_called()
        self.assertEqual(request.disconnect_checks, 0)

    def test_old_background_helpers_are_removed(self) -> None:
        from server.routers import learning

        self.assertFalse(hasattr(learning, "_generate_single_node_bg"))
        self.assertFalse(hasattr(learning, "_generate_remaining_nodes_bg"))
```

- [ ] **Step 2: Run router tests and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_learning_graph_router.StagedCompatibilityRouterTests -v
```

Expected: FAIL because old helpers and disconnect cleanup still exist.

- [ ] **Step 3: Replace old route internals without changing public status yet**

Delete these from `server/routers/learning.py`:

```text
BackgroundTasks parameter/import
session_ref
request-disconnect polling loop
graph task cancellation and session deletion
_adjacent_summaries
_generate_single_node_bg
_generate_remaining_nodes_bg
direct generator_agent/quizzer_agent imports used only by old tail
five-topic batches and 30-second sleeps
```

Temporary Phase 4 `_generate_course_with_graph()` performs:

1. `generation_job_store.create_session_shell_and_job()` with web off because search headers arrive in Phase 5.
2. `asyncio.create_task(run_generation_job(...))` and `await asyncio.shield(task)` so request cancellation does not cancel graph.
3. Fetch completed session/nodes through existing manager and return current `LearningSessionWithNodes` shape.

Keep endpoint `201` only for this phase so existing client remains usable. It now waits for complete staged graph, not preview plus detached tail. Phase 5 replaces wrapper and response with immediate `202`; no new code should depend on compatibility helper.

- [ ] **Step 4: Run graph/router and full server tests**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_learning_graph_router server.tests.test_graph server.tests.test_staged_graph server.tests.test_generation_recovery -v
server\.venv\Scripts\python.exe -m unittest
```

Expected: targeted and full suites PASS.

- [ ] **Step 5: Commit old-path removal**

```powershell
git add server/routers/learning.py server/tests/test_learning_graph_router.py
git commit -m "refactor(learning): remove legacy background generation"
```

## Phase Checkpoint

- [ ] Verify exact batch sequence and no secret checkpoint fields:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_staged_graph server.tests.test_generation_recovery server.tests.test_graph -v
```

- [ ] Verify old fixed tail and disconnect deletion are absent:

```powershell
rg "_generate_remaining_nodes_bg|_generate_single_node_bg|is_disconnected|session_ref|sleep\(30\)" server/routers/learning.py server/graph
```

Expected: no matches.

- [ ] Verify runtime secret names occur only in context/adapter boundaries, not `CourseState`:

```powershell
rg "llm_context|search_context|api_key|credentials" server/graph/state.py
```

Expected: `llm_context` and `search_context` only in `CourseGraphContext`; no secret field in `CourseState`.

- [ ] Record checkpoint:

```powershell
git notes add -m "Phase 4 complete: durable optional-research staged graph verified"
```
