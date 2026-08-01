"""
============================================================================
FILE: test_generation_security_acceptance.py
LOCATION: server/tests/test_generation_security_acceptance.py
============================================================================
PURPOSE:
    Verifies retained recovery, SSE replay, duplicate fencing, and absence of
    request secrets from every persisted, public, and logged surface.
ROLE IN PROJECT:
    Supplies final security and durability acceptance gates for generation.
KEY COMPONENTS:
    - GenerationRecoverySecurityAcceptanceTests: Recovery and secret audits
    - SafeLoggingTests: External exception-message suppression
DEPENDENCIES:
    - External: unittest
    - Internal: acceptance harness, safe logging
USAGE:
    python -m unittest server.tests.test_generation_security_acceptance -v
============================================================================
"""

from __future__ import annotations

import logging
import unittest

from server.tests.generation_acceptance_harness import (
    GenerationAcceptanceHarness,
    RecoveryScenario,
)
from server.utils.safe_logging import log_external_failure


LLM_CANARY = "llm-canary-7d45f2"
SEARCH_CANARY = "search-canary-a91c0e"


class GenerationRecoverySecurityAcceptanceTests(
    unittest.IsolatedAsyncioTestCase
):
    """Tests durable recovery and secret isolation across process boundaries."""

    async def asyncSetUp(self) -> None:
        self.harness = await GenerationAcceptanceHarness.create()

    async def asyncTearDown(self) -> None:
        await self.harness.close()

    async def test_cancel_restart_resume_keeps_ids_and_avoids_duplicates(
        self,
    ) -> None:
        result = await self.harness.run_recovery(
            RecoveryScenario(
                topic_count=14,
                web_search=True,
                cancel_after_ready=3,
                llm_key=LLM_CANARY,
                search_key=SEARCH_CANARY,
            )
        )

        # C4: abrupt restart without user cancel → PAUSED (not CANCELLED).
        self.assertNotEqual(result.cancelled_stage, "CANCELLED")
        self.assertEqual(result.stage_after_restart, "PAUSED")
        self.assertIn(result.terminal_stage, {"COMPLETE", "COMPLETE_DEGRADED"})
        self.assertEqual(result.thread_ids, [result.thread_ids[0]] * 3)
        self.assertEqual(result.node_ids_before, result.node_ids_after[: len(result.node_ids_before)])
        self.assertEqual(len(result.node_ids_after), 14)
        self.assertEqual(len(set(result.node_ids_after)), 14)
        self.assertEqual(
            len(result.event_dedupe_keys),
            len(set(result.event_dedupe_keys)),
        )
        self.assertTrue(result.fresh_credentials_used_on_resume)

    async def test_sse_disconnect_does_not_cancel_and_reconnect_replays_gap(
        self,
    ) -> None:
        result = await self.harness.run_sse_reconnect(topic_count=13)

        self.assertTrue(result.task_running_after_disconnect)
        self.assertEqual(result.terminal_stage, "COMPLETE")
        self.assertTrue(result.replayed_event_ids)
        self.assertTrue(
            all(
                event_id > result.disconnect_cursor
                for event_id in result.replayed_event_ids
            )
        )
        self.assertEqual(
            result.replayed_event_ids,
            sorted(set(result.replayed_event_ids)),
        )
        self.assertEqual(
            result.polling_last_event_id,
            result.replayed_event_ids[-1],
        )

    async def test_duplicate_resume_is_fenced_without_duplicate_work(self) -> None:
        result = await self.harness.run_duplicate_resume(topic_count=4)

        self.assertEqual(result.accepted_resumes, 1)
        self.assertEqual(result.conflicting_resumes, 1)
        self.assertEqual(len(result.node_ids), len(set(result.node_ids)))
        self.assertEqual(
            len(result.event_dedupe_keys),
            len(set(result.event_dedupe_keys)),
        )

    async def test_canary_secrets_are_absent_from_all_surfaces(self) -> None:
        surfaces = await self.harness.audit_secret_surfaces(
            llm_key=LLM_CANARY,
            search_key=SEARCH_CANARY,
            provider_error=f"transport failed for {SEARCH_CANARY}",
        )

        expected_names = {
            "database_dump",
            "checkpoint_bytes",
            "event_json",
            "research_json",
            "session_json",
            "sse_frames",
            "http_error_json",
            "captured_logs",
        }
        self.assertEqual(set(surfaces), expected_names)
        for name, value in surfaces.items():
            with self.subTest(surface=name):
                self.assertNotIn(LLM_CANARY, value)
                self.assertNotIn(SEARCH_CANARY, value)


class SafeLoggingTests(unittest.TestCase):
    """Tests fixed-shape logging for untrusted external exceptions."""

    def test_external_exception_message_and_traceback_are_not_logged(self) -> None:
        logger = logging.getLogger("generation-safe-log-test")
        with self.assertLogs(logger, level="ERROR") as captured:
            log_external_failure(
                logger,
                event="generation_failed",
                session_id="session-1",
                error=RuntimeError(f"{LLM_CANARY}:{SEARCH_CANARY}"),
            )

        rendered = "\n".join(captured.output)
        self.assertIn("error_type=RuntimeError", rendered)
        self.assertIn("session_id=session-1", rendered)
        self.assertNotIn(LLM_CANARY, rendered)
        self.assertNotIn(SEARCH_CANARY, rendered)
        self.assertNotIn("Traceback", rendered)


if __name__ == "__main__":
    unittest.main()
