"""
============================================================================
FILE: sqlite.py
LOCATION: server/database/repositories/sqlite.py
============================================================================
PURPOSE:
    Thin SQLite adapters that delegate repository Protocol calls to existing
    store classes, plus local app-settings unavailability and bundle builder.
ROLE IN PROJECT:
    SQLite side of ports-and-adapters for optional MongoDB Atlas storage.
    - Preserves proven LearningManager / store exception behavior
    - Keeps credentials browser-owned while SQLite is active
DEPENDENCIES:
    - External: None
    - Internal: server.database.repositories.errors,
                server.database.repositories.bundle
USAGE:
    from server.database.repositories.sqlite import build_sqlite_bundle
============================================================================
"""

from __future__ import annotations

from typing import Any

from server.database.repositories.bundle import RepositoryBundle
from server.database.repositories.errors import (
    RepositoryUnavailableError,
)


class _DelegatingRepository:
    """Forward public calls to one proven SQLite store."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


class SqliteLearningRepository(_DelegatingRepository):
    """Learning port backed by `LearningManager`."""


class SqliteGenerationJobRepository(_DelegatingRepository):
    """Generation-job port backed by `GenerationJobStore`."""


class SqliteGenerationArtifactRepository(_DelegatingRepository):
    """Artifact port backed by `GenerationArtifactStore`."""


class SqliteResearchRepository(_DelegatingRepository):
    """Research port backed by `ResearchStore`."""


class SqliteProgressEventRepository(_DelegatingRepository):
    """Progress port backed by `ProgressEventStore`."""


class LocalAppSettingsRepository:
    """Keep local-mode credentials browser-only by product contract."""

    @staticmethod
    def _unavailable() -> None:
        raise RepositoryUnavailableError(
            "App settings are browser-owned while SQLite is active"
        )

    def get_provider_settings(self) -> None:
        self._unavailable()

    def put_provider_settings(self, payload: dict[str, Any]) -> None:
        self._unavailable()

    def get_web_search_settings(self) -> None:
        self._unavailable()

    def put_web_search_settings(self, payload: dict[str, Any]) -> None:
        self._unavailable()


def build_sqlite_bundle(
    *,
    learning: Any,
    jobs: Any,
    artifacts: Any,
    research: Any,
    progress: Any,
) -> RepositoryBundle:
    """Wrap existing SQLite stores into a complete repository bundle."""
    return RepositoryBundle(
        learning=SqliteLearningRepository(learning),
        jobs=SqliteGenerationJobRepository(jobs),
        artifacts=SqliteGenerationArtifactRepository(artifacts),
        research=SqliteResearchRepository(research),
        progress=SqliteProgressEventRepository(progress),
        app_settings=LocalAppSettingsRepository(),
    )
