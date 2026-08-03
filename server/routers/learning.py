"""
============================================================================
FILE: learning.py
LOCATION: server/routers/learning.py
============================================================================
PURPOSE:
    FastAPI router providing REST API endpoints for the adaptive learning
    system. Handles course generation, session retrieval, concept node
    management, and quiz state transitions.
ROLE IN PROJECT:
    Defines the HTTP interface for the learning feature.
    - Maps URL routes to business logic in LangGraph course graph
    - Enforces server-authoritative state validation on all transitions
KEY COMPONENTS:
    - generate_course: Creates structured learning courses from topic queries
    - get_learning_session: Retrieves session with all concept nodes
    - get_concept_node: Fetches node with state-based content visibility
    - transition_node: Validates and applies state transitions
    - submit_quiz: Records answer and unlocks next node on mastery
    - retry_quiz: Resets node state for retry after incorrect answer
DEPENDENCIES:
    - External: fastapi
    - Internal: server.database.learning_persistence, server.schemas.learning,
              server.graph.build
USAGE:
    ```python
    response = await client.post("/learning/generate",
        json={"query": "Python basics", "user_id": "user123"})
    ```
============================================================================
"""

import asyncio
import logging
import time
from typing import List, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query, status, Depends, Request, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from server.agents.planner import OutlineTopicCountError
from server.database.generation_jobs import (
    GenerationJobNotFound,
    InvalidGenerationTransition,
)
from server.database.storage_registry import (
    generation_job_repository as generation_job_store,
    learning_repository as learning_manager,
    progress_event_repository as progress_event_store,
    research_repository as research_store,
)
from server.graph.build import get_graph
from server.schemas.search import SearchContext, get_search_context
from server.graph.regen import regenerate_failed_node, regenerate_topic_node
from server.graph.runner import GenerationAlreadyRunning
from server.schemas.generation import (
    GenerateCourseAcceptedResponse,
    GenerationControlResponse,
    GenerationJobPublic,
)
from server.schemas.learning import (
    ConceptChatRequest,
    ConceptNodeResponse,
    LearningSessionResponse,
    LearningSessionSummary,
    ModuleGenerationStatus,
    NodeStatus,
    PublicNodeCitation,
    QuizAttemptHistory,
    QuizAttemptResponse,
    QuizSetHidden,
    RevisionCreateRequest,
    RevisionNodeProgress,
    RevisionQuizSubmissionResult,
    RevisionSessionListResponse,
    RevisionSessionResponse,
    RevisionSessionWithProgress,
    RevisionSummary,
    SessionProgress,
    SessionListResponse,
    TopicNode,
    FailedStep,
    QuizSet,
)
from server.agents.generator import generator_agent
from server.agents.quizzer import quizzer_agent
from server.schemas.llm import (
    LLMContext,
    get_llm_context,
    require_agent_models,
)
from server.schemas.research import ResearchReport
from server.services.concept_chat import stream_concept_chat
from server.services.depth_router import resolve_depth_mode
from server.services.quiz_randomization import (
    get_or_create_shuffle_order,
    hide_quiz_card,
    shuffle_quiz_set_with_seed,
)
from server.services.session_event_stream import stream_session_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/learning", tags=["learning"])


CONTENT_VISIBLE_STATES = {
    NodeStatus.VIEWING_EXPLANATION,
    NodeStatus.SHOWING_FEEDBACK,
    NodeStatus.COMPLETED,
}
QUIZ_VISIBLE_STATES = {
    NodeStatus.IN_QUIZ,
    NodeStatus.SHOWING_FEEDBACK,
    NodeStatus.COMPLETED,
}


class GenerateCourseRequest(BaseModel):
    """Request schema for generating a learning course."""

    query: str = Field(
        ...,
        description="Topic to learn about",
        min_length=1,
        max_length=500,
    )
    user_id: Optional[str] = Field(default=None, description="Optional user ID")
    mode: Literal["auto", "lite", "full"] = Field(
        default="auto",
        description="Depth mode: auto routes; lite 3-10; full 10-30 topics",
    )


class LearningSessionWithNodes(LearningSessionResponse):
    """Learning session with all concept nodes."""

    nodes: List[ConceptNodeResponse] = Field(
        default_factory=list,
        description="All concept nodes in sequence order",
    )
    generation: Optional[GenerationJobPublic] = Field(
        default=None,
        description="Progressive generation job snapshot when present",
    )


class ConceptNodeWithVisibility(ConceptNodeResponse):
    """Node response with state-based content visibility."""

    content_visible: bool = Field(
        ...,
        description="Whether explanation content is visible in current state",
    )
    quiz_visible: bool = Field(
        ...,
        description="Whether quiz is visible in current state",
    )


class TransitionRequest(BaseModel):
    """Request to transition node to a new state."""

    target_status: NodeStatus = Field(
        ...,
        description="Target status to transition to",
    )


class QuizSubmitRequest(BaseModel):
    """Request to submit a quiz answer.

    Uses stable option_id (UUID) for secure evaluation even when options
    are shuffled. The option_id is returned with each option and persists
    across shuffles, while display_label (A, B, C, D) may change position.
    """

    selected_option_ids: List[str] = Field(
        ...,
        min_length=1,
        description="Selected option UUID(s) (stable IDs from option.option_id)",
    )
    quiz_index: int = Field(
        default=0,
        description="Index of quiz in set being answered (0-based)",
        ge=0,
    )


class LastActiveRequest(BaseModel):
    """Request to update last active node for a session."""

    node_id: str = Field(..., description="ID of the last active node")


class DeleteRevisionResponse(BaseModel):
    """Response payload for deleting a revision session."""

    deleted: bool = Field(..., description="Whether the revision was deleted")


def _apply_node_visibility(node: dict, include_flags: bool = False) -> dict:
    """Apply state-based content visibility and quiz randomization to a node."""
    status_val = NodeStatus(node["status"])

    content_visible = status_val in CONTENT_VISIBLE_STATES
    quiz_visible = status_val in QUIZ_VISIBLE_STATES

    response_node = dict(node)
    response_node["quiz_set"] = None
    response_node["quiz_hidden"] = None
    response_node["quiz_set_hidden"] = None

    raw_quiz = node.get("quiz")
    total_quizzes = None
    if raw_quiz:
        if isinstance(raw_quiz, dict):
            if "quizzes" in raw_quiz:
                total_quizzes = len(raw_quiz["quizzes"])
            elif "question" in raw_quiz:
                total_quizzes = 1

        if total_quizzes is None:
            complexity = node.get("complexity")
            if complexity == "Basic":
                total_quizzes = 1
            elif complexity == "Advanced":
                total_quizzes = 3
            else:
                total_quizzes = 2

    response_node["total_quizzes"] = total_quizzes

    if include_flags and not content_visible:
        response_node["content_markdown"] = ""

    if quiz_visible and node.get("quiz"):
        quiz_set_data = learning_manager.get_quiz_set_for_node(node["id"])
        if quiz_set_data:
            quiz_set = quiz_set_data["quiz_set"]
            existing_seed = quiz_set_data.get("shuffle_seed")
            current_index = quiz_set_data.get("current_index", 0)
            shuffled_set = quiz_set

            if quiz_set.quizzes:
                current_index = max(0, min(current_index, len(quiz_set.quizzes) - 1))
            else:
                current_index = 0

            if status_val == NodeStatus.IN_QUIZ and quiz_set.quizzes:
                shuffle_seed = (
                    existing_seed
                    or quiz_set.shuffle_seed
                    or _ensure_quiz_shuffle_seed(node["id"])
                )
                if shuffle_seed:
                    shuffled_set = shuffle_quiz_set_with_seed(quiz_set, shuffle_seed)
                    shuffled_quiz = shuffled_set.quizzes[current_index]
                else:
                    shuffled_quiz = quiz_set.quizzes[current_index]
                hidden_quiz = hide_quiz_card(shuffled_quiz)
                response_node["quiz_hidden"] = hidden_quiz
                response_node["quiz"] = None

                # Populate quiz_set_hidden for multi-quiz progress indicator
                if len(quiz_set.quizzes) > 1:
                    hidden_quizzes = [hide_quiz_card(q) for q in shuffled_set.quizzes]
                    response_node["quiz_set_hidden"] = QuizSetHidden(
                        quizzes=hidden_quizzes,
                        current_index=current_index,
                        total_quizzes=len(quiz_set.quizzes),
                    )
            elif quiz_set.quizzes:
                review_seed = (
                    existing_seed
                    or quiz_set.shuffle_seed
                    or _ensure_quiz_shuffle_seed(node["id"])
                )
                if not review_seed:
                    review_seed = node["id"]
                shuffled_set = shuffle_quiz_set_with_seed(quiz_set, review_seed)
                response_node["quiz_set"] = shuffled_set
                response_node["quiz"] = shuffled_set.quizzes[current_index]
        else:
            response_node["quiz"] = None
    else:
        response_node["quiz"] = None

    if include_flags:
        response_node["content_visible"] = content_visible
        response_node["quiz_visible"] = quiz_visible

    return response_node


def _ensure_quiz_shuffle_seed(node_id: str) -> Optional[str]:
    """Ensure a node has a persisted shuffle seed and return it."""
    quiz_set_data = learning_manager.get_quiz_set_for_node(node_id)
    if not quiz_set_data:
        return None

    quiz_set = quiz_set_data["quiz_set"]
    current_index = quiz_set_data.get("current_index", 0)

    if not quiz_set.quizzes:
        return None

    current_index = max(0, min(current_index, len(quiz_set.quizzes) - 1))
    current_quiz = quiz_set.quizzes[current_index]

    existing_seed = quiz_set_data.get("shuffle_seed")
    _, shuffle_seed = get_or_create_shuffle_order(
        current_quiz,
        existing_seed=existing_seed,
        quiz_set_seed=quiz_set.shuffle_seed,
    )

    if shuffle_seed != existing_seed:
        learning_manager.update_quiz_shuffle_seed(node_id, shuffle_seed)

    return shuffle_seed


