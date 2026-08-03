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
from pathlib import Path
from unittest.mock import MagicMock

from server.database.repositories.protocols import (
    AppSettingsRepository,
    GenerationArtifactRepository,
    GenerationJobRepository,
    LearningRepository,
    ProgressEventRepository,
    ResearchRepository,
)
from server.database.repositories.sqlite import build_sqlite_bundle
from server.database.storage_mode import DeploymentMode, StorageContext


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

    def test_context_exposes_sqlite_bundle_by_default(self) -> None:
        stores = {
            "learning": MagicMock(),
            "jobs": MagicMock(),
            "artifacts": MagicMock(),
            "research": MagicMock(),
            "progress": MagicMock(),
        }
        bundle = build_sqlite_bundle(**stores)
        context = StorageContext(
            deployment_mode=DeploymentMode.LOCAL,
            sqlite_path=Path("unused.db"),
            sqlite_repositories=bundle,
        )

        self.assertIs(context.learning, bundle.learning)
        self.assertIs(context.jobs, bundle.jobs)
        self.assertIs(context.artifacts, bundle.artifacts)
        self.assertIs(context.research, bundle.research)
        self.assertIs(context.progress, bundle.progress)


if __name__ == "__main__":
    unittest.main()
