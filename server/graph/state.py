"""
============================================================================
FILE: state.py
LOCATION: server/graph/state.py
============================================================================
PURPOSE:
    Defines TypedDict state contracts and keyed reducers for staged course generation.
ROLE IN PROJECT:
    Shared state schema for graph nodes in the internet-grounded staged graph.
    - Excludes secrets, large content markdown, and unparsed artifacts from checkpoint state
    - Provides idempotent keyed reducers for fan-out worker results
KEY COMPONENTS:
    - GeneratorResult: Compact status per generator worker
    - TopicResult: Compact status per quizzer worker
    - CourseMetrics: Summary counts for cards ready vs failed
    - CourseGraphContext: Runtime context carrying LLMContext and SearchContext
    - CourseState: Secret-free persisted graph state
    - GeneratorWorkerState: Fan-out payload for generator worker
    - QuizzerWorkerState: Fan-out payload for quizzer worker
DEPENDENCIES:
    - External: typing, typing_extensions
    - Internal: server.schemas.llm, server.schemas.search
USAGE:
    from server.graph.state import CourseState, CourseGraphContext
============================================================================
"""

from __future__ import annotations

from typing import Annotated, Optional

from typing_extensions import NotRequired, TypedDict

from server.schemas.llm import LLMContext
from server.schemas.search import SearchContext


class GeneratorResult(TypedDict):
    """Result returned by one generator worker for a topic."""

    batch_start: int
    sequence_index: int
    content_ready: bool
    error_message: Optional[str]


class TopicResult(TypedDict):
    """Terminal status returned by one quizzer worker for a topic."""

    batch_start: int
    sequence_index: int
    terminal_status: str  # "READY" | "ERROR"
    error_message: Optional[str]


class CourseMetrics(TypedDict):
    """Summary counts for generated course cards."""

    cards_ready: int
    cards_failed: int


class CourseGraphContext(TypedDict):
    """Runtime-only context for graph execution (not persisted in checkpointer)."""

    llm_context: LLMContext
    search_context: SearchContext
    worker_id: str
    lock: NotRequired[object]
    shutdown_pause: NotRequired[bool]


def merge_generator_results(
    current: list[GeneratorResult],
    update: list[GeneratorResult],
) -> list[GeneratorResult]:
    """Idempotent keyed reducer for generator results keyed by (batch_start, sequence_index)."""
    by_key: dict[tuple[int, int], GeneratorResult] = {
        (item["batch_start"], item["sequence_index"]): item for item in current
    }
    for item in update:
        by_key[(item["batch_start"], item["sequence_index"])] = item
    return [by_key[k] for k in sorted(by_key.keys())]


def merge_topic_results(
    current: list[TopicResult],
    update: list[TopicResult],
) -> list[TopicResult]:
    """Idempotent keyed reducer for topic results keyed by (batch_start, sequence_index)."""
    by_key: dict[tuple[int, int], TopicResult] = {
        (item["batch_start"], item["sequence_index"]): item for item in current
    }
    for item in update:
        by_key[(item["batch_start"], item["sequence_index"])] = item
    return [by_key[k] for k in sorted(by_key.keys())]


class CourseState(TypedDict):
    """Secret-free state schema for staged LangGraph course generation."""

    job_id: str
    session_id: str
    query: str
    user_id: Optional[str]
    mode: str  # auto|lite|full
    resolved_mode: str  # lite|full
    web_search_enabled: bool
    research_report_id: Optional[str]
    topic_count: int
    next_topic_index: int
    active_batch_start: int
    active_batch_size: int
    generator_results: Annotated[list[GeneratorResult], merge_generator_results]
    topic_results: Annotated[list[TopicResult], merge_topic_results]
    degraded: bool


class GeneratorWorkerState(TypedDict):
    """Fan-out payload for generator node."""

    job_id: str
    session_id: str
    batch_start: int
    sequence_index: int


class QuizzerWorkerState(TypedDict):
    """Fan-out payload for quizzer node."""

    job_id: str
    session_id: str
    batch_start: int
    sequence_index: int
