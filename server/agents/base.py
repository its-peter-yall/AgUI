"""
============================================================================
FILE: base.py
LOCATION: server/agents/base.py
============================================================================
PURPOSE:
    Abstract base class providing common functionality for all AI
    agents in the adaptive learning system.
ROLE IN PROJECT:
    Foundation for the agent hierarchy (Planner, Generator, Quizzer).
    - Defines the contract for structured LLM generation
    - Provides system prompt building and context formatting
KEY COMPONENTS:
    - BaseAgent (ABC): Abstract base with common agent functionality
    - generate(): Core method for structured response generation
    - _build_system_prompt(): Combines base prompt with context
    - _format_context(): Formats context dict for prompt injection
    - get_model_config(): Retrieves model config for the agent role
DEPENDENCIES:
    - External: pydantic, asyncio
    - Internal: server.utils.instructor_client
USAGE:
    ```python
    class MyAgent(BaseAgent):
        @property
        def system_prompt(self) -> str:
            return 'You are a specialized agent...'
    ```
============================================================================
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

from server.utils.instructor_client import instructor_client
from server.schemas.llm import LLMContext


logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class BaseAgent(ABC):
    """
    Abstract base class for AI agents.

    Provides common functionality for all agents including structured generation
    via InstructorClient, system prompt building, and context formatting.

    Subclasses must implement the system_prompt property to define their
    specific behavior and persona.
    """

    def __init__(self, role: str) -> None:
        """
        Initialize the agent with a specific role.

        Args:
            role: Agent role key matching MODEL_CONFIGS (planner, generator, quizzer)
        """
        self._role = role
        logger.debug(f"Initialized {self.__class__.__name__} with role: {role}")

    @property
    def role(self) -> str:
        """Get the agent's role."""
        return self._role

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """
        Return the system prompt for this agent.

        Must be implemented by subclasses to define the agent's persona,
        capabilities, and output format requirements.

        Returns:
            System prompt string
        """
        pass

    async def generate(
        self,
        response_model: Type[T],
        user_message: str,
        context: Optional[dict[str, Any]] = None,
        llm_context: Optional[LLMContext] = None,
        system_prompt_override: Optional[str] = None,
        **kwargs: Any,
    ) -> T:
        """Generate a structured response using the agent's role configuration.

        Builds the full system prompt with context injection and calls
        the InstructorClient for validated structured output.

        Args:
            response_model: Pydantic model class for response validation
            user_message: The user's input message/query
            context: Optional dict of context data for prompt augmentation
            llm_context: Optional OpenRouter context
            system_prompt_override: Optional explicit system prompt override
            **kwargs: Additional arguments passed to the instructor client

        Returns:
            Validated instance of response_model

        Raises:
            ValueError: If OpenRouter API key is missing
            Exception: On generation failures
        """
        if not llm_context:
            raise ValueError("AI API key is required in llm_context.")

        full_system_prompt = self._build_system_prompt(
            context, system_prompt_override=system_prompt_override
        )
        messages = [{"role": "user", "content": user_message}]

        model_override, provider, api_key, reasoning_params = (
            llm_context.resolve_agent_call(self._role)
        )
        if not api_key:
            raise ValueError(
                f"{provider.value.title()} API key is required in llm_context."
            )
        attribution_headers = llm_context.get_attribution_headers()

        response = await instructor_client.create_structured(
            role=self._role,
            response_model=response_model,
            messages=messages,
            api_key=api_key,
            model_override=model_override,
            attribution_headers=attribution_headers,
            system_prompt=full_system_prompt,
            provider=provider,
            reasoning_params=reasoning_params,
            max_completion_tokens=llm_context.max_completion_tokens,
            **kwargs,
        )
        logger.info(f"{self.__class__.__name__} generated structured response")
        return response

    def _build_system_prompt(
        self,
        context: Optional[dict[str, Any]] = None,
        system_prompt_override: Optional[str] = None,
    ) -> str:
        """
        Build the full system prompt with optional context injection.

        Combines the base system prompt from the subclass (or override) with
        formatted context data when provided.

        Args:
            context: Optional dict of context data to inject
            system_prompt_override: Optional system prompt string override

        Returns:
            Complete system prompt string
        """
        base_prompt = (
            system_prompt_override
            if system_prompt_override is not None
            else self.system_prompt
        )

        if context:
            context_str = self._format_context(context)
            return f"{base_prompt}\n\n{context_str}"

        return base_prompt

    def _format_context(self, context: dict[str, Any]) -> str:
        """
        Format context dictionary for injection into the system prompt.

        Override in subclasses for custom context formatting.

        Args:
            context: Dictionary of context data

        Returns:
            Formatted context string
        """
        if not context:
            return ""

        lines = ["## Context"]
        for key, value in context.items():
            if isinstance(value, list):
                lines.append(f"\n### {key.replace('_', ' ').title()}")
                for item in value:
                    lines.append(f"- {item}")
            else:
                lines.append(f"\n### {key.replace('_', ' ').title()}")
                lines.append(str(value))

        return "\n".join(lines)

    def get_model_config(self) -> dict[str, Any]:
        """
        Get the model configuration for this agent's role.

        Returns:
            Configuration dict with model, temperature, max_tokens
        """
        return instructor_client.get_model_config(self._role)
