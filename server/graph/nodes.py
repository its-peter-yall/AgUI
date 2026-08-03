"""
============================================================================
FILE: nodes.py
LOCATION: server/graph/nodes.py
============================================================================
PURPOSE:
    Provides LangGraph node functions for durable staged course generation.
ROLE IN PROJECT:
    Implements graph steps for research, TOC outline, exact brief batching,
    fan-out Generator/Quizzer execution, advance barrier, and finalization.
KEY COMPONENTS:
    - initialize_generation_node
    - route_optional_research
    - researcher_node
    - outline_planner_node
    - select_topic_batch
    - plan_brief_batch_node
    - fan_out_generators
    - generator_node
    - prepare_quiz_batch_node
    - fan_out_quizzers
    - quizzer_node
    - advance_batch_node
    - route_next_batch
    - finalize_generation_node
DEPENDENCIES:
    - External: asyncio, logging, collections, langgraph
    - Internal: server.agents, server.database, server.schemas, server.graph.runner
USAGE:
    from server.graph.nodes import initialize_generation_node, plan_brief_batch_node
============================================================================
"""

from __future__ import annotations

import asyncio
import logging
from collections import namedtuple
from typing import Any, Optional

from langgraph.runtime import Runtime
from langgraph.types import Send

from server.agents.generator import GeneratedContent, generator_agent
from server.agents.planner import PlannerAgent, ResumablePlannerError, planner_agent
from server.agents.quizzer import QuizzerAgent, quizzer_agent
from server.database.generation_artifacts import (
    GenerationArtifactConflict,
    generation_artifact_store,
)
from server.database.generation_jobs import generation_job_store
from server.database.learning_persistence import learning_manager
from server.database.progress_events import progress_event_store
from server.database.research_store import research_store
from server.graph.runner import GenerationCancelled, ResumableGenerationError
from server.graph.state import (
    CourseGraphContext,
    CourseState,
    GeneratorResult,
    GeneratorWorkerState,
    QuizzerWorkerState,
    TopicResult,
)
from server.schemas.generation import (
    PREVIEW_BATCH_SIZE,
    STANDARD_BATCH_SIZE,
    GenerationBrief,
    GenerationStage,
    GroundingStatus,
)
from server.schemas.learning import CourseOutline, FailedStep, NodeStatus, QuizSet, TopicNode
from server.schemas.progress import (
    GenerationCompletePayload,
    ModuleFailedPayload,
    ModuleReadyPayload,
    OutlineReadyPayload,
    ProgressEventType,
    ResearchDegradedPayload,
    StageChangedPayload,
)
from server.schemas.generation import GenerationWarning
from server.schemas.llm import LLMContext
from server.schemas.search import SearchContext
from server.services.depth_router import resolve_depth_mode
from server.services.research_runner import ResearchCancelled, run_research

logger = logging.getLogger(__name__)


def _get_lock(runtime: Any = None) -> Any:
    """Extract fenced GenerationLock from runtime context when present."""
    if runtime is None:
        return None
    ctx = getattr(runtime, "context", None)
    if isinstance(ctx, dict):
        return ctx.get("lock")
    return getattr(ctx, "lock", None) if ctx is not None else None


def _fenced_update_stage(
    session_id: str,
    stage: GenerationStage,
    runtime: Any = None,
) -> None:
    """Update stage with lock fence when available."""
    lock = _get_lock(runtime)
    try:
        if lock is not None:
            generation_job_store.update_stage(
                session_id, stage, lock=lock
            )
        else:
            generation_job_store.update_stage(session_id, stage)
    except TypeError:
        generation_job_store.update_stage(session_id, stage)


def _fenced_update_progress(
    session_id: str,
    completed_topics: int,
    runtime: Any = None,
) -> None:
    """Update progress with lock fence when available."""
    lock = _get_lock(runtime)
    try:
        if lock is not None:
            generation_job_store.update_progress(
                session_id, completed_topics, lock=lock
            )
        else:
            generation_job_store.update_progress(
                session_id, completed_topics
            )
    except TypeError:
        generation_job_store.update_progress(session_id, completed_topics)

BatchSpec = namedtuple("BatchSpec", ["start", "size"])


def _append_job_warning(session_id: str, warning: GenerationWarning) -> None:
    """Append a safe warning to the generation job public surface."""
    generation_job_store.append_warning(session_id, warning)


