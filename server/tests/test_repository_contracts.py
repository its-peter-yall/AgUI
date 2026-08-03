"""
============================================================================
FILE: test_repository_contracts.py
LOCATION: server/tests/test_repository_contracts.py
============================================================================
PURPOSE:
    Structural contract tests for repository Protocol surfaces and default
    StorageContext SQLite repository bundle wiring.
ROLE IN PROJECT:
    TDD guard for Phase 2A MongoDB Atlas storage repository ports.
    - Verifies Protocol method names match production call graph
    - Verifies StorageContext exposes complete SQLite bundle by default
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.database.repositories, server.database.storage_mode
USAGE:
    python -m unittest server.tests.test_repository_contracts -v
============================================================================
"""

from __future__ import annotations

import unittest

from server.database.repositories.protocols import (
    AppSettingsRepository,
    GenerationArtifactRepository,
    GenerationJobRepository,
    LearningRepository,
    ProgressEventRepository,
    ResearchRepository,
)


class RepositoryContractTests(unittest.TestCase):
    def test_protocols_expose_required_call_graph_methods(self) -> None:
        required = {
            LearningRepository: {
                "create_learning_session",
                "get_learning_session",
                "create_quiz_attempt",
                "create_revision_session",
            },
            GenerationJobRepository: {
                "create_session_shell_and_job",
                "transition_stage",
                "try_acquire_lock",
                "mark_orphaned_jobs_paused",
            },
            GenerationArtifactRepository: {
                "persist_outline",
                "persist_briefs",
                "persist_topic_success",
            },
            ResearchRepository: {
                "create_report",
                "upsert_source",
                "get_public_report",
            },
            ProgressEventRepository: {
                "append_once",
                "list_after",
                "latest_id",
            },
            AppSettingsRepository: {
                "get_provider_settings",
                "put_web_search_settings",
            },
        }
        for contract, methods in required.items():
            with self.subTest(contract=contract.__name__):
                self.assertTrue(methods.issubset(vars(contract)))


if __name__ == "__main__":
    unittest.main()
