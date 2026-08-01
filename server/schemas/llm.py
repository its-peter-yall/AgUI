"""
============================================================================
FILE: llm.py
LOCATION: server/schemas/llm.py
============================================================================
PURPOSE:
    Defines Pydantic schemas for LLM request context and model proxying.
ROLE IN PROJECT:
    Provides validation structures for OpenRouter request parameters,
    headers, and model information.
KEY COMPONENTS:
    - LLMContext: Pydantic model for request-scoped LLM context
    - ModelResponse: Pydantic model for trimmed model information
DEPENDENCIES:
    - External: pydantic
    - Internal: None
USAGE:
    ```python
    from server.schemas.llm import LLMContext
    context = LLMContext(api_key="...", http_referer="...")
    ```
============================================================================
"""

from enum import Enum
from typing import Any, Optional, Union

from fastapi import HTTPException, Header, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class AIProviderEnum(str, Enum):
    """Supported AI provider identifiers."""
    OPENROUTER = "openrouter"
    GENERALCOMPUTE = "generalcompute"


class LLMContext(BaseModel):
    """
    Pydantic model representing request-scoped LLM context.

    api_key is SecretStr (excluded from dumps/repr). Prefer get_api_key()
    for plaintext access at call sites that talk to external SDKs.
    """
    model_config = ConfigDict(from_attributes=True)

    provider: AIProviderEnum = Field(
        default=AIProviderEnum.OPENROUTER,
        description="AI provider to route requests through",
    )
    api_key: SecretStr = Field(
        ...,
        description="Provider API Key",
        repr=False,
        exclude=True,
    )
    model: Optional[str] = Field(
        default=None,
        description="Global model slug override to use for all agents",
    )
    http_referer: Optional[str] = Field(
        default=None,
        description="Referer URL for OpenRouter analytics attribution",
    )
    app_title: Optional[str] = Field(
        default=None,
        description="Application title for OpenRouter analytics attribution",
    )
    chat_model: Optional[str] = Field(
        default=None,
        description="Model slug for concept chat (overrides main model when set)",
    )
    thinking_enabled: bool = Field(
        default=False,
        description="Whether thinking/reasoning mode is enabled",
    )
    thinking_effort: Optional[str] = Field(
        default=None,
        description="Thinking effort level: minimal, low, medium, high, xhigh",
        pattern="^(minimal|low|medium|high|xhigh)$",
    )
    max_completion_tokens: Optional[int] = Field(
        default=None,
        description="Model-specific max output token limit from settings",
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def _coerce_api_key(cls, value: Union[str, SecretStr]) -> SecretStr:
        if isinstance(value, SecretStr):
            return value
        return SecretStr(str(value))

    def get_api_key(self) -> str:
        """Return plaintext API key for outbound SDK calls only."""
        return self.api_key.get_secret_value()

    def get_attribution_headers(self) -> dict[str, str]:
        """
        Builds the dictionary of attribution headers for OpenRouter.
        """
        headers = {}
        if self.provider == AIProviderEnum.OPENROUTER:
            if self.http_referer:
                headers["HTTP-Referer"] = self.http_referer
            if self.app_title:
                headers["X-OpenRouter-Title"] = self.app_title
        return headers

    def get_reasoning_params(self) -> Optional[dict[str, Any]]:
        """
        Build OpenRouter reasoning parameters dict.

        Returns:
            Dict with 'reasoning' key if thinking is enabled, else None.
        """
        if not self.thinking_enabled:
            return None

        if not self.thinking_effort:
            # Default to 'high' if enabled but no effort specified
            return {"reasoning": {"effort": "high"}}

        return {"reasoning": {"effort": self.thinking_effort}}


class ModelResponse(BaseModel):
    """
    Pydantic model representing trimmed model information returned to UI.
    """
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Model identifier slug")
    name: Optional[str] = Field(None, description="Human-readable model name")
    context_length: Optional[int] = Field(
        None,
        description="Context window length in tokens",
    )
    max_completion_tokens: Optional[int] = Field(
        None,
        description="Maximum tokens the model can generate in a single response",
    )
    supports_thinking: bool = Field(
        default=False,
        description="Whether the model supports thinking/reasoning mode",
    )


async def get_llm_context(
    x_ai_provider: Optional[str] = Header(None, alias="X-AI-Provider"),
    x_openrouter_key: Optional[str] = Header(None, alias="X-OpenRouter-Key"),
    x_generalcompute_key: Optional[str] = Header(None, alias="X-GeneralCompute-Key"),
    x_openrouter_model: Optional[str] = Header(None, alias="X-OpenRouter-Model"),
    x_generalcompute_model: Optional[str] = Header(None, alias="X-GeneralCompute-Model"),
    x_max_completion_tokens: Optional[str] = Header(
        None, alias="X-Max-Completion-Tokens"
    ),
    http_referer: Optional[str] = Header(None, alias="HTTP-Referer"),
    x_openrouter_title: Optional[str] = Header(None, alias="X-OpenRouter-Title"),
    x_thinking_enabled: Optional[str] = Header(None, alias="X-Thinking-Enabled"),
    x_thinking_effort: Optional[str] = Header(None, alias="X-Thinking-Effort"),
) -> LLMContext:
    """
    FastAPI dependency to extract LLM context from request headers.

    Returns 401 when the active provider's API key is missing or blank.
    """
    provider_str = x_ai_provider or "openrouter"
    if provider_str not in [p.value for p in AIProviderEnum]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported AI provider: {provider_str}",
        )
    
    provider = AIProviderEnum(provider_str)

    if provider == AIProviderEnum.OPENROUTER:
        api_key = x_openrouter_key
        model = x_openrouter_model
        key_header_name = "X-OpenRouter-Key"
    else:
        api_key = x_generalcompute_key
        model = x_generalcompute_model
        key_header_name = "X-GeneralCompute-Key"

    if not api_key or not api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"{key_header_name} header is missing.",
        )

    # Parse thinking enabled (string 'true'/'false' -> bool)
    thinking_enabled = bool(
        x_thinking_enabled and x_thinking_enabled.lower() == 'true'
    )

    # Validate effort level if provided
    thinking_effort = None
    valid_efforts = {'minimal', 'low', 'medium', 'high', 'xhigh'}
    if x_thinking_effort and x_thinking_effort in valid_efforts:
        thinking_effort = x_thinking_effort
    elif thinking_enabled:
        # Default to 'high' if enabled but no valid effort provided
        thinking_effort = 'high'

    # Parse max completion tokens (model-specific output limit)
    max_completion_tokens = None
    if x_max_completion_tokens and x_max_completion_tokens.strip():
        try:
            max_completion_tokens = int(x_max_completion_tokens)
        except (ValueError, TypeError):
            max_completion_tokens = None

    return LLMContext(
        provider=provider,
        api_key=SecretStr(api_key.strip()),
        model=model,
        http_referer=http_referer,
        app_title=x_openrouter_title,
        thinking_enabled=thinking_enabled,
        thinking_effort=thinking_effort,
        max_completion_tokens=max_completion_tokens,
    )