def _bump_job_counts(session_id: str, **increments: Any) -> None:
    """Best-effort count/grounding update via repository (no direct SQL)."""
    grounding_status = increments.pop("grounding_status", None)
    mapped: dict[str, int] = {}
    absolute_keys = {"topics_total", "briefs_ready"}
    needs_job = bool(absolute_keys & increments.keys())
    job = None
    if needs_job:
        job = generation_job_store.get_by_session(session_id)
        if job is None:
            return
    for key, value in increments.items():
        if value is None:
            continue
        if key.endswith("_delta"):
            field = key[: -len("_delta")]
            mapped[field] = mapped.get(field, 0) + int(value)
            continue
        if key in absolute_keys and job is not None:
            current = int(getattr(job.counts, key))
            delta = int(value) - current
            if delta > 0:
                mapped[key] = mapped.get(key, 0) + delta
            continue
        mapped[key] = mapped.get(key, 0) + int(value)
    if mapped:
        generation_job_store.bump_counts(session_id, **mapped)
    if grounding_status is not None:
        generation_job_store.set_grounding_status(
            session_id, grounding_status
        )


def select_topic_batch(cursor: int, total_topics: int) -> BatchSpec:
    """Select the next batch range starting at cursor."""
    if cursor == 0:
        size = min(PREVIEW_BATCH_SIZE, total_topics)
    else:
        size = min(STANDARD_BATCH_SIZE, total_topics - cursor)
    return BatchSpec(start=cursor, size=size)


import sqlite3

def raise_if_cancel_requested(session_id: str) -> None:
    """Check database for cooperative cancel flag and raise GenerationCancelled if set."""
    if not session_id:
        return
    try:
        if generation_job_store.is_cancel_requested(session_id):
            raise GenerationCancelled(session_id)
    except (sqlite3.OperationalError, LookupError):
        pass


def _context_payload(runtime: Any) -> dict[str, Any]:
    """Extract runtime context payload dictionary."""
    if runtime is None:
        return {}
    if isinstance(runtime, dict):
        if "llm_context" in runtime or "search_context" in runtime:
            return runtime
        context = runtime.get("context", {})
        if isinstance(context, dict):
            return context
    if hasattr(runtime, "context"):
        val = getattr(runtime, "context")
        if isinstance(val, dict):
            return val
        if hasattr(val, "model_dump"):
            dumped = val.model_dump()
            if isinstance(dumped, dict):
                return dumped
    if hasattr(runtime, "get"):
        val = runtime.get("context", {})
        if isinstance(val, dict):
            return val
        val = runtime.get("configurable", {})
        if isinstance(val, dict):
            return val
    val = getattr(runtime, "configurable", {})
    if isinstance(val, dict):
        return val
    return {}


def _get_llm_context(runtime: Any) -> LLMContext:
    """Extract request-scoped LLM context from runtime context."""
    context = _context_payload(runtime).get("llm_context")
    if isinstance(context, LLMContext):
        return context
    if isinstance(context, dict):
        return LLMContext.model_validate(context)
    if context is not None:
        return LLMContext.model_validate(context)
    raise ValueError("llm_context is required in graph config.")


def _get_search_context(runtime: Any) -> SearchContext:
    """Extract request-scoped Search context from runtime context."""
    context = _context_payload(runtime).get("search_context")
    if isinstance(context, SearchContext):
        return context
    if isinstance(context, dict):
        return SearchContext.model_validate(context)
    return SearchContext(enabled=False)


async def initialize_generation_node(
    state: CourseState,
    runtime: Any = None,
) -> dict[str, Any]:
    """Initialize job execution, resolve depth mode, and determine web search status."""
    session_id = state["session_id"]
    raise_if_cancel_requested(session_id)

    user_mode = state.get("mode") or "auto"
    existing = state.get("resolved_mode")
    if existing in ("lite", "full") and user_mode == "auto":
        # Resume: keep previously persisted resolution.
        resolved_mode = existing
    elif user_mode in ("lite", "full"):
        resolved_mode = user_mode
    else:
        llm_ctx = None
        try:
            llm_ctx = _get_llm_context(runtime)
        except Exception:
            llm_ctx = None
        resolved_mode = await resolve_depth_mode(
            query=str(state.get("query") or ""),
            mode=user_mode,
            llm_context=llm_ctx,
        )

    # Persist resolved mode once on the learning session row.
    learning_manager.update_session_resolved_mode(
        session_id,
        resolved_mode,
    )

    search_ctx = _get_search_context(runtime)
    web_enabled = state.get("web_search_enabled")
    if web_enabled is None:
        web_enabled = search_ctx.enabled

    next_stage = GenerationStage.RESEARCHING if web_enabled else GenerationStage.OUTLINING
    _fenced_update_stage(session_id, next_stage, runtime)
    progress_event_store.append_once(
        session_id=session_id,
        event_type=ProgressEventType.STAGE_CHANGED,
        payload=StageChangedPayload(
            previous_stage=GenerationStage.INITIALIZING,
            stage=next_stage,
        ),
        dedupe_key=f"stage_init_{next_stage.value}",
    )

    return {
        "resolved_mode": resolved_mode,
        "web_search_enabled": web_enabled,
    }


