"""
============================================================================
FILE: test_agent_model_resolution.py
LOCATION: server/tests/test_agent_model_resolution.py
============================================================================
PURPOSE:
    Tests per-role model resolution for agents and depth_router.
ROLE IN PROJECT:
    Guards resolve_agent_call matrix and BaseAgent.generate wiring.
KEY COMPONENTS:
    - ResolveAgentCallTests
    - BaseAgentGenerateResolutionTests
DEPENDENCIES:
    - External: unittest, pydantic
    - Internal: server.agents.base, server.schemas.llm
USAGE:
    python -m unittest server.tests.test_agent_model_resolution
============================================================================
"""

import unittest
from unittest.mock import AsyncMock, patch

from pydantic import BaseModel, SecretStr

from server.agents.base import BaseAgent
from server.schemas.llm import (
    AIProviderEnum,
    AgentModelConfig,
    LLMContext,
)


class _Out(BaseModel):
    ok: bool = True


class _StubAgent(BaseAgent):
    @property
    def system_prompt(self) -> str:
        return "stub"


class ResolveAgentCallTests(unittest.TestCase):
    def test_role_uses_agent_model_not_main(self) -> None:
        ctx = LLMContext(
            api_key=SecretStr("or"),
            model="main/model",
            provider=AIProviderEnum.OPENROUTER,
            openrouter_api_key=SecretStr("or"),
            generalcompute_api_key=SecretStr("gc"),
            agent_models={
                "planner": AgentModelConfig(
                    model="planner/model",
                    provider=AIProviderEnum.GENERALCOMPUTE,
                    thinking_enabled=True,
                    thinking_effort="low",
                )
            },
        )
        model, provider, key, reasoning = ctx.resolve_agent_call(
            "planner"
        )
        self.assertEqual(model, "planner/model")
        self.assertEqual(provider, AIProviderEnum.GENERALCOMPUTE)
        self.assertEqual(key, "gc")
        self.assertEqual(
            reasoning, {"reasoning": {"effort": "low"}}
        )

    def test_depth_router_uses_main(self) -> None:
        ctx = LLMContext(
            api_key=SecretStr("or"),
            model="main/model",
            thinking_enabled=True,
            thinking_effort="high",
            agent_models={
                "planner": AgentModelConfig(model="p"),
            },
        )
        model, provider, key, reasoning = ctx.resolve_agent_call(
            "depth_router"
        )
        self.assertEqual(model, "main/model")
        self.assertEqual(provider, AIProviderEnum.OPENROUTER)
        self.assertEqual(
            reasoning, {"reasoning": {"effort": "high"}}
        )


class BaseAgentGenerateResolutionTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_generate_passes_resolved_model(self) -> None:
        agent = _StubAgent(role="quizzer")
        ctx = LLMContext(
            api_key=SecretStr("or"),
            model="main/model",
            openrouter_api_key=SecretStr("or"),
            agent_models={
                "quizzer": AgentModelConfig(
                    model="quiz/model",
                    thinking_enabled=False,
                )
            },
        )
        with patch(
            "server.agents.base.instructor_client.create_structured",
            new_callable=AsyncMock,
        ) as mock_cs:
            mock_cs.return_value = _Out()
            await agent.generate(
                response_model=_Out,
                user_message="hi",
                llm_context=ctx,
            )
            kwargs = mock_cs.await_args.kwargs
            self.assertEqual(kwargs["model_override"], "quiz/model")
            self.assertEqual(kwargs["api_key"], "or")
            self.assertIsNone(kwargs["reasoning_params"])


if __name__ == "__main__":
    unittest.main()