@router.post(
    "/generate",
    response_model=GenerateCourseAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate a learning course",
    description=(
        "Create a durable session shell and start detached progressive "
        "course generation. Returns immediately with 202."
    ),
)
async def generate_course(
    request_body: GenerateCourseRequest,
    request: Request,
    llm_context: LLMContext = Depends(get_llm_context),
    search_context: SearchContext = Depends(get_search_context),
) -> JSONResponse:
    """Accept generation and return shell + public job immediately."""
    require_agent_models(llm_context)
    try:
        runtime = getattr(request.app.state, "generation_runtime", None)
        if runtime is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Generation runtime unavailable",
            )
        accepted = await runtime.start(
            request_body=request_body,
            llm_context=llm_context,
            search_context=search_context,
        )
        # JSONResponse preserves store ISO timestamps (no Z re-normalization).
        return JSONResponse(
            content=accepted,
            status_code=status.HTTP_202_ACCEPTED,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error accepting course generation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    summary="List learning sessions",
    description=(
        "Get a paginated, filterable learning session list with progress "
        "and revision counts."
    ),
)
def get_learning_sessions(
    user_id: Optional[str] = Query(default=None),
    status_filter: str = Query(default="all", alias="status"),
    sort_by: str = Query(default="updated_at"),
    sort_order: str = Query(default="desc"),
    limit: int = Query(default=20, ge=0),
    offset: int = Query(default=0, ge=0),
) -> SessionListResponse:
    """List learning sessions with filtering, sorting, and pagination."""
    allowed_status = {"all", "in_progress", "completed"}
    allowed_sort_by = {"updated_at", "created_at", "progress_percent"}
    allowed_sort_order = {"asc", "desc"}
    try:
        if status_filter not in allowed_status:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid status filter",
            )
        if sort_by not in allowed_sort_by:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid sort_by field",
            )
        if sort_order not in allowed_sort_order:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid sort_order field",
            )

        safe_limit = min(limit, 100)
        sessions, total_count = learning_manager.get_sessions_list(
            user_id=user_id,
            status=status_filter,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=safe_limit,
            offset=offset,
        )
        has_more = total_count > (offset + safe_limit)
        job_map = generation_job_store.get_public_by_sessions(
            [s["id"] for s in sessions if s.get("id")]
        )
        typed_sessions: list[LearningSessionSummary] = []
        for s in sessions:
            row = dict(s)
            public_job = job_map.get(s["id"])
            if public_job is not None:
                row["generation_stage"] = public_job.stage.value
                row["grounding_status"] = public_job.grounding_status.value
                # M10: nested generation matches client CourseCard contract.
                row["generation"] = (
                    public_job.model_dump(mode="json")
                    if hasattr(public_job, "model_dump")
                    else public_job
                )
            typed_sessions.append(LearningSessionSummary.model_validate(row))
        return SessionListResponse(
            sessions=typed_sessions,
            total_count=total_count,
            has_more=has_more,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing learning sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get(
    "/sessions/{session_id}/progress",
    response_model=SessionProgress,
    summary="Get learning session progress",
    description=(
        "Get progress summary for a learning session, including completed node "
        "counts and last active node."
    ),
)
def get_learning_session_progress(session_id: str) -> SessionProgress:
    """Get progress summary for a learning session."""
    try:
        progress = learning_manager.get_session_progress(session_id)
        if not progress:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Learning session not found: {session_id}",
            )
        return SessionProgress(**progress)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting learning session progress: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.patch(
    "/sessions/{session_id}/last-active",
    summary="Update last active node",
    description="Update the last active node for a learning session.",
)
def update_last_active(
    session_id: str,
    request: LastActiveRequest,
) -> dict:
    """Update the last active node position for resume."""
    try:
        learning_manager.update_last_active_node(session_id, request.node_id)
        return {"updated": True}
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(f"Learning session not found: {session_id}"),
        )
    except Exception as e:
        logger.error(f"Error updating last active node: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(f"Failed to update last active node: {str(e)}"),
        )


def _map_module_status(raw: object) -> ModuleGenerationStatus:
    """Map DB generation_status to public module_status."""
    if raw is None:
        return ModuleGenerationStatus.READY
    try:
        return ModuleGenerationStatus(str(raw))
    except ValueError:
        return ModuleGenerationStatus.READY


