"""
============================================================================
FILE: test_mongo_learning.py
LOCATION: server/tests/test_mongo_learning.py
============================================================================
PURPOSE:
    Critical Mongo learning repository CRUD tests using mocked collections.
ROLE IN PROJECT:
    Phase 3A parity coverage for MongoLearningRepository without live Atlas.
KEY COMPONENTS:
    - MongoLearningTests: session, node, quiz, revision, cascade tests
DEPENDENCIES:
    - External: unittest, unittest.mock, pymongo
    - Internal: server.database.repositories.mongo_learning,
                server.schemas.learning
USAGE:
    python -m unittest server.tests.test_mongo_learning -v
============================================================================
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from pymongo import ReturnDocument

from server.database.repositories.mongo_learning import (
    MongoLearningRepository,
)
from server.schemas.learning import (
    NodeStatus,
    QuizCard,
    QuizOption,
    QuizSet,
)


NOW = datetime(2026, 8, 3, tzinfo=timezone.utc)


def make_quiz_set() -> QuizSet:
    return QuizSet(
        quizzes=[
            QuizCard(
                question_text="q",
                options=[
                    QuizOption(
                        option_id="option-1",
                        display_label="A",
                        text="t1",
                        is_correct=True,
                        explanation="e1",
                    ),
                    QuizOption(
                        option_id="option-2",
                        display_label="B",
                        text="t2",
                        is_correct=False,
                        explanation="e2",
                    ),
                    QuizOption(
                        option_id="option-3",
                        display_label="C",
                        text="t3",
                        is_correct=False,
                        explanation="e3",
                    ),
                    QuizOption(
                        option_id="option-4",
                        display_label="D",
                        text="t4",
                        is_correct=False,
                        explanation="e4",
                    ),
                ],
            )
        ]
    )


class MongoLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = MagicMock()
        self.collections: dict[str, MagicMock] = {}

        def get_collection(name: str) -> MagicMock:
            if name not in self.collections:
                self.collections[name] = MagicMock(name=name)
            return self.collections[name]

        self.database.__getitem__.side_effect = get_collection
        self.repository = MongoLearningRepository(self.database)

    @patch("server.database.repositories.mongo_learning.uuid.uuid4")
    def test_create_session_uses_string_id_and_api_shape(
        self,
        uuid4: MagicMock,
    ) -> None:
        uuid4.return_value = "session-1"
        with patch(
            "server.database.repositories.mongo_learning.utc_iso",
            return_value="2026-08-03T00:00:00+00:00",
        ):
            result = self.repository.create_learning_session(
                "query",
                "Course",
                mode="auto",
            )

        inserted = self.database["learning_sessions"].insert_one.call_args.args[0]
        self.assertEqual(inserted["_id"], "session-1")
        self.assertEqual(result["id"], "session-1")
        self.assertNotIn("_id", result)

    def test_get_sessions_list_uses_safe_sort_and_pagination(self) -> None:
        collection = self.database["learning_sessions"]
        collection.count_documents.return_value = 1
        cursor = collection.find.return_value
        cursor.sort.return_value.skip.return_value.limit.return_value = [
            {"_id": "s1", "query": "q"}
        ]

        sessions, total = self.repository.get_sessions_list(
            None,
            sort_by="unknown",
            sort_order="asc",
            limit=20,
            offset=2,
        )

        cursor.sort.assert_called_once_with("updated_at", 1)
        self.assertEqual(total, 1)
        self.assertEqual(sessions[0]["id"], "s1")

    def test_node_status_update_uses_current_status_compare(self) -> None:
        nodes = self.database["concept_nodes"]
        nodes.count_documents.return_value = 0
        nodes.find_one.return_value = {
            "_id": "n1",
            "status": NodeStatus.LOCKED.value,
        }
        nodes.find_one_and_update.return_value = {
            "_id": "n1",
            "status": NodeStatus.VIEWING_EXPLANATION.value,
            "learning_session_id": "s1",
        }

        result = self.repository.update_node_status(
            "n1",
            NodeStatus.VIEWING_EXPLANATION,
        )

        query = nodes.find_one_and_update.call_args.args[0]
        self.assertEqual(
            query,
            {"_id": "n1", "status": NodeStatus.LOCKED.value},
        )
        self.assertEqual(
            nodes.find_one_and_update.call_args.kwargs["return_document"],
            ReturnDocument.AFTER,
        )
        self.assertEqual(result["id"], "n1")

    def test_create_quiz_set_stores_native_payload(self) -> None:
        quiz_set = make_quiz_set()
        self.repository.create_quiz_set("n1", quiz_set, "seed")
        update = self.database["quiz_data"].replace_one.call_args.args[1]
        self.assertIsInstance(update["payload"], dict)
        self.assertEqual(update["format_version"], 1)
        self.assertEqual(update["shuffle_seed"], "seed")

    def test_create_attempt_uses_next_attempt_number(self) -> None:
        attempts = self.database["quiz_attempts"]
        attempts.count_documents.return_value = 2
        self.database["concept_nodes"].find_one.return_value = {
            "_id": "n1",
            "learning_session_id": "s1",
        }
        self.database["quiz_data"].find_one.return_value = {
            "node_id": "n1",
            "payload": make_quiz_set().model_dump(mode="json"),
            "format_version": 1,
            "current_index": 0,
        }
        result = self.repository.create_quiz_attempt(
            "n1",
            ["option-1"],
        )
        inserted = attempts.insert_one.call_args.args[0]
        self.assertEqual(inserted["attempt_number"], 3)
        self.assertEqual(inserted["selected_option_id"], ["option-1"])
        self.assertEqual(result["attempt_number"], 3)

    def test_create_revision_clones_all_node_progress(self) -> None:
        self.database["learning_sessions"].find_one.return_value = {
            "_id": "s1",
            "status": "completed",
        }
        self.database["revision_sessions"].count_documents.return_value = 0
        self.database["concept_nodes"].find.return_value = [
            {"_id": "n1", "title": "One", "sequence_index": 0},
            {"_id": "n2", "title": "Two", "sequence_index": 1},
        ]
        revision = self.repository.create_revision_session(
            "s1",
            "full_review",
        )
        inserts = self.database["revision_node_progress"].insert_many.call_args.args[0]
        self.assertEqual(len(inserts), 2)
        self.assertEqual(revision["revision_number"], 1)

    def test_delete_session_removes_all_dependent_documents(self) -> None:
        self.database["concept_nodes"].find.return_value = [
            {"_id": "n1"},
            {"_id": "n2"},
        ]
        self.database["revision_sessions"].find.return_value = [
            {"_id": "r1"}
        ]
        self.database["research_reports"].find.return_value = [
            {"_id": "report-1"}
        ]
        self.database["research_sections"].find.return_value = [
            {"_id": "section-1"}
        ]
        self.database["learning_sessions"].delete_one.return_value.deleted_count = 1

        deleted = self.repository.delete_learning_session("s1")

        self.assertTrue(deleted)
        self.database["quiz_data"].delete_many.assert_called_once_with(
            {"node_id": {"$in": ["n1", "n2"]}}
        )
        self.database["research_section_sources"].delete_many.assert_called_once_with(
            {"section_id": {"$in": ["section-1"]}}
        )
        self.database["progress_events"].delete_many.assert_called_once_with(
            {"session_id": "s1"}
        )


if __name__ == "__main__":
    unittest.main()