def route_optional_research(state: CourseState, runtime: Any = None) -> str:
    """Route to researcher_node if web search is enabled and report is missing."""
    if state.get("web_search_enabled") and not state.get("research_report_id"):
        return "researcher_node"
    return "outline_planner_node"


async def researcher_node(
    state: CourseState,
    runtime: Any = None,
) -> dict[str, Any]:
    """Run research pipeline when web search is enabled."""
    session_id = state["session_id"]
    raise_if_cancel_requested(session_id)

    llm_ctx = _get_llm_context(runtime)
    search_ctx = _get_search_context(runtime)

    logger.info("Executing research node for session %s", session_id)
    report_id = state.get("research_report_id")
    degraded = state.get("degraded", False)

    if not report_id:
        try:
            report_id, is_degraded = await run_research(
                session_id=session_id,
                topic_query=state["query"],
                llm_context=llm_ctx,
                search_context=search_ctx,
                resolved_mode=str(state.get("resolved_mode") or "lite"),
                lock=_get_lock(runtime),
            )
            degraded = is_degraded
        except ResearchCancelled as exc:
            # Cancel during research must cancel generation, not degrade.
            raise GenerationCancelled(session_id) from exc
        except GenerationCancelled:
            raise
        except Exception:
            logger.warning(
                "Research failed for session %s; continuing degraded",
                session_id,
            )
            degraded = True
            report_id = None
            try:
                warning = GenerationWarning(
                    code="research_unavailable",
                    message=(
                        "Web research unavailable; "
                        "continuing without grounding."
                    ),
                )
                progress_event_store.append_once(
                    session_id=session_id,
                    event_type=ProgressEventType.RESEARCH_DEGRADED,
                    payload=ResearchDegradedPayload(warning=warning),
                    dedupe_key=f"research_degraded:{session_id}",
                )
                _append_job_warning(session_id, warning)
            except Exception:
                pass

    if degraded:
        _bump_job_counts(
            session_id,
            grounding_status=GroundingStatus.DEGRADED,
        )
    elif report_id:
        _bump_job_counts(
            session_id,
            grounding_status=GroundingStatus.GROUNDED,
        )

    _fenced_update_stage(session_id, GenerationStage.OUTLINING, runtime)
    progress_event_store.append_once(
        session_id=session_id,
        event_type=ProgressEventType.STAGE_CHANGED,
        payload=StageChangedPayload(
            previous_stage=GenerationStage.RESEARCHING,
            stage=GenerationStage.OUTLINING,
        ),
        dedupe_key="stage_research_outlining",
    )

    return {
        "research_report_id": report_id,
        "degraded": degraded,
    }


async def outline_planner_node(
    state: CourseState,
    runtime: Any = None,
) -> dict[str, Any]:
    """Generate CourseOutline TOC and persist topic skeletons into SQLite."""
    session_id = state["session_id"]
    raise_if_cancel_requested(session_id)

    llm_ctx = _get_llm_context(runtime)
    mode = state.get("resolved_mode") or "lite"

    report_context: Optional[str] = None
    report_id = state.get("research_report_id")
    if report_id:
        report_context = research_store.get_report_context(report_id, max_bytes=8000)

    logger.info("Generating TOC outline for session %s (mode=%s)", session_id, mode)
    outline: CourseOutline = await planner_agent.plan(
        query=state["query"],
        research_context=report_context,
        llm_context=llm_ctx,
        mode=mode,  # type: ignore[arg-type]
    )

    generation_artifact_store.persist_outline(session_id, outline)
    try:
        progress_event_store.append_once(
            session_id=session_id,
            event_type=ProgressEventType.OUTLINE_READY,
            payload=OutlineReadyPayload(
                course_title=outline.course_title,
                topic_count=len(outline.topics),
            ),
            dedupe_key="outline:ready",
        )
    except Exception:
        logger.debug("outline_ready event skipped for session %s", session_id)

    _bump_job_counts(session_id, topics_total=len(outline.topics))
    _fenced_update_stage(
        session_id, GenerationStage.PLANNING_PREVIEW, runtime
    )
    progress_event_store.append_once(
        session_id=session_id,
        event_type=ProgressEventType.STAGE_CHANGED,
        payload=StageChangedPayload(
            previous_stage=GenerationStage.OUTLINING,
            stage=GenerationStage.PLANNING_PREVIEW,
        ),
        dedupe_key="stage_outline_preview",
    )

    return {
        "topic_count": len(outline.topics),
        "next_topic_index": 0,
    }


