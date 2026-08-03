"""
============================================================================
FILE: storage.py
LOCATION: server/routers/storage.py
============================================================================
PURPOSE:
    REST endpoints for storage status, connect, and disconnect lifecycle.
ROLE IN PROJECT:
    Exposes local-only Mongo connection controls and deployment-aware status.
    - GET /settings/storage/status
    - POST /settings/storage/connect (local only)
    - POST /settings/storage/disconnect (local only)
DEPENDENCIES:
    - External: fastapi
    - Internal: server.database.mongo_client, server.database.storage_mode,
      server.schemas.storage
USAGE:
    app.include_router(storage_router)
============================================================================
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool

from server.database.mongo_client import (
    MongoConfigurationError,
    MongoUnavailableError,
)
from server.database.storage_mode import DeploymentMode, StorageContext
from server.schemas.storage import (
    StorageConnectRequest,
    StorageStatusResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings/storage", tags=["storage"])


def _storage(request: Request) -> StorageContext:
    return request.app.state.storage


def _status(context: StorageContext) -> StorageStatusResponse:
    local_mode = context.deployment_mode == DeploymentMode.LOCAL
    return StorageStatusResponse(
        deployment_mode=context.deployment_mode,
        active_backend=context.active_backend,
        connected=context.connected,
        mongo_db_name=context.mongo_db_name,
        can_connect=local_mode,
        can_disconnect=local_mode and context.connected,
        can_migrate=(
            local_mode
            and context.connected
            and context.local_data_present()
        ),
        local_data_present=context.local_data_present(),
    )


def _require_local(context: StorageContext) -> None:
    if context.deployment_mode == DeploymentMode.CLOUD:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Storage is managed by deployment environment",
        )


def _require_idle(request: Request) -> None:
    runtime = getattr(request.app.state, "generation_runtime", None)
    session_ids = runtime.active_session_ids if runtime is not None else []
    if session_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "storage_switch_requires_idle_jobs",
                "message": (
                    "Cancel or wait for active generation before "
                    "switching storage"
                ),
                "sessionIds": session_ids,
            },
        )


@router.get(
    "/status",
    response_model=StorageStatusResponse,
    summary="Get active storage status",
)
async def get_storage_status(request: Request) -> StorageStatusResponse:
    return _status(_storage(request))


@router.post(
    "/connect",
    response_model=StorageStatusResponse,
    summary="Connect local server to MongoDB",
)
async def connect_storage(
    payload: StorageConnectRequest,
    request: Request,
) -> StorageStatusResponse:
    context = _storage(request)
    _require_local(context)
    _require_idle(request)
    try:
        await run_in_threadpool(
            context.connect,
            payload.uri,
            payload.db_name,
        )
    except MongoConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MongoDB connection is invalid or unauthorized",
        ) from exc
    except MongoUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MongoDB is unreachable",
        ) from exc
    return _status(context)


@router.post(
    "/disconnect",
    response_model=StorageStatusResponse,
    summary="Return local server to SQLite",
)
async def disconnect_storage(request: Request) -> StorageStatusResponse:
    context = _storage(request)
    _require_local(context)
    _require_idle(request)
    await run_in_threadpool(context.disconnect)
    return _status(context)