def _project_session_node(
    node: dict,
    citations_by_node: dict[str, list],
) -> ConceptNodeResponse:
    """Apply visibility, progressive blanking, module status, and citations."""
    module_status = _map_module_status(node.get("generation_status"))
    working = dict(node)
    if module_status in {
        ModuleGenerationStatus.SKELETON,
        ModuleGenerationStatus.GENERATING,
    }:
        working["content_markdown"] = ""
        working["quiz"] = None
        visible = _apply_node_visibility(working)
        visible["content_markdown"] = ""
        visible["quiz"] = None
        visible["quiz_set"] = None
        visible["quiz_hidden"] = None
        visible["quiz_set_hidden"] = None
        visible["total_quizzes"] = None
    else:
        visible = _apply_node_visibility(working)

    visible["module_status"] = module_status
    raw_citations = citations_by_node.get(node["id"], [])
    citations: list[PublicNodeCitation] = []
    for item in raw_citations:
        if isinstance(item, PublicNodeCitation):
            citations.append(item)
        elif isinstance(item, dict):
            citations.append(PublicNodeCitation.model_validate(item))
    visible["citations"] = citations
    return ConceptNodeResponse(**visible)


@router.get(
    "/sessions/{session_id}",
    response_model=LearningSessionWithNodes,
    summary="Get learning session",
    description="Get a learning session with all its concept nodes.",
)
def get_learning_session(session_id: str) -> LearningSessionWithNodes:
    """Get a learning session by ID with all nodes."""
    try:
        session = learning_manager.get_learning_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Learning session not found: {session_id}",
            )

        nodes_data = learning_manager.get_session_nodes(session_id)
        generation = generation_job_store.to_public_by_session(session_id)
        try:
            citations_by_node = research_store.get_citations_by_session(session_id)
        except Exception:
            citations_by_node = {}

        nodes = [
            _project_session_node(node, citations_by_node) for node in nodes_data
        ]

        title_finalized = session.get("title_finalized", True)
        if isinstance(title_finalized, int):
            title_finalized = bool(title_finalized)
        if generation is None and "title_finalized" not in session:
            title_finalized = True

        payload = dict(session)
        payload["title_finalized"] = title_finalized
        if isinstance(generation, GenerationJobPublic):
            payload["generation"] = generation
        elif isinstance(generation, dict):
            payload["generation"] = GenerationJobPublic.model_validate(generation)
        else:
            payload["generation"] = None

        return LearningSessionWithNodes(**payload, nodes=nodes)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting learning session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


def _parse_event_cursor(
    after: Optional[int],
    last_event_id: Optional[str],
) -> int:
    """Resolve SSE cursor from query and Last-Event-ID header."""
    after_val = 0 if after is None else after
    if after_val < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="after must be a non-negative integer",
        )
    header_val = 0
    if last_event_id is not None and str(last_event_id).strip() != "":
        try:
            header_val = int(str(last_event_id).strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Last-Event-ID must be a non-negative integer",
            ) from exc
        if header_val < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Last-Event-ID must be a non-negative integer",
            )
    return max(after_val, header_val)


@router.get(
    "/sessions/{session_id}/research",
    response_model=ResearchReport,
    summary="Get course research report",
    description=(
        "Return the public research report and normalized sources for a "
        "session. Never includes credentials or private briefs."
    ),
)
def get_session_research(session_id: str) -> ResearchReport:
    """Return public research report projection for a session."""
    from datetime import datetime, timezone

    from server.schemas.research import ResearchStatus

    session = learning_manager.get_learning_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Learning session not found: {session_id}",
        )

    job = generation_job_store.get_by_session(session_id)
    now = datetime.now(timezone.utc)
    created = session.get("created_at") or now.isoformat()
    updated = session.get("updated_at") or created

    if job is None or not job.web_search_requested:
        return ResearchReport.model_validate(
            {
                "id": f"not-requested-{session_id}",
                "session_id": session_id,
                "status": ResearchStatus.NOT_REQUESTED.value,
                "summary": None,
                "limitations": [],
                "freshness_note": None,
                "sections": [],
                "sources": [],
                "provider_statuses": [],
                "warnings": [],
                "created_at": created,
                "updated_at": updated,
            }
        )

    report = research_store.get_public_report(session_id)
    if report is None:
        return ResearchReport.model_validate(
            {
                "id": f"pending-{session_id}",
                "session_id": session_id,
                "status": ResearchStatus.PENDING.value,
                "summary": None,
                "limitations": [],
                "freshness_note": None,
                "sections": [],
                "sources": [],
                "provider_statuses": [],
                "warnings": [],
                "created_at": created,
                "updated_at": updated,
            }
        )
    if isinstance(report, ResearchReport):
        return report
    return ResearchReport.model_validate(report)


