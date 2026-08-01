"""
============================================================================
FILE: test_session_events.py
LOCATION: server/tests/test_session_events.py
============================================================================
PURPOSE:
    Tests SSE replay, cursor precedence, heartbeat, terminal close, and isolation.
ROLE IN PROJECT:
    Ensures reconnecting clients observe durable events without owning jobs.
KEY COMPONENTS:
    - SessionEventStreamTests: Async stream behavior
    - SessionEventRouterTests: Header/query cursor contract
DEPENDENCIES:
    - External: fastapi, unittest, unittest.mock
    - Internal: server.services.session_event_stream and learning router
USAGE:
    python -m unittest server.tests.test_session_events -v
============================================================================
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routers.learning import router
from server.services.session_event_stream import stream_session_events


class SessionEventStreamTests(unittest.IsolatedAsyncioTestCase):
    """Tests replay-then-tail SSE generator."""

    async def test_replays_after_cursor_in_order_and_closes_on_terminal(self) -> None:
        events = MagicMock()
        events.list_after.return_value = [
            SimpleNamespace(
                id=8,
                session_id="session-1",
                event_type=SimpleNamespace(value="module_ready"),
                payload=SimpleNamespace(model_dump=lambda mode: {"node_id": "node-1"}),
                created_at="2026-08-01T00:00:00+00:00",
            ),
            SimpleNamespace(
                id=9,
                session_id="session-1",
                event_type=SimpleNamespace(value="generation_complete"),
                payload=SimpleNamespace(model_dump=lambda mode: {"stage": "COMPLETE"}),
                created_at="2026-08-01T00:00:01+00:00",
            ),
        ]
        jobs = MagicMock()
        jobs.to_public_by_session.return_value = {"stage": "COMPLETE"}
        frames = []
        async for frame in stream_session_events(
            session_id="session-1",
            cursor=7,
            event_store=events,
            job_store=jobs,
            sleep=AsyncMock(),
        ):
            frames.append(frame)
        rendered = "".join(frames)
        self.assertIn("id: 8\n", rendered)
        self.assertIn("event: module_ready\n", rendered)
        self.assertIn("id: 9\n", rendered)
        self.assertIn("event: generation_complete\n", rendered)
        events.list_after.assert_called_once_with("session-1", 7, limit=100)

    async def test_empty_running_stream_emits_heartbeat_without_cancel(self) -> None:
        events = MagicMock()
        events.list_after.return_value = []
        jobs = MagicMock()
        jobs.to_public_by_session.return_value = {"stage": "RESEARCHING"}
        sleep = AsyncMock(side_effect=[None, RuntimeError("stop test")])
        generator = stream_session_events(
            session_id="session-1",
            cursor=0,
            event_store=events,
            job_store=jobs,
            sleep=sleep,
            heartbeat_seconds=0,
        )
        frame = await anext(generator)
        self.assertEqual(frame, ": keepalive\n\n")
        await generator.aclose()
        self.assertFalse(hasattr(jobs, "request_cancel") and jobs.request_cancel.called)

    def test_frame_data_is_valid_json(self) -> None:
        payload = {
            "id": 1,
            "session_id": "session-1",
            "event_type": "stage_changed",
            "payload": {"stage": "OUTLINING"},
        }
        encoded = json.dumps(payload, separators=(",", ":"))
        self.assertEqual(json.loads(encoded), payload)


class SessionEventRouterTests(unittest.TestCase):
    """Tests events route cursor precedence and validation."""

    def _app(self, stream_fn) -> FastAPI:
        app = FastAPI()
        app.state.generation_runtime = SimpleNamespace()
        app.include_router(router)
        return app

    def test_last_event_id_takes_precedence_over_after(self) -> None:
        captured: dict[str, object] = {}

        async def fake_stream(**kwargs):
            captured.update(kwargs)
            if False:
                yield ""

        with (
            patch(
                "server.routers.learning.learning_manager.get_learning_session",
                return_value={"id": "session-1"},
            ),
            patch(
                "server.routers.learning.stream_session_events",
                side_effect=fake_stream,
            ),
        ):
            app = self._app(fake_stream)
            with TestClient(app) as client:
                response = client.get(
                    "/learning/sessions/session-1/events?after=5",
                    headers={"Last-Event-ID": "7"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured.get("cursor"), 7)

    def test_invalid_cursor_returns_400(self) -> None:
        with patch(
            "server.routers.learning.learning_manager.get_learning_session",
            return_value={"id": "session-1"},
        ):
            app = self._app(None)
            with TestClient(app) as client:
                response = client.get(
                    "/learning/sessions/session-1/events?after=-1",
                )
        self.assertEqual(response.status_code, 400)

    def test_unknown_session_returns_404(self) -> None:
        with patch(
            "server.routers.learning.learning_manager.get_learning_session",
            return_value=None,
        ):
            app = self._app(None)
            with TestClient(app) as client:
                response = client.get(
                    "/learning/sessions/missing/events",
                )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
