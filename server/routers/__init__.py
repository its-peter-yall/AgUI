"""
============================================================================
FILE: __init__.py
LOCATION: server/routers/__init__.py
============================================================================
PURPOSE:
    API routers module entry point. Re-exports the learning router for
    easy inclusion in the main FastAPI application.
ROLE IN PROJECT:
    Aggregates all API routers into a single importable namespace.
    - Exposes learning_router for registration in server/main.py
    - Provides a single import point for future router additions
KEY COMPONENTS:
    - learning_router: FastAPI APIRouter from server/routers/learning.py
DEPENDENCIES:
    - External: None
    - Internal: server.routers.learning
USAGE:
    ```python
    from server.routers import learning_router
    app.include_router(learning_router)
    ```
============================================================================
"""

from server.routers.learning import router as learning_router
from server.routers.llm import router as llm_router
from server.routers.storage import router as storage_router

__all__ = ["learning_router", "llm_router", "storage_router"]

