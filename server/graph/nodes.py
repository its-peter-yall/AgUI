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
    FailedStep,
    GenerationBrief,
    GenerationStage,
    GroundingStatus,
    ProgressEventType,
)
from server.schemas.learning import CourseOutline, NodeStatus, QuizSet, TopicNode
from server.schemas.llm import LLMContext
from server.schemas.search import SearchContext
from server.services.research_runner import run_research

logger = logging.getLogger(__name__)

BatchSpec = namedtuple("BatchSpec", ["start", "size"])


def select_topic_batch(cursor: int, total_topics: int) -> BatchSpec:
    """Select the next batch range starting at cursor."""
    if cursor == 0:
        size = min(PREVIEW_BATCH_SIZE, total_topics)
    else:
        size = min(STANDARD_BATCH_SIZE, total_topics - cursor)
    return BatchSpec(start=cursor, size=size)


def raise_if_cancel_requested(session_id: str) -> None:
    """Check database for cooperative cancel flag and raise GenerationCancelled if set."""
    if session_id and generation_job_store.is_cancel_requested(session_id):
        raise GenerationCancelled(session_id)


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
        stage=next_stage,
        message=f"Initialized course generation (mode={resolved_mode}, web={web_enabled})",
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
        except Exception as exc:
            logger.warning("Research failed for session %s, degrading: %s", session_id, exc)
            degraded = True
            report_id = None

    generation_job_store.update_stage(session_id, GenerationStage.OUTLINING)
    progress_event_store.append_once(
        session_id=session_id,
        event_type=ProgressEventType.STAGE_CHANGED,
        stage=GenerationStage.OUTLINING,
        message="Research complete, proceeding to outline planning",
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

    generation_job_store.update_stage(session_id, GenerationStage.PLANNING_PREVIEW)
    progress_event_store.append_once(
        session_id=session_id,
        event_type=ProgressEventType.STAGE_CHANGED,
        stage=GenerationStage.PLANNING_PREVIEW,
        message=f"Outline created with {len(outline.topics)} topics",
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
        stage=stage_plan,
        message=f"Planning briefs for topics {batch.start} to {batch.start + batch.size - 1}",
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

    stage_gen = GenerationStage.GENERATING_PREVIEW if batch.start == 0 else GenerationStage.GENERATING_BATCH
    generation_job_store.update_stage(session_id, stage_gen)
    progress_event_store.append_once(
        session_id=session_id,
        event_type=ProgressEventType.STAGE_CHANGED,
        stage=stage_gen,
        message=f"Generating content for batch starting at {batch.start}",
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
    batch_start = state["batch_start"]
    raise_if_cancel_requested(session_id)

    llm_ctx = _get_llm_context(runtime)
    node_id = generation_artifact_store._node_id_for_topic(session_id, seq_idx) if hasattr(generation_artifact_store, "_node_id_for_topic") else f"node-{seq_idx}"

    try:
        topic = generation_artifact_store.get_topic(session_id, seq_idx)
        brief = generation_artifact_store.get_brief(node_id)
        prev_summary, next_summary = generation_artifact_store.get_adjacent_summaries(session_id, seq_idx)

        content: GeneratedContent = await generator_agent.generate_explanation(
            topic=topic,
            brief=brief,
            prev_summary=prev_summary,
            next_summary=next_summary,
            llm_context=llm_ctx,
        )

        learning_manager.update_node_content(
            node_id=node_id,
            content_markdown=content.content_markdown,
            status=NodeStatus.GENERATING,
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
    except Exception as exc:
        logger.exception("Generator failed for session %s index %s: %s", session_id, seq_idx, exc)
        learning_manager.update_node_content(
            node_id=node_id,
            content_markdown="Content generation failed.",
            status=NodeStatus.ERROR,
            error_message=str(exc),
            retry_available=True,
            failed_step=FailedStep.GENERATOR,
        )
        return {
            "generator_results": [
                {
                    "batch_start": batch_start,
                    "sequence_index": seq_idx,
                    "content_ready": False,
                    "error_message": str(exc),
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
    batch_start = state["batch_start"]
    raise_if_cancel_requested(session_id)

    llm_ctx = _get_llm_context(runtime)
    node = learning_manager.get_concept_node_by_index(session_id, seq_idx) if hasattr(learning_manager, "get_concept_node_by_index") else None
    if not node:
        all_nodes = learning_manager.get_session_nodes(session_id)
        node = next((n for n in all_nodes if n["sequence_index"] == seq_idx), None)

    if not node or node.get("status") == NodeStatus.ERROR.value:
        return {
            "topic_results": [
                {
                    "batch_start": batch_start,
                    "sequence_index": seq_idx,
                    "terminal_status": "ERROR",
                    "error_message": node.get("error_message") if node else "Node not found",
                }
            ]
        }

    try:
        topic = generation_artifact_store.get_topic(session_id, seq_idx)
        brief = generation_artifact_store.get_brief(node["id"])
        content_markdown = node.get("content_markdown") or ""

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

        learning_manager.update_node_content(
            node_id=node["id"],
            content_markdown=content_markdown,
            status=new_status,
            quiz_set=quiz_set,
        )

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
    except Exception as exc:
        logger.exception("Quizzer failed for session %s index %s: %s", session_id, seq_idx, exc)
        learning_manager.update_node_content(
            node_id=node["id"],
            content_markdown=node.get("content_markdown") or "",
            status=NodeStatus.ERROR,
            error_message=str(exc),
            retry_available=True,
            failed_step=FailedStep.QUIZZER,
        )
        return {
            "topic_results": [
                {
                    "batch_start": batch_start,
                    "sequence_index": seq_idx,
                    "terminal_status": "ERROR",
                    "error_message": str(exc),
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

    topic_results = state.get("topic_results", [])
    has_errors = any(item.get("terminal_status") == "ERROR" for item in topic_results)
    degraded = state.get("degraded", False) or has_errors

    final_stage = GenerationStage.COMPLETE_DEGRADED if degraded else GenerationStage.COMPLETE

    generation_job_store.update_stage(session_id, final_stage)
    progress_event_store.append_once(
        session_id=session_id,
        event_type=ProgressEventType.STAGE_CHANGED,
        stage=final_stage,
        message=f"Course generation completed ({final_stage.value})",
    )

    logger.info("Generation job finalized for session %s with stage %s", session_id, final_stage.value)
    return {}


def build_response_node(state: CourseState) -> dict[str, Any]:
    """Legacy helper for backward compatibility."""
    return {}
