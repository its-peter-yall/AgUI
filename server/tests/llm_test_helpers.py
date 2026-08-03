"""
============================================================================
FILE: llm_test_helpers.py
LOCATION: server/tests/llm_test_helpers.py
============================================================================
PURPOSE:
    Shared LLMContext fixtures with four agent role models for tests.
ROLE IN PROJECT:
    Keeps generate/resume/regen test overrides aligned with require_agent_models.
KEY COMPONENTS:
    - make_test_llm_context: full agent_models dict
DEPENDENCIES:
    - Internal: server.schemas.llm
USAGE:
    from server.tests.llm_test_helpers import make_test_llm_context
============================================================================
"""

from typing import Optional

from server.schemas.llm import (
    AgentModelConfig,
    LLMContext,
    REQUIRED_AGENT_ROLES,
)


def make_test_llm_context(
    api_key: str = "test-key",
    model: str = "test/model",
    **kwargs: object,
) -> LLMContext:
    """Build LLMContext with all four required agent models."""
    agent_models = kwargs.pop("agent_models", None)
    if agent_models is None:
        agent_models = {
            role: AgentModelConfig(model=f"test/{role}")
            for role in REQUIRED_AGENT_ROLES
        }
    return LLMContext(
        api_key=api_key,
        model=model,
        agent_models=agent_models,  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )
