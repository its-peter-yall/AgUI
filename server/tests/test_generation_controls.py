"""
============================================================================
FILE: test_generation_controls.py
LOCATION: server/tests/test_generation_controls.py
============================================================================
PURPOSE:
    Tests retained cancellation, fresh-credential resume, and permanent delete.
ROLE IN PROJECT:
    Separates cooperative stop from explicit irreversible cleanup.
KEY COMPONENTS:
    - GenerationControlTests: Cancel, resume conflict, credential, delete tests
DEPENDENCIES:
    - External: fastapi, unittest, unittest.mock
    - Internal: server.routers.learning and generation runtime
USAGE:
    python -m unittest server.tests.test_generation_controls -v
============================================================================
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routers.learning import router
from server.schemas.llm import get_llm_context
from server.tests.llm_test_helpers import make_test_llm_context


def _client(runtime) -> TestClient:
    app = FastAPI()
    app.state.generation_runtime = runtime
    app.state.checkpointer = SimpleNamespace(adelete_thread=AsyncMock())
    app.include_router(router)
    app.dependency_overrides[get_llm_context] = lambda: make_test_llm_context(
        api_key="fresh-llm-key",
        model="test/model",
    )
    return TestClient(app)


class GenerationControlTests(unittest.TestCase):
    """Tests cancel/resume/delete HTTP semantics."""

    def test_cancel_returns_202_and_does_not_delete_partial_artifacts(self) -> None:
        runtime = SimpleNamespace(
            cancel=AsyncMock(return_value={"generation": {"stage": "RESEARCHING"}})
        )
        with (
            patch(
                "server.routers.learning.learning_manager.get_learning_session",
                return_value={"id": "session-1"},
            ),
            patch(
                "server.routers.learning.learning_manager.delete_learning_session"
            ) as delete,
        ):
            with _client(runtime) as client:
                response = client.post(
                    "/learning/sessions/session-1/cancel"
                )
        self.assertEqual(response.status_code, 202)
        runtime.cancel.assert_awaited_once_with("session-1")
        delete.assert_not_called()

    def test_resume_passes_fresh_context_and_returns_202(self) -> None:
        runtime = SimpleNamespace(
            resume=AsyncMock(
                return_value={"generation": {"stage": "RESEARCHING"}}
            )
        )
        with patch(
            "server.routers.learning.learning_manager.get_learning_session",
            return_value={"id": "session-1"},
        ):
            with _client(runtime) as client:
                response = client.post(
                    "/learning/sessions/session-1/resume",
                    headers={
                        "X-Web-Search": "true",
                        "X-Web-Search-Providers": "exa",
                        "X-Exa-Key": "fresh-search-key",
                    },
                )
        self.assertEqual(response.status_code, 202)
        call = runtime.resume.await_args.kwargs
        self.assertEqual(call["llm_context"].get_api_key(), "fresh-llm-key")
        self.assertEqual(
            call["search_context"].get_api_key(
                call["search_context"].provider_ids[0]
            ),
            "fresh-search-key",
        )

    def test_duplicate_resume_maps_to_409(self) -> None:
        from server.graph.runner import GenerationAlreadyRunning

        runtime = SimpleNamespace(
            resume=AsyncMock(side_effect=GenerationAlreadyRunning("session-1"))
        )
        with patch(
            "server.routers.learning.learning_manager.get_learning_session",
            return_value={"id": "session-1"},
        ):
            with _client(runtime) as client:
                response = client.post(
                    "/learning/sessions/session-1/resume"
                )
        self.assertEqual(response.status_code, 409)

    def test_delete_is_only_endpoint_that_removes_session(self) -> None:
        runtime = SimpleNamespace(stop_for_delete=AsyncMock())
        with (
            patch(
                "server.routers.learning.learning_manager.get_learning_session",
                return_value={"id": "session-1"},
            ),
            patch(
                "server.routers.learning.learning_manager.delete_learning_session",
                return_value=True,
            ) as delete,
        ):
            with _client(runtime) as client:
                response = client.delete(
                    "/learning/sessions/session-1"
                )
        self.assertEqual(response.status_code, 200)
        runtime.stop_for_delete.assert_awaited_once_with("session-1")
        delete.assert_called_once_with("session-1")


if __name__ == "__main__":
    unittest.main()
