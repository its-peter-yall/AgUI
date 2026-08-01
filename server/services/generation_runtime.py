"""
============================================================================
FILE: generation_runtime.py
LOCATION: server/services/generation_runtime.py
============================================================================
PURPOSE:
    Lifespan-scoped strong task registry for detached course generation.
ROLE IN PROJECT:
    Owns asyncio tasks so browser/SSE disconnect never cancels durable work.
    - Atomically creates session shell/job then schedules the graph runner
    - Coordinates cooperative cancel, resume, shutdown pause, and delete stop
KEY COMPONENTS:
    - GenerationRuntime: start/resume/cancel/stop_for_delete/shutdown
DEPENDENCIES:
    - External: asyncio, logging, typing
    - Internal: server.database, server.graph.runner, server.schemas
USAGE:
    runtime = GenerationRuntime(app_state=app.state)
    accepted = await runtime.start(request_body, llm_context, search_context)
============================================================================
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional, Set

from server.database.generation_jobs import (
    GenerationJobNotFound,
    InvalidGenerationTransition,
    generation_job_store,
)
from server.database.progress_events import progress_event_store
from server.database.research_store import research_store
from server.graph.runner import GenerationAlreadyRunning, run_generation_job
from server.schemas.generation import (
    GenerateCourseAcceptedResponse,
    GenerationControlResponse,
    GenerationJobPublic,
    GenerationStage,
)
from server.schemas.llm import LLMContext
from server.schemas.progress import ProgressEventType, StageChangedPayload
from server.schemas.research import ResearchStatus
from server.schemas.search import SearchContext

logger = logging.getLogger(__name__)

RunnerFn = Callable[..., Awaitable[None]]


class GenerationRuntime:
    """Strongly references detached generation tasks for process lifetime."""

    def __init__(
        self,
        *,
        app_state: Any,
        job_store: Any = None,
        event_store: Any = None,
        research: Any = None,
        runner: Optional[RunnerFn] = None,
    ) -> None:
        self.app_state = app_state
        self.job_store = job_store or generation_job_store
        self.event_store = event_store or progress_event_store
        self.research = research or research_store
        self.runner = runner or run_generation_job
        self.active_tasks: Set[asyncio.Task[None]] = set()
        self._session_tasks: dict[str, asyncio.Task[None]] = {}

    def _track_task(self, session_id: str, task: asyncio.Task[None]) -> None:
        self.active_tasks.add(task)
        self._session_tasks[session_id] = task

        def _done(done: asyncio.Task[None]) -> None:
            self.active_tasks.discard(done)
            if self._session_tasks.get(session_id) is done:
                self._session_tasks.pop(session_id, None)
            try:
                exc = done.exception()
            except asyncio.CancelledError:
                return
            if exc is not None:
                from server.utils.safe_logging import log_external_failure

                log_external_failure(
                    logger,
                    event="generation_task_failed",
                    session_id=session_id,
                    error=exc,
                )

        task.add_done_callback(_done)

    def _schedule(
        self,
        *,
        session_id: str,
        llm_context: LLMContext,
        search_context: SearchContext,
        resume: bool,
        shutdown_pause: bool = False,
    ) -> None:
        async def _run() -> None:
            try:
                await self.runner(
                    app_state=self.app_state,
                    session_id=session_id,
                    llm_context=llm_context,
                    search_context=search_context,
                    resume=resume,
                    shutdown_pause=shutdown_pause,
                )
            except TypeError:
                # Older runner doubles may omit shutdown_pause.
                await self.runner(
                    app_state=self.app_state,
                    session_id=session_id,
                    llm_context=llm_context,
                    search_context=search_context,
                    resume=resume,
                )

        task = asyncio.create_task(_run(), name=f"gen-{session_id}")
        self._track_task(session_id, task)

    async def start(
        self,
        *,
        request_body: Any,
        llm_context: LLMContext,
        search_context: SearchContext,
    ) -> dict[str, Any]:
        """Create shell/job, emit initial event, schedule runner, return 202 body."""
        session, job = self.job_store.create_session_shell_and_job(
            query=request_body.query,
            user_id=getattr(request_body, "user_id", None),
            mode=request_body.mode,
            web_search_requested=search_context.enabled,
        )
        session_id = session["id"]
        try:
            self.event_store.append_once(
                session_id=session_id,
                event_type=ProgressEventType.STAGE_CHANGED,
                payload=StageChangedPayload(
                    previous_stage=GenerationStage.INITIALIZING,
                    stage=GenerationStage.INITIALIZING,
                ),
                dedupe_key="stage:INITIALIZING:0",
            )
        except Exception:
            logger.debug("Initial stage event skipped for session %s", session_id)

        self._schedule(
            session_id=session_id,
            llm_context=llm_context,
            search_context=search_context,
            resume=False,
        )

        public_session = self._shell_session_payload(session)
        generation = self.job_store.to_public(job)
        return {
            "session": public_session,
            "generation": (
                generation.model_dump(mode="json")
                if hasattr(generation, "model_dump")
                else generation
            ),
        }

    @staticmethod
    def _shell_session_payload(session: dict[str, Any]) -> dict[str, Any]:
        title_finalized = session.get("title_finalized", False)
        if isinstance(title_finalized, int):
            title_finalized = bool(title_finalized)
        query = session.get("query") or ""
        return {
            "id": session.get("id"),
            "user_id": session.get("user_id"),
            "query": query,
            "course_title": session.get("course_title") or query,
            "title_finalized": title_finalized,
            "mode": session.get("mode"),
            "resolved_mode": session.get("resolved_mode"),
            "total_nodes": int(session.get("total_nodes") or 0),
            "completed_nodes": int(session.get("completed_nodes") or 0),
            "last_active_node_id": session.get("last_active_node_id"),
            "created_at": session.get("created_at"),
            "updated_at": session.get("updated_at"),
            "nodes": session.get("nodes") or [],
        }

    async def cancel(self, session_id: str) -> dict[str, Any]:
        """Set cooperative cancel flag; retain all artifacts."""
        job = self.job_store.get_by_session(session_id)
        if job is None:
            raise GenerationJobNotFound(session_id)
        if job.stage in {
            GenerationStage.COMPLETE,
            GenerationStage.COMPLETE_DEGRADED,
            GenerationStage.FAILED,
            GenerationStage.CANCELLED,
        }:
            raise InvalidGenerationTransition(
                f"Cannot cancel job in stage {job.stage.value}"
            )
        updated = self.job_store.request_cancel(session_id)
        public = self.job_store.to_public(updated)
        return {
            "generation": (
                public.model_dump(mode="json")
                if hasattr(public, "model_dump")
                else public
            )
        }

    async def resume(
        self,
        *,
        session_id: str,
        llm_context: LLMContext,
        search_context: SearchContext,
    ) -> dict[str, Any]:
        """Restore paused/cancelled job and schedule same thread with fresh secrets."""
        job = self.job_store.get_by_session(session_id)
        if job is None:
            raise GenerationJobNotFound(session_id)
        if job.stage not in {
            GenerationStage.PAUSED,
            GenerationStage.CANCELLED,
        }:
            raise GenerationAlreadyRunning(session_id)

        if job.web_search_requested:
            report = None
            try:
                report = self.research.get_report(session_id)
            except Exception:
                report = None
            research_open = report is None or report.status in {
                ResearchStatus.PENDING,
                ResearchStatus.RESEARCHING,
                ResearchStatus.NOT_REQUESTED,
            }
            if research_open and not search_context.enabled:
                from fastapi import HTTPException, status

                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Web search credentials required to resume research.",
                )

        existing = self._session_tasks.get(session_id)
        if existing is not None and not existing.done():
            raise GenerationAlreadyRunning(session_id)

        previous_stage = job.stage
        updated = self.job_store.prepare_resume(session_id)
        # M9: emit monotonic progress event so equal-ID polls cannot undo resume.
        try:
            from server.database.progress_events import progress_event_store
            from server.schemas.progress import (
                ProgressEventType,
                StageChangedPayload,
            )

            progress_event_store.append_once(
                session_id=session_id,
                event_type=ProgressEventType.STAGE_CHANGED,
                payload=StageChangedPayload(
                    previous_stage=previous_stage,
                    stage=updated.stage,
                ),
                dedupe_key=(
                    f"stage_resume:{session_id}:{updated.stage.value}:"
                    f"{updated.updated_at.isoformat()}"
                ),
            )
        except Exception:
            logger = __import__("logging").getLogger(__name__)
            logger.debug(
                "resume stage event skipped for session %s", session_id
            )
        self._schedule(
            session_id=session_id,
            llm_context=llm_context,
            search_context=search_context,
            resume=True,
        )
        public = self.job_store.to_public(updated)
        return {
            "generation": (
                public.model_dump(mode="json")
                if hasattr(public, "model_dump")
                else public
            )
        }

    async def stop_for_delete(self, session_id: str) -> None:
        """Cooperatively stop local work before permanent session delete."""
        try:
            self.job_store.request_cancel(session_id)
        except (GenerationJobNotFound, LookupError):
            pass

        task = self._session_tasks.get(session_id)
        if task is None or task.done():
            return

        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def shutdown(self) -> None:
        """Pause unfinished jobs and cancel only this process's tasks.

        Marks nonterminal jobs PAUSED before cancelling local tasks so
        task cancellation is not recorded as user CANCELLED.
        """
        try:
            try:
                self.job_store.mark_orphaned_jobs_paused(
                    pause_all_nonterminal=True
                )
            except TypeError:
                self.job_store.mark_orphaned_jobs_paused()
        except Exception:
            logger.exception("Failed to mark orphaned jobs paused on shutdown")

        # Flag in-flight runners that task cancel means process pause.
        self._shutdown_in_progress = True
        tasks = list(self.active_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.active_tasks.clear()
        self._session_tasks.clear()
