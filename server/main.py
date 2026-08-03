"""
============================================================================
FILE: main.py
LOCATION: server/main.py
============================================================================
PURPOSE:
    FastAPI application entry point. Initializes the web application,
    configures CORS middleware, manages application lifecycle, and registers
    all API route routers.
ROLE IN PROJECT:
    Top-level server entry point that wires together all backend components.
    - Bootstraps database and OpenRouter integration on startup
    - Mounts all API routers and exposes health check endpoints
KEY COMPONENTS:
    - app: FastAPI application instance with title and version metadata
    - lifespan(): Async context manager handling startup/shutdown lifecycle
    - root(): Root endpoint returning server status
    - health(): Detailed health check exposing OpenRouter status
DEPENDENCIES:
    - External: fastapi, uvicorn
    - Internal: server.utils.instructor_client,
              server.database.learning_persistence, server.routers
USAGE:
    ```bash
    python -m uvicorn server.main:app --reload --port 8000
    ```
============================================================================
"""

from contextlib import asynccontextmanager
import logging
import os
from typing import Any

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from server.config import settings
from server.database.checkpointer import CheckpointerController
from server.database.storage_mode import DeploymentMode, StorageContext
from server.database.storage_registry import (
    initialize_sqlite_storage,
    storage_context,
)
from server.graph.build import CHECKPOINT_DB_PATH, build_graph
from server.routers import learning_router, llm_router, storage_router
from server.services.generation_runtime import GenerationRuntime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _require_cloud_mongo_config() -> tuple[str, str]:
    """Return validated cloud Mongo URI and database name."""
    uri = settings.mongo_uri
    db_name = settings.mongo_db
    if not uri or not db_name:
        raise RuntimeError(
            "DEPLOYMENT_MODE=cloud requires MONGO_URI and MONGO_DB"
        )
    return uri, db_name


async def start_cloud_runtime(
    *,
    app_state: Any,
    storage: StorageContext,
    uri: str,
    db_name: str,
    runtime_type: type[GenerationRuntime] = GenerationRuntime,
) -> GenerationRuntime:
    """Connect cloud Mongo, wire checkpointer, and create runtime."""
    controller = CheckpointerController(
        app_state=app_state,
        sqlite_saver=None,
        graph_builder=lambda saver: build_graph(checkpointer=saver),
    )
    storage.set_checkpointer_controller(controller)
    try:
        await run_in_threadpool(storage.connect, uri, db_name)
    except Exception as exc:
        logger.error(
            "Cloud MongoDB startup failed error=%s",
            type(exc).__name__,
        )
        raise RuntimeError("Cloud MongoDB startup failed") from exc
    app_state.storage = storage
    runtime = runtime_type(app_state=app_state)
    app_state.generation_runtime = runtime
    return runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager for the FastAPI app.
    Initializes database on startup.
    """
    logger.info("Starting A2UI Backend...")

    if settings.deployment_mode == DeploymentMode.CLOUD:
        uri, db_name = _require_cloud_mongo_config()
        runtime = await start_cloud_runtime(
            app_state=app.state,
            storage=storage_context,
            uri=uri,
            db_name=db_name,
        )
        try:
            yield
        finally:
            await runtime.shutdown()
            storage_context.close()
            storage_context.set_checkpointer_controller(None)
            logger.info("Shutting down A2UI Backend...")
        return

    # Initialize database
    try:
        initialize_sqlite_storage()
        storage_context.jobs.mark_orphaned_jobs_paused(
            pause_all_nonterminal=True,
        )
        logger.info("Database initialized successfully.")
    except Exception:
        logger.exception("Database initialization failed")
        raise

    app.state.storage = storage_context

    CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(
        str(CHECKPOINT_DB_PATH),
    ) as checkpointer:
        controller = CheckpointerController(
            app_state=app.state,
            sqlite_saver=checkpointer,
            graph_builder=lambda saver: build_graph(checkpointer=saver),
        )
        controller.activate_sqlite()
        storage_context.set_checkpointer_controller(controller)
        runtime = GenerationRuntime(app_state=app.state)
        app.state.generation_runtime = runtime
        try:
            yield
        finally:
            await runtime.shutdown()
            if storage_context.deployment_mode == DeploymentMode.LOCAL:
                storage_context.disconnect()
            storage_context.set_checkpointer_controller(None)

    logger.info("Shutting down A2UI Backend...")


app = FastAPI(title="A2UI Backend", version="1.0.0", lifespan=lifespan)

# Configure CORS
cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "A2UI Backend is running"}


@app.get("/health")
async def health():
    """Health check endpoint exposing provider status."""
    return {
        "status": "ok",
        "services": {
            "openrouter": "enabled",
            "generalcompute": "enabled",
        },
    }


# Include routers
app.include_router(learning_router)
app.include_router(llm_router)
app.include_router(storage_router)