async def plan_brief_batch_node(
    state: CourseState,
    runtime: Any = None,
) -> dict[str, Any]:
    """Plan generation briefs for current batch (3 preview or up to 10 standard)."""
    session_id = state["session_id"]
    raise_if_cancel_requested(session_id)

    llm_ctx = _get_llm_context(runtime)
    cursor = state.get("next_topic_index", 0)
    total_topics = state.get("topic_count", generation_artifact_store.count_topics(session_id))

    batch = select_topic_batch(cursor, total_topics)
    stage_plan = GenerationStage.PLANNING_PREVIEW if batch.start == 0 else GenerationStage.PLANNING_BATCH

    _fenced_update_stage(session_id, stage_plan, runtime)
    progress_event_store.append_once(
        session_id=session_id,
        event_type=ProgressEventType.STAGE_CHANGED,
        payload=StageChangedPayload(
            previous_stage=GenerationStage.OUTLINING if batch.start == 0 else GenerationStage.PLANNING_BATCH,
            stage=stage_plan,
        ),
        dedupe_key=f"stage_plan_batch_{batch.start}",
    )

    outline = generation_artifact_store.get_outline(session_id)

    web_enabled = state.get("web_search_enabled", False)
    degraded = state.get("degraded", False)

    # M5: reuse durable briefs for this batch when already present.
    existing_briefs = generation_artifact_store.get_briefs(
        session_id, batch.start, batch.size
    )
    if len(existing_briefs) >= batch.size:
        logger.info(
            "Reusing durable briefs for session %s batch start=%s",
            session_id,
            batch.start,
        )
        _bump_job_counts(
            session_id,
            briefs_ready=batch.start + batch.size,
        )
        stage_gen = (
            GenerationStage.GENERATING_PREVIEW
            if batch.start == 0
            else GenerationStage.GENERATING_BATCH
        )
        _fenced_update_stage(session_id, stage_gen, runtime)
        progress_event_store.append_once(
            session_id=session_id,
            event_type=ProgressEventType.STAGE_CHANGED,
            payload=StageChangedPayload(
                previous_stage=stage_plan,
                stage=stage_gen,
            ),
            dedupe_key=f"stage_gen_batch_{batch.start}",
        )
        return {
            "active_batch_start": batch.start,
            "active_batch_size": batch.size,
        }

    if not web_enabled:
        grounding_status = GroundingStatus.DISABLED
        research_context = None
        allowed_source_ids: set[str] = set()
    elif degraded:
        grounding_status = GroundingStatus.DEGRADED
        research_context = None
        allowed_source_ids = set()
    else:
        grounding_status = GroundingStatus.GROUNDED
        report_id = state.get("research_report_id")
        # M4: topic-scoped structured planner context, not whole report dump.
        research_context = None
        allowed_source_ids = set()
        if report_id:
            try:
                planner_ctx = research_store.get_planner_context(
                    session_id, max_excerpt_chars=1200
                )
                research_context = _format_topic_scoped_context(
                    planner_ctx,
                    outline=outline,
                    start_index=batch.start,
                    batch_size=batch.size,
                )
                allowed_source_ids = {
                    str(src.get("id"))
                    for src in (planner_ctx.get("sources") or [])
                    if src.get("id")
                }
            except Exception:
                research_context = research_store.get_report_context(
                    report_id, max_bytes=8000
                )

    logger.info("Planning brief batch for session %s (start=%s, size=%s)", session_id, batch.start, batch.size)

    try:
        brief_batch = await planner_agent.plan_briefs(
            outline=outline,
            start_index=batch.start,
            batch_size=batch.size,
            research_context=research_context,
            grounding_status=grounding_status,
            llm_context=llm_ctx,
            mode=state.get("resolved_mode") or "lite",  # type: ignore[arg-type]
        )
    except ResumablePlannerError as exc:
        logger.error("Planner brief validation failed for session %s: %s", session_id, exc)
        raise ResumableGenerationError(f"Brief generation failed: {exc}") from exc

    # M4: validate brief source IDs against persisted store before write.
    brief_batch = _validate_brief_batch_sources(
        brief_batch,
        session_id=session_id,
        report_id=state.get("research_report_id"),
        allowed_source_ids=allowed_source_ids,
    )

    generation_artifact_store.persist_briefs(session_id, brief_batch)
    _bump_job_counts(
        session_id,
        briefs_ready=batch.start + batch.size,
    )

    stage_gen = GenerationStage.GENERATING_PREVIEW if batch.start == 0 else GenerationStage.GENERATING_BATCH
    _fenced_update_stage(session_id, stage_gen, runtime)
    progress_event_store.append_once(
        session_id=session_id,
        event_type=ProgressEventType.STAGE_CHANGED,
        payload=StageChangedPayload(
            previous_stage=stage_plan,
            stage=stage_gen,
        ),
        dedupe_key=f"stage_gen_batch_{batch.start}",
    )

    return {
        "active_batch_start": batch.start,
        "active_batch_size": batch.size,
    }