@router.get(
    "/sessions/{session_id}/events",
    summary="Stream generation progress events",
    description=(
        "Replay durable progress events after a cursor, then tail new events "
        "as Server-Sent Events. Disconnect does not cancel generation."
    ),
)
async def stream_learning_session_events(
    session_id: str,
    after: Optional[int] = Query(default=None, description="Exclusive event id cursor"),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Replay-then-tail SSE for a learning session."""
    session = learning_manager.get_learning_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Learning session not found: {session_id}",
        )
    cursor = _parse_event_cursor(after, last_event_id)
    generator = stream_session_events(
        session_id=session_id,
        cursor=cursor,
        event_store=progress_event_store,
        job_store=generation_job_store,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/sessions/{session_id}/revisions",
    response_model=RevisionSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create revision session",
    description=("Create a revision session for a completed learning session."),
)
def create_revision(
    session_id: str,
    request: RevisionCreateRequest,
) -> RevisionSessionResponse:
    """Create a new revision session for a completed learning session."""
    try:
        revision = learning_manager.create_revision_session(
            session_id,
            request.mode,
        )
        return RevisionSessionResponse(**revision)
    except LookupError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error creating revision session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get(
    "/sessions/{session_id}/revisions",
    response_model=RevisionSessionListResponse,
    summary="List revision sessions",
    description=("Get revision sessions for a learning session with pagination."),
)
def get_revisions_for_session(
    session_id: str,
    limit: int = Query(default=20, ge=0),
    offset: int = Query(default=0, ge=0),
) -> RevisionSessionListResponse:
    """List revision sessions for an original learning session."""
    try:
        safe_limit = min(limit, 100)
        revisions, total_count = learning_manager.get_revisions_for_session(
            session_id=session_id,
            limit=safe_limit,
            offset=offset,
        )
        typed_revisions = [
            RevisionSessionResponse.model_validate(r) for r in revisions
        ]
        return RevisionSessionListResponse(
            revisions=typed_revisions,
            total_count=total_count,
        )
    except Exception as e:
        logger.error(f"Error listing revision sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get(
    "/revisions/{revision_id}",
    response_model=RevisionSessionWithProgress,
    summary="Get revision session",
    description="Get a revision session with node-level progress details.",
)
def get_revision(revision_id: str) -> RevisionSessionWithProgress:
    """Get a revision session by ID."""
    try:
        revision = learning_manager.get_revision_session(revision_id)
        if not revision:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Revision session not found: {revision_id}",
            )
        return RevisionSessionWithProgress(**revision)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting revision session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.delete(
    "/revisions/{revision_id}",
    response_model=DeleteRevisionResponse,
    summary="Delete revision session",
    description="Delete a revision session and its node progress records.",
)
def delete_revision(revision_id: str) -> DeleteRevisionResponse:
    """Delete a revision session by ID."""
    try:
        deleted = learning_manager.delete_revision_session(revision_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Revision session not found: {revision_id}",
            )
        return DeleteRevisionResponse(deleted=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting revision session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


class DeleteLearningSessionResponse(BaseModel):
    """Response payload for deleting a learning session."""

    deleted: bool = Field(..., description="Whether the session was deleted")


@router.post(
    "/sessions/{session_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Cancel generation",
    description=(
        "Request cooperative cancellation. Retains partial artifacts; "
        "does not delete the session."
    ),
)
async def cancel_generation(
    session_id: str,
    request: Request,
) -> JSONResponse:
    """Set cooperative cancel flag and return public generation state."""
    session = learning_manager.get_learning_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Learning session not found: {session_id}",
        )
    runtime = getattr(request.app.state, "generation_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Generation runtime unavailable",
        )
    try:
        result = await runtime.cancel(session_id)
    except GenerationJobNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generation job not found: {session_id}",
        ) from exc
    except InvalidGenerationTransition as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generation cannot be cancelled in its current stage",
        ) from exc
    except Exception:
        logger.exception("Cancel failed for session %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )
    return JSONResponse(content=result, status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/sessions/{session_id}/resume",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Resume generation",
    description=(
        "Resume a paused or cancelled generation job using fresh credentials."
    ),
)
async def resume_generation(
    session_id: str,
    request: Request,
    llm_context: LLMContext = Depends(get_llm_context),
    search_context: SearchContext = Depends(get_search_context),
) -> JSONResponse:
    """Resume generation with fresh LLM/search secrets."""
    require_agent_models(llm_context)
    session = learning_manager.get_learning_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Learning session not found: {session_id}",
        )
    runtime = getattr(request.app.state, "generation_runtime", None)
    if runtime is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Generation runtime unavailable",
        )
    try:
        result = await runtime.resume(
            session_id=session_id,
            llm_context=llm_context,
            search_context=search_context,
        )
    except HTTPException:
        raise
    except GenerationAlreadyRunning as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generation is already running or not resumable",
        ) from exc
    except InvalidGenerationTransition as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Generation cannot be resumed in its current stage",
        ) from exc
    except GenerationJobNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generation job not found: {session_id}",
        ) from exc
    except Exception:
        logger.exception("Resume failed for session %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )
    return JSONResponse(content=result, status_code=status.HTTP_202_ACCEPTED)


@router.delete(
    "/sessions/{session_id}",
    response_model=DeleteLearningSessionResponse,
    summary="Delete learning session",
    description=(
        "Stop local generation work, delete session artifacts, and remove "
        "the checkpoint thread. This is the only permanent cleanup path."
    ),
)
async def delete_learning_session(
    session_id: str,
    request: Request,
) -> DeleteLearningSessionResponse:
    """Delete a learning session by ID with cascade deletion."""
    try:
        session = learning_manager.get_learning_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Learning session not found: {session_id}",
            )

        runtime = getattr(request.app.state, "generation_runtime", None)
        if runtime is not None:
            try:
                await runtime.stop_for_delete(session_id)
            except Exception:
                logger.exception(
                    "stop_for_delete failed for session %s", session_id
                )

        # M14: checkpoint first so partial failure is retryable without orphans.
        checkpointer = getattr(request.app.state, "checkpointer", None)
        if checkpointer is not None and hasattr(checkpointer, "adelete_thread"):
            try:
                await checkpointer.adelete_thread(f"gen-{session_id}")
            except Exception as exc:
                logger.exception(
                    "Checkpoint delete failed for session %s", session_id
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=(
                        "Checkpoint cleanup failed; retry delete. "
                        "App data retained."
                    ),
                ) from exc

        deleted = learning_manager.delete_learning_session(session_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Learning session not found: {session_id}",
            )

        return DeleteLearningSessionResponse(deleted=True)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error deleting learning session")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post(
    "/revisions/{revision_id}/nodes/{node_id}/mark-reviewed",
    response_model=RevisionNodeProgress,
    summary="Mark revision node reviewed",
    description="Mark a revision node as reviewed in full_review mode.",
)
def mark_revision_node_reviewed(
    revision_id: str,
    node_id: str,
) -> RevisionNodeProgress:
    """Mark a revision node as reviewed."""
    try:
        progress = learning_manager.mark_revision_node_reviewed(
            revision_id=revision_id,
            node_id=node_id,
        )
        return RevisionNodeProgress(**progress)
    except LookupError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error marking revision node reviewed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post(
    "/revisions/{revision_id}/nodes/{node_id}/submit-quiz",
    response_model=RevisionQuizSubmissionResult,
    summary="Submit revision quiz answer",
    description="Submit a quiz answer for a node in a revision session.",
)
def submit_revision_quiz(
    revision_id: str,
    node_id: str,
    request: QuizSubmitRequest,
) -> RevisionQuizSubmissionResult:
    """Submit a revision quiz answer and return evaluation result."""
    try:
        result = learning_manager.submit_revision_quiz(
            revision_id=revision_id,
            node_id=node_id,
            selected_option_ids=request.selected_option_ids,
            quiz_index=request.quiz_index,
        )
        return RevisionQuizSubmissionResult(**result)
    except LookupError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error submitting revision quiz: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get(
    "/revisions/{revision_id}/summary",
    response_model=RevisionSummary,
    summary="Get revision summary",
    description="Get aggregate progress and quiz metrics for a revision session.",
)
def get_revision_summary(revision_id: str) -> RevisionSummary:
    """Get summary metrics for a revision session."""
    try:
        summary = learning_manager.get_revision_summary(revision_id)
        return RevisionSummary(**summary)
    except LookupError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error getting revision summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get(
    "/nodes/{node_id}",
    response_model=ConceptNodeWithVisibility,
    summary="Get concept node",
    description="Get a concept node with state-based content visibility.",
)
def get_concept_node(node_id: str) -> ConceptNodeWithVisibility:
    """Get a concept node with visibility flags based on state."""
    try:
        node = learning_manager.get_concept_node(node_id)

        if not node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Concept node not found: {node_id}",
            )

        response_node = _apply_node_visibility(node, include_flags=True)
        return ConceptNodeWithVisibility(**response_node)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting concept node: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post(
    "/nodes/{node_id}/transition",
    response_model=ConceptNodeResponse,
    summary="Transition node state",
    description="Transition a concept node to a new state.",
)
def transition_node(
    node_id: str,
    request: TransitionRequest,
) -> ConceptNodeResponse:
    """Transition a node to a new state if valid."""
    try:
        updated_node = learning_manager.update_node_status(
            node_id=node_id,
            status=request.target_status,
        )

        if not updated_node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Concept node not found: {node_id}",
            )

        if request.target_status == NodeStatus.IN_QUIZ:
            _ensure_quiz_shuffle_seed(node_id)

        response_node = _apply_node_visibility(updated_node)
        return ConceptNodeResponse(**response_node)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error transitioning node: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get(
    "/nodes/{node_id}/attempts",
    response_model=QuizAttemptHistory,
    summary="Get quiz attempts",
    description="Get all quiz attempts for a concept node with history.",
)
def get_quiz_attempts(node_id: str) -> QuizAttemptHistory:
    """Retrieve quiz attempt history for a node."""
    try:
        history = learning_manager.get_quiz_attempts(node_id)
        return QuizAttemptHistory(**history)
    except Exception as e:
        logger.error(f"Error getting quiz attempts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post(
    "/nodes/{node_id}/submit-quiz",
    response_model=QuizAttemptResponse,
    summary="Submit quiz answer",
    description="Submit a quiz answer and get immediate feedback. If mastered, unlocks next node.",
)
def submit_quiz(
    node_id: str,
    request: QuizSubmitRequest,
) -> QuizAttemptResponse:
    """Submit a quiz answer and record the attempt."""
    try:
        # Get current node info for session and sequence
        node = learning_manager.get_concept_node(node_id)
        if not node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Concept node not found: {node_id}",
            )

        # Create the quiz attempt
        result = learning_manager.create_quiz_attempt(
            node_id=node_id,
            selected_option_ids=request.selected_option_ids,
            quiz_index=request.quiz_index,
        )

        # Advance quiz-set progress after a correct answer when mastery is not
        # yet achieved. This enables sequential multi-quiz flow.
        if result.get("is_correct") and not result.get("is_mastered"):
            quiz_set_data = learning_manager.get_quiz_set_for_node(node_id)
            if quiz_set_data is not None:
                total_quizzes = len(quiz_set_data["quiz_set"].quizzes)
                next_index = request.quiz_index + 1
                if next_index < total_quizzes:
                    learning_manager.update_quiz_set_progress(
                        node_id=node_id,
                        current_index=next_index,
                    )

        # Always transition to SHOWING_FEEDBACK after quiz submission
        # User sees feedback, then either retries (if not mastered) or continues (if mastered)
        next_node_unlocked = False
        learning_manager.update_node_status(
            node_id=node_id,
            status=NodeStatus.SHOWING_FEEDBACK,
        )

        # If mastered, unlock the next node
        if result.get("is_mastered"):
            # Check if there's a next node to unlock
            next_node = learning_manager.get_next_node(
                session_id=node["learning_session_id"],
                sequence_index=node["sequence_index"],
            )
            if next_node and NodeStatus(next_node["status"]) == NodeStatus.LOCKED:
                # Unlock the next node
                learning_manager.update_node_status(
                    node_id=next_node["id"],
                    status=NodeStatus.VIEWING_EXPLANATION,
                )
                next_node_unlocked = True

        # Add next_node_unlocked to result
        result["next_node_unlocked"] = next_node_unlocked

        return QuizAttemptResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting quiz: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post(
    "/nodes/{node_id}/retry-quiz",
    response_model=ConceptNodeResponse,
    summary="Retry quiz",
    description="Transition node from SHOWING_FEEDBACK back to IN_QUIZ to retry.",
)
def retry_quiz(node_id: str) -> ConceptNodeResponse:
    """Transition node to IN_QUIZ state for retry after incorrect answer."""
    try:
        updated_node = learning_manager.update_node_status(
            node_id=node_id,
            status=NodeStatus.IN_QUIZ,
        )

        if not updated_node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Concept node not found: {node_id}",
            )

        _ensure_quiz_shuffle_seed(node_id)

        response_node = _apply_node_visibility(updated_node)
        return ConceptNodeResponse(**response_node)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying quiz: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post(
    "/nodes/{node_id}/previous-quiz",
    response_model=ConceptNodeResponse,
    summary="Previous quiz",
    description="Transition to the previous quiz in a quiz set.",
)
def previous_quiz(node_id: str) -> ConceptNodeResponse:
    """Decrement the current quiz index for a node's quiz set."""
    try:
        updated_node = learning_manager.decrement_quiz_set_progress(node_id)

        if not updated_node:
            # Check if node exists to distinguish 404 from "cannot decrement"
            node = learning_manager.get_concept_node(node_id)
            if not node:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Concept node not found: {node_id}",
                )
            # If node exists but decrement returned None (e.g. legacy quiz), just return node
            updated_node = node

        # Ensure we are in IN_QUIZ state for the returned node
        if NodeStatus(updated_node["status"]) != NodeStatus.IN_QUIZ:
            learning_manager.update_node_status(node_id, NodeStatus.IN_QUIZ)
            updated_node["status"] = NodeStatus.IN_QUIZ.value

        _ensure_quiz_shuffle_seed(node_id)
        response_node = _apply_node_visibility(updated_node)
        return ConceptNodeResponse(**response_node)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error going to previous quiz: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post(
    "/nodes/{node_id}/regenerate",
    response_model=ConceptNodeResponse,
    summary="Regenerate node",
    description=(
        "Regenerate content for a concept node. "
        "ERROR nodes: partial regen based on failed_step. "
        "Non-ERROR nodes: full regen of content + quizzes."
    ),
)
async def regenerate_node_endpoint(
    node_id: str,
    request: Request,
    step: Optional[str] = Query(
        default=None,
        description=(
            "Optional regen step override for ERROR nodes only. "
            "One of GENERATOR, QUIZZER, BOTH. "
            "If omitted, uses the node's stored failed_step."
        ),
    ),
    llm_context: LLMContext = Depends(get_llm_context),
) -> ConceptNodeResponse:
    """Regenerate content for a concept node.
    
    Auto-detects path based on node status:
    - ERROR nodes → regenerate_failed_node (existing partial-regen)
    - Non-ERROR, non-LOCKED → regenerate_topic_node (full regen)
    - LOCKED → 400 error
    """
    require_agent_models(llm_context)

    node = learning_manager.get_concept_node(node_id)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Concept node not found: {node_id}",
        )

    if node.get("status") == NodeStatus.LOCKED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot regenerate a LOCKED node. Complete the previous topic first.",
        )

    VALID_STEPS = {"GENERATOR", "QUIZZER", "BOTH"}
    if step is not None and step.upper() not in VALID_STEPS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid regen step: {step}. Must be one of: "
            f"{', '.join(sorted(VALID_STEPS))}",
        )
    try:
        if node.get("status") == NodeStatus.ERROR.value:
            updated_node = await regenerate_failed_node(
                node_id=node_id,
                llm_context=llm_context,
                regen_step=step.upper() if step else None,
            )
        else:
            updated_node = await regenerate_topic_node(
                node_id=node_id,
                llm_context=llm_context,
            )

        if updated_node is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Regeneration failed unexpectedly",
            )
        response_node = _apply_node_visibility(updated_node)
        return ConceptNodeResponse(**response_node)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Concept node not found: {node_id}",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error regenerating node %s: %s", node_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post(
    "/nodes/{node_id}/regenerate/stream",
    summary="Stream node regeneration",
    description="Stream explanation regeneration, then generate new quizzes and return updated node.",
)
async def stream_regenerate_node_endpoint(
    node_id: str,
    request: Request,
    step: Optional[str] = Query(
        default=None,
        description=(
            "Optional regen step override for ERROR nodes only. "
            "One of GENERATOR, QUIZZER, BOTH."
        ),
    ),
    llm_context: LLMContext = Depends(get_llm_context),
) -> StreamingResponse:
    """Stream regeneration of content and quizzes for a concept node."""
    require_agent_models(llm_context)
    from server.graph.regen_stream import stream_regenerate_node_generator

    return StreamingResponse(
        stream_regenerate_node_generator(
            node_id=node_id,
            llm_context=llm_context,
            regen_step_override=step.upper() if step else None,
        ),
        media_type="text/event-stream",
    )


