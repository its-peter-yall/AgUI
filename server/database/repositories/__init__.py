"""
============================================================================
FILE: __init__.py
LOCATION: server/database/repositories/__init__.py
============================================================================
PURPOSE:
    Public exports for repository ports, SQLite adapters, bundle, and errors.
ROLE IN PROJECT:
    Clean import surface for StorageContext and future Mongo adapters.
DEPENDENCIES:
    - Internal: protocols, bundle, errors, sqlite adapters
USAGE:
    from server.database.repositories import RepositoryBundle, LearningRepository
============================================================================
"""

from server.database.repositories.bundle import RepositoryBundle
from server.database.repositories.errors import (
    RepositoryConflictError,
    RepositoryUnavailableError,
)
from server.database.repositories.mongo_artifacts import (
    MongoGenerationArtifactRepository,
)
from server.database.repositories.mongo_factory import build_mongo_bundle
from server.database.repositories.mongo_indexes import (
    ensure_all_indexes,
    ensure_learning_indexes,
    ensure_operational_indexes,
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
from server.database.repositories.protocols import (
    AppSettingsRepository,
    GenerationArtifactRepository,
    GenerationJobRepository,
    LearningRepository,
    ProgressEventRepository,
    ResearchRepository,
)
from server.database.repositories.sqlite import (
    LocalAppSettingsRepository,
    SqliteGenerationArtifactRepository,
    SqliteGenerationJobRepository,
    SqliteLearningRepository,
    SqliteProgressEventRepository,
    SqliteResearchRepository,
    build_sqlite_bundle,
)

__all__ = [
    "AppSettingsRepository",
    "GenerationArtifactRepository",
    "GenerationJobRepository",
    "LearningRepository",
    "LocalAppSettingsRepository",
    "MongoAppSettingsRepository",
    "MongoGenerationArtifactRepository",
    "MongoGenerationJobRepository",
    "MongoLearningRepository",
    "MongoProgressEventRepository",
    "MongoResearchRepository",
    "ProgressEventRepository",
    "RepositoryBundle",
    "RepositoryConflictError",
    "RepositoryUnavailableError",
    "ResearchRepository",
    "SqliteGenerationArtifactRepository",
    "SqliteGenerationJobRepository",
    "SqliteLearningRepository",
    "SqliteProgressEventRepository",
    "SqliteResearchRepository",
    "build_mongo_bundle",
    "build_sqlite_bundle",
    "ensure_all_indexes",
    "ensure_learning_indexes",
    "ensure_operational_indexes",
]
