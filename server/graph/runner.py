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
    - External: asyncio, logging, typing, uuid
    - Internal: server.database, server.graph.build, server.schemas,
                server.utils.safe_logging
USAGE:
    await run_generation_job(app_state, session_id, llm_context, search_context)
============================================================================
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Optional

from server.database.storage_registry import (
    generation_job_repository as generation_job_store,
    learning_repository as learning_manager,
    progress_event_repository as progress_event_store,
)
from server.schemas.generation import (
    GENERATION_LOCK_HEARTBEAT_SECONDS,
    GENERATION_MAX_CONCURRENCY,
    GenerationLock,
    GenerationStage,
    GenerationWarning,
)
from server.schemas.llm import LLMContext
from server.schemas.progress import (
    GenerationCancelledPayload,
    GenerationPausedPayload,
    ProgressEventType,
    StageChangedPayload,
)
from server.schemas.search import SearchContext
from server.utils.safe_logging import log_external_failure

logger = logging.getLogger(__name__)

_LOCK_TTL_SECONDS = GENERATION_LOCK_HEARTBEAT_SECONDS * 3


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


class LockHeartbeatLost(ResumableGenerationError):
    """Raised when lock renewal fails; graph must abort immediately."""

    pass


def _call_maybe_kwargs(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Invoke store methods supporting either keyword or legacy mock APIs."""
    try:
        return fn(**kwargs)
    except TypeError:
        return fn(*args)


async def run_generation_job(
    app_state: Any,
    session_id: str,
    llm_context: LLMContext,
    search_context: SearchContext,
    resume: bool = False,
    worker_id: Optional[str] = None,
    job_store: Any = None,
    event_store: Any = None,
    *,
    shutdown_pause: bool = False,
) -> None:
    """Run course generation job under an execution lock with heartbeat.

    Args:
        shutdown_pause: When True, cooperative task cancellation is recorded
            as PAUSED (process shutdown) rather than user CANCELLED.
    """
    from server.graph.build import get_graph

    js = job_store or generation_job_store
    es = event_store or progress_event_store
    owner = worker_id or f"worker-{uuid.uuid4().hex}"

    job = js.get_by_session(session_id)
    if not job:
        raise LookupError(f"Generation job for session {session_id} not found")

    lock = _call_maybe_kwargs(
        js.try_acquire_lock,
        job.id,
        owner,
        session_id=session_id,
        owner=owner,
        ttl_seconds=_LOCK_TTL_SECONDS,
    )
    if not lock:
        raise GenerationAlreadyRunning(
            f"Job {job.id} for session {session_id} is locked by another worker"
        )

    # Normalize mock SimpleNamespace locks into GenerationLock when possible.
    if not isinstance(lock, GenerationLock):
        try:
            lock = GenerationLock(
                session_id=session_id,
                owner=getattr(lock, "owner", owner),
                version=int(getattr(lock, "version", 1)),
                expires_at=getattr(lock, "expires_at", None)
                or __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ),
            )
        except Exception:
            pass

    heartbeat_task: Optional[asyncio.Task[None]] = None
    heartbeat_lost = asyncio.Event()
    graph_task: Optional[asyncio.Task[Any]] = None

    async def _heartbeat_loop() -> None:
        try:
            while True:
                await asyncio.sleep(GENERATION_LOCK_HEARTBEAT_SECONDS)
                try:
                    renewed = _call_maybe_kwargs(
                        js.renew_lock,
                        job.id,
                        owner,
                        lock=lock,
                        ttl_seconds=_LOCK_TTL_SECONDS,
                    )
                except Exception:
                    renewed = None
                if not renewed:
                    logger.warning("Lock renewal failed for job %s", job.id)
                    heartbeat_lost.set()
                    if graph_task is not None and not graph_task.done():
                        graph_task.cancel()
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
            "worker_id": owner,
            "lock": lock,
            "shutdown_pause": shutdown_pause,
        }

        if resume:
            input_data = None
        else:
            session = None
            try:
                session = learning_manager.get_learning_session(session_id)
            except Exception:
                session = None
            query = ""
            mode = "auto"
            resolved_mode = None
            if session:
                query = session.get("query") or ""
                mode = session.get("mode") or "auto"
                resolved_mode = session.get("resolved_mode")
            # M7: leave auto unresolved here; initialize_generation_node
            # calls depth_router and persists the same value for research+plan.
            if resolved_mode not in ("lite", "full"):
                resolved_mode = None
            input_data = {
                "job_id": job.id,
                "session_id": session_id,
                "query": query,
                "user_id": session.get("user_id") if session else None,
                "mode": mode,
                "resolved_mode": resolved_mode,
                "web_search_enabled": search_context.enabled,
                "research_report_id": None,
                "topic_count": 0,
                "next_topic_index": 0,
                "active_batch_start": 0,
                "active_batch_size": 0,
                "generator_results": [],
                "topic_results": [],
                "degraded": False,
            }

        graph_task = asyncio.create_task(
            graph.ainvoke(input_data, config=config, context=context)
        )
        try:
            await graph_task
        except asyncio.CancelledError:
            if heartbeat_lost.is_set():
                raise LockHeartbeatLost(
                    f"Lock heartbeat lost for session {session_id}"
                ) from None
            raise

        if heartbeat_lost.is_set():
            raise LockHeartbeatLost(
                f"Lock heartbeat lost for session {session_id}"
            )

    except GenerationCancelled:
        logger.info("Generation cancelled for session %s", session_id)
        try:
            _call_maybe_kwargs(
                js.mark_cancelled,
                job.id,
                session_id=session_id,
                lock=lock,
            )
        except Exception:
            try:
                js.update_stage(session_id, GenerationStage.CANCELLED, lock=lock)
            except Exception:
                js.update_stage(session_id, GenerationStage.CANCELLED)
        try:
            es.append_once(
                session_id=session_id,
                event_type=ProgressEventType.GENERATION_CANCELLED,
                payload=GenerationCancelledPayload(stage=GenerationStage.CANCELLED),
                dedupe_key="cancelled_event",
            )
        except Exception:
            pass

    except asyncio.CancelledError:
        # Process shutdown pauses jobs first, then cancels tasks. If the job
        # is already PAUSED (or shutdown_pause flag set), keep PAUSED.
        already_paused = False
        try:
            current = js.get_by_session(session_id)
            already_paused = (
                current is not None
                and getattr(current, "stage", None) == GenerationStage.PAUSED
            )
        except Exception:
            already_paused = False

        if shutdown_pause or already_paused:
            logger.info(
                "Generation paused on shutdown for session %s", session_id
            )
            if not already_paused:
                try:
                    _call_maybe_kwargs(
                        js.mark_paused,
                        job.id,
                        session_id=session_id,
                        lock=lock,
                    )
                except Exception:
                    try:
                        js.update_stage(
                            session_id, GenerationStage.PAUSED, lock=lock
                        )
                    except Exception:
                        js.update_stage(session_id, GenerationStage.PAUSED)
            try:
                es.append_once(
                    session_id=session_id,
                    event_type=ProgressEventType.GENERATION_PAUSED,
                    payload=GenerationPausedPayload(
                        stage=GenerationStage.PAUSED,
                        warning=GenerationWarning(
                            code="process_shutdown",
                            message=(
                                "Generation paused for process restart; "
                                "resume with fresh credentials."
                            ),
                        ),
                    ),
                    dedupe_key="paused_shutdown_event",
                )
            except Exception:
                pass
        else:
            # Cooperative cancel via task cancellation without GenerationCancelled
            logger.info("Generation cancelled for session %s", session_id)
            try:
                _call_maybe_kwargs(
                    js.mark_cancelled,
                    job.id,
                    session_id=session_id,
                    lock=lock,
                )
            except Exception:
                try:
                    js.update_stage(
                        session_id, GenerationStage.CANCELLED, lock=lock
                    )
                except Exception:
                    js.update_stage(session_id, GenerationStage.CANCELLED)
            try:
                es.append_once(
                    session_id=session_id,
                    event_type=ProgressEventType.GENERATION_CANCELLED,
                    payload=GenerationCancelledPayload(
                        stage=GenerationStage.CANCELLED
                    ),
                    dedupe_key="cancelled_event",
                )
            except Exception:
                pass

    except ResumableGenerationError as exc:
        log_external_failure(
            logger,
            event="generation_paused",
            session_id=session_id,
            error=exc,
        )
        try:
            _call_maybe_kwargs(
                js.mark_paused,
                job.id,
                session_id=session_id,
                lock=lock,
            )
        except Exception:
            try:
                js.update_stage(session_id, GenerationStage.PAUSED, lock=lock)
            except Exception:
                js.update_stage(session_id, GenerationStage.PAUSED)
        try:
            es.append_once(
                session_id=session_id,
                event_type=ProgressEventType.GENERATION_PAUSED,
                payload=GenerationPausedPayload(
                    stage=GenerationStage.PAUSED,
                    warning=GenerationWarning(
                        code="resumable_error",
                        message="Generation paused; resume with fresh credentials.",
                    ),
                ),
                dedupe_key="paused_event",
            )
        except Exception:
            pass

    except Exception as exc:
        log_external_failure(
            logger,
            event="generation_failed",
            session_id=session_id,
            error=exc,
        )
        try:
            _call_maybe_kwargs(
                js.mark_failed,
                job.id,
                "Generation failed",
                session_id=session_id,
                safe_message="Generation failed",
            )
        except Exception:
            try:
                js.update_stage(session_id, GenerationStage.FAILED, lock=lock)
            except Exception:
                js.update_stage(session_id, GenerationStage.FAILED)
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

    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        try:
            _call_maybe_kwargs(
                js.release_lock,
                job.id,
                owner,
                lock=lock,
            )
        except Exception:
            pass
