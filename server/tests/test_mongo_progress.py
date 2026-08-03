"""
============================================================================
FILE: test_mongo_progress.py
LOCATION: server/tests/test_mongo_progress.py
============================================================================
PURPOSE:
    Unit tests for Mongo progress event repository counter and dedupe.
ROLE IN PROJECT:
    Phase 3B coverage for mongo_progress without live Atlas.
KEY COMPONENTS:
    - MongoProgressTests: monotonic IDs and duplicate payload handling
DEPENDENCIES:
    - External: unittest, unittest.mock, pymongo
    - Internal: server.database.repositories.mongo_progress,
                server.schemas.progress
USAGE:
    python -m unittest server.tests.test_mongo_progress -v
============================================================================
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from pymongo.errors import DuplicateKeyError

from server.database.repositories.mongo_progress import (
    MongoProgressEventRepository,
)
from server.schemas.generation import GenerationStage
from server.schemas.progress import ProgressEventType, StageChangedPayload


def make_stage_payload() -> StageChangedPayload:
    return StageChangedPayload(
        previous_stage=GenerationStage.INITIALIZING,
        stage=GenerationStage.OUTLINING,
    )


def make_event_document() -> dict:
    return {
        "_id": 1,
        "session_id": "s1",
        "event_type": ProgressEventType.STAGE_CHANGED.value,
        "payload": make_stage_payload().model_dump(mode="json"),
        "dedupe_key": "stage:1",
        "created_at": "2026-08-03T00:00:00+00:00",
    }


class MongoProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events = MagicMock()
        self.counters = MagicMock()
        self.jobs = MagicMock()
        self.database = MagicMock()
        self.database.__getitem__.side_effect = lambda name: {
            "progress_events": self.events,
            "storage_counters": self.counters,
            "generation_jobs": self.jobs,
        }[name]
        self.repository = MongoProgressEventRepository(self.database)

    def test_append_allocates_monotonic_integer_id(self) -> None:
        self.events.find_one.return_value = None
        self.counters.find_one_and_update.return_value = {
            "_id": "progress_events",
            "value": 42,
        }
        event = self.repository.append_once(
            session_id="s1",
            event_type=ProgressEventType.STAGE_CHANGED,
            payload=make_stage_payload(),
            dedupe_key="stage:1",
        )
        inserted = self.events.insert_one.call_args.args[0]
        self.assertEqual(inserted["_id"], 42)
        self.assertEqual(event.id, 42)

    def test_duplicate_equal_payload_returns_existing_event(self) -> None:
        # Race path: first find misses, insert hits unique, second find hits.
        self.events.find_one.side_effect = [
            None,
            make_event_document(),
        ]
        self.counters.find_one_and_update.return_value = {
            "_id": "progress_events",
            "value": 2,
        }
        self.events.insert_one.side_effect = DuplicateKeyError("duplicate")
        event = self.repository.append_once(
            session_id="s1",
            event_type=ProgressEventType.STAGE_CHANGED,
            payload=make_stage_payload(),
            dedupe_key="stage:1",
        )
        self.assertEqual(event.id, 1)

    def test_dedupe_hit_finds_existing_before_counter_increment(
        self,
    ) -> None:
        """H6: pure dedupe must not burn monotonic counter IDs."""
        self.events.find_one.return_value = make_event_document()
        event = self.repository.append_once(
            session_id="s1",
            event_type=ProgressEventType.STAGE_CHANGED,
            payload=make_stage_payload(),
            dedupe_key="stage:1",
        )
        self.assertEqual(event.id, 1)
        self.counters.find_one_and_update.assert_not_called()
        self.events.insert_one.assert_not_called()


if __name__ == "__main__":
    unittest.main()
