"""
============================================================================
FILE: test_concept_chat_search.py
LOCATION: server/tests/test_concept_chat_search.py
============================================================================
PURPOSE:
    Unit tests for the concept-chat web_search tool schema, ChatSearchLedger,
    and one-shot ProviderCoordinator helper.
ROLE IN PROJECT:
    Locks Plan 3 contracts so Plan 4 can call one_shot_chat_search without
    live network or research-budget types.
    - Tool schema: query-only web_search
    - Ledger: 2x providers, 25s window, RuntimeError hard-stop
    - Helper: filter adapters, empty persisted_order, close httpx client
KEY COMPONENTS:
    - WebSearchToolSchemaTests: OpenAI function schema
    - ChatSearchLedgerTests: duck-typed budget stub
    - OneShotChatSearchTests: mocked coordinator wiring
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.services.concept_chat_search, search types/context
USAGE:
    python -m unittest server.tests.test_concept_chat_search
============================================================================
"""

from __future__ import annotations

import json
import unittest

from server.services.concept_chat_search import WEB_SEARCH_TOOL


class WebSearchToolSchemaTests(unittest.TestCase):
    """Locks the OpenAI-compatible web_search tool exposed to the model."""

    def test_schema_is_web_search_with_query_only(self) -> None:
        self.assertEqual(WEB_SEARCH_TOOL["type"], "function")
        function = WEB_SEARCH_TOOL["function"]
        self.assertEqual(function["name"], "web_search")
        parameters = function["parameters"]
        self.assertEqual(parameters["type"], "object")
        self.assertEqual(list(parameters["properties"].keys()), ["query"])
        self.assertEqual(parameters["properties"]["query"]["type"], "string")
        self.assertEqual(parameters["required"], ["query"])
        self.assertNotIn("max_results", json.dumps(WEB_SEARCH_TOOL))

    def test_description_states_what_when_how_and_one_call(self) -> None:
        description = WEB_SEARCH_TOOL["function"]["description"]
        lowered = description.lower()
        self.assertIn("search the public web", lowered)
        self.assertIn("concept content", lowered)
        self.assertIn("prior messages", lowered)
        self.assertIn("lack the context", lowered)
        self.assertIn("prior web_search results already", lowered)
        self.assertIn("one search per turn", lowered)
        self.assertIn("meticulous query", lowered)
        self.assertIn("specific terms", lowered)
        self.assertIn("versions", lowered)
        self.assertIn("concept-title", lowered)
        self.assertIn("disambiguation", lowered)
        self.assertNotIn("max_results", lowered)
