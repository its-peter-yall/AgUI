"""
============================================================================
FILE: runner.py
LOCATION: server/graph/runner.py
============================================================================
PURPOSE:
    Provides durable, locked graph execution for new and resumed generation jobs.
ROLE IN PROJECT:
    Orchestrates LangGraph execution with lock heartbeats, cancellation,
    pause, and error recovery.
KEY COMPONENTS:
    - GenerationAlreadyRunning: Raised when lock acquisition fails
    - GenerationCancelled: Raised when job cancellation is detected
    - ResumableGenerationError: Raised when execution should pause for retry
    - run_generation_job: Main execution entry point
DEPENDENCIES:
    - External: asyncio, logging, typing
    - Internal: server.database, server.graph.build, server.schemas
USAGE:
    await run_generation_job(app_state, session_id, llm_context, search_context)
============================================================================
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from server.database.generation_jobs import generation_job_store
from server.database.progress_events import progress_event_store
from server.schemas.generation import (
    GENERATION_LOCK_HEARTBEAT_SECONDS,
    GENERATION_MAX_CONCURRENCY,
    GenerationStage,
)
from server.schemas.progress import (
    GenerationCancelledPayload,
    GenerationPausedPayload,
    ProgressEventType,
    StageChangedPayload,
)
from server.schemas.generation import GenerationWarning

logger = logging.getLogger(__name__)


class GenerationAlreadyRunning(RuntimeError):
    """Raised when another worker currently holds the job execution lock."""

    pass


class GenerationCancelled(RuntimeError):
    """Raised when job execution is cancelled cooperatively."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Generation job for session {session_id} was cancelled")
        self.session_id = session_id


class ResumableGenerationError(RuntimeError):
    """Raised when execution encounters a resumable pause condition."""

    pass


async def run_generation_job(
    app_state: Any,
    session_id: str,
    llm_context: LLMContext,
    search_context: SearchContext,
    resume: bool = False,
    worker_id: str = "worker-1",
    job_store: Any = None,
    event_store: Any = None,
) -> None:
    """Run course generation job under an execution lock with heartbeat."""
    from server.graph.build import get_graph
    js = job_store or generation_job_store
    es = event_store or progress_event_store

    job = js.get_by_session(session_id)
    if not job:
        raise LookupError(f"Generation job for session {session_id} not found")

    lock = js.try_acquire_lock(job.id, worker_id)
    if not lock:
        raise GenerationAlreadyRunning(
            f"Job {job.id} for session {session_id} is locked by another worker"
        )

    heartbeat_task: Optional[asyncio.Task] = None

    async def _heartbeat_loop() -> None:
        try:
            while True:
                await asyncio.sleep(GENERATION_LOCK_HEARTBEAT_SECONDS)
                renewed = js.renew_lock(job.id, worker_id)
                if not renewed:
                    logger.warning("Lock renewal failed for job %s", job.id)
                    break
        except asyncio.CancelledError:
            pass

    heartbeat_task = asyncio.create_task(_heartbeat_loop())

    try:
        graph = get_graph(app_state)
        thread_id = getattr(job, "thread_id", f"gen-{session_id}")

        config = {
            "configurable": {"thread_id": thread_id},
            "max_concurrency": GENERATION_MAX_CONCURRENCY,
        }
        context = {
            "llm_context": llm_context,
            "search_context": search_context,
            "worker_id": worker_id,
        }

        if resume:
            input_data = None
        else:
            input_data = {
                "job_id": job.id,
                "session_id": session_id,
                "query": getattr(job, "query", ""),
                "user_id": getattr(job, "user_id", None),
                "mode": getattr(job, "mode", "full"),
                "resolved_mode": getattr(job, "resolved_mode", "full"),
                "web_search_enabled": search_context.enabled,
                "research_report_id": getattr(job, "research_report_id", None),
                "topic_count": 0,
                "next_topic_index": 0,
                "active_batch_start": 0,
                "active_batch_size": 0,
                "generator_results": [],
                "topic_results": [],
                "degraded": False,
            }

        await graph.ainvoke(input_data, config=config, context=context)

    except (GenerationCancelled, asyncio.CancelledError):
        logger.info("Generation cancelled for session %s", session_id)
        js.mark_cancelled(job.id)
        try:
            es.append_once(
                session_id=session_id,
                event_type=ProgressEventType.GENERATION_CANCELLED,
                payload=GenerationCancelledPayload(stage=GenerationStage.CANCELLED),
                dedupe_key="cancelled_event",
            )
        except Exception:
            pass

    except ResumableGenerationError as exc:
        logger.warning("Generation paused for session %s: %s", session_id, exc)
        js.mark_paused(job.id)
        try:
            es.append_once(
                session_id=session_id,
                event_type=ProgressEventType.GENERATION_PAUSED,
                payload=GenerationPausedPayload(
                    stage=GenerationStage.PAUSED,
                    warning=GenerationWarning(code="resumable_error", message=str(exc)),
                ),
                dedupe_key=f"paused_{abs(hash(str(exc)))}",
            )
        except Exception:
            pass

    except Exception as exc:
        logger.exception("Generation job failed for session %s", session_id)
        js.mark_failed(job.id, str(exc))
        try:
            es.append_once(
                session_id=session_id,
                event_type=ProgressEventType.STAGE_CHANGED,
                payload=StageChangedPayload(
                    previous_stage=GenerationStage.INITIALIZING,
                    stage=GenerationStage.FAILED,
                ),
                dedupe_key="failed_event",
            )
        except Exception:
            pass
        except Exception:
            pass

    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        js.release_lock(job.id, worker_id)
