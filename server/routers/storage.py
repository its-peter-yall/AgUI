"""
============================================================================
FILE: storage.py
LOCATION: server/routers/storage.py
============================================================================
PURPOSE:
    REST endpoints for storage lifecycle, migrate, and app settings.
ROLE IN PROJECT:
    Exposes local-only Mongo connection controls and cloud-backed settings.
    - GET /settings/storage/status
    - POST /settings/storage/connect|disconnect|migrate (local only)
    - GET/PUT /settings/storage/app-settings (Mongo active)
DEPENDENCIES:
    - External: fastapi
    - Internal: server.database.mongo_client, server.database.migrate_to_mongo,
      server.database.storage_mode, server.schemas.storage
USAGE:
    app.include_router(storage_router)
============================================================================
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool

from server.database.migrate_to_mongo import (
    MigrationError,
    migrate_to_mongo,
)
from server.database.mongo_client import (
    MongoConfigurationError,
    MongoUnavailableError,
)
from server.database.persistence import DB_PATH
from server.database.storage_mode import (
    DeploymentMode,
    StorageBackend,
    StorageContext,
)
from server.graph.build import CHECKPOINT_DB_PATH
from server.schemas.storage import (
    AppSettingsResponse,
    AppSettingsUpdate,
    CollectionMigrationResponse,
    StorageConnectRequest,
    StorageMigrateRequest,
    StorageMigrateResponse,
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


def _require_mongo(context: StorageContext) -> None:
    if context.active_backend != StorageBackend.MONGO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MongoDB storage is not active",
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


@router.get(
    "/app-settings",
    response_model=AppSettingsResponse,
    summary="Read cloud-backed application settings",
)
async def get_app_settings(request: Request) -> AppSettingsResponse:
    context = _storage(request)
    _require_mongo(context)
    provider = await run_in_threadpool(
        context.app_settings.get_provider_settings
    )
    search = await run_in_threadpool(
        context.app_settings.get_web_search_settings
    )
    return AppSettingsResponse(
        provider_settings=provider,
        web_search_settings=search,
    )


@router.put(
    "/app-settings",
    response_model=AppSettingsResponse,
    summary="Write cloud-backed application settings",
)
async def put_app_settings(
    payload: AppSettingsUpdate,
    request: Request,
) -> AppSettingsResponse:
    context = _storage(request)
    _require_mongo(context)
    await run_in_threadpool(
        context.app_settings.put_provider_settings,
        payload.provider_settings,
    )
    await run_in_threadpool(
        context.app_settings.put_web_search_settings,
        payload.web_search_settings,
    )
    return AppSettingsResponse(
        provider_settings=payload.provider_settings,
        web_search_settings=payload.web_search_settings,
    )


@router.post(
    "/migrate",
    response_model=StorageMigrateResponse,
    summary="Copy local SQLite data into active MongoDB",
)
async def migrate_storage(
    payload: StorageMigrateRequest,
    request: Request,
) -> StorageMigrateResponse:
    context = _storage(request)
    _require_local(context)
    _require_idle(request)
    _require_mongo(context)
    mongo = context.mongo_connection
    controller = context.checkpointer_controller
    if mongo is None or controller is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MongoDB storage is not active",
        )
    try:
        summary = await migrate_to_mongo(
            sqlite_path=DB_PATH,
            checkpoint_path=CHECKPOINT_DB_PATH,
            database=mongo.database,
            mongo_checkpointer=controller.active_saver,
            app_settings=context.app_settings,
            provider_settings=payload.provider_settings,
            web_search_settings=payload.web_search_settings,
        )
    except MigrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "storage_migration_failed",
                "collection": exc.collection,
                "message": "Migration can be retried safely",
            },
        ) from exc
    collections = {
        name: CollectionMigrationResponse(
            rows=item.rows,
            matched=item.matched,
            upserted=item.upserted,
            modified=item.modified,
        )
        for name, item in summary.collections.items()
    }
    return StorageMigrateResponse(
        collections=collections,
        checkpoints=summary.checkpoints,
        checkpoint_writes=summary.checkpoint_writes,
        warnings=summary.warnings,
    )
