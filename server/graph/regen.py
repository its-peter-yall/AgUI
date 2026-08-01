"""
============================================================================
FILE: regen.py
LOCATION: server/graph/regen.py
============================================================================
PURPOSE:
    Standalone regeneration function for failed concept nodes.
ROLE IN PROJECT:
    Provides single-node regen without invoking the full LangGraph
    course graph runtime.
    - Calls generator and quizzer agents directly
    - Updates node content via persistence layer
KEY COMPONENTS:
    - regenerate_failed_node: Async function to regenerate one node
DEPENDENCIES:
    - External: logging
    - Internal: server.agents, server.database, server.schemas
USAGE:
    from server.graph.regen import regenerate_failed_node
    result = await regenerate_failed_node(node_id, llm_context)
============================================================================
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from server.agents.generator import GeneratedContent, generator_agent
from server.agents.quizzer import quizzer_agent
from server.database.learning_persistence import learning_manager
from server.schemas.learning import (
    FailedStep,
    NodeStatus,
    QuizSet,
    TopicNode,
)
from server.schemas.llm import LLMContext

logger = logging.getLogger(__name__)


from server.database.generation_artifacts import generation_artifact_store


async def regenerate_failed_node(
    node_id: str,
    llm_context: Optional[LLMContext] = None,
    regen_step: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Re-generate content for a single failed concept node.

    By default, dispatches only the LLM step(s) that failed according to
    the node's stored `failed_step`:
        - QUIZZER: re-run quizzer_agent only (keeps existing content)
        - GENERATOR: re-run generator_agent, then quizzer_agent (quiz
          depends on content)
        - BOTH or missing: re-run both

    Args:
        node_id: Identifier of the node to regenerate.
        llm_context: Optional LLM provider context.
        regen_step: Optional override. One of "GENERATOR", "QUIZZER",
            "BOTH". If None, the node's stored failed_step is used.

    Returns:
        Updated node dict on success, None on failure.

    Raises:
        LookupError: If node_id does not exist.
        ValueError: If node is not eligible for regeneration or
            regen_step is invalid.
    """
    node = learning_manager.get_concept_node(node_id)

    if not node:
        raise LookupError(f"Node not found: {node_id}")

    if node.get("status") != NodeStatus.ERROR.value:
        raise ValueError(f"Node {node_id} is not in ERROR status")

    if not node.get("retry_available", False):
        raise ValueError(f"Node {node_id} does not have retry available")

    stored_step = node.get("failed_step")
    if regen_step is not None:
        if regen_step not in {s.value for s in FailedStep}:
            raise ValueError(
                f"Invalid regen_step '{regen_step}'. "
                f"Must be one of: {[s.value for s in FailedStep]}"
            )
        target_step = regen_step
    elif stored_step:
        target_step = stored_step
    else:
        target_step = FailedStep.BOTH.value

    session_id = node["learning_session_id"]
    sequence_index = node["sequence_index"]
    title = node["title"]

    all_nodes = learning_manager.get_session_nodes(session_id)

    prev_summary: Optional[str] = None
    next_summary: Optional[str] = None
    previous_status: Optional[str] = None

    for sibling in all_nodes:
        if sibling["sequence_index"] == sequence_index - 1:
            prev_summary = sibling["title"]
            previous_status = sibling["status"]
        elif sibling["sequence_index"] == sequence_index + 1:
            next_summary = sibling["title"]

    quiz_count = 1
    quiz_payload = node.get("quiz")
    if quiz_payload and isinstance(quiz_payload, dict):
        quizzes = quiz_payload.get("quizzes")
        if quizzes and isinstance(quizzes, list):
            quiz_count = len(quizzes)

    topic = TopicNode(
        index=sequence_index,
        title=title,
        summary_for_context=node.get("summary_for_context") or title,
        key_terms=node.get("key_terms") or ["concept", "topic"],
        complexity=node.get("complexity", "Intermediate"),
        quiz_count=quiz_count,
    )

    brief = generation_artifact_store.get_brief(node_id)

    new_content_markdown = node.get("content_markdown") or ""
    new_quiz_set: Optional[QuizSet] = None
    run_generator = target_step in {
        FailedStep.GENERATOR.value,
        FailedStep.BOTH.value,
    }
    run_quizzer = target_step in {
        FailedStep.QUIZZER.value,
        FailedStep.GENERATOR.value,
        FailedStep.BOTH.value,
    }

    new_citations: list = []
    if run_generator:
        content: GeneratedContent = (
            await generator_agent.generate_explanation(
                topic=topic,
                brief=brief,
                prev_summary=prev_summary,
                next_summary=next_summary,
                llm_context=llm_context,
            )
        )
        new_content_markdown = content.content_markdown
        new_citations = list(content.citations or [])

    if run_quizzer:
        new_quiz_set = await quizzer_agent.generate_quiz_set(
            topic=topic,
            content=new_content_markdown,
            quiz_count=quiz_count,
            brief=brief,
            llm_context=llm_context,
        )

    new_status = NodeStatus.LOCKED
    if sequence_index == 0:
        new_status = NodeStatus.VIEWING_EXPLANATION
    elif previous_status == NodeStatus.COMPLETED.value:
        new_status = NodeStatus.VIEWING_EXPLANATION

    updated_node = learning_manager.update_node_content(
        node_id=node_id,
        content_markdown=new_content_markdown,
        status=new_status,
        quiz_set=new_quiz_set,
        error_message=None,
        retry_available=False,
        failed_step=None,
    )

    # M13: regeneration always replaces citation set, including empty.
    if run_generator:
        try:
            generation_artifact_store.replace_node_sources(
                node_id,
                new_citations,
            )
        except Exception:
            logger.warning(
                "Failed to replace citations on regen for node %s",
                node_id,
            )

    if not updated_node:
        logger.error("Node vanished during regen: %s", node_id)
        return None

    logger.info(
        "Regenerated node %s (step=%s, ran_generator=%s, ran_quizzer=%s)",
        node_id,
        target_step,
        run_generator,
        run_quizzer,
    )
    return updated_node


