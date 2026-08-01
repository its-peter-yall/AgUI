"""
============================================================================
FILE: database/__init__.py
LOCATION: server/database/__init__.py
============================================================================
PURPOSE:
    Database persistence module entry point. Re-exports the shared
    database path constant, generation schema initializer, and store
    instances for convenient imports.
ROLE IN PROJECT:
    Namespace package marker for the database module.
    - Provides a clean public API surface for the database package
    - Allows imports from server.database without knowing internals
KEY COMPONENTS:
    - DB_PATH: Re-exported Path object pointing to server/data/agui.db
    - initialize_generation_schema: Creates generation persistence tables
    - generation_job_store: Job lifecycle persistence instance
    - research_store: Research report persistence instance
    - generation_artifact_store: Outline, brief, and node source instance
    - progress_event_store: Replayable progress event instance
DEPENDENCIES:
    - External: None
    - Internal: server.database.persistence
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

generation_job_store = GenerationJobStore(DB_PATH)
research_store = ResearchStore(DB_PATH)
generation_artifact_store = GenerationArtifactStore(DB_PATH)
progress_event_store = ProgressEventStore(DB_PATH)

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
]
