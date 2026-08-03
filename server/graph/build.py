"""
============================================================================
FILE: build.py
LOCATION: server/graph/build.py
============================================================================
PURPOSE:
    Builds and compiles the durable optional-research staged LangGraph workflow.
ROLE IN PROJECT:
    Assembles the permanent course generation state machine with fan-in barriers.
KEY COMPONENTS:
    - CHECKPOINT_DB_PATH: Path to SQLite checkpointer database
    - build_graph: Factory function compiling StateGraph with 3/10 staged topology
    - get_graph: Singleton/app-state accessor for compiled graph
DEPENDENCIES:
    - External: pathlib, typing, langgraph
    - Internal: server.graph.nodes, server.graph.state
USAGE:
    from server.graph.build import build_graph
    graph = build_graph()
============================================================================
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from langgraph.graph import END, START, StateGraph

from server.graph.nodes import (
    advance_batch_node,
    fan_out_generators,
    fan_out_quizzers,
    finalize_generation_node,
    generator_node,
    initialize_generation_node,
    outline_planner_node,
    plan_brief_batch_node,
    prepare_quiz_batch_node,
    quizzer_node,
    researcher_node,
    route_next_batch,
    route_optional_research,
)
from server.graph.state import CourseGraphContext, CourseState

CHECKPOINT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "checkpoints.db"


def build_graph(
    checkpointer: Any | None = None,
    node_overrides: Optional[dict[str, Any]] = None,
) -> Any:
    """Compile course generation graph with optional research and 3/10 staged batching."""
    workflow = StateGraph(CourseState, context_schema=CourseGraphContext)

    nodes = {
        "initialize_generation_node": initialize_generation_node,
        "researcher_node": researcher_node,
        "outline_planner_node": outline_planner_node,
        "plan_brief_batch_node": plan_brief_batch_node,
        "generator_node": generator_node,
        "prepare_quiz_batch_node": prepare_quiz_batch_node,
        "quizzer_node": quizzer_node,
        "advance_batch_node": advance_batch_node,
        "finalize_generation_node": finalize_generation_node,
    }

    if node_overrides:
        nodes.update(node_overrides)

    for name, fn in nodes.items():
        workflow.add_node(name, fn)

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

    return workflow.compile(checkpointer=checkpointer)


def get_graph(app_state: Any) -> Any:
    """Return cached compiled graph from app state."""
    graph = getattr(app_state, "course_graph", None)
    if graph is None:
        checkpointer = getattr(app_state, "checkpointer", None)
        graph = build_graph(checkpointer=checkpointer)
        setattr(app_state, "course_graph", graph)
    return graph


def replace_graph(app_state: Any, checkpointer: Any) -> Any:
    """Compile and publish graph bound to selected checkpointer."""

    graph = build_graph(checkpointer=checkpointer)
    app_state.checkpointer = checkpointer
    app_state.course_graph = graph
    return graph