async def regenerate_topic_node(
    node_id: str,
    llm_context: Optional[LLMContext] = None,
) -> Optional[Dict[str, Any]]:
    """Re-generate content for any non-LOCKED, non-ERROR topic node.

    Runs both generator and quizzer agents unconditionally. Resets node
    status based on position in the sequence. Bypasses the normal state-
    machine validation because manual regeneration is an intentional
    overwrite, not a user-progression transition.

    Args:
        node_id: Identifier of the node to regenerate.
        llm_context: Optional LLM provider context.

    Returns:
        Updated node dict on success, None on failure.

    Raises:
        LookupError: If node_id does not exist.
        ValueError: If node is LOCKED or ERROR (use regenerate_failed_node
            for ERROR nodes instead).
    """
    node = learning_manager.get_concept_node(node_id)

    if not node:
        raise LookupError(f"Node not found: {node_id}")

    if node.get("status") == NodeStatus.LOCKED.value:
        raise ValueError(f"Node {node_id} is LOCKED; cannot regenerate")

    if node.get("status") == NodeStatus.ERROR.value:
        raise ValueError(
            f"Node {node_id} is ERROR; use error retry endpoint instead"
        )

    session_id = node["learning_session_id"]
    sequence_index = node["sequence_index"]
    title = node["title"]

    all_nodes = learning_manager.get_session_nodes(session_id)

    prev_summary: Optional[str] = None
    next_summary: Optional[str] = None
    previous_status: Optional[str] = None

    for sibling in all_nodes:
        if sibling["sequence_index"] == sequence_index - 1:
            prev_summary = sibling["title"]
            previous_status = sibling["status"]
        elif sibling["sequence_index"] == sequence_index + 1:
            next_summary = sibling["title"]

    quiz_count = 1
    quiz_payload = node.get("quiz")
    if quiz_payload and isinstance(quiz_payload, dict):
        quizzes = quiz_payload.get("quizzes")
        if quizzes and isinstance(quizzes, list):
            quiz_count = len(quizzes)

    topic = TopicNode(
        index=sequence_index,
        title=title,
        summary_for_context=node.get("summary_for_context") or title,
        key_terms=node.get("key_terms") or ["concept", "topic"],
        complexity=node.get("complexity", "Intermediate"),
        quiz_count=quiz_count,
    )

    brief = generation_artifact_store.get_brief(node_id)

    content: GeneratedContent = (
        await generator_agent.generate_explanation(
            topic=topic,
            brief=brief,
            prev_summary=prev_summary,
            next_summary=next_summary,
            llm_context=llm_context,
        )
    )
    new_content_markdown = content.content_markdown

    new_quiz_set: Optional[QuizSet] = await quizzer_agent.generate_quiz_set(
        topic=topic,
        content=new_content_markdown,
        quiz_count=quiz_count,
        brief=brief,
        llm_context=llm_context,
    )

    new_status = NodeStatus.LOCKED
    if sequence_index == 0:
        new_status = NodeStatus.VIEWING_EXPLANATION
    elif previous_status == NodeStatus.COMPLETED.value:
        new_status = NodeStatus.VIEWING_EXPLANATION

    updated_node = learning_manager.replace_node_content(
        node_id=node_id,
        content_markdown=new_content_markdown,
        status=new_status,
        quiz_set=new_quiz_set,
    )

    if not updated_node:
        logger.error("Node vanished during regen: %s", node_id)
        return None

    logger.info(
        "Regenerated topic node %s (status=%s)",
        node_id,
        new_status.value,
    )
    return updated_node
