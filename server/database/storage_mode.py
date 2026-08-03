"""
============================================================================
FILE: storage_mode.py
LOCATION: server/database/storage_mode.py
============================================================================
PURPOSE:
    Deployment and storage backend enums plus process-wide StorageContext.
ROLE IN PROJECT:
    Foundation for optional MongoDB Atlas storage (Approach A repository swap).
    - DeploymentMode controls mutable storage endpoints (local vs cloud)
    - StorageBackend tracks active persistence (sqlite vs mongo)
    - StorageContext owns Mongo connection lifecycle and active repo bundle
DEPENDENCIES:
    - External: None (stdlib only for enums; context adds sqlite3/threading)
    - Internal: server.database.mongo_client, server.database.repositories
USAGE:
    from server.database.storage_mode import DeploymentMode, StorageBackend
============================================================================
"""
from __future__ import annotations

import sqlite3
import threading
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from server.database.mongo_client import MongoConnection, connect_mongo
from server.database.repositories.bundle import RepositoryBundle
from server.database.repositories.protocols import (
    AppSettingsRepository,
    GenerationArtifactRepository,
    GenerationJobRepository,
    LearningRepository,
    ProgressEventRepository,
    ResearchRepository,
)

MongoFactory = Callable[[str, str], MongoConnection]


class DeploymentMode(str, Enum):
    """Server deployment policy controlling mutable storage endpoints."""

    LOCAL = "local"
    CLOUD = "cloud"


class StorageBackend(str, Enum):
    """Active application persistence backend."""

    SQLITE = "sqlite"
    MONGO = "mongo"


def _default_sqlite_repositories() -> RepositoryBundle:
    """Build SQLite bundle from process store singletons."""
    from server.database import (
        generation_artifact_store,
        generation_job_store,
        progress_event_store,
        research_store,
    )
    from server.database.learning_persistence import learning_manager
    from server.database.repositories.sqlite import build_sqlite_bundle

    return build_sqlite_bundle(
        learning=learning_manager,
        jobs=generation_job_store,
        artifacts=generation_artifact_store,
        research=research_store,
        progress=progress_event_store,
    )


class StorageContext:
    """Own active storage mode and process-wide Mongo connection."""

    def __init__(
        self,
        *,
        deployment_mode: DeploymentMode,
        sqlite_path: Path,
        mongo_factory: MongoFactory = connect_mongo,
        sqlite_repositories: Optional[RepositoryBundle] = None,
    ) -> None:
        self.deployment_mode = deployment_mode
        self.sqlite_path = sqlite_path
        self.active_backend = StorageBackend.SQLITE
        self._mongo_factory = mongo_factory
        self._mongo: Optional[MongoConnection] = None
        self._lock = threading.RLock()
        bundle = (
            sqlite_repositories
            if sqlite_repositories is not None
            else _default_sqlite_repositories()
        )
        self._sqlite_repositories = bundle
        self._repositories = bundle

    @property
    def connected(self) -> bool:
        return self._mongo is not None

    @property
    def mongo_db_name(self) -> Optional[str]:
        return self._mongo.db_name if self._mongo is not None else None

    @property
    def mongo_connection(self) -> Optional[MongoConnection]:
        return self._mongo

    @property
    def learning(self) -> LearningRepository:
        return self._repositories.learning

    @property
    def jobs(self) -> GenerationJobRepository:
        return self._repositories.jobs

    @property
    def artifacts(self) -> GenerationArtifactRepository:
        return self._repositories.artifacts

    @property
    def research(self) -> ResearchRepository:
        return self._repositories.research

    @property
    def progress(self) -> ProgressEventRepository:
        return self._repositories.progress

    @property
    def app_settings(self) -> AppSettingsRepository:
        return self._repositories.app_settings

    def connect(self, uri: str, db_name: str) -> None:
        candidate = self._mongo_factory(uri, db_name)
        with self._lock:
            previous = self._mongo
            self._mongo = candidate
            self.active_backend = StorageBackend.MONGO
        if previous is not None:
            previous.client.close()

    def disconnect(self) -> None:
        with self._lock:
            previous = self._mongo
            self._mongo = None
            self.active_backend = StorageBackend.SQLITE
            self._repositories = self._sqlite_repositories
        if previous is not None:
            previous.client.close()

    def local_data_present(self) -> bool:
        if not self.sqlite_path.exists():
            return False
        try:
            with sqlite3.connect(self.sqlite_path) as connection:
                row = connection.execute(
                    "SELECT 1 FROM learning_sessions LIMIT 1"
                ).fetchone()
        except sqlite3.Error:
            return False
        return row is not None
