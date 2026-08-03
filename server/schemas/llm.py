"""
============================================================================
FILE: llm.py
LOCATION: server/schemas/llm.py
============================================================================
PURPOSE:
    Defines Pydantic schemas for LLM request context and model proxying.
ROLE IN PROJECT:
    Provides validation structures for OpenRouter request parameters,
    headers, model information, and per-agent model configs.
KEY COMPONENTS:
    - LLMContext: Pydantic model for request-scoped LLM context
    - AgentModelConfig: Per-role model/provider/thinking
    - ModelResponse: Pydantic model for trimmed model information
    - get_llm_context / require_agent_models
DEPENDENCIES:
    - External: pydantic, fastapi
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


REQUIRED_AGENT_ROLES: tuple[str, ...] = (
    "researcher",
    "planner",
    "generator",
    "quizzer",
)

_VALID_EFFORTS = frozenset(
    {"minimal", "low", "medium", "high", "xhigh"}
)


class AgentModelConfig(BaseModel):
    """Per-agent model, optional provider, and thinking settings."""

    model_config = ConfigDict(from_attributes=True)

    model: str = Field(..., min_length=1)
    provider: Optional[AIProviderEnum] = Field(
        default=None,
        description="Override provider; default LLMContext.provider",
    )
    thinking_enabled: bool = False
    thinking_effort: Optional[str] = Field(
        default=None,
        pattern="^(minimal|low|medium|high|xhigh)$",
    )

    def get_reasoning_params(self) -> Optional[dict[str, Any]]:
        if not self.thinking_enabled:
            return None
        effort = self.thinking_effort or "high"
        return {"reasoning": {"effort": effort}}


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
    openrouter_api_key: Optional[SecretStr] = Field(
        default=None,
        repr=False,
        exclude=True,
    )
    generalcompute_api_key: Optional[SecretStr] = Field(
        default=None,
        repr=False,
        exclude=True,
    )
    agent_models: dict[str, AgentModelConfig] = Field(
        default_factory=dict,
        description="Per-role model configs from request headers",
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

    def get_api_key_for_provider(
        self, provider: AIProviderEnum
    ) -> str:
        """Resolve plaintext key for a provider (role-aware)."""
        if provider == AIProviderEnum.OPENROUTER:
            secret = self.openrouter_api_key or (
                self.api_key
                if self.provider == AIProviderEnum.OPENROUTER
                else None
            )
        else:
            secret = self.generalcompute_api_key or (
                self.api_key
                if self.provider == AIProviderEnum.GENERALCOMPUTE
                else None
            )
        if secret is None:
            return ""
        return secret.get_secret_value()

    def resolve_agent_call(
        self, role: str
    ) -> tuple[str, AIProviderEnum, str, Optional[dict[str, Any]]]:
        """
        Returns (model, provider, api_key, reasoning_params).

        For researcher/planner/generator/quizzer: require agent_models.
        For depth_router / unknown: main model + global thinking.
        """
        if role in REQUIRED_AGENT_ROLES:
            cfg = self.agent_models.get(role)
            if cfg is None or not cfg.model.strip():
                raise ValueError(
                    f"Missing agent model for role '{role}'. "
                    "Configure all four agent models in Settings."
                )
            provider = cfg.provider or self.provider
            key = self.get_api_key_for_provider(provider)
            if not key:
                raise ValueError(
                    f"Missing API key for provider "
                    f"'{provider.value}' (role={role})."
                )
            return (
                cfg.model.strip(),
                provider,
                key,
                cfg.get_reasoning_params(),
            )
        # depth_router and fallback
        if not self.model or not str(self.model).strip():
            raise ValueError(
                f"No model specified for role '{role}'."
            )
        return (
            str(self.model).strip(),
            self.provider,
            self.get_api_key(),
            self.get_reasoning_params(),
        )

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


def require_agent_models(llm_context: LLMContext) -> None:
    """Raise HTTP 400 if required agent roles/keys incomplete."""
    missing: list[str] = []
    for role in REQUIRED_AGENT_ROLES:
        cfg = llm_context.agent_models.get(role)
        if cfg is None or not cfg.model.strip():
            missing.append(role)
            continue
        provider = cfg.provider or llm_context.provider
        if not llm_context.get_api_key_for_provider(provider):
            missing.append(f"{role} key ({provider.value})")
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Missing required agent model configuration: "
                + ", ".join(missing)
                + ". Set Researcher, Planner, Generator, and "
                "Quizzer models (and keys) in Settings."
            ),
        )


def _parse_role_agent(
    model: Optional[str],
    provider_str: Optional[str],
    thinking_enabled: Optional[str],
    thinking_effort: Optional[str],
) -> Optional[AgentModelConfig]:
    if not model or not model.strip():
        return None
    provider = None
    if provider_str in {p.value for p in AIProviderEnum}:
        provider = AIProviderEnum(provider_str)
    enabled = bool(
        thinking_enabled and thinking_enabled.lower() == "true"
    )
    effort = None
    if thinking_effort and thinking_effort in _VALID_EFFORTS:
        effort = thinking_effort
    elif enabled:
        effort = "high"
    return AgentModelConfig(
        model=model.strip(),
        provider=provider,
        thinking_enabled=enabled,
        thinking_effort=effort,
    )


async def get_llm_context(
    x_ai_provider: Optional[str] = Header(None, alias="X-AI-Provider"),
    x_openrouter_key: Optional[str] = Header(
        None, alias="X-OpenRouter-Key"
    ),
    x_generalcompute_key: Optional[str] = Header(
        None, alias="X-GeneralCompute-Key"
    ),
    x_openrouter_model: Optional[str] = Header(
        None, alias="X-OpenRouter-Model"
    ),
    x_generalcompute_model: Optional[str] = Header(
        None, alias="X-GeneralCompute-Model"
    ),
    x_max_completion_tokens: Optional[str] = Header(
        None, alias="X-Max-Completion-Tokens"
    ),
    http_referer: Optional[str] = Header(None, alias="HTTP-Referer"),
    x_openrouter_title: Optional[str] = Header(
        None, alias="X-OpenRouter-Title"
    ),
    x_thinking_enabled: Optional[str] = Header(
        None, alias="X-Thinking-Enabled"
    ),
    x_thinking_effort: Optional[str] = Header(
        None, alias="X-Thinking-Effort"
    ),
    x_researcher_model: Optional[str] = Header(
        None, alias="X-Researcher-Model"
    ),
    x_researcher_provider: Optional[str] = Header(
        None, alias="X-Researcher-Provider"
    ),
    x_researcher_thinking_enabled: Optional[str] = Header(
        None, alias="X-Researcher-Thinking-Enabled"
    ),
    x_researcher_thinking_effort: Optional[str] = Header(
        None, alias="X-Researcher-Thinking-Effort"
    ),
    x_planner_model: Optional[str] = Header(
        None, alias="X-Planner-Model"
    ),
    x_planner_provider: Optional[str] = Header(
        None, alias="X-Planner-Provider"
    ),
    x_planner_thinking_enabled: Optional[str] = Header(
        None, alias="X-Planner-Thinking-Enabled"
    ),
    x_planner_thinking_effort: Optional[str] = Header(
        None, alias="X-Planner-Thinking-Effort"
    ),
    x_generator_model: Optional[str] = Header(
        None, alias="X-Generator-Model"
    ),
    x_generator_provider: Optional[str] = Header(
        None, alias="X-Generator-Provider"
    ),
    x_generator_thinking_enabled: Optional[str] = Header(
        None, alias="X-Generator-Thinking-Enabled"
    ),
    x_generator_thinking_effort: Optional[str] = Header(
        None, alias="X-Generator-Thinking-Effort"
    ),
    x_quizzer_model: Optional[str] = Header(
        None, alias="X-Quizzer-Model"
    ),
    x_quizzer_provider: Optional[str] = Header(
        None, alias="X-Quizzer-Provider"
    ),
    x_quizzer_thinking_enabled: Optional[str] = Header(
        None, alias="X-Quizzer-Thinking-Enabled"
    ),
    x_quizzer_thinking_effort: Optional[str] = Header(
        None, alias="X-Quizzer-Thinking-Effort"
    ),
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

    agent_models: dict[str, AgentModelConfig] = {}
    for role, parsed in (
        (
            "researcher",
            _parse_role_agent(
                x_researcher_model,
                x_researcher_provider,
                x_researcher_thinking_enabled,
                x_researcher_thinking_effort,
            ),
        ),
        (
            "planner",
            _parse_role_agent(
                x_planner_model,
                x_planner_provider,
                x_planner_thinking_enabled,
                x_planner_thinking_effort,
            ),
        ),
        (
            "generator",
            _parse_role_agent(
                x_generator_model,
                x_generator_provider,
                x_generator_thinking_enabled,
                x_generator_thinking_effort,
            ),
        ),
        (
            "quizzer",
            _parse_role_agent(
                x_quizzer_model,
                x_quizzer_provider,
                x_quizzer_thinking_enabled,
                x_quizzer_thinking_effort,
            ),
        ),
    ):
        if parsed is not None:
            agent_models[role] = parsed

    return LLMContext(
        provider=provider,
        api_key=SecretStr(api_key.strip()),
        model=model,
        http_referer=http_referer,
        app_title=x_openrouter_title,
        thinking_enabled=thinking_enabled,
        thinking_effort=thinking_effort,
        max_completion_tokens=max_completion_tokens,
        openrouter_api_key=(
            SecretStr(x_openrouter_key.strip())
            if x_openrouter_key and x_openrouter_key.strip()
            else None
        ),
        generalcompute_api_key=(
            SecretStr(x_generalcompute_key.strip())
            if x_generalcompute_key and x_generalcompute_key.strip()
            else None
        ),
        agent_models=agent_models,
    )
