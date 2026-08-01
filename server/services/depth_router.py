"""
============================================================================
FILE: depth_router.py
LOCATION: server/services/depth_router.py
============================================================================
PURPOSE:
    Cheap LLM classify of learning query depth into lite or full mode.
ROLE IN PROJECT:
    Resolves user mode=auto before planner runs; token-saving fallback
    to lite on any classify failure.
KEY COMPONENTS:
    - DepthRouteResult: Structured classify output
    - classify_depth: Instructor call with depth_router role
    - resolve_depth_mode: Explicit pass-through or auto classify
DEPENDENCIES:
    - External: pydantic
    - Internal: server.utils.instructor_client, server.schemas.llm
USAGE:
    resolved = await resolve_depth_mode(query, mode, llm_context)
============================================================================
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

from server.schemas.llm import LLMContext
from server.utils.instructor_client import instructor_client

logger = logging.getLogger(__name__)

DEPTH_ROUTER_SYSTEM_PROMPT = """You classify learning queries for curriculum length only.

Return mode "lite" or "full" plus a short reason.

lite cues:
- single concept, trivia, short explainer
- named effect, method, or phenomenon
- can be taught thoroughly in a short path

full cues:
- multi-system domain or field of study
- "from scratch", architecture, multi-week mastery
- many prerequisites and subdomains

Do not write a curriculum. Only classify depth.
"""


class DepthRouteResult(BaseModel):
    """Structured result of depth classification."""

    mode: Literal["lite", "full"] = Field(
        ...,
        description="Resolved depth mode for course planning",
    )
    reason: str = Field(
        ...,
        description="Short reason for the classification",
        min_length=1,
    )


async def classify_depth(
    query: str,
    llm_context: LLMContext,
) -> DepthRouteResult:
    """Classify query depth via structured instructor call.

    Args:
        query: User learning query.
        llm_context: Provider key and model from request.

    Returns:
        DepthRouteResult with mode lite|full.
    """
    user_message = (
        "Classify curriculum depth for this learning query:\n\n"
        f"{query}"
    )
    return await instructor_client.create_structured(
        role="depth_router",
        response_model=DepthRouteResult,
        messages=[{"role": "user", "content": user_message}],
        api_key=llm_context.get_api_key(),
        model_override=llm_context.model,
        attribution_headers=llm_context.get_attribution_headers(),
        system_prompt=DEPTH_ROUTER_SYSTEM_PROMPT,
        provider=llm_context.provider,
        reasoning_params=llm_context.get_reasoning_params(),
        max_completion_tokens=llm_context.max_completion_tokens,
    )


async def resolve_depth_mode(
    query: str,
    mode: str,
    llm_context: Optional[LLMContext] = None,
) -> Literal["lite", "full"]:
    """Resolve user depth mode to lite or full.

    Args:
        query: Learning query (used only for auto).
        mode: User selection auto|lite|full.
        llm_context: Required when mode is auto.

    Returns:
        Resolved mode lite or full. Auto failures → lite.
    """
    if mode in ("lite", "full"):
        return mode  # type: ignore[return-value]

    if mode != "auto":
        logger.warning("Unknown depth mode %r; falling back to lite", mode)
        return "lite"

    if llm_context is None or not llm_context.get_api_key():
        logger.warning("Depth router missing llm_context; fallback lite")
        return "lite"

    try:
        result = await classify_depth(query, llm_context)
        if result.mode not in ("lite", "full"):
            logger.warning(
                "Depth router invalid mode %r; fallback lite",
                result.mode,
            )
            return "lite"
        logger.info(
            "Depth router classified mode=%s reason=%s",
            result.mode,
            result.reason,
        )
        return result.mode
    except Exception as exc:
        logger.warning(
            "Depth router failed (%s); fallback lite",
            exc,
        )
        return "lite"