def fan_out_generators(state: CourseState) -> list[Send]:
    """Fan out one Send packet per topic in active batch to generator_node."""
    job_id = state["job_id"]
    session_id = state["session_id"]
    start = state["active_batch_start"]
    size = state["active_batch_size"]

    sends: list[Send] = []
    for index in range(start, start + size):
        sends.append(
            Send(
                "generator_node",
                {
                    "job_id": job_id,
                    "session_id": session_id,
                    "batch_start": start,
                    "sequence_index": index,
                },
            )
        )
    return sends


async def generator_node(
    state: GeneratorWorkerState,
    runtime: Any = None,
) -> dict[str, list[GeneratorResult]]:
    """Generate educational explanation content for a single topic node."""
    session_id = state["session_id"]
    seq_idx = state["sequence_index"]
    batch_start = state.get("batch_start", 0)
    raise_if_cancel_requested(session_id)

    llm_ctx = _get_llm_context(runtime)
    node_id = generation_artifact_store.node_id_for_topic(session_id, seq_idx)

    try:
        # M5: skip generator when content already durable for this topic.
        if generation_artifact_store.has_durable_content(node_id):
            return {
                "generator_results": [
                    {
                        "batch_start": batch_start,
                        "sequence_index": seq_idx,
                        "content_ready": True,
                        "error_message": None,
                    }
                ]
            }

        topic = generation_artifact_store.get_topic(session_id, seq_idx)
        brief = generation_artifact_store.get_brief(node_id)
        prev_summary, next_summary = (
            generation_artifact_store.get_adjacent_summaries(session_id, seq_idx)
        )

        content: GeneratedContent = await generator_agent.generate_explanation(
            topic=topic,
            brief=brief,
            prev_summary=prev_summary,
            next_summary=next_summary,
            llm_context=llm_ctx,
        )

        # M13: transactional content + citation replacement (incl. empty).
        generation_artifact_store.persist_content_with_citations(
            node_id=node_id,
            content_markdown=content.content_markdown,
            citations=list(content.citations or []),
        )

        return {
            "generator_results": [
                {
                    "batch_start": batch_start,
                    "sequence_index": seq_idx,
                    "content_ready": True,
                    "error_message": None,
                }
            ]
        }
    except GenerationCancelled:
        raise
    except Exception:
        logger.error(
            "Generator failed for session %s index %s",
            session_id,
            seq_idx,
        )
        generation_artifact_store.persist_topic_error(
            node_id=node_id,
            failed_step=FailedStep.GENERATOR.value,
            safe_error_message="Content generation failed.",
            content_markdown="Content generation failed.",
        )
        try:
            progress_event_store.append_once(
                session_id=session_id,
                event_type=ProgressEventType.MODULE_FAILED,
                payload=ModuleFailedPayload(
                    node_id=node_id,
                    sequence_index=seq_idx,
                    failed_step=FailedStep.GENERATOR.value,
                    warning=GenerationWarning(
                        code="generator_failed",
                        message="Topic content generation failed.",
                    ),
                ),
                dedupe_key=f"module_failed:{seq_idx}:generator",
            )
        except Exception:
            pass
        _bump_job_counts(session_id, topics_failed_delta=1)
        return {
            "generator_results": [
                {
                    "batch_start": batch_start,
                    "sequence_index": seq_idx,
                    "content_ready": False,
                    "error_message": "generator_failed",
                }
            ]
        }


async def prepare_quiz_batch_node(
    state: CourseState,
    runtime: Any = None,
) -> dict[str, Any]:
    """Fan-in barrier after all generator sends complete for active batch."""
    session_id = state["session_id"]
    raise_if_cancel_requested(session_id)
    return {}


def fan_out_quizzers(state: CourseState) -> list[Send]:
    """Fan out one Send packet per topic in active batch to quizzer_node."""
    job_id = state["job_id"]
    session_id = state["session_id"]
    start = state["active_batch_start"]
    size = state["active_batch_size"]

    sends: list[Send] = []
    for index in range(start, start + size):
        sends.append(
            Send(
                "quizzer_node",
                {
                    "job_id": job_id,
                    "session_id": session_id,
                    "batch_start": start,
                    "sequence_index": index,
                },
            )
        )
    return sends


