"""
============================================================================
FILE: llm.py
LOCATION: server/routers/llm.py
============================================================================
PURPOSE:
    Provides LLM utility routes, specifically proxying OpenRouter model queries.
ROLE IN PROJECT:
    Exposes endpoints for querying OpenRouter models and configurations.
    All endpoints require X-OpenRouter-Key authentication.
KEY COMPONENTS:
    - router: APIRouter for LLM routes
    - get_llm_context(): Auth dependency extracting OpenRouter headers
    - list_models(): Endpoint proxying OpenRouter's /api/v1/models
DEPENDENCIES:
    - External: httpx, fastapi
    - Internal: server.schemas.llm
USAGE:
    Endpoint exposed at /llm/models (requires X-OpenRouter-Key header)
============================================================================
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
import httpx
import logging

from server.config import settings
from server.schemas.llm import AIProviderEnum, LLMContext, ModelResponse, get_llm_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["llm"])


async def _fetch_openrouter_models(llm_context: LLMContext) -> List[ModelResponse]:
    """Fetch and trim models from OpenRouter."""
    url = f"{settings.OPENROUTER_BASE_URL}/models"
    try:
        headers = {"Authorization": f"Bearer {llm_context.get_api_key()}"}
        attribution = llm_context.get_attribution_headers()
        headers.update(attribution)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers=headers, timeout=settings.OPENROUTER_TIMEOUT_SECONDS
            )
            if response.status_code in (401, 403):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or rejected OpenRouter API key.",
                )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"OpenRouter returned error: {response.text}",
                )

            data = response.json()
            models_list = data.get("data", [])

            result = []
            for item in models_list:
                model_id = item.get("id")
                if not model_id:
                    continue

                # Check if model supports thinking
                supported_params = item.get("supported_parameters") or []
                supports_thinking = "reasoning" in supported_params

                # Extract max completion tokens from top provider
                top_provider_info = item.get("top_provider") or {}
                max_completion_tokens = top_provider_info.get(
                    "max_completion_tokens"
                )

                result.append(
                    ModelResponse(
                        id=model_id,
                        name=item.get("name"),
                        context_length=item.get("context_length"),
                        max_completion_tokens=max_completion_tokens,
                        supports_thinking=supports_thinking,
                    )
                )
            return result
    except httpx.RequestError as e:
        logger.error(f"Failed to connect to OpenRouter: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to connect to OpenRouter",
        )


async def _fetch_generalcompute_models(llm_context: LLMContext) -> List[ModelResponse]:
    """Fetch and trim models from General Compute."""
    url = f"{settings.GENERALCOMPUTE_BASE_URL}/models/list"
    try:
        headers = {"Authorization": f"Bearer {llm_context.get_api_key()}"}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers=headers, timeout=settings.GENERALCOMPUTE_TIMEOUT_SECONDS
            )
            if response.status_code in (401, 403):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or rejected General Compute API key.",
                )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"General Compute returned error: {response.text}",
                )

            data = response.json()
            models_list = data.get("data", [])

            result = []
            for item in models_list:
                model_id = item.get("id")
                if not model_id:
                    continue
                max_tokens = item.get("max_completion_tokens")
                result.append(
                    ModelResponse(
                        id=model_id,
                        name=model_id,
                        context_length=None,
                        max_completion_tokens=max_tokens,
                    )
                )
            return result
    except httpx.RequestError as e:
        logger.error(f"Failed to connect to General Compute: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to connect to General Compute",
        )


@router.get(
    "/models",
    response_model=List[ModelResponse],
    summary="List available AI models",
    description=(
        "Fetch available models from the active AI provider and return trimmed "
        "metadata. Requires X-AI-Provider and appropriate key headers."
    ),
)
async def list_models(
    llm_context: LLMContext = Depends(get_llm_context),
) -> List[ModelResponse]:
    """
    Fetch models from active provider and trim to only include ID, Name,
    and Context Length. Requires authentication.
    """
    try:
        if llm_context.provider == AIProviderEnum.GENERALCOMPUTE:
            return await _fetch_generalcompute_models(llm_context)
        return await _fetch_openrouter_models(llm_context)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error listing models: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Internal server error",
        )
