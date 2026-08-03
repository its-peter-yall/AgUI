"""
============================================================================
FILE: test_regen_stream.py
LOCATION: server/tests/test_regen_stream.py
============================================================================
PURPOSE:
    Tests for the streaming regeneration endpoint.
ROLE IN PROJECT:
    Ensures that the SSE streaming regeneration endpoint functions properly,
    returns correctly formatted deltas, updates DB on completion,
    and returns correct errors on failure.
KEY COMPONENTS:
    - TestRegenStreamEndpoint: Unit tests for POST /nodes/{node_id}/regenerate/stream
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.main
USAGE:
    python -m unittest server.tests.test_regen_stream
============================================================================
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from server.main import app
from server.schemas.llm import get_llm_context
from server.tests.llm_test_helpers import make_test_llm_context

def _client() -> TestClient:
    app.dependency_overrides[get_llm_context] = lambda: make_test_llm_context(
        api_key="test_key",
        model="test_model",
    )
    return TestClient(app)

class TestRegenStreamEndpoint(unittest.TestCase):
    """Unit tests for the SSE regeneration streaming endpoint."""

    @patch("server.graph.regen_stream.learning_manager.get_concept_node")
    def test_stream_regenerate_endpoint_not_found(self, mock_get: MagicMock) -> None:
        mock_get.return_value = None
        client = _client()

        response = client.post(
            "/learning/nodes/nonexistent-node/regenerate/stream",
            headers={"X-Provider-Api-Key": "test_key", "X-Model": "test_model"}
        )

        self.assertEqual(response.status_code, 200)
        # Verify it streams an error payload
        lines = [line for line in response.iter_lines() if line]
        self.assertTrue(any("node not found" in line.lower() for line in lines))

    @patch("server.graph.regen_stream.learning_manager.get_concept_node")
    def test_stream_regenerate_endpoint_locked(self, mock_get: MagicMock) -> None:
        mock_get.return_value = {
            "id": "node-1",
            "learning_session_id": "session-1",
            "sequence_index": 1,
            "title": "Topic 1",
            "status": "LOCKED",
            "complexity": "Basic",
            "content_markdown": "",
        }
        client = _client()

        response = client.post(
            "/learning/nodes/node-1/regenerate/stream",
            headers={"X-Provider-Api-Key": "test_key", "X-Model": "test_model"}
        )

        self.assertEqual(response.status_code, 200)
        lines = [line for line in response.iter_lines() if line]
        self.assertTrue(any("Cannot regenerate a LOCKED node" in line for line in lines))

    @patch("server.graph.regen_stream.learning_manager.get_concept_node")
    @patch("server.graph.regen_stream.learning_manager.get_session_nodes")
    @patch("server.graph.regen_stream.instructor_client._get_provider_config")
    @patch("server.graph.regen_stream.instructor.from_openai")
    @patch("server.graph.regen_stream.quizzer_agent.generate_quiz_set")
    @patch("server.graph.regen_stream.learning_manager.replace_node_content")
    def test_stream_regenerate_endpoint_success(
        self,
        mock_replace: MagicMock,
        mock_quiz_gen: AsyncMock,
        mock_instructor_from_openai: MagicMock,
        mock_provider_config: MagicMock,
        mock_get_session_nodes: MagicMock,
        mock_get: MagicMock,
    ) -> None:
        mock_get.return_value = {
            "id": "node-1",
            "learning_session_id": "session-1",
            "sequence_index": 0,
            "title": "Topic 0",
            "status": "VIEWING_EXPLANATION",
            "complexity": "Basic",
            "content_markdown": "Original",
            "quiz": None,
        }
        mock_get_session_nodes.return_value = [mock_get.return_value]
        mock_provider_config.return_value = ("https://api.openai.com/v1", 30)

        # Mock instructor stream/create_partial behavior
        mock_client = MagicMock()
        mock_instructor_from_openai.return_value = mock_client

        # Mock create_partial to yield chunks of a mock GeneratedContent object
        class MockPartialContent:
            def __init__(self, content_markdown: str):
                self.content_markdown = content_markdown

        async def mock_async_generator(*args, **kwargs):
            yield MockPartialContent("Reg")
            yield MockPartialContent("Regenerated")

        mock_client.chat.completions.create_partial = mock_async_generator

        # Mock quizzer
        mock_quiz_gen.return_value = MagicMock()

        # Mock replacement in DB
        mock_replace.return_value = {
            "id": "node-1",
            "learning_session_id": "session-1",
            "sequence_index": 0,
            "title": "Topic 0",
            "status": "VIEWING_EXPLANATION",
            "complexity": "Basic",
            "content_markdown": "Regenerated",
            "quiz": None,
        }

        client = _client()
        response = client.post(
            "/learning/nodes/node-1/regenerate/stream",
            headers={"X-Provider-Api-Key": "test_key", "X-Model": "test_model"}
        )

        self.assertEqual(response.status_code, 200)
        lines = [line for line in response.iter_lines() if line]

        # Verify delta chunks
        deltas = [line for line in lines if "delta" in line]
        self.assertTrue(len(deltas) > 0)
        
        # Verify done chunk
        done = [line for line in lines if "done" in line]
        self.assertEqual(len(done), 1)

        # Verify terminal sentinel
        self.assertEqual(lines[-1], "data: [DONE]")
