"""
============================================================================
FILE: storage_registry.py
LOCATION: server/database/storage_registry.py
============================================================================
PURPOSE:
    Process-wide storage context, SQLite store singletons, and repository
    facade aliases resolved on every call.
ROLE IN PROJECT:
    Single owner of active repository bundle for Approach A backend swap.
    - Constructs SQLite stores once and wraps them via build_sqlite_bundle
    - Exposes late-bound facades so routers/graph/services need no re-import
KEY COMPONENTS:
    - storage_context: Process StorageContext (default SQLite)
    - learning_repository / generation_* / research / progress facades
    - initialize_sqlite_storage: Local backup schema init
DEPENDENCIES:
    - External: None
    - Internal: server.config, server.database stores, repositories, storage_mode
USAGE:
    from server.database.storage_registry import (
        learning_repository as learning_manager,
        initialize_sqlite_storage,
        storage_context,
    )
============================================================================
"""

from __future__ import annotations

import os
from typing import cast

from server.database.generation_artifacts import GenerationArtifactStore
from server.database.generation_jobs import GenerationJobStore
from server.database.generation_migrations import (
    initialize_generation_schema,
)
from server.database.learning_persistence import LearningManager
from server.database.persistence import DB_PATH
from server.database.progress_events import ProgressEventStore
from server.database.repositories.facade import RepositoryFacade
from server.database.repositories.protocols import (
    GenerationArtifactRepository,
    GenerationJobRepository,
    LearningRepository,
    ProgressEventRepository,
    ResearchRepository,
)
from server.database.repositories.sqlite import build_sqlite_bundle
from server.database.research_store import ResearchStore
from server.database.storage_mode import DeploymentMode, StorageContext


def _resolve_deployment_mode() -> DeploymentMode:
    """Read deployment mode without importing server.config (cycle-safe)."""
    raw = os.getenv("DEPLOYMENT_MODE", "local").strip().lower()
    try:
        return DeploymentMode(raw)
    except ValueError as exc:
        raise RuntimeError(
            "DEPLOYMENT_MODE must be local or cloud"
        ) from exc


sqlite_learning_store = LearningManager(DB_PATH)
sqlite_job_store = GenerationJobStore(DB_PATH)
sqlite_artifact_store = GenerationArtifactStore(DB_PATH)
sqlite_research_store = ResearchStore(DB_PATH)
sqlite_progress_store = ProgressEventStore(DB_PATH)

sqlite_repositories = build_sqlite_bundle(
    learning=sqlite_learning_store,
    jobs=sqlite_job_store,
    artifacts=sqlite_artifact_store,
    research=sqlite_research_store,
    progress=sqlite_progress_store,
)

storage_context = StorageContext(
    deployment_mode=_resolve_deployment_mode(),
    sqlite_path=DB_PATH,
    sqlite_repositories=sqlite_repositories,
)

learning_repository = cast(
    LearningRepository,
    RepositoryFacade(lambda: storage_context.learning),
)
generation_job_repository = cast(
    GenerationJobRepository,
    RepositoryFacade(lambda: storage_context.jobs),
)
generation_artifact_repository = cast(
    GenerationArtifactRepository,
    RepositoryFacade(lambda: storage_context.artifacts),
)
research_repository = cast(
    ResearchRepository,
    RepositoryFacade(lambda: storage_context.research),
)
progress_event_repository = cast(
    ProgressEventRepository,
    RepositoryFacade(lambda: storage_context.progress),
)


def initialize_sqlite_storage() -> None:
    """Initialize local backup regardless of active cloud target."""

    sqlite_learning_store.init_learning_tables()
    initialize_generation_schema(DB_PATH)
