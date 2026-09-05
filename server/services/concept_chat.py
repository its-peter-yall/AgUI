"""
============================================================================
FILE: concept_chat.py
LOCATION: server/services/concept_chat.py
============================================================================
PURPOSE:
    Provides ephemeral concept chat functionality using direct OpenAI-compatible
    streaming. Supports context-aware Q&A with heading selection and server-side
    history capping.
ROLE IN PROJECT:
    Backend service for the in-concept chatbot assistant.
    - Resolves provider base URLs from model slug prefixes
    - Constructs system prompts with concept content and heading context
    - Streams SSE responses via openai.AsyncOpenAI (no Instructor)
KEY COMPONENTS:
    - resolve_chat_base_url(): Maps model slug to OpenAI-compatible base URL
    - build_concept_chat_messages(): Constructs prompt with context
    - stream_concept_chat(): Async generator yielding SSE frames
DEPENDENCIES:
    - External: openai
    - Internal: server.schemas.learning, server.database.learning_persistence
USAGE:
    ```python
    from server.services.concept_chat import stream_concept_chat
    async for chunk in stream_concept_chat(...):
        yield chunk
    ```
============================================================================
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator, List, Optional, cast

from openai import AsyncOpenAI

from server.database.storage_registry import (
    learning_repository as learning_manager,
)
from server.schemas.learning import ConceptChatMessage
from server.utils.prompt_cache import apply_openrouter_cache_control

logger = logging.getLogger(__name__)

MAX_CHAT_HISTORY_MESSAGES = 10

# Connection pool: reuse AsyncOpenAI clients per base_url
_client_cache: dict[str, AsyncOpenAI] = {}


def _get_client(base_url: str, api_key: str) -> AsyncOpenAI:
    """Return cached AsyncOpenAI client for base_url, or create one."""
    if base_url not in _client_cache:
        _client_cache[base_url] = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            max_retries=0,
        )
    return _client_cache[base_url]

OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
GENERALCOMPUTE_BASE_URL = "https://api.generalcompute.com/v1"


def resolve_chat_base_url(model_slug: str, provider: str = "openrouter") -> str:
    """Resolve the OpenAI-compatible base URL from the provider and model slug.

    Args:
        model_slug: Full model identifier (e.g. 'openai/gpt-4o-mini').
        provider: AI provider identifier ('openrouter' or 'generalcompute').

    Returns:
        Base URL for the provider's OpenAI-compatible API.
    """
    if provider == "generalcompute":
        return GENERALCOMPUTE_BASE_URL
    lower_slug = model_slug.lower()
    if lower_slug.startswith("openai/") or lower_slug.startswith("gpt-"):
        return OPENAI_BASE_URL
    return OPENROUTER_BASE_URL


def build_concept_chat_messages(
    message: str,
    history: List[ConceptChatMessage],
    content_markdown: str,
    selected_heading_ids: List[str],
    node_title: str,
) -> list[dict[str, Any]]:
    """Construct the full message list for the LLM chat request.

    Builds a system prompt with concept content and heading context,
    appends the last MAX_CHAT_HISTORY_MESSAGES from history, then
    appends the current user message.

    Args:
        message: The current user message.
        history: Ephemeral conversation history for this node.
        content_markdown: The full concept content in markdown.
        selected_heading_ids: User-selected heading identifiers.
        node_title: Title of the concept node.

    Returns:
        List of message dicts ready for AsyncOpenAI chat completions.
    """
    if selected_heading_ids:
        headings_text = "\n".join(f"- {h}" for h in selected_heading_ids)
        system_prompt = (
            "You are a helpful teaching assistant. The student is reading a "
            "learning concept and has questions about it.\n\n"
            f"CONCEPT: {node_title}\n\n"
            "CONCEPT CONTENT:\n"
            f"{content_markdown}\n\n"
            "The student is specifically asking about the following sections:\n"
            f"{headings_text}\n\n"
            "Focus your answer on these sections, but use the full concept "
            "content for context. If the student's question is about something "
            "not covered in the selected sections, answer based on the full "
            "concept content.\n\n"
            "Keep answers concise, clear, and educational. Use examples when "
            "helpful. You can produce Mermaid diagrams/flowcharts "
            "(using ```mermaid code blocks) for better visual demonstration when necessary. "
            "When using Mermaid, always wrap node labels in double quotes if they contain "
            "spaces, special characters, or `<br>` line breaks (e.g. `A[\"Label<br>Detail\"]`). "
            "If a node label contains double quotes internally, replace them with single quotes "
            "(e.g. `A[\"Can 'see' context\"]` instead of `A[\"Can \"see\" context\"]`) to avoid parsing errors. "
            "DO NOT style nodes/cells with background or fill colors (do not use "
            "style fill commands), as colors disrupt text readability in dark "
            "mode; you can use emojis inside node labels instead. "
            "You can also use vector plots (using ```vector-plot JSON code blocks) to draw "
            "2D mathematical coordinates/vector plots when describing vector systems, alignments, "
            "or cosine similarity. Example structure:\n"
            "```vector-plot\n"
            "{\n"
            "  \"vectors\": [\n"
            "    {\"name\": \"A\", \"x\": 3, \"y\": 4, \"color\": \"#ffb74d\"},\n"
            "    {\"name\": \"B\", \"x\": 4, \"y\": 1, \"color\": \"#4caf50\"}\n"
            "  ],\n"
            "  \"grid\": true\n"
            "}\n"
            "```\n"
            "If you don't know the answer based on the provided content, say so."
        )
    else:
        system_prompt = (
            "You are a helpful and friendly teaching assistant. The student is reading a "
            "learning concept and has questions about it.\n\n"
            f"CONCEPT: {node_title}\n\n"
            "CONCEPT CONTENT:\n"
            f"{content_markdown}\n\n"
            "Answer the student's question based on this content. Keep answers "
            "concise, clear, and educational. Use examples when helpful. Always underestimate user's understanding and over-explain"
            "You can produce Mermaid diagrams/flowcharts "
            "(using ```mermaid code blocks) for better visual demonstration when necessary. "
            "When using Mermaid, always wrap node labels in double quotes if they contain "
            "spaces, special characters, or `<br>` line breaks (e.g. `A[\"Label<br>Detail\"]`). "
            "If a node label contains double quotes internally, replace them with single quotes "
            "(e.g. `A[\"Can 'see' context\"]` instead of `A[\"Can \"see\" context\"]`) to avoid parsing errors. "
            "DO NOT use style commands with fill colors (e.g., style A fill:#24483f). Just use default Mermaid, no colours."
            "You can also use vector plots (using ```vector-plot JSON code blocks) to draw "
            "2D mathematical coordinates/vector plots when describing vector systems, "
            "alignments, "
            "or cosine similarity. Example structure:\n"
            "```vector-plot\n"
            "{\n"
            "  \"vectors\": [\n"
            "    {\"name\": \"A\", \"x\": 3, \"y\": 4, \"color\": \"#ffb74d\"},\n"
            "    {\"name\": \"B\", \"x\": 4, \"y\": 1, \"color\": \"#4caf50\"}\n"
            "  ],\n"
            "  \"grid\": true\n"
            "}\n"
            "```\n"
            "Make sure user understands fully before moving on. If user doesn't understand, re-explain in a different way."
            "If you don't know the answer based on the provided content, say so."
        )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    capped_history = history[-MAX_CHAT_HISTORY_MESSAGES:]
    for h in capped_history:
        search = getattr(h, "search", None)
        tool_call_id = (
            getattr(search, "tool_call_id", None) if search else None
        )
        query = getattr(search, "query", None) if search else None
        results = getattr(search, "results", None) if search else None
        if (
            h.role == "assistant"
            and tool_call_id
            and query
            and results
        ):
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps(
                                    {"query": query}
                                ),
                            },
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": results,
                }
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": h.content,
                }
            )
            continue
        messages.append({"role": h.role, "content": h.content})

    messages.append({"role": "user", "content": message})

    return messages


async def stream_concept_chat(
    api_key: str,
    model_slug: str,
    message: str,
    history: List[ConceptChatMessage],
    content_markdown: str,
    selected_heading_ids: List[str],
    node_title: str,
    provider: str = "openrouter",
    thinking_enabled: bool = False,
    thinking_effort: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Stream chat completions as SSE frames.

    Constructs messages with context, calls AsyncOpenAI with stream=True,
    and yields SSE-formatted delta chunks terminated by [DONE].

    Args:
        api_key: Provider API key.
        model_slug: Model identifier slug for the chat model.
        message: Current user message.
        history: Ephemeral conversation history.
        content_markdown: Full concept content in markdown.
        selected_heading_ids: User-selected heading identifiers.
        node_title: Title of the concept node.
        provider: AI provider identifier ('openrouter' or 'generalcompute').
        thinking_enabled: OpenRouter reasoning mode on/off.
        thinking_effort: Effort level when thinking is enabled.

    Yields:
        SSE frame strings: 'data: {"delta":"...", ...}\\n\\n' per chunk,
        and a terminal 'data: [DONE]\\n\\n'.
    """
    base_url = resolve_chat_base_url(model_slug, provider)

    logger.info(
        "Concept chat request: provider=%s, base_url=%s, model=%s, "
        "thinking=%s",
        provider,
        base_url,
        model_slug,
        thinking_enabled,
    )

    client = _get_client(base_url, api_key)

    messages = build_concept_chat_messages(
        message=message,
        history=history,
        content_markdown=content_markdown,
        selected_heading_ids=selected_heading_ids,
        node_title=node_title,
    )

    # Enable OpenRouter prompt caching for cacheable model families by
    # marking the stable system prefix with an explicit cache_control
    # breakpoint. No-op for General Compute and auto-caching providers.
    messages = apply_openrouter_cache_control(messages, provider, model_slug)

    logger.info(
        "Starting concept chat stream: model=%s, history_msgs=%d",
        model_slug,
        min(len(history), MAX_CHAT_HISTORY_MESSAGES),
    )

    create_kwargs: dict[str, Any] = {
        "model": model_slug,
        "messages": cast(Any, messages),
        "stream": True,
    }
    if provider == "openrouter" and thinking_enabled:
        effort = thinking_effort or "high"
        create_kwargs["extra_body"] = {
            "reasoning": {"effort": effort},
        }

    try:
        stream = await client.chat.completions.create(**create_kwargs)

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta:
                delta = chunk.choices[0].delta
                if delta.content:
                    payload = json.dumps({"delta": delta.content})
                    yield f"data: {payload}\n\n"

    except Exception as e:
        logger.error("Concept chat stream failed: %s", e)
        error_payload = json.dumps({"error": str(e)})
        yield f"data: {error_payload}\n\n"

    yield "data: [DONE]\n\n"
