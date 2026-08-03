"""
============================================================================
FILE: database/__init__.py
LOCATION: server/database/__init__.py
============================================================================
PURPOSE:
    Database persistence module entry point. Re-exports the shared
    database path constant, generation schema initializer, store classes,
    and process repository facades for convenient imports.
ROLE IN PROJECT:
    Namespace package marker for the database module.
    - Provides a clean public API surface for the database package
    - Facade aliases keep stable names while StorageContext owns backends
KEY COMPONENTS:
    - DB_PATH: Re-exported Path object pointing to server/data DB file
    - initialize_generation_schema: Creates generation persistence tables
    - generation_job_store / research_store / etc.: Repository facades
    - storage_context: Process-wide active storage context
DEPENDENCIES:
    - External: None
    - Internal: server.database.persistence, storage_registry, store classes
USAGE:
    ```python
    from server.database import (
        DB_PATH,
        generation_job_store,
        initialize_generation_schema,
    )
    ```
============================================================================
"""

from server.database.generation_artifacts import GenerationArtifactStore
from server.database.generation_jobs import GenerationJobStore
from server.database.generation_migrations import initialize_generation_schema
from server.database.persistence import DB_PATH
from server.database.progress_events import ProgressEventStore
from server.database.research_store import ResearchStore
from server.database.storage_registry import (
    generation_artifact_repository as generation_artifact_store,
    generation_job_repository as generation_job_store,
    progress_event_repository as progress_event_store,
    research_repository as research_store,
    storage_context,
)

__all__ = [
    "DB_PATH",
    "GenerationArtifactStore",
    "GenerationJobStore",
    "ProgressEventStore",
    "ResearchStore",
    "generation_artifact_store",
    "generation_job_store",
    "initialize_generation_schema",
    "progress_event_store",
    "research_store",
    "storage_context",
]
