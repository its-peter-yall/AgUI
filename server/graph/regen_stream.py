"""
============================================================================
FILE: regen_stream.py
LOCATION: server/graph/regen_stream.py
============================================================================
PURPOSE:
    Provides streaming regeneration functionality for concept nodes.
ROLE IN PROJECT:
    Implements SSE streaming generator for node regeneration.
    Supports partial regeneration (ERROR status) and full regeneration (non-ERROR).
KEY COMPONENTS:
    - stream_regenerate_node_generator: Async generator yielding SSE frames
DEPENDENCIES:
    - External: logging, json, openai, instructor
    - Internal: server.database, server.schemas, server.agents
USAGE:
    Called by the POST /nodes/{node_id}/regenerate/stream router.
============================================================================
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, Optional

import instructor
from openai import AsyncOpenAI

from server.agents.generator import GeneratedContent, generator_agent
from server.agents.quizzer import quizzer_agent
from server.database.storage_registry import (
    generation_artifact_repository as generation_artifact_store,
    learning_repository as learning_manager,
)
from server.schemas.learning import FailedStep, NodeStatus, QuizSet, TopicNode
from server.schemas.llm import LLMContext
from server.utils.instructor_client import instructor_client

logger = logging.getLogger(__name__)

async def stream_regenerate_node_generator(
    node_id: str,
    llm_context: LLMContext,
    regen_step_override: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Async generator streaming SSE-formatted frames for node regeneration.

    Yields:
        SSE-formatted delta and status frames, ending with the finalized node
        data or an error frame, terminated by [DONE].
    """
    try:
        node = learning_manager.get_concept_node(node_id)
        if not node:
            yield f"data: {json.dumps({'error': f'Concept node not found: {node_id}'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        if node.get("status") == NodeStatus.LOCKED.value:
            yield f"data: {json.dumps({'error': 'Cannot regenerate a LOCKED node. Complete the previous topic first.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        is_error_status = node.get("status") == NodeStatus.ERROR.value

        # Determine target steps to run
        if is_error_status:
            stored_step = node.get("failed_step")
            if regen_step_override is not None:
                if regen_step_override not in {s.value for s in FailedStep}:
                    yield f"data: {json.dumps({'error': f'Invalid regen step override: {regen_step_override}'})}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                target_step = regen_step_override
            elif stored_step:
                target_step = stored_step
            else:
                target_step = FailedStep.BOTH.value
        else:
            target_step = FailedStep.BOTH.value

        run_generator = target_step in {
            FailedStep.GENERATOR.value,
            FailedStep.BOTH.value,
        }
        run_quizzer = target_step in {
            FailedStep.QUIZZER.value,
            FailedStep.GENERATOR.value,
            FailedStep.BOTH.value,
        }

        session_id = node["learning_session_id"]
        sequence_index = node["sequence_index"]
        title = node["title"]

        all_nodes = learning_manager.get_session_nodes(session_id)
        prev_summary = None
        next_summary = None
        previous_status = None

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

        new_content_markdown = node.get("content_markdown") or ""
        new_quiz_set: Optional[QuizSet] = None

        brief = generation_artifact_store.get_brief(node_id)

        if run_generator:
            user_message = generator_agent._build_user_message(
                topic, brief, prev_summary, next_summary
            )
            full_system_prompt = generator_agent._build_system_prompt()
            messages = [
                {"role": "system", "content": full_system_prompt},
                {"role": "user", "content": user_message},
            ]

            try:
                model_slug, provider, api_key, reasoning_params = (
                    llm_context.resolve_agent_call(generator_agent.role)
                )
            except ValueError as exc:
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"
                yield "data: [DONE]\n\n"
                return

            attribution_headers = llm_context.get_attribution_headers()

            instructor_client._raise_for_invalid_state(generator_agent.role)
            if not api_key:
                yield f"data: {json.dumps({'error': 'API key is required.'})}\n\n"
                yield "data: [DONE]\n\n"
                return

            config = instructor_client.get_model_config(generator_agent.role)
            if not model_slug or not model_slug.strip():
                yield f"data: {json.dumps({'error': 'No model specified for generator.'})}\n\n"
                yield "data: [DONE]\n\n"
                return
            model_slug = model_slug.strip()

            temperature = config.get("temperature", 0.7)
            max_tokens = config.get("max_tokens", 60000)

            if llm_context.max_completion_tokens and llm_context.max_completion_tokens > 0:
                if max_tokens > llm_context.max_completion_tokens:
                    max_tokens = llm_context.max_completion_tokens

            base_url, timeout = instructor_client._get_provider_config(provider)
            base_client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                default_headers=attribution_headers or {},
                timeout=timeout,
                max_retries=0,
            )
            client = instructor.from_openai(
                base_client,
                mode=instructor.Mode.JSON,
            )

            extra_body = {}
            if reasoning_params:
                extra_body.update(reasoning_params)

            # Stream generator explanation using create_partial
            response_stream = client.chat.completions.create_partial(
                model=model_slug,
                response_model=GeneratedContent,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=extra_body if extra_body else None,
            )

            last_content = ""
            async for partial_obj in response_stream:
                if partial_obj and partial_obj.content_markdown:
                    current_content = partial_obj.content_markdown
                    if len(current_content) > len(last_content):
                        delta = current_content[len(last_content):]
                        last_content = current_content
                        yield f"data: {json.dumps({'delta': delta})}\n\n"

            new_content_markdown = last_content

        if run_quizzer:
            payload = {"status": "generating_quizzes"}
            yield f"data: {json.dumps(payload)}\n\n"
            # Quizzer is fast and structured, run directly
            new_quiz_set = await quizzer_agent.generate_quiz_set(
                topic=topic,
                content=new_content_markdown,
                quiz_count=quiz_count,
                brief=brief,
                llm_context=llm_context,
            )

        # Compute next status
        new_status = NodeStatus.LOCKED
        if sequence_index == 0:
            new_status = NodeStatus.VIEWING_EXPLANATION
        elif previous_status == NodeStatus.COMPLETED.value:
            new_status = NodeStatus.VIEWING_EXPLANATION

        # Save to DB
        if is_error_status:
            # Keep previous quiz data if quizzer did not run
            final_quiz_set = new_quiz_set
            if not run_quizzer and quiz_payload:
                # Wrap existing quiz dict in QuizSet if possible
                try:
                    final_quiz_set = QuizSet(**quiz_payload)
                except Exception:
                    pass

            updated_node = learning_manager.update_node_content(
                node_id=node_id,
                content_markdown=new_content_markdown,
                status=new_status,
                quiz_set=final_quiz_set,
                error_message=None,
                retry_available=False,
                failed_step=None,
            )
        else:
            updated_node = learning_manager.replace_node_content(
                node_id=node_id,
                content_markdown=new_content_markdown,
                status=new_status,
                quiz_set=new_quiz_set,
            )

        if not updated_node:
            yield f"data: {json.dumps({'error': 'Node vanished during regeneration.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        from server.routers.learning import _apply_node_visibility
        response_node = _apply_node_visibility(updated_node)

        yield f"data: {json.dumps({'done': True, 'node': response_node})}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as e:
        logger.exception("Streaming regeneration failed")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"
