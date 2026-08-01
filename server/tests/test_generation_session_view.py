"""
============================================================================
FILE: test_generation_session_view.py
LOCATION: server/tests/test_generation_session_view.py
============================================================================
PURPOSE:
    Tests polling snapshots across shell, TOC, preview, batch, and degraded stages.
ROLE IN PROJECT:
    Makes two-second polling a complete repair/fallback channel for SSE clients.
KEY COMPONENTS:
    - GenerationSessionViewTests: Session and node public projection tests
DEPENDENCIES:
    - External: fastapi, unittest, unittest.mock
    - Internal: server.routers.learning
USAGE:
    python -m unittest server.tests.test_generation_session_view -v
============================================================================
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from server.routers.learning import get_learning_session


class GenerationSessionViewTests(unittest.TestCase):
    """Tests progressive session polling projection."""

    def test_shell_and_skeletons_include_generation_but_not_briefs(self) -> None:
        manager = MagicMock()
        manager.get_learning_session.return_value = {
            "id": "session-1",
            "user_id": None,
            "query": "Topic",
            "course_title": "Generated Course",
            "title_finalized": True,
            "mode": "full",
            "resolved_mode": "full",
            "last_active_node_id": None,
            "created_at": "2026-08-01T00:00:00+00:00",
            "updated_at": "2026-08-01T00:00:00+00:00",
            "total_nodes": 2,
            "completed_nodes": 0,
        }
        manager.get_session_nodes.return_value = [
            {
                "id": "node-1",
                "learning_session_id": "session-1",
                "sequence_index": 0,
                "title": "Topic 0",
                "content_markdown": "stored but not ready",
                "status": "LOCKED",
                "generation_status": "GENERATING",
                "error_message": None,
                "retry_available": False,
                "failed_step": None,
                "complexity": "Basic",
                "created_at": "2026-08-01T00:00:00+00:00",
                "updated_at": "2026-08-01T00:00:00+00:00",
                "quiz": None,
            },
            {
                "id": "node-2",
                "learning_session_id": "session-1",
                "sequence_index": 1,
                "title": "Topic 1",
                "content_markdown": "",
                "status": "LOCKED",
                "generation_status": "SKELETON",
                "error_message": None,
                "retry_available": False,
                "failed_step": None,
                "complexity": "Intermediate",
                "created_at": "2026-08-01T00:00:00+00:00",
                "updated_at": "2026-08-01T00:00:00+00:00",
                "quiz": None,
            },
        ]
        jobs = MagicMock()
        jobs.to_public_by_session.return_value = {
            "id": "job-1",
            "session_id": "session-1",
            "stage": "GENERATING_PREVIEW",
            "web_search_requested": False,
            "grounding_status": "DISABLED",
            "counts": {
                "topics_total": 2,
                "briefs_ready": 2,
                "topics_ready": 0,
                "topics_failed": 0,
                "research_sections": 0,
                "sources": 0,
            },
            "warnings": [],
            "cancel_requested": False,
            "can_cancel": True,
            "can_resume": False,
            "last_event_id": 3,
            "created_at": "2026-08-01T00:00:00+00:00",
            "updated_at": "2026-08-01T00:00:00+00:00",
        }
        research = MagicMock()
        research.get_citations_by_session.return_value = {}
        with (
            patch("server.routers.learning.learning_manager", manager),
            patch("server.routers.learning.generation_job_store", jobs),
            patch("server.routers.learning.research_store", research),
        ):
            response = get_learning_session("session-1")
        payload = response.model_dump(mode="json")
        self.assertEqual(payload["generation"]["stage"], "GENERATING_PREVIEW")
        self.assertEqual(payload["nodes"][0]["module_status"], "GENERATING")
        self.assertEqual(payload["nodes"][0]["content_markdown"], "")
        # Substring "brief" appears in counts.briefs_ready; check field keys only.
        self.assertNotIn("brief", payload)
        self.assertNotIn("brief", payload["nodes"][0])
        self.assertNotIn("source_excerpts", payload)
        self.assertNotIn("source_excerpts", payload["nodes"][0])


if __name__ == "__main__":
    unittest.main()