@router.post(
    "/sessions/{session_id}/nodes/{node_id}/chat",
    summary="Concept chat assistant",
    description=(
        "Stream a chat response for a concept node using the concept content "
        "as context. Returns SSE text/event-stream."
    ),
)
async def concept_chat(
    session_id: str,
    node_id: str,
    request_body: ConceptChatRequest,
    x_provider_api_key: Optional[str] = Header(None, alias="X-Provider-Api-Key"),
    x_model: str = Header(None, alias="X-Model"),
    x_chat_model: str = Header(None, alias="X-Chat-Model"),
    x_ai_provider: Optional[str] = Header(None, alias="X-AI-Provider"),
    x_thinking_enabled: Optional[str] = Header(
        None, alias="X-Thinking-Enabled"
    ),
    x_thinking_effort: Optional[str] = Header(
        None, alias="X-Thinking-Effort"
    ),
) -> StreamingResponse:
    """Stream a context-aware chat response for a concept node."""
    logger.info(
        "DEBUG chat headers: x_ai_provider=%s, x_provider_api_key present=%s, "
        "x_chat_model=%s, thinking=%s",
        x_ai_provider,
        bool(x_provider_api_key),
        x_chat_model,
        x_thinking_enabled,
    )
    if not x_provider_api_key or not x_provider_api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Provider-Api-Key header is required",
        )

    effective_model = x_chat_model or x_model
    if not effective_model or not effective_model.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Chat-Model or X-Model header is required",
        )

    try:
        session = learning_manager.get_learning_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Learning session not found: {session_id}",
            )

        node = learning_manager.get_concept_node(node_id)
        if not node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Concept node not found: {node_id}",
            )

        if node.get("learning_session_id") != session_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Node {node_id} does not belong to "
                    f"session {session_id}"
                ),
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating chat session/node: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    thinking_on = bool(
        x_thinking_enabled and x_thinking_enabled.lower() == "true"
    )
    valid_efforts = {"minimal", "low", "medium", "high", "xhigh"}
    thinking_effort = None
    if x_thinking_effort and x_thinking_effort in valid_efforts:
        thinking_effort = x_thinking_effort
    elif thinking_on:
        thinking_effort = "high"

    return StreamingResponse(
        stream_concept_chat(
            api_key=x_provider_api_key.strip(),
            model_slug=effective_model.strip(),
            message=request_body.message,
            history=request_body.history,
            content_markdown=node["content_markdown"],
            selected_heading_ids=request_body.selected_heading_ids,
            node_title=node["title"],
            provider=(x_ai_provider or "openrouter").strip(),
            thinking_enabled=thinking_on,
            thinking_effort=thinking_effort,
        ),
        media_type="text/event-stream",
    )