async def quizzer_node(
    state: QuizzerWorkerState,
    runtime: Any = None,
) -> dict[str, list[TopicResult]]:
    """Generate diagnostic quizzes and finalize topic node status."""
    session_id = state["session_id"]
    seq_idx = state["sequence_index"]
    batch_start = state.get("batch_start", 0)
    raise_if_cancel_requested(session_id)

    llm_ctx = _get_llm_context(runtime)
    node_id = generation_artifact_store.node_id_for_topic(session_id, seq_idx)
    node = learning_manager.get_concept_node(node_id)
    if not node:
        all_nodes = learning_manager.get_session_nodes(session_id)
        node = next((n for n in all_nodes if n["sequence_index"] == seq_idx), None)

    # Generator-error short-circuit (worker state or prior ERROR node).
    if isinstance(state, dict) and state.get("error_message"):
        content_markdown = (
            state.get("content_markdown") or "Content generation failed."
        )
        target_id = node["id"] if node else node_id
        if node is not None:
            try:
                learning_manager.update_node_content(
                    node_id=target_id,
                    content_markdown=content_markdown,
                    status=NodeStatus.ERROR,
                    error_message="Content generation failed.",
                    retry_available=True,
                    failed_step=FailedStep.GENERATOR,
                )
            except Exception:
                generation_artifact_store.persist_topic_error(
                    node_id=target_id,
                    failed_step=FailedStep.GENERATOR.value,
                    safe_error_message="Content generation failed.",
                    content_markdown=content_markdown,
                )
        return {
            "topic_results": [
                {
                    "batch_start": batch_start,
                    "sequence_index": seq_idx,
                    "terminal_status": "ERROR",
                    "error_message": "generator_failed",
                }
            ]
        }

    if (
        not node
        or node.get("status") == NodeStatus.ERROR.value
        or node.get("generation_status") == "ERROR"
    ):
        return {
            "topic_results": [
                {
                    "batch_start": batch_start,
                    "sequence_index": seq_idx,
                    "terminal_status": "ERROR",
                    "error_message": (
                        node.get("error_message") if node else "Node not found"
                    ),
                }
            ]
        }

    try:
        try:
            topic = generation_artifact_store.get_topic(session_id, seq_idx)
        except Exception:
            topic_data = state.get("topic_data") if isinstance(state, dict) else None
            if topic_data:
                topic = TopicNode.model_validate(topic_data)
            else:
                topic = TopicNode(
                    index=seq_idx,
                    title=node.get("title") or f"Topic {seq_idx}",
                    summary_for_context=node.get("summary_for_context")
                    or node.get("title")
                    or f"Topic {seq_idx}",
                    key_terms=["topic", "concept"],
                )
        brief = generation_artifact_store.get_brief(node["id"])
        content_markdown = (
            (state.get("content_markdown") if isinstance(state, dict) else None)
            or node.get("content_markdown")
            or ""
        )

        quiz_set: QuizSet = await quizzer_agent.generate_quiz_set(
            topic=topic,
            content=content_markdown,
            quiz_count=topic.quiz_count,
            brief=brief,
            llm_context=llm_ctx,
        )

        previous_status = None
        all_nodes = learning_manager.get_session_nodes(session_id)
        for sibling in all_nodes:
            if sibling["sequence_index"] == seq_idx - 1:
                previous_status = sibling["status"]

        new_status = NodeStatus.LOCKED
        if seq_idx == 0 or previous_status == NodeStatus.COMPLETED.value:
            new_status = NodeStatus.VIEWING_EXPLANATION

        try:
            generation_artifact_store.persist_topic_success(
                node_id=node["id"],
                quiz_set=quiz_set,
                citations=[],
            )
        except Exception:
            learning_manager.update_node_content(
                node_id=node["id"],
                content_markdown=content_markdown,
                status=new_status,
                quiz_set=quiz_set,
            )

        try:
            progress_event_store.append_once(
                session_id=session_id,
                event_type=ProgressEventType.MODULE_READY,
                payload=ModuleReadyPayload(
                    node_id=node["id"],
                    sequence_index=seq_idx,
                ),
                dedupe_key=f"module_ready:{seq_idx}",
            )
        except Exception:
            pass
        _bump_job_counts(session_id, topics_ready_delta=1)

        return {
            "topic_results": [
                {
                    "batch_start": batch_start,
                    "sequence_index": seq_idx,
                    "terminal_status": "READY",
                    "error_message": None,
                }
            ]
        }
    except GenerationCancelled:
        raise
    except Exception:
        logger.error(
            "Quizzer failed for session %s index %s",
            session_id,
            seq_idx,
        )
        content_markdown = (node or {}).get("content_markdown") or ""
        if isinstance(state, dict) and state.get("content_markdown"):
            content_markdown = state["content_markdown"]
        try:
            learning_manager.update_node_content(
                node_id=node["id"],
                content_markdown=content_markdown,
                status=NodeStatus.ERROR,
                error_message="Quiz generation failed.",
                retry_available=True,
                failed_step=FailedStep.QUIZZER,
            )
        except Exception:
            generation_artifact_store.persist_topic_error(
                node_id=node["id"],
                failed_step=FailedStep.QUIZZER.value,
                safe_error_message="Quiz generation failed.",
                content_markdown=content_markdown,
            )
        try:
            progress_event_store.append_once(
                session_id=session_id,
                event_type=ProgressEventType.MODULE_FAILED,
                payload=ModuleFailedPayload(
                    node_id=node["id"],
                    sequence_index=seq_idx,
                    failed_step=FailedStep.QUIZZER.value,
                    warning=GenerationWarning(
                        code="quizzer_failed",
                        message="Topic quiz generation failed.",
                    ),
                ),
                dedupe_key=f"module_failed:{seq_idx}:quizzer",
            )
        except Exception:
            pass
        _bump_job_counts(session_id, topics_failed_delta=1)
        return {
            "topic_results": [
                {
                    "batch_start": batch_start,
                    "sequence_index": seq_idx,
                    "terminal_status": "ERROR",
                    "error_message": "quizzer_failed",
                }
            ]
        }


