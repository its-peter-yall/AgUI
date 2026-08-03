"""
============================================================================
FILE: errors.py
LOCATION: server/database/repositories/errors.py
============================================================================
PURPOSE:
    Backend-independent repository error types shared by SQLite and Mongo
    adapters.
ROLE IN PROJECT:
    Ports-and-adapters boundary for optional MongoDB Atlas storage.
    - Signal missing repository implementations for the active backend
    - Signal unique, transition, or optimistic-lock conflicts
DEPENDENCIES:
    - External: None
    - Internal: None
USAGE:
    from server.database.repositories.errors import (
        RepositoryUnavailableError,
        RepositoryConflictError,
    )
============================================================================
"""


class RepositoryUnavailableError(RuntimeError):
    """Requested repository has no implementation for active backend."""


class RepositoryConflictError(RuntimeError):
    """Unique, transition, or optimistic-lock constraint failed."""
