"""
============================================================================
FILE: facade.py
LOCATION: server/database/repositories/facade.py
============================================================================
PURPOSE:
    Late-bound repository proxy that resolves the active backend on each call.
ROLE IN PROJECT:
    Keeps stable import identity for routers, graph nodes, and services while
    StorageContext can swap repository bundles (SQLite ↔ Mongo) at runtime.
KEY COMPONENTS:
    - RepositoryFacade: getattr forwarder via resolver callable
DEPENDENCIES:
    - External: None (stdlib typing only)
    - Internal: None
USAGE:
    facade = RepositoryFacade(lambda: storage_context.learning)
    facade.get_learning_session("s1")
============================================================================
"""

from __future__ import annotations

from typing import Any, Callable


class RepositoryFacade:
    """Resolve active repository lazily while preserving import identity."""

    def __init__(self, resolver: Callable[[], Any]) -> None:
        object.__setattr__(self, "_resolver", resolver)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolver(), name)