async def advance_batch_node(
    state: CourseState,
    runtime: Any = None,
) -> dict[str, Any]:
    """Advance batch cursor after all fan-out workers complete for active batch."""
    session_id = state["session_id"]
    raise_if_cancel_requested(session_id)

    start = state["active_batch_start"]
    size = state["active_batch_size"]
    next_index = start + size

    # M6: verify every durable node in batch is READY or ERROR.
    nodes = learning_manager.get_session_nodes(session_id)
    batch_nodes = [
        n
        for n in nodes
        if start <= int(n.get("sequence_index", -1)) < start + size
    ]
    if len(batch_nodes) < size:
        raise ResumableGenerationError(
            f"Batch barrier incomplete: expected {size} nodes, found "
            f"{len(batch_nodes)} for session {session_id}"
        )
    nonterminal: list[str] = []
    for node in batch_nodes:
        gen_status = (node.get("generation_status") or "").upper()
        learner = (node.get("status") or "").upper()
        if gen_status == "READY":
            continue
        if gen_status == "ERROR" or learner == "ERROR":
            continue
        nonterminal.append(str(node.get("id")))
    if nonterminal:
        raise ResumableGenerationError(
            f"Batch barrier blocked: nonterminal nodes {nonterminal}"
        )

    # Exact global READY/ERROR counts — never count failed as ready.
    global_ready = sum(
        1
        for n in nodes
        if (n.get("generation_status") or "").upper() == "READY"
    )
    global_failed = sum(
        1
        for n in nodes
        if (n.get("generation_status") or "").upper() == "ERROR"
        or (n.get("status") or "").upper() == "ERROR"
    )
    lock = _get_lock(runtime)
    generation_job_store.update_progress(
        session_id,
        next_index,
        lock=lock,
        topics_ready=global_ready,
        topics_failed=global_failed,
    )

    return {
        "next_topic_index": next_index,
    }


def route_next_batch(state: CourseState, runtime: Any = None) -> str:
    """Route to plan_next for subsequent brief batches or finalize when complete."""
    if state["next_topic_index"] < state["topic_count"]:
        return "plan_next"
    return "finalize"


