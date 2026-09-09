"""
============================================================================
FILE: test_concept_chat_router.py
LOCATION: server/tests/test_concept_chat_router.py
============================================================================
PURPOSE:
    Tests concept-chat route wiring for SearchContext.
ROLE IN PROJECT:
    Ensures globe-ON headers parse via get_search_context and the
    context object is passed into stream_concept_chat.
KEY COMPONENTS:
    - ConceptChatRouterTests: Depends, 400 on bad search headers,
      pass-through of enabled/disabled context
DEPENDENCIES:
    - External: unittest, fastapi
    - Internal: server.routers.learning, server.schemas.search
USAGE:
    python -m unittest server.tests.test_concept_chat_router -v
============================================================================
"""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.params import Depends as DependsParam
from fastapi.testclient import TestClient

from server.routers.learning import concept_chat, router
from server.schemas.search import get_search_context


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _fake_stream(**kwargs):
    async def _gen():
        yield "data: {\"delta\":\"ok\"}\n\n"
        yield "data: [DONE]\n\n"

    _fake_stream.captured = kwargs
    return _gen()


class ConceptChatRouterTests(unittest.TestCase):
    def test_concept_chat_depends_get_search_context(self) -> None:
        param = inspect.signature(concept_chat).parameters.get(
            "search_context"
        )
        self.assertIsNotNone(param)
        self.assertIsInstance(param.default, DependsParam)
        self.assertIs(param.default.dependency, get_search_context)

    def test_web_search_true_without_providers_returns_400(self) -> None:
        response = _client().post(
            "/learning/sessions/s1/nodes/n1/chat",
            json={"message": "hello"},
            headers={
                "X-Provider-Api-Key": "k",
                "X-Chat-Model": "openai/gpt-4o-mini",
                "X-Web-Search": "true",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_passes_disabled_context_when_headers_omitted(self) -> None:
        session = {"id": "s1"}
        node = {
            "id": "n1",
            "learning_session_id": "s1",
            "content_markdown": "# Hi",
            "title": "Node",
        }
        with patch(
            "server.routers.learning.stream_concept_chat",
            side_effect=_fake_stream,
        ), patch(
            "server.routers.learning.learning_manager"
        ) as manager:
            manager.get_learning_session.return_value = session
            manager.get_concept_node.return_value = node
            response = _client().post(
                "/learning/sessions/s1/nodes/n1/chat",
                json={"message": "hello"},
                headers={
                    "X-Provider-Api-Key": "k",
                    "X-Chat-Model": "openai/gpt-4o-mini",
                },
            )
        self.assertEqual(response.status_code, 200)
        context = _fake_stream.captured["search_context"]
        self.assertFalse(context.enabled)

    def test_passes_enabled_context_when_search_headers_present(self) -> None:
        session = {"id": "s1"}
        node = {
            "id": "n1",
            "learning_session_id": "s1",
            "content_markdown": "# Hi",
            "title": "Node",
        }
        with patch(
            "server.routers.learning.stream_concept_chat",
            side_effect=_fake_stream,
        ), patch(
            "server.routers.learning.learning_manager"
        ) as manager:
            manager.get_learning_session.return_value = session
            manager.get_concept_node.return_value = node
            response = _client().post(
                "/learning/sessions/s1/nodes/n1/chat",
                json={"message": "hello"},
                headers={
                    "X-Provider-Api-Key": "k",
                    "X-Chat-Model": "openai/gpt-4o-mini",
                    "X-Web-Search": "true",
                    "X-Web-Search-Providers": "tavily",
                    "X-Tavily-Key": "tvly-test",
                },
            )
        self.assertEqual(response.status_code, 200)
        context = _fake_stream.captured["search_context"]
        self.assertTrue(context.enabled)
        self.assertEqual(
            [item.value for item in context.provider_ids],
            ["tavily"],
        )
        self.assertNotIn("tvly-test", response.text)
