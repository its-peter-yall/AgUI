"""
============================================================================
FILE: test_concept_chat_cache.py
LOCATION: server/tests/test_concept_chat_cache.py
============================================================================
PURPOSE:
    Integration tests confirming prompt caching breakpoints reach the wire
    for the concept chatbot on OpenRouter cacheable models only.
ROLE IN PROJECT:
    Validates stream_concept_chat attaches cache_control to the system
    prefix for OpenRouter + Anthropic/Google/Qwen, and stays clean for
    General Compute and auto-caching providers.
KEY COMPONENTS:
    - FakeStream: Minimal async-iterable chat stream stub
    - TestConceptChatCaching: End-to-end caching assertions
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.services.concept_chat
USAGE:
    python -m unittest server.tests.test_concept_chat_cache
============================================================================
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import unittest

from server.schemas.learning import ConceptChatMessage
from server.schemas.search import SearchContext
from server.search.types import SearchProviderId
from server.services.concept_chat import stream_concept_chat


class FakeStream:
    """Minimal async-iterable stub emulating an OpenAI chat stream."""

    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for chunk in self._chunks:
            yield chunk


def _chunk(text):
    delta = MagicMock()
    delta.content = text
    delta.tool_calls = None
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = None
    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


def _tool_delta_chunk(
    index, call_id=None, name=None, arguments=None
):
    function = MagicMock()
    function.name = name
    function.arguments = arguments
    tool_call = MagicMock()
    tool_call.index = index
    tool_call.id = call_id
    tool_call.function = function
    delta = MagicMock()
    delta.content = None
    delta.tool_calls = [tool_call]
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = None
    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


def _tool_stream(query="LangChain BaseTool"):
    encoded = json.dumps({"query": query})
    mid = max(1, len(encoded) // 2)
    return [
        _tool_delta_chunk(
            0,
            call_id="call_abc123",
            name="web_search",
            arguments="",
        ),
        _tool_delta_chunk(0, arguments=encoded[:mid]),
        _tool_delta_chunk(0, arguments=encoded[mid:]),
    ]


def _make_client():
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=FakeStream([_chunk("hi"), _chunk(" there")])
    )
    return client


class TestConceptChatCaching(unittest.TestCase):
    def _run(self, provider, model):
        client = _make_client()
        captured = {}

        async def go():
            with patch(
                "server.services.concept_chat._get_client", return_value=client
            ):
                async for _ in stream_concept_chat(
                    api_key="k",
                    model_slug=model,
                    message="What is this about?",
                    history=[],
                    content_markdown="LONG STABLE CONCEPT CONTENT " * 50,
                    selected_heading_ids=[],
                    node_title="Test Node",
                    provider=provider,
                ):
                    pass
            _, kwargs = client.chat.completions.create.call_args
            captured["messages"] = kwargs.get("messages")

        asyncio.run(go())
        return captured["messages"]

    def test_openrouter_anthropic_has_cache_control(self):
        messages = self._run("openrouter", "anthropic/claude-sonnet-4")
        sys_msg = messages[0]
        self.assertIsInstance(sys_msg["content"], list)
        self.assertEqual(sys_msg["content"][0]["cache_control"], {"type": "ephemeral"})

    def test_openrouter_openai_no_cache_control(self):
        messages = self._run("openrouter", "openai/gpt-4o-mini")
        sys_msg = messages[0]
        self.assertIsInstance(sys_msg["content"], str)
        self.assertNotIn("cache_control", sys_msg)

    def test_generalcompute_no_cache_control(self):
        messages = self._run("generalcompute", "anthropic/claude-sonnet-4")
        sys_msg = messages[0]
        self.assertIsInstance(sys_msg["content"], str)
        self.assertNotIn("cache_control", sys_msg)

    def test_openrouter_thinking_extra_body(self):
        client = _make_client()
        captured = {}

        async def go():
            with patch(
                "server.services.concept_chat._get_client", return_value=client
            ):
                async for _ in stream_concept_chat(
                    api_key="k",
                    model_slug="openai/o3",
                    message="Why?",
                    history=[],
                    content_markdown="content",
                    selected_heading_ids=[],
                    node_title="Node",
                    provider="openrouter",
                    thinking_enabled=True,
                    thinking_effort="medium",
                ):
                    pass
            _, kwargs = client.chat.completions.create.call_args
            captured["extra_body"] = kwargs.get("extra_body")

        asyncio.run(go())
        self.assertEqual(
            captured["extra_body"],
            {"reasoning": {"effort": "medium"}},
        )

    def test_thinking_disabled_no_extra_body(self):
        client = _make_client()
        captured = {}

        async def go():
            with patch(
                "server.services.concept_chat._get_client", return_value=client
            ):
                async for _ in stream_concept_chat(
                    api_key="k",
                    model_slug="openai/o3",
                    message="Why?",
                    history=[],
                    content_markdown="content",
                    selected_heading_ids=[],
                    node_title="Node",
                    provider="openrouter",
                    thinking_enabled=False,
                ):
                    pass
            _, kwargs = client.chat.completions.create.call_args
            captured["extra_body"] = kwargs.get("extra_body")

        asyncio.run(go())
        self.assertIsNone(captured["extra_body"])

    def test_cache_control_on_both_rounds_when_tools_used(self) -> None:
        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=[
                FakeStream(_tool_stream()),
                FakeStream([_chunk("cached.")]),
            ]
        )
        search_response = MagicMock()
        search_response.results = [object()]
        context = SearchContext.from_plaintext_credentials(
            enabled=True,
            provider_ids=[SearchProviderId.TAVILY],
            credentials={SearchProviderId.TAVILY: "tvly-test"},
        )
        blob = 'WEB SEARCH RESULTS for: "LangChain BaseTool"\n'
        sources = [
            {
                "title": "BaseTool",
                "url": "https://python.langchain.com/docs",
            }
        ]

        async def go():
            with patch(
                "server.services.concept_chat._get_client",
                return_value=client,
            ), patch(
                "server.services.concept_chat.one_shot_chat_search",
                new_callable=AsyncMock,
                return_value=search_response,
            ), patch(
                "server.services.concept_chat.format_chat_search_results",
                return_value=(blob, sources),
            ):
                async for _ in stream_concept_chat(
                    api_key="k",
                    model_slug="anthropic/claude-sonnet-4",
                    message="What is this about?",
                    history=[],
                    content_markdown="LONG STABLE CONCEPT CONTENT " * 50,
                    selected_heading_ids=[],
                    node_title="Test Node",
                    provider="openrouter",
                    search_context=context,
                ):
                    pass

        asyncio.run(go())
        self.assertEqual(client.chat.completions.create.await_count, 2)
        for index, call in enumerate(
            client.chat.completions.create.call_args_list
        ):
            sys_msg = call.kwargs["messages"][0]
            self.assertIsInstance(sys_msg["content"], list, msg=index)
            self.assertEqual(
                sys_msg["content"][0]["cache_control"],
                {"type": "ephemeral"},
                msg=index,
            )
            for message in call.kwargs["messages"][1:]:
                content = message.get("content")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            self.assertNotIn("cache_control", part)


if __name__ == "__main__":
    unittest.main()
