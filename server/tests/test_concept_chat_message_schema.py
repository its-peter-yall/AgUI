"""
============================================================================
FILE: test_concept_chat_message_schema.py
LOCATION: server/tests/test_concept_chat_message_schema.py
============================================================================
PURPOSE:
    Contract tests for optional search blobs on ConceptChatMessage.
ROLE IN PROJECT:
    Locks the concept-chat web-search history payload before the tool
    loop, formatter, or router consume it.
    - Optional nested search accepted
    - Old {role, content} messages still parse
    - Unknown extras ignored (never extra=forbid)
    - Invalid search fields rejected
KEY COMPONENTS:
    - ConceptChatMessageSchemaTests: Pydantic v2 validation cases
DEPENDENCIES:
    - External: unittest, pydantic
    - Internal: server.schemas.learning
USAGE:
    python -m unittest server.tests.test_concept_chat_message_schema -v
============================================================================
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from server.schemas.learning import (
    ConceptChatMessage,
    ConceptChatRequest,
    ConceptChatSearch,
    ConceptChatSearchSource,
)


_VALID_SEARCH = {
    "query": "LangChain BaseTool documentation",
    "tool_call_id": "call_abc123",
    "results": (
        'WEB SEARCH RESULTS for: "LangChain BaseTool documentation"'
    ),
    "sources": [
        {
            "title": "LangChain docs",
            "url": "https://python.langchain.com",
        }
    ],
}


class ConceptChatMessageSchemaTests(unittest.TestCase):
    def test_optional_search_accepted(self) -> None:
        msg = ConceptChatMessage.model_validate(
            {
                "role": "assistant",
                "content": "Here is the answer.",
                "search": _VALID_SEARCH,
            }
        )
        self.assertEqual(msg.role, "assistant")
        self.assertEqual(msg.content, "Here is the answer.")
        self.assertIsNotNone(msg.search)
        self.assertIsInstance(msg.search, ConceptChatSearch)
        self.assertEqual(
            msg.search.query,
            "LangChain BaseTool documentation",
        )
        self.assertEqual(msg.search.tool_call_id, "call_abc123")
        self.assertIn("WEB SEARCH RESULTS", msg.search.results)
        self.assertEqual(len(msg.search.sources), 1)
        self.assertIsInstance(
            msg.search.sources[0],
            ConceptChatSearchSource,
        )
        self.assertEqual(
            msg.search.sources[0].title,
            "LangChain docs",
        )
        self.assertEqual(
            msg.search.sources[0].url,
            "https://python.langchain.com",
        )

    def test_missing_search_ok(self) -> None:
        msg = ConceptChatMessage.model_validate(
            {"role": "user", "content": "hello"}
        )
        self.assertEqual(msg.role, "user")
        self.assertEqual(msg.content, "hello")
        self.assertIsNone(msg.search)

    def test_search_null_ok(self) -> None:
        msg = ConceptChatMessage.model_validate(
            {
                "role": "assistant",
                "content": "plain answer",
                "search": None,
            }
        )
        self.assertIsNone(msg.search)

    def test_empty_sources_ok(self) -> None:
        msg = ConceptChatMessage.model_validate(
            {
                "role": "assistant",
                "content": "answer",
                "search": {
                    "query": "q",
                    "tool_call_id": "call_1",
                    "results": "blob",
                    "sources": [],
                },
            }
        )
        self.assertIsNotNone(msg.search)
        self.assertEqual(msg.search.sources, [])

    def test_unknown_extras_ignored(self) -> None:
        msg = ConceptChatMessage.model_validate(
            {
                "role": "user",
                "content": "hello from old client",
                "timestamp": 1,
                "foo": "bar",
            }
        )
        self.assertEqual(msg.role, "user")
        self.assertEqual(msg.content, "hello from old client")
        self.assertIsNone(msg.search)
        dumped = msg.model_dump()
        self.assertNotIn("timestamp", dumped)
        self.assertNotIn("foo", dumped)

    def test_nested_search_extras_ignored(self) -> None:
        msg = ConceptChatMessage.model_validate(
            {
                "role": "assistant",
                "content": "answer",
                "search": {
                    "query": "q",
                    "tool_call_id": "call_1",
                    "results": "blob",
                    "provider": "tavily",
                    "sources": [
                        {
                            "title": "T",
                            "url": "https://example.com",
                            "snippet": "ignored",
                        }
                    ],
                },
            }
        )
        self.assertIsNotNone(msg.search)
        dumped = msg.search.model_dump()
        self.assertNotIn("provider", dumped)
        self.assertNotIn("snippet", dumped["sources"][0])
        self.assertEqual(dumped["sources"][0]["title"], "T")
        self.assertEqual(
            dumped["sources"][0]["url"],
            "https://example.com",
        )

    def test_extra_is_not_forbid(self) -> None:
        self.assertNotEqual(
            ConceptChatMessage.model_config.get("extra"),
            "forbid",
        )
        self.assertNotEqual(
            ConceptChatSearch.model_config.get("extra"),
            "forbid",
        )
        self.assertNotEqual(
            ConceptChatSearchSource.model_config.get("extra"),
            "forbid",
        )

    def test_invalid_search_fields_rejected(self) -> None:
        base = {
            "role": "assistant",
            "content": "answer from concept",
        }
        invalid_searches = [
            "not-an-object",
            [],
            {},
            {
                "tool_call_id": "call_1",
                "results": "blob",
                "sources": [],
            },
            {
                "query": "",
                "tool_call_id": "call_1",
                "results": "blob",
                "sources": [],
            },
            {
                "query": "q",
                "results": "blob",
                "sources": [],
            },
            {
                "query": "q",
                "tool_call_id": "",
                "results": "blob",
                "sources": [],
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "sources": [],
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "results": "",
                "sources": [],
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "results": "blob",
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "results": "blob",
                "sources": "not-a-list",
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "results": "blob",
                "sources": [{"url": "https://ex.com"}],
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "results": "blob",
                "sources": [{"title": "T"}],
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "results": "blob",
                "sources": [
                    {"title": "", "url": "https://ex.com"}
                ],
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "results": "blob",
                "sources": [{"title": "T", "url": ""}],
            },
        ]
        for search in invalid_searches:
            with self.subTest(search=search):
                payload = {**base, "search": search}
                with self.assertRaises(ValidationError):
                    ConceptChatMessage.model_validate(payload)

    def test_role_rejects_tool(self) -> None:
        with self.assertRaises(ValidationError):
            ConceptChatMessage.model_validate(
                {"role": "tool", "content": "search results"}
            )

    def test_content_min_length_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ConceptChatMessage.model_validate(
                {"role": "user", "content": ""}
            )

    def test_request_history_preserves_search(self) -> None:
        req = ConceptChatRequest.model_validate(
            {
                "message": "follow up",
                "history": [
                    {"role": "user", "content": "first question"},
                    {
                        "role": "assistant",
                        "content": "grounded answer",
                        "search": _VALID_SEARCH,
                    },
                ],
            }
        )
        self.assertEqual(len(req.history), 2)
        self.assertIsNone(req.history[0].search)
        self.assertIsNotNone(req.history[1].search)
        self.assertEqual(
            req.history[1].search.tool_call_id,
            "call_abc123",
        )


if __name__ == "__main__":
    unittest.main()
