"""
============================================================================
FILE: mongo_factory.py
LOCATION: server/database/repositories/mongo_factory.py
============================================================================
PURPOSE:
    Build a complete Mongo RepositoryBundle from a connected database.
ROLE IN PROJECT:
    StorageContext uses this factory so connect publishes all six Mongo
    repositories together after indexes are ensured.
DEPENDENCIES:
    - External: None (duck-typed Database)
    - Internal: mongo_* repository classes, bundle
USAGE:
    from server.database.repositories.mongo_factory import build_mongo_bundle
    bundle = build_mongo_bundle(database)
============================================================================
"""
from __future__ import annotations

from typing import Any

from server.database.repositories.bundle import RepositoryBundle
from server.database.repositories.mongo_artifacts import (
    MongoGenerationArtifactRepository,
)
from server.database.repositories.mongo_jobs import (
    MongoGenerationJobRepository,
)
from server.database.repositories.mongo_learning import (
    MongoLearningRepository,
)
from server.database.repositories.mongo_progress import (
    MongoProgressEventRepository,
)
from server.database.repositories.mongo_research import (
    MongoResearchRepository,
)
from server.database.repositories.mongo_settings import (
    MongoAppSettingsRepository,
)


def build_mongo_bundle(database: Any) -> RepositoryBundle:
    """Construct the full Mongo repository bundle for one database."""

    return RepositoryBundle(
        learning=MongoLearningRepository(database),
        jobs=MongoGenerationJobRepository(database),
        artifacts=MongoGenerationArtifactRepository(database),
        research=MongoResearchRepository(database),
        progress=MongoProgressEventRepository(database),
        app_settings=MongoAppSettingsRepository(database),
    )
