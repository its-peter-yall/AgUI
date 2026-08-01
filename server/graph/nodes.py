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
from server.services.research_runner import run_research

logger = logging.getLogger(__name__)

BatchSpec = namedtuple("BatchSpec", ["start", "size"])


def _append_job_warning(session_id: str, warning: GenerationWarning) -> None:
    """Append a safe warning to the generation job public surface."""
    try:
        from datetime import datetime, timezone

        from server.database.sqlite_utils import (
            canonical_json,
            optional_transaction,
        )

        job = generation_job_store.get_by_session(session_id)
        if job is None:
            return
        warnings = [
            w.model_dump(mode="json") if hasattr(w, "model_dump") else w
            for w in list(job.warnings)
        ]
        warnings.append(warning.model_dump(mode="json"))
        with optional_transaction(generation_job_store.db_path, None) as conn:
            conn.execute(
                """
                UPDATE generation_jobs
                SET warnings_json = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    canonical_json(warnings),
                    datetime.now(timezone.utc).isoformat(),
                    session_id,
                ),
            )
    except Exception:
        logger.debug("warning append skipped for session %s", session_id)


def _bump_job_counts(
    session_id: str,
    *,
    topics_total: Optional[int] = None,
    briefs_ready: Optional[int] = None,
    topics_ready_delta: int = 0,
    topics_failed_delta: int = 0,
    research_sections: Optional[int] = None,
    sources: Optional[int] = None,
    grounding_status: Optional[GroundingStatus] = None,
) -> None:
    """Best-effort update of generation job counts without requiring a lock."""
    try:
        from datetime import datetime, timezone

        from server.database.sqlite_utils import (
            canonical_json,
            optional_transaction,
        )
        from server.schemas.generation import GenerationCounts

        job = generation_job_store.get_by_session(session_id)
        if job is None:
            return
        counts = job.counts
        updates: dict[str, int] = {}
        if topics_total is not None:
            updates["topics_total"] = topics_total
        if briefs_ready is not None:
            updates["briefs_ready"] = briefs_ready
        if topics_ready_delta:
            updates["topics_ready"] = counts.topics_ready + topics_ready_delta
        if topics_failed_delta:
            updates["topics_failed"] = counts.topics_failed + topics_failed_delta
        if research_sections is not None:
            updates["research_sections"] = research_sections
        if sources is not None:
            updates["sources"] = sources
        if updates:
            counts = counts.model_copy(update=updates)
        with optional_transaction(generation_job_store.db_path, None) as conn:
            if grounding_status is not None:
                conn.execute(
                    """
                    UPDATE generation_jobs
                    SET counts_json = ?, grounding_status = ?, updated_at = ?
                    WHERE session_id = ?
                    """,
                    (
                        canonical_json(counts),
                        grounding_status.value,
                        datetime.now(timezone.utc).isoformat(),
                        session_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE generation_jobs
                    SET counts_json = ?, updated_at = ?
                    WHERE session_id = ?
                    """,
                    (
                        canonical_json(counts),
                        datetime.now(timezone.utc).isoformat(),
                        session_id,
                    ),
                )
    except Exception:
        logger.debug("count bump skipped for session %s", session_id)


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
    resolved_mode = state.get("resolved_mode") or "lite"
    if user_mode != "auto" and user_mode in ("lite", "full"):
        resolved_mode = user_mode
    elif resolved_mode not in ("lite", "full"):
        resolved_mode = "lite"

    search_ctx = _get_search_context(runtime)
    web_enabled = state.get("web_search_enabled")
    if web_enabled is None:
        web_enabled = search_ctx.enabled

    next_stage = GenerationStage.RESEARCHING if web_enabled else GenerationStage.OUTLINING
    generation_job_store.update_stage(session_id, next_stage)
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
            )
            degraded = is_degraded
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

    generation_job_store.update_stage(session_id, GenerationStage.OUTLINING)
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
    generation_job_store.update_stage(session_id, GenerationStage.PLANNING_PREVIEW)
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

    generation_job_store.update_stage(session_id, stage_plan)
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

    if not web_enabled:
        grounding_status = GroundingStatus.DISABLED
        research_context = None
    elif degraded:
        grounding_status = GroundingStatus.DEGRADED
        research_context = None
    else:
        grounding_status = GroundingStatus.GROUNDED
        report_id = state.get("research_report_id")
        research_context = research_store.get_report_context(report_id, max_bytes=8000) if report_id else None

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

    generation_artifact_store.persist_briefs(session_id, brief_batch)
    _bump_job_counts(
        session_id,
        briefs_ready=batch.start + batch.size,
    )

    stage_gen = GenerationStage.GENERATING_PREVIEW if batch.start == 0 else GenerationStage.GENERATING_BATCH
    generation_job_store.update_stage(session_id, stage_gen)
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

        generation_artifact_store.persist_generated_content(
            node_id=node_id,
            content_markdown=content.content_markdown,
        )
        if content.citations:
            try:
                generation_artifact_store.replace_node_sources(
                    node_id,
                    content.citations,
                )
            except Exception:
                logger.debug(
                    "citation persist deferred for node %s", node_id
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

    generation_job_store.update_progress(session_id, next_index)

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
        generation_job_store.update_stage(session_id, final_stage)
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

    logger.info(
        "Generation job finalized for session %s with stage %s",
        session_id,
        final_stage.value,
    )
    return {}


def build_response_node(state: CourseState) -> dict[str, Any]:
    """Legacy helper for backward compatibility."""
    return {}