async def finalize_generation_node(
    state: CourseState,
    runtime: Any = None,
) -> dict[str, Any]:
    """Mark generation job complete and record terminal progress event."""
    session_id = state["session_id"]
    raise_if_cancel_requested(session_id)

    # Research degradation drives COMPLETE_DEGRADED; per-topic errors stay
    # COMPLETE so partial courses remain fully usable without false labels.
    degraded = bool(state.get("degraded", False))
    final_stage = (
        GenerationStage.COMPLETE_DEGRADED if degraded else GenerationStage.COMPLETE
    )

    job = None
    try:
        job = generation_job_store.get_by_session(session_id)
    except Exception:
        job = None
    grounding = (
        job.grounding_status if job is not None else GroundingStatus.DISABLED
    )
    if degraded and grounding in {
        GroundingStatus.PENDING,
        GroundingStatus.DISABLED,
    }:
        grounding = GroundingStatus.DEGRADED
        _bump_job_counts(session_id, grounding_status=grounding)
    elif (
        not degraded
        and state.get("web_search_enabled")
        and grounding == GroundingStatus.PENDING
    ):
        grounding = GroundingStatus.GROUNDED
        _bump_job_counts(session_id, grounding_status=grounding)

    try:
        _fenced_update_stage(session_id, final_stage, runtime)
    except Exception:
        pass
    counts = job.counts if job is not None else None
    if counts is None:
        from server.schemas.generation import GenerationCounts

        counts = GenerationCounts()
    try:
        progress_event_store.append_once(
            session_id=session_id,
            event_type=ProgressEventType.STAGE_CHANGED,
            payload=StageChangedPayload(
                previous_stage=GenerationStage.GENERATING_BATCH,
                stage=final_stage,
            ),
            dedupe_key=f"stage_finalize_{final_stage.value}",
        )
        progress_event_store.append_once(
            session_id=session_id,
            event_type=ProgressEventType.GENERATION_COMPLETE,
            payload=GenerationCompletePayload(
                stage=final_stage,
                counts=counts,
                grounding_status=grounding,
            ),
            dedupe_key="generation_complete",
        )
    except Exception:
        logger.debug("finalize events skipped for session %s", session_id)

    # M14: compact event log on terminal stage.
    try:
        progress_event_store.compact_completed(session_id)
    except Exception:
        logger.debug("event compact skipped for session %s", session_id)

    logger.info(
        "Generation job finalized for session %s with stage %s",
        session_id,
        final_stage.value,
    )
    return {}


def build_response_node(state: CourseState) -> dict[str, Any]:
    """Legacy helper for backward compatibility."""
    return {}


def _format_topic_scoped_context(
    planner_ctx: dict[str, Any],
    *,
    outline: CourseOutline,
    start_index: int,
    batch_size: int,
) -> str:
    """Build capped topic-scoped research text for a brief batch."""
    topics = list(getattr(outline, "topics", []) or [])
    batch_topics = topics[start_index : start_index + batch_size]
    titles = {
        str(getattr(t, "title", "") or "").lower()
        for t in batch_topics
    }
    parts: list[str] = []
    for section in planner_ctx.get("sections") or []:
        theme = str(section.get("theme") or "")
        markdown = str(section.get("markdown") or "")
        theme_l = theme.lower()
        if titles and not any(
            title and (title in theme_l or theme_l in title)
            for title in titles
        ):
            # Keep fundamentals-style sections for every batch.
            if "fundamental" not in theme_l and start_index > 0:
                continue
        parts.append(f"## {theme}\n{markdown}")
    for source in (planner_ctx.get("sources") or [])[:12]:
        sid = source.get("id")
        excerpt = (source.get("excerpt") or "")[:400]
        title = source.get("title") or ""
        if sid and excerpt:
            parts.append(f"[source:{sid}] {title}\n{excerpt}")
    text = "\n\n".join(parts)
    return text[:8000]


def _validate_brief_batch_sources(
    brief_batch: Any,
    *,
    session_id: str,
    report_id: Optional[str],
    allowed_source_ids: set[str],
) -> Any:
    """Drop fabricated brief source IDs before durable persist."""
    briefs = list(getattr(brief_batch, "briefs", None) or [])
    if not briefs:
        return brief_batch
    persisted_ids: set[str] = set(allowed_source_ids)
    if report_id or session_id:
        try:
            stored = research_store.get_sources_by_ids(
                session_id,
                list(allowed_source_ids) if allowed_source_ids else [],
            )
            if allowed_source_ids:
                persisted_ids = {s.id for s in stored}
            else:
                # Load all session sources when allowlist empty but grounded.
                ctx = research_store.get_planner_context(
                    session_id, max_excerpt_chars=1
                )
                persisted_ids = {
                    str(s.get("id"))
                    for s in (ctx.get("sources") or [])
                    if s.get("id")
                }
        except Exception:
            persisted_ids = set(allowed_source_ids)

    cleaned = []
    for brief in briefs:
        excerpts = list(getattr(brief, "source_excerpts", None) or [])
        if not excerpts:
            cleaned.append(brief)
            continue
        valid = [
            ex
            for ex in excerpts
            if getattr(ex, "source_id", None) in persisted_ids
        ]
        report_ok = getattr(brief, "research_report_id", None)
        if report_id and report_ok and report_ok != report_id:
            report_ok = report_id
        cleaned.append(
            brief.model_copy(
                update={
                    "source_excerpts": valid or None,
                    "research_report_id": report_ok
                    if valid
                    else getattr(brief, "research_report_id", None),
                }
            )
        )
    try:
        return brief_batch.model_copy(update={"briefs": cleaned})
    except Exception:
        return brief_batch
