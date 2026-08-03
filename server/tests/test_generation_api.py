"""
============================================================================
FILE: test_generation_api.py
LOCATION: server/tests/test_generation_api.py
============================================================================
PURPOSE:
    Tests immediate generation acceptance and research API contracts.
ROLE IN PROJECT:
    Replaces blocking generation HTTP behavior with durable shell creation.
KEY COMPONENTS:
    - GenerationApiTests: 202, validation, and secret-boundary tests
DEPENDENCIES:
    - External: fastapi, unittest
    - Internal: server.routers.learning
USAGE:
    python -m unittest server.tests.test_generation_api -v
============================================================================
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routers.learning import router
from server.schemas.llm import get_llm_context
from server.tests.llm_test_helpers import make_test_llm_context


def _accepted() -> dict[str, object]:
    return {
        "session": {
            "id": "session-1",
            "user_id": None,
            "query": "Modern CSS",
            "course_title": "Modern CSS",
            "title_finalized": False,
            "mode": "auto",
            "resolved_mode": None,
            "total_nodes": 0,
            "completed_nodes": 0,
            "last_active_node_id": None,
            "created_at": "2026-08-01T12:00:00+00:00",
            "updated_at": "2026-08-01T12:00:00+00:00",
            "nodes": [],
        },
        "generation": {
            "id": "job-1",
            "session_id": "session-1",
            "stage": "INITIALIZING",
            "web_search_requested": True,
            "grounding_status": "PENDING",
            "counts": {
                "topics_total": 0,
                "briefs_ready": 0,
                "topics_ready": 0,
                "topics_failed": 0,
                "research_sections": 0,
                "sources": 0,
            },
            "warnings": [],
            "cancel_requested": False,
            "can_cancel": True,
            "can_resume": False,
            "last_event_id": 1,
            "created_at": "2026-08-01T12:00:00+00:00",
            "updated_at": "2026-08-01T12:00:00+00:00",
        },
    }


class GenerationApiTests(unittest.TestCase):
    """Tests accepted-shell route and runtime context boundary."""

    def test_generate_returns_202_before_job_finishes_without_secrets(self) -> None:
        app = FastAPI()
        runtime = SimpleNamespace(start=AsyncMock(return_value=_accepted()))
        app.state.generation_runtime = runtime
        app.include_router(router)
        app.dependency_overrides[get_llm_context] = lambda: make_test_llm_context(
            api_key="llm-secret",
            model="test/model",
        )
        with TestClient(app) as client:
            response = client.post(
                "/learning/generate",
                json={"query": "Modern CSS", "mode": "auto"},
                headers={
                    "X-Web-Search": "true",
                    "X-Web-Search-Providers": "tavily",
                    "X-Tavily-Key": "search-secret",
                },
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), _accepted())
        self.assertNotIn("llm-secret", response.text)
        self.assertNotIn("search-secret", response.text)
        call = runtime.start.await_args.kwargs
        self.assertEqual(call["llm_context"].get_api_key(), "llm-secret")
        self.assertEqual(
            call["search_context"].get_api_key(call["search_context"].provider_ids[0]),
            "search-secret",
        )

    def test_invalid_mode_still_returns_422_without_starting_job(self) -> None:
        app = FastAPI()
        runtime = SimpleNamespace(start=AsyncMock())
        app.state.generation_runtime = runtime
        app.include_router(router)
        app.dependency_overrides[get_llm_context] = lambda: make_test_llm_context(
            api_key="llm-key",
            model="test/model",
        )
        with TestClient(app) as client:
            response = client.post(
                "/learning/generate",
                json={"query": "Topic", "mode": "turbo"},
            )
        self.assertEqual(response.status_code, 422)
        runtime.start.assert_not_awaited()

    def test_delete_calls_mongo_style_adelete_thread(self) -> None:
        checkpointer = SimpleNamespace(adelete_thread=AsyncMock())
        runtime = SimpleNamespace(stop_for_delete=AsyncMock())
        app = FastAPI()
        app.state.generation_runtime = runtime
        app.state.checkpointer = checkpointer
        app.include_router(router)
        with (
            patch(
                "server.routers.learning.learning_manager.get_learning_session",
                return_value={"id": "s1"},
            ),
            patch(
                "server.routers.learning.learning_manager.delete_learning_session",
                return_value=True,
            ),
        ):
            with TestClient(app) as client:
                response = client.delete("/learning/sessions/s1")
        self.assertEqual(response.status_code, 200)
        checkpointer.adelete_thread.assert_awaited_once_with("gen-s1")


class ResearchApiTests(unittest.TestCase):
    """Tests public research report projection."""

    def test_web_off_returns_not_requested_report(self) -> None:
        app = FastAPI()
        app.include_router(router)
        app.state.generation_runtime = SimpleNamespace()
        with (
            patch(
                "server.routers.learning.learning_manager.get_learning_session",
                return_value={"id": "session-1"},
            ),
            patch(
                "server.routers.learning.generation_job_store.get_by_session",
                return_value=SimpleNamespace(web_search_requested=False),
            ),
        ):
            with TestClient(app) as client:
                response = client.get(
                    "/learning/sessions/session-1/research"
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "NOT_REQUESTED")
        self.assertEqual(response.json()["sections"], [])
        self.assertEqual(response.json()["sources"], [])

    def test_report_response_omits_private_and_secret_fields(self) -> None:
        public_report = {
            "id": "report-1",
            "session_id": "session-1",
            "status": "DEGRADED",
            "summary": "Partial current research.",
            "limitations": ["Provider unavailable."],
            "freshness_note": "Retrieved 2026-08-01.",
            "sections": [],
            "sources": [
                {
                    "id": "source-1",
                    "title": "Current docs",
                    "url": "https://example.com/docs",
                    "publisher": "Example",
                    "published_at": None,
                    "retrieved_at": "2026-08-01T00:00:00+00:00",
                    "provider_id": "tavily",
                    "snippet": "Current docs.",
                    "excerpt": "Current evidence.",
                    "relevance_score": 0.9,
                }
            ],
            "provider_statuses": [],
            "warnings": [],
            "created_at": "2026-08-01T00:00:00+00:00",
            "updated_at": "2026-08-01T00:00:00+00:00",
        }
        app = FastAPI()
        app.include_router(router)
        with (
            patch(
                "server.routers.learning.learning_manager.get_learning_session",
                return_value={"id": "session-1"},
            ),
            patch(
                "server.routers.learning.generation_job_store.get_by_session",
                return_value=SimpleNamespace(web_search_requested=True),
            ),
            patch(
                "server.routers.learning.research_store.get_public_report",
                return_value=public_report,
            ),
        ):
            with TestClient(app) as client:
                response = client.get(
                    "/learning/sessions/session-1/research"
                )
        self.assertEqual(response.status_code, 200)
        rendered = response.text.lower()
        self.assertNotIn("canonical_url", rendered)
        self.assertNotIn("content_hash", rendered)
        self.assertNotIn("brief", rendered)
        self.assertNotIn("api_key", rendered)


if __name__ == "__main__":
    unittest.main()
