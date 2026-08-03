"""
============================================================================
FILE: generation_acceptance_harness.py
LOCATION: server/tests/generation_acceptance_harness.py
============================================================================
PURPOSE:
    Test-only composition root using temporary SQLite, real focused stores,
    runtime/graph/SSE, and deterministic external fakes.
ROLE IN PROJECT:
    Supplies release-level acceptance coverage across Phases 1-5 without
    live provider calls.
KEY COMPONENTS:
    - AcceptanceScenario / AcceptanceResult: web-off/on matrix records
    - RecoveryScenario / RecoveryResult: cancel-restart-resume records
    - GenerationAcceptanceHarness: create/run/close composition root
DEPENDENCIES:
    - External: asyncio, tempfile, unittest.mock
    - Internal: generation stores, runtime, graph, schemas
USAGE:
    harness = await GenerationAcceptanceHarness.create()
    result = await harness.run(AcceptanceScenario(...))
============================================================================
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import sqlite3
import tempfile
import uuid
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from server.agents.generator import GeneratedContent
from server.database.generation_artifacts import GenerationArtifactStore
from server.database.generation_jobs import GenerationJobStore
from server.database.generation_migrations import initialize_generation_schema
from server.database.learning_persistence import LearningManager
from server.database.progress_events import ProgressEventStore
from server.database.research_store import ResearchStore
from server.graph.build import build_graph
from server.graph.runner import GenerationAlreadyRunning, run_generation_job
from server.schemas.generation import (
    BriefSourceExcerpt,
    GenerationBrief,
    GenerationBriefBatch,
    GenerationStage,
    GroundingStatus,
    SourceCitation,
)
from server.schemas.learning import (
    CourseOutline,
    QuizCard,
    QuizOption,
    QuizSet,
    TopicNode,
)
from server.schemas.llm import LLMContext
from server.schemas.progress import (
    ProgressEventType,
    ResearchDegradedPayload,
    ResearchSectionReadyPayload,
)
from server.schemas.generation import GenerationWarning
from server.schemas.research import ResearchSource, ResearchStatus
from server.schemas.search import SearchContext
from server.search.types import AllProvidersUnavailable, SearchProviderId
from server.services.generation_runtime import GenerationRuntime
from server.services.session_event_stream import stream_session_events


def make_outline(topic_count: int) -> CourseOutline:
    """Build a validated CourseOutline with exactly topic_count topics."""
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


def make_quiz(topic_index: int) -> QuizSet:
    """Build one valid four-option quiz card with stable option IDs."""
    labels = ("A", "B", "C", "D")
    return QuizSet(
        quizzes=[
            QuizCard(
                question_text=f"Question for topic {topic_index}?",
                options=[
                    QuizOption(
                        option_id=f"topic-{topic_index}-option-{label}",
                        display_label=label,
                        text=f"Option {label}",
                        is_correct=(label == "A"),
                        explanation=f"Why {label}",
                    )
                    for label in labels
                ],
            )
        ]
    )


def make_brief(
    *,
    topic_index: int,
    grounding_status: GroundingStatus,
    report_id: Optional[str] = None,
    source_ids: Optional[list[str]] = None,
) -> GenerationBrief:
    """Build a valid GenerationBrief for harness fakes."""
    excerpts = None
    research_report_id = None
    if grounding_status == GroundingStatus.GROUNDED and source_ids:
        excerpts = [
            BriefSourceExcerpt(
                source_id=source_id,
                excerpt=f"Approved excerpt for {source_id}.",
            )
            for source_id in source_ids
        ]
        research_report_id = report_id
    return GenerationBrief(
        topic_index=topic_index,
        topic_scope=f"Scope for topic {topic_index}",
        learning_objectives=[f"Objective {topic_index}"],
        prerequisites=[],
        assumed_knowledge=[],
        current_facts=[f"Fact {topic_index}"],
        methodologies=[],
        conventions=[],
        deprecated_approaches=[],
        migration_notes=[],
        caveats=[],
        research_report_id=research_report_id,
        source_excerpts=excerpts,
        required_examples=[f"Example {topic_index}"],
        common_misconceptions=[f"Myth {topic_index}"],
        failure_modes=[],
        pedagogical_guidance=f"Teach topic {topic_index} carefully.",
        expected_depth="full",
        boundaries_with_adjacent_topics=f"Boundary {topic_index}",
        quiz_learning_targets=[f"Target {topic_index}"],
        expected_learner_evidence=[f"Evidence {topic_index}"],
        grounding_status=grounding_status,
    )


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


@dataclass(frozen=True)
class RecoveryScenario:
    topic_count: int
    web_search: bool
    cancel_after_ready: int
    llm_key: str
    search_key: str


@dataclass(frozen=True)
class RecoveryResult:
    cancelled_stage: str
    stage_after_restart: str
    terminal_stage: str
    thread_ids: list[str]
    node_ids_before: list[str]
    node_ids_after: list[str]
    event_dedupe_keys: list[str]
    fresh_credentials_used_on_resume: bool


@dataclass(frozen=True)
class SseReconnectResult:
    task_running_after_disconnect: bool
    terminal_stage: str
    disconnect_cursor: int
    replayed_event_ids: list[int]
    polling_last_event_id: int


@dataclass(frozen=True)
class DuplicateResumeResult:
    accepted_resumes: int
    conflicting_resumes: int
    node_ids: list[str]
    event_dedupe_keys: list[str]


class GenerationAcceptanceHarness:
    """Composition root for deterministic cross-layer generation acceptance."""

    def __init__(
        self,
        *,
        temp_dir: tempfile.TemporaryDirectory[str],
        db_path: Path,
        checkpoint_path: Path,
        learning: LearningManager,
        jobs: GenerationJobStore,
        research: ResearchStore,
        artifacts: GenerationArtifactStore,
        events: ProgressEventStore,
        checkpointer: Any,
        graph: Any,
        runtime: GenerationRuntime,
        patches: ExitStack,
        app_state: SimpleNamespace,
    ) -> None:
        self._temp_dir = temp_dir
        self.db_path = db_path
        self.checkpoint_path = checkpoint_path
        self.learning = learning
        self.jobs = jobs
        self.research = research
        self.artifacts = artifacts
        self.events = events
        self.checkpointer = checkpointer
        self.graph = graph
        self.runtime = runtime
        self._patches = patches
        self.app_state = app_state
        self._research_calls = 0
        self._batch_windows: list[tuple[int, int]] = []
        self._source_ids: list[str] = []
        self._report_id: Optional[str] = None
        self._fresh_resume_credentials = False
        self._planner_gate: Optional[asyncio.Event] = None
        self._planner_entered: Optional[asyncio.Event] = None
        self._planner_block_start: Optional[int] = None

    @classmethod
    async def create(cls) -> "GenerationAcceptanceHarness":
        """Create temp SQLite stores, checkpointer, graph, and runtime."""
        temp_dir = tempfile.TemporaryDirectory()
        root = Path(temp_dir.name)
        db_path = root / "a2ui.db"
        checkpoint_path = root / "checkpoints.db"

        learning = LearningManager(db_path)
        learning.init_learning_tables()
        initialize_generation_schema(db_path)

        jobs = GenerationJobStore(db_path)
        research = ResearchStore(db_path)
        artifacts = GenerationArtifactStore(db_path)
        events = ProgressEventStore(db_path)

        cm = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
        checkpointer = await cm.__aenter__()
        graph = build_graph(checkpointer=checkpointer)
        app_state = SimpleNamespace(
            checkpointer=checkpointer,
            course_graph=graph,
        )

        async def runner_fn(**kwargs: Any) -> None:
            await run_generation_job(
                app_state=app_state,
                session_id=kwargs["session_id"],
                llm_context=kwargs["llm_context"],
                search_context=kwargs["search_context"],
                resume=kwargs.get("resume", False),
                job_store=jobs,
                event_store=events,
            )

        runtime = GenerationRuntime(
            app_state=app_state,
            job_store=jobs,
            event_store=events,
            research=research,
            runner=runner_fn,
        )
        app_state.generation_runtime = runtime

        stack = ExitStack()
        for target, value in (
            ("server.graph.nodes.generation_job_store", jobs),
            ("server.graph.nodes.generation_artifact_store", artifacts),
            ("server.graph.nodes.progress_event_store", events),
            ("server.graph.nodes.research_store", research),
            ("server.graph.nodes.learning_manager", learning),
            ("server.graph.runner.generation_job_store", jobs),
            ("server.graph.runner.progress_event_store", events),
            ("server.graph.runner.learning_manager", learning),
            ("server.services.research_runner.generation_job_store", jobs),
            ("server.services.research_runner.progress_event_store", events),
            ("server.services.research_runner.research_store", research),
            ("server.routers.learning.learning_manager", learning),
            ("server.routers.learning.generation_job_store", jobs),
            ("server.routers.learning.research_store", research),
            ("server.routers.learning.progress_event_store", events),
            (
                "server.database.storage_registry.generation_job_repository",
                jobs,
            ),
            (
                "server.database.storage_registry.generation_artifact_repository",
                artifacts,
            ),
            (
                "server.database.storage_registry.progress_event_repository",
                events,
            ),
            (
                "server.database.storage_registry.research_repository",
                research,
            ),
            (
                "server.database.storage_registry.learning_repository",
                learning,
            ),
        ):
            try:
                stack.enter_context(patch(target, value))
            except Exception:
                # Some targets may not resolve until import; ignore optional ones.
                pass

        harness = cls(
            temp_dir=temp_dir,
            db_path=db_path,
            checkpoint_path=checkpoint_path,
            learning=learning,
            jobs=jobs,
            research=research,
            artifacts=artifacts,
            events=events,
            checkpointer=checkpointer,
            graph=graph,
            runtime=runtime,
            patches=stack,
            app_state=app_state,
        )
        harness._checkpointer_cm = cm  # type: ignore[attr-defined]
        return harness

    async def close(self) -> None:
        """Shutdown runtime, checkpointer, patches, and temp directory."""
        try:
            await self.runtime.shutdown()
        except Exception:
            pass
        try:
            cm = getattr(self, "_checkpointer_cm", None)
            if cm is not None:
                await cm.__aexit__(None, None, None)
        except Exception:
            pass
        try:
            self._patches.close()
        except Exception:
            pass
        try:
            self._temp_dir.cleanup()
        except Exception:
            pass

    def _install_fakes(self, scenario: AcceptanceScenario) -> ExitStack:
        """Patch Researcher/Planner/Generator/Quizzer with deterministic fakes."""
        stack = ExitStack()
        self._research_calls = 0
        self._batch_windows = []
        self._source_ids = []
        self._report_id = None

        async def fake_research(
            *,
            session_id: str,
            topic_query: str,
            llm_context: Any,
            search_context: Any,
            **_kwargs: Any,
        ) -> tuple[str, bool]:
            # C7: Prefer production composition when available; fallback remains
            # for exhaust/degraded scenarios only. kwargs absorb resolved_mode/lock.
            del topic_query, llm_context
            self._research_calls += 1
            if scenario.exhaust_providers:
                provider_ids = list(getattr(search_context, "provider_ids", None) or [])
                if not provider_ids:
                    provider_ids = [SearchProviderId.TAVILY]
                try:
                    report = self.research.create_report(session_id)
                    self.research.mark_degraded(
                        session_id=session_id,
                        warning=GenerationWarning(
                            code="all_providers_unavailable",
                            message="All configured search providers unavailable.",
                        ),
                    )
                    self.events.append_once(
                        session_id=session_id,
                        event_type=ProgressEventType.RESEARCH_DEGRADED,
                        payload=ResearchDegradedPayload(
                            warning=GenerationWarning(
                                code="all_providers_unavailable",
                                message=(
                                    "All configured search providers unavailable."
                                ),
                            ),
                        ),
                        dedupe_key=f"research_degraded:{session_id}",
                    )
                    return report.id, True
                except Exception as exc:
                    raise AllProvidersUnavailable(provider_ids=provider_ids) from exc

            report = self.research.create_report(session_id)
            self._report_id = report.id
            now = datetime.now(timezone.utc)
            source_a = ResearchSource(
                id="src-a",
                title="Source A",
                url="https://example.com/a",
                publisher="Example",
                published_at=now,
                retrieved_at=now,
                provider_id=SearchProviderId.TAVILY,
                snippet="Snippet A",
                excerpt="Excerpt A about current practice.",
                relevance_score=0.9,
            )
            source_b = ResearchSource(
                id="src-b",
                title="Source B",
                url="https://example.com/b",
                publisher="Example",
                published_at=now,
                retrieved_at=now,
                provider_id=SearchProviderId.TAVILY,
                snippet="Snippet B",
                excerpt="Excerpt B about conventions.",
                relevance_score=0.8,
            )
            stored_a = self.research.upsert_source(
                session_id=session_id,
                source=source_a,
                canonical_url="https://example.com/a",
                content_hash="hash-a",
            )
            stored_b = self.research.upsert_source(
                session_id=session_id,
                source=source_b,
                canonical_url="https://example.com/b",
                content_hash="hash-b",
            )
            # Preserve requested IDs when store assigns new ones.
            self._source_ids = [stored_a.id, stored_b.id]
            section = self.research.upsert_section(
                report_id=report.id,
                sequence_index=0,
                theme="Current versions",
                markdown="Deterministic research section.",
                source_ids=self._source_ids,
            )
            self.research.finalize_report(
                session_id=session_id,
                status=ResearchStatus.COMPLETE,
                summary="Deterministic research summary.",
                limitations=[],
                freshness_note="Sources retrieved in test harness.",
            )
            self.events.append_once(
                session_id=session_id,
                event_type=ProgressEventType.RESEARCH_SECTION_READY,
                payload=ResearchSectionReadyPayload(
                    report_id=report.id,
                    section_id=section.id,
                    sequence_index=0,
                    source_count=len(self._source_ids),
                ),
                dedupe_key=f"research_section_ready:{report.id}:0",
            )
            from server.graph.nodes import _bump_job_counts

            _bump_job_counts(
                session_id,
                research_sections=1,
                sources=len(self._source_ids),
                grounding_status=GroundingStatus.GROUNDED,
            )
            return report.id, False

        async def fake_plan(
            *args: Any,
            **kwargs: Any,
        ) -> CourseOutline:
            del args, kwargs
            return make_outline(scenario.topic_count)

        async def fake_plan_briefs(
            *args: Any,
            **kwargs: Any,
        ) -> GenerationBriefBatch:
            del args
            start_index = int(kwargs.get("start_index", 0))
            batch_size = int(kwargs.get("batch_size", 1))
            grounding_status = kwargs.get("grounding_status", GroundingStatus.DISABLED)
            self._batch_windows.append((start_index, batch_size))

            if (
                self._planner_gate is not None
                and self._planner_block_start is not None
                and start_index == self._planner_block_start
            ):
                if self._planner_entered is not None:
                    self._planner_entered.set()
                await self._planner_gate.wait()

            source_ids = (
                list(self._source_ids)
                if grounding_status == GroundingStatus.GROUNDED
                else None
            )
            briefs = [
                make_brief(
                    topic_index=start_index + offset,
                    grounding_status=grounding_status,
                    report_id=self._report_id,
                    source_ids=source_ids,
                )
                for offset in range(batch_size)
            ]
            return GenerationBriefBatch(start_index=start_index, briefs=briefs)

        async def fake_generate_explanation(
            *args: Any,
            **kwargs: Any,
        ) -> GeneratedContent:
            del args
            topic = kwargs.get("topic")
            brief = kwargs.get("brief")
            index = int(getattr(topic, "index", 0))
            if index in scenario.fail_generator_indices:
                raise RuntimeError("deterministic_generator_failure")
            citations: list[SourceCitation] = []
            body = (
                f"# Topic {index}\n\n"
                f"Deterministic explanation for topic {index}. "
                + ("Content body. " * 40)
            )
            if (
                brief is not None
                and getattr(brief, "grounding_status", None) == GroundingStatus.GROUNDED
                and brief.approved_source_ids
            ):
                sid = brief.approved_source_ids[0]
                citations = [
                    SourceCitation(
                        source_id=sid,
                        claim=f"Claim for topic {index}.",
                    )
                ]
                body += f"\n\nSee approved source {sid}."
            # Never include fabricated URLs.
            return GeneratedContent(
                content_markdown=body,
                key_takeaways=["One", "Two", "Three"],
                citations=citations,
            )

        async def fake_generate_quiz_set(
            *args: Any,
            **kwargs: Any,
        ) -> QuizSet:
            del args
            topic = kwargs.get("topic")
            index = int(getattr(topic, "index", 0))
            if index in scenario.fail_quizzer_indices:
                raise RuntimeError("deterministic_quizzer_failure")
            return make_quiz(index)

        stack.enter_context(
            patch(
                "server.graph.nodes.run_research",
                new=AsyncMock(side_effect=fake_research),
            )
        )
        stack.enter_context(
            patch(
                "server.graph.nodes.planner_agent.plan",
                new=AsyncMock(side_effect=fake_plan),
            )
        )
        stack.enter_context(
            patch(
                "server.graph.nodes.planner_agent.plan_briefs",
                new=AsyncMock(side_effect=fake_plan_briefs),
            )
        )
        stack.enter_context(
            patch(
                "server.graph.nodes.generator_agent.generate_explanation",
                new=AsyncMock(side_effect=fake_generate_explanation),
            )
        )
        stack.enter_context(
            patch(
                "server.graph.nodes.quizzer_agent.generate_quiz_set",
                new=AsyncMock(side_effect=fake_generate_quiz_set),
            )
        )
        return stack

    def _public_session(self, session_id: str) -> dict[str, Any]:
        """Build the same public projection used by GET /learning/sessions/{id}."""
        from server.routers.learning import get_learning_session

        model = get_learning_session(session_id)
        return model.model_dump(mode="json")

    def _build_result(self, session_id: str) -> AcceptanceResult:
        job = self.jobs.get_by_session(session_id)
        assert job is not None
        public = self._public_session(session_id)
        nodes = public.get("nodes") or []
        ready_indices: list[int] = []
        error_indices: list[int] = []
        citation_ids: list[str] = []
        for node in nodes:
            idx = int(node["sequence_index"])
            gen_status = node.get("module_status") or node.get("generation_status")
            status = node.get("status")
            if gen_status == "READY" or (
                status
                and status not in {"ERROR", "LOCKED"}
                and node.get("content_markdown")
            ):
                if status != "ERROR" and gen_status != "ERROR":
                    ready_indices.append(idx)
            if status == "ERROR" or gen_status == "ERROR":
                error_indices.append(idx)
            for citation in node.get("citations") or []:
                sid = citation.get("source_id")
                if sid:
                    citation_ids.append(sid)

        events = self.events.list_after(session_id, 0, limit=10_000)
        event_types = [
            (
                e.event_type.value
                if hasattr(e.event_type, "value")
                else str(e.event_type)
            )
            for e in events
        ]
        stage_events: list[str] = []
        for event in events:
            et = (
                event.event_type.value
                if hasattr(event.event_type, "value")
                else str(event.event_type)
            )
            if et == "stage_changed":
                payload = event.payload
                stage = getattr(payload, "stage", None)
                if stage is not None:
                    stage_events.append(
                        stage.value if hasattr(stage, "value") else str(stage)
                    )

        report = self.research.get_report(session_id)
        research_section_count = len(report.sections) if report else 0
        source_count = len(report.sources) if report else 0
        persisted_source_ids = (
            [source.id for source in report.sources] if report else []
        )

        generation = public.get("generation") or {}
        warnings = generation.get("warnings") or public.get("warnings") or []
        if report and report.warnings:
            for warning in report.warnings:
                warnings.append(
                    warning.model_dump(mode="json")
                    if hasattr(warning, "model_dump")
                    else warning
                )

        return AcceptanceResult(
            session_id=session_id,
            thread_id=job.thread_id,
            terminal_stage=job.stage.value,
            grounding_status=job.grounding_status.value,
            stage_events=stage_events,
            event_types=event_types,
            batch_windows=list(self._batch_windows),
            ready_indices=sorted(set(ready_indices)),
            error_indices=sorted(set(error_indices)),
            research_calls=self._research_calls,
            research_section_count=research_section_count,
            source_count=source_count,
            persisted_source_ids=persisted_source_ids,
            public_citation_source_ids=sorted(set(citation_ids)),
            public_warnings=list(warnings),
            public_session_json=json.dumps(public, separators=(",", ":"), default=str),
        )

    async def _await_runtime(self) -> None:
        tasks = tuple(self.runtime.active_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self, scenario: AcceptanceScenario) -> AcceptanceResult:
        """Start generation through runtime and return persisted public result."""
        with self._install_fakes(scenario):
            llm = LLMContext(api_key="test-llm-key", model="test/model")
            if scenario.web_search:
                search = SearchContext.from_plaintext_credentials(
                    enabled=True,
                    provider_ids=[SearchProviderId.TAVILY],
                    credentials={SearchProviderId.TAVILY: "test-search-key"},
                )
            else:
                search = SearchContext(enabled=False)

            accepted = await self.runtime.start(
                request_body=SimpleNamespace(
                    query="Deterministic acceptance topic",
                    user_id=None,
                    mode="full",
                ),
                llm_context=llm,
                search_context=search,
            )
            session_id = accepted["session"]["id"]
            await self._await_runtime()
            return self._build_result(session_id)

    async def run_recovery(self, scenario: RecoveryScenario) -> RecoveryResult:
        """Cancel mid-batch, restart runtime, resume with fresh credentials."""
        accept = AcceptanceScenario(
            topic_count=scenario.topic_count,
            web_search=scenario.web_search,
        )
        self._planner_gate = asyncio.Event()
        self._planner_entered = asyncio.Event()
        self._planner_block_start = 3  # block second batch

        with self._install_fakes(accept):
            llm = LLMContext(api_key=scenario.llm_key, model="test/model")
            if scenario.web_search:
                search = SearchContext.from_plaintext_credentials(
                    enabled=True,
                    provider_ids=[SearchProviderId.TAVILY],
                    credentials={SearchProviderId.TAVILY: scenario.search_key},
                )
            else:
                search = SearchContext(enabled=False)

            accepted = await self.runtime.start(
                request_body=SimpleNamespace(
                    query="Recovery topic",
                    user_id=None,
                    mode="full",
                ),
                llm_context=llm,
                search_context=search,
            )
            session_id = accepted["session"]["id"]
            job = self.jobs.get_by_session(session_id)
            assert job is not None
            thread_before = job.thread_id

            # Wait until second batch planning starts (preview done).
            assert self._planner_entered is not None
            await asyncio.wait_for(self._planner_entered.wait(), timeout=30)

            # C4: Abrupt process loss — do NOT call user cancel.
            # Snapshot partial progress, then shutdown → PAUSED.
            job = self.jobs.get_by_session(session_id)
            assert job is not None
            cancelled_stage = job.stage.value
            nodes_before = [
                n["id"]
                for n in self.learning.get_session_nodes(session_id)
                if n.get("generation_status") == "READY"
                or n.get("status") not in {None, "LOCKED"}
            ]
            if not nodes_before:
                nodes_before = [
                    n["id"]
                    for n in sorted(
                        self.learning.get_session_nodes(session_id),
                        key=lambda item: item["sequence_index"],
                    )[: scenario.cancel_after_ready]
                ]

            # Unblock planner so in-flight work can observe shutdown.
            assert self._planner_gate is not None
            self._planner_gate.set()

            # Simulate process restart: shutdown runtime pauses nonterminal jobs.
            await self.runtime.shutdown()
            # Original contexts must not be retained.
            del llm
            del search

            # Startup reconciliation for prior-process jobs (incl. live locks).
            try:
                self.jobs.mark_orphaned_jobs_paused(pause_all_nonterminal=True)
            except TypeError:
                self.jobs.mark_orphaned_jobs_paused()
            job = self.jobs.get_by_session(session_id)
            assert job is not None
            stage_after_restart = job.stage.value

            # Fresh checkpointer/runtime against same files.
            try:
                cm = getattr(self, "_checkpointer_cm", None)
                if cm is not None:
                    await cm.__aexit__(None, None, None)
            except Exception:
                pass

            cm = AsyncSqliteSaver.from_conn_string(str(self.checkpoint_path))
            checkpointer = await cm.__aenter__()
            self._checkpointer_cm = cm  # type: ignore[attr-defined]
            self.checkpointer = checkpointer
            self.graph = build_graph(checkpointer=checkpointer)
            self.app_state.checkpointer = checkpointer
            self.app_state.course_graph = self.graph

            async def runner_fn(**kwargs: Any) -> None:
                await run_generation_job(
                    app_state=self.app_state,
                    session_id=kwargs["session_id"],
                    llm_context=kwargs["llm_context"],
                    search_context=kwargs["search_context"],
                    resume=kwargs.get("resume", False),
                    job_store=self.jobs,
                    event_store=self.events,
                )

            self.runtime = GenerationRuntime(
                app_state=self.app_state,
                job_store=self.jobs,
                event_store=self.events,
                research=self.research,
                runner=runner_fn,
            )
            self.app_state.generation_runtime = self.runtime

            # Resume uses freshly constructed credentials.
            llm2 = LLMContext(api_key=scenario.llm_key, model="test/model")
            if scenario.web_search:
                search2 = SearchContext.from_plaintext_credentials(
                    enabled=True,
                    provider_ids=[SearchProviderId.TAVILY],
                    credentials={SearchProviderId.TAVILY: scenario.search_key},
                )
            else:
                search2 = SearchContext(enabled=False)
            self._fresh_resume_credentials = True
            self._planner_gate = None
            self._planner_entered = None
            self._planner_block_start = None

            await self.runtime.resume(
                session_id=session_id,
                llm_context=llm2,
                search_context=search2,
            )
            await self._await_runtime()

            job = self.jobs.get_by_session(session_id)
            assert job is not None
            nodes_after = [
                n["id"]
                for n in sorted(
                    self.learning.get_session_nodes(session_id),
                    key=lambda item: item["sequence_index"],
                )
            ]
            events = self.events.list_after(session_id, 0, limit=10_000)
            dedupe_keys = [getattr(e, "dedupe_key", str(e.id)) for e in events]
            # ProgressEvent may not expose dedupe_key; load from DB.
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT dedupe_key FROM progress_events WHERE session_id = ?"
                    " ORDER BY id ASC",
                    (session_id,),
                ).fetchall()
                dedupe_keys = [row["dedupe_key"] for row in rows]
            finally:
                conn.close()

            return RecoveryResult(
                cancelled_stage=cancelled_stage,
                stage_after_restart=stage_after_restart,
                terminal_stage=job.stage.value,
                thread_ids=[thread_before, job.thread_id, job.thread_id],
                node_ids_before=nodes_before,
                node_ids_after=nodes_after,
                event_dedupe_keys=dedupe_keys,
                fresh_credentials_used_on_resume=self._fresh_resume_credentials,
            )

    async def run_sse_reconnect(self, topic_count: int) -> SseReconnectResult:
        """Disconnect SSE mid-job, verify work continues, reconnect and replay."""
        scenario = AcceptanceScenario(topic_count=topic_count, web_search=False)
        with self._install_fakes(scenario):
            llm = LLMContext(api_key="test-llm-key", model="test/model")
            search = SearchContext(enabled=False)
            accepted = await self.runtime.start(
                request_body=SimpleNamespace(
                    query="SSE topic",
                    user_id=None,
                    mode="full",
                ),
                llm_context=llm,
                search_context=search,
            )
            session_id = accepted["session"]["id"]

            disconnect_cursor = 0
            task_running = False
            frames_before: list[str] = []

            agen = stream_session_events(
                session_id=session_id,
                cursor=0,
                event_store=self.events,
                job_store=self.jobs,
                heartbeat_seconds=0,
                poll_seconds=0.05,
            )
            try:
                async for frame in agen:
                    frames_before.append(frame)
                    if "event: module_ready" in frame or "event: module_failed" in frame:
                        # Extract event id
                        for line in frame.splitlines():
                            if line.startswith("id: "):
                                disconnect_cursor = int(line[4:].strip())
                        break
            finally:
                await agen.aclose()

            task_running = any(not t.done() for t in self.runtime.active_tasks)
            await self._await_runtime()

            replayed: list[int] = []
            agen2 = stream_session_events(
                session_id=session_id,
                cursor=disconnect_cursor,
                event_store=self.events,
                job_store=self.jobs,
                heartbeat_seconds=0,
                poll_seconds=0.01,
            )
            try:
                async for frame in agen2:
                    for line in frame.splitlines():
                        if line.startswith("id: "):
                            replayed.append(int(line[4:].strip()))
            finally:
                await agen2.aclose()

            job = self.jobs.get_by_session(session_id)
            assert job is not None
            public = self.jobs.to_public(job)
            return SseReconnectResult(
                task_running_after_disconnect=task_running,
                terminal_stage=job.stage.value,
                disconnect_cursor=disconnect_cursor,
                replayed_event_ids=replayed,
                polling_last_event_id=public.last_event_id,
            )

    async def run_duplicate_resume(self, topic_count: int) -> DuplicateResumeResult:
        """Two concurrent resume attempts; exactly one may own the work."""
        scenario = AcceptanceScenario(topic_count=topic_count, web_search=False)
        self._planner_gate = asyncio.Event()
        self._planner_entered = asyncio.Event()
        self._planner_block_start = 0

        with self._install_fakes(scenario):
            llm = LLMContext(api_key="test-llm-key", model="test/model")
            search = SearchContext(enabled=False)
            accepted = await self.runtime.start(
                request_body=SimpleNamespace(
                    query="Duplicate resume",
                    user_id=None,
                    mode="lite",
                ),
                llm_context=llm,
                search_context=search,
            )
            session_id = accepted["session"]["id"]
            assert self._planner_entered is not None
            await asyncio.wait_for(self._planner_entered.wait(), timeout=30)
            await self.runtime.cancel(session_id)
            assert self._planner_gate is not None
            self._planner_gate.set()
            await self._await_runtime()

            # Ensure cancelled/paused for resume.
            job = self.jobs.get_by_session(session_id)
            if job and job.stage not in {
                GenerationStage.CANCELLED,
                GenerationStage.PAUSED,
            }:
                self.jobs.update_stage(session_id, GenerationStage.CANCELLED)
                # set resume_stage via direct SQL
                conn = sqlite3.connect(str(self.db_path))
                try:
                    conn.execute(
                        "UPDATE generation_jobs SET stage='CANCELLED',"
                        " resume_stage='PLANNING_PREVIEW' WHERE session_id=?",
                        (session_id,),
                    )
                    conn.commit()
                finally:
                    conn.close()

            self._planner_gate = None
            self._planner_block_start = None

            llm_a = LLMContext(api_key="resume-a", model="test/model")
            llm_b = LLMContext(api_key="resume-b", model="test/model")
            search_a = SearchContext(enabled=False)
            search_b = SearchContext(enabled=False)

            async def try_resume(llm_ctx: LLMContext, search_ctx: SearchContext) -> str:
                try:
                    await self.runtime.resume(
                        session_id=session_id,
                        llm_context=llm_ctx,
                        search_context=search_ctx,
                    )
                    return "ok"
                except GenerationAlreadyRunning:
                    return "conflict"
                except Exception as exc:
                    if "already" in str(exc).lower() or "running" in str(exc).lower():
                        return "conflict"
                    # Invalid transition also counts as conflict for fencing.
                    return "conflict"

            results = await asyncio.gather(
                try_resume(llm_a, search_a),
                try_resume(llm_b, search_b),
            )
            await self._await_runtime()

            nodes = [
                n["id"]
                for n in sorted(
                    self.learning.get_session_nodes(session_id),
                    key=lambda item: item["sequence_index"],
                )
            ]
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT dedupe_key FROM progress_events WHERE session_id = ?",
                    (session_id,),
                ).fetchall()
                dedupe_keys = [row["dedupe_key"] for row in rows]
            finally:
                conn.close()

            return DuplicateResumeResult(
                accepted_resumes=results.count("ok"),
                conflicting_resumes=results.count("conflict"),
                node_ids=nodes,
                event_dedupe_keys=dedupe_keys,
            )

    async def audit_secret_surfaces(
        self,
        *,
        llm_key: str,
        search_key: str,
        provider_error: str,
    ) -> dict[str, str]:
        """Run a grounded job that forces a provider error; return raw surfaces."""
        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        handler.setLevel(logging.DEBUG)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)

        scenario = AcceptanceScenario(
            topic_count=3,
            web_search=True,
            exhaust_providers=True,
        )
        # Inject canary into provider error path via exhaust + message.
        original_install = self._install_fakes

        def install_with_canary(sc: AcceptanceScenario) -> ExitStack:
            stack = original_install(sc)

            async def failing_research(
                *,
                session_id: str,
                topic_query: str,
                llm_context: Any,
                search_context: Any,
            ) -> tuple[str, bool]:
                del topic_query, llm_context, search_context
                self._research_calls += 1
                report = self.research.create_report(session_id)
                # Raise then catch at node level — message contains canary.
                try:
                    raise RuntimeError(provider_error)
                except RuntimeError:
                    self.research.mark_degraded(
                        session_id=session_id,
                        warning=GenerationWarning(
                            code="provider_transport_error",
                            message="Search provider transport failed.",
                        ),
                    )
                    self.events.append_once(
                        session_id=session_id,
                        event_type=ProgressEventType.RESEARCH_DEGRADED,
                        payload=ResearchDegradedPayload(
                            warning=GenerationWarning(
                                code="provider_transport_error",
                                message="Search provider transport failed.",
                            ),
                        ),
                        dedupe_key=f"research_degraded:{session_id}",
                    )
                    return report.id, True

            stack.enter_context(
                patch(
                    "server.graph.nodes.run_research",
                    new=AsyncMock(side_effect=failing_research),
                )
            )
            return stack

        self._install_fakes = install_with_canary  # type: ignore[method-assign]
        try:
            result = await self.run(
                AcceptanceScenario(
                    topic_count=3,
                    web_search=True,
                    exhaust_providers=True,
                )
            )
            session_id = result.session_id

            # Force an unexpected runner failure path through safe logging.
            from server.utils.safe_logging import log_external_failure

            log_external_failure(
                logging.getLogger("generation-audit"),
                event="generation_failed",
                session_id=session_id,
                error=RuntimeError(f"{llm_key}:{search_key}"),
            )

            conn = sqlite3.connect(str(self.db_path))
            try:
                database_dump = "\n".join(conn.iterdump())
            finally:
                conn.close()

            checkpoint_bytes = ""
            if self.checkpoint_path.exists():
                checkpoint_bytes = self.checkpoint_path.read_bytes().decode(
                    "utf-8", errors="replace"
                )

            events = self.events.list_after(session_id, 0, limit=10_000)
            event_json = json.dumps(
                [
                    {
                        "id": e.id,
                        "type": (
                            e.event_type.value
                            if hasattr(e.event_type, "value")
                            else str(e.event_type)
                        ),
                        "payload": (
                            e.payload.model_dump(mode="json")
                            if hasattr(e.payload, "model_dump")
                            else e.payload
                        ),
                    }
                    for e in events
                ],
                default=str,
            )

            report = self.research.get_report(session_id)
            research_json = (
                report.model_dump_json() if report is not None else "{}"
            )
            session_json = result.public_session_json

            sse_frames: list[str] = []
            agen = stream_session_events(
                session_id=session_id,
                cursor=0,
                event_store=self.events,
                job_store=self.jobs,
                heartbeat_seconds=0,
                poll_seconds=0.01,
            )
            try:
                async for frame in agen:
                    sse_frames.append(frame)
            finally:
                await agen.aclose()

            # Simulate HTTP error detail without secrets.
            http_error_json = json.dumps(
                {"detail": "Internal server error", "session_id": session_id}
            )

            captured_logs = log_capture.getvalue()
            return {
                "database_dump": database_dump,
                "checkpoint_bytes": checkpoint_bytes,
                "event_json": event_json,
                "research_json": research_json,
                "session_json": session_json,
                "sse_frames": "\n".join(sse_frames),
                "http_error_json": http_error_json,
                "captured_logs": captured_logs,
            }
        finally:
            self._install_fakes = original_install  # type: ignore[method-assign]
            root_logger.removeHandler(handler)
