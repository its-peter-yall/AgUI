"""
============================================================================
FILE: test_llm_context_agent_models.py
LOCATION: server/tests/test_llm_context_agent_models.py
============================================================================
PURPOSE:
    Tests agent model header parsing and required-role validation.
ROLE IN PROJECT:
    Guards LLMContext.agent_models parse + require_agent_models 400s.
KEY COMPONENTS:
    - AgentModelConfigTests
    - RequireAgentModelsTests
    - GetLlmContextAgentHeadersTests
DEPENDENCIES:
    - External: unittest, fastapi, pydantic
    - Internal: server.schemas.llm
USAGE:
    python -m unittest server.tests.test_llm_context_agent_models
============================================================================
"""

import unittest

from fastapi import HTTPException
from pydantic import SecretStr

from server.schemas.llm import (
    AIProviderEnum,
    AgentModelConfig,
    LLMContext,
    get_llm_context,
    require_agent_models,
    REQUIRED_AGENT_ROLES,
)


class AgentModelConfigTests(unittest.TestCase):
    def test_reasoning_params_when_enabled(self) -> None:
        cfg = AgentModelConfig(
            model="m",
            thinking_enabled=True,
            thinking_effort="medium",
        )
        self.assertEqual(
            cfg.get_reasoning_params(),
            {"reasoning": {"effort": "medium"}},
        )

    def test_reasoning_params_none_when_disabled(self) -> None:
        cfg = AgentModelConfig(model="m", thinking_enabled=False)
        self.assertIsNone(cfg.get_reasoning_params())


class RequireAgentModelsTests(unittest.TestCase):
    def _ctx(self, **kwargs: object) -> LLMContext:
        base: dict = dict(
            api_key=SecretStr("k"),
            model="main",
            provider=AIProviderEnum.OPENROUTER,
            agent_models={},
            openrouter_api_key=SecretStr("or"),
            generalcompute_api_key=SecretStr("gc"),
        )
        base.update(kwargs)
        return LLMContext(**base)  # type: ignore[arg-type]

    def test_missing_roles_raise_400(self) -> None:
        ctx = self._ctx(
            agent_models={
                "researcher": AgentModelConfig(model="r"),
            }
        )
        with self.assertRaises(HTTPException) as cm:
            require_agent_models(ctx)
        self.assertEqual(cm.exception.status_code, 400)
        detail = str(cm.exception.detail).lower()
        self.assertIn("planner", detail)

    def test_all_roles_pass(self) -> None:
        models = {
            role: AgentModelConfig(model=f"{role}-m")
            for role in REQUIRED_AGENT_ROLES
        }
        require_agent_models(self._ctx(agent_models=models))

    def test_cross_provider_missing_key_raises(self) -> None:
        models = {
            "researcher": AgentModelConfig(
                model="r",
                provider=AIProviderEnum.GENERALCOMPUTE,
            ),
            "planner": AgentModelConfig(model="p"),
            "generator": AgentModelConfig(model="g"),
            "quizzer": AgentModelConfig(model="q"),
        }
        ctx = self._ctx(
            agent_models=models,
            generalcompute_api_key=None,
        )
        with self.assertRaises(HTTPException) as cm:
            require_agent_models(ctx)
        self.assertEqual(cm.exception.status_code, 400)


class GetLlmContextAgentHeadersTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_role_headers(self) -> None:
        ctx = await get_llm_context(
            x_ai_provider="openrouter",
            x_openrouter_key="or-secret",
            x_generalcompute_key="gc-secret",
            x_openrouter_model="main/model",
            x_generalcompute_model=None,
            x_max_completion_tokens=None,
            http_referer=None,
            x_openrouter_title=None,
            x_thinking_enabled="true",
            x_thinking_effort="high",
            x_researcher_model="r-m",
            x_researcher_provider="openrouter",
            x_researcher_thinking_enabled=None,
            x_researcher_thinking_effort=None,
            x_planner_model="p-m",
            x_planner_provider="generalcompute",
            x_planner_thinking_enabled=None,
            x_planner_thinking_effort=None,
            x_generator_model="g-m",
            x_generator_provider="openrouter",
            x_generator_thinking_enabled="true",
            x_generator_thinking_effort="medium",
            x_quizzer_model="q-m",
            x_quizzer_provider=None,
            x_quizzer_thinking_enabled=None,
            x_quizzer_thinking_effort=None,
        )
        self.assertEqual(ctx.agent_models["researcher"].model, "r-m")
        self.assertEqual(
            ctx.agent_models["planner"].provider,
            AIProviderEnum.GENERALCOMPUTE,
        )
        self.assertTrue(ctx.agent_models["generator"].thinking_enabled)
        self.assertEqual(
            ctx.agent_models["generator"].thinking_effort, "medium"
        )
        self.assertEqual(
            ctx.get_api_key_for_provider(AIProviderEnum.GENERALCOMPUTE),
            "gc-secret",
        )


if __name__ == "__main__":
    unittest.main()
