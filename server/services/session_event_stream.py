"""
============================================================================
FILE: session_event_stream.py
LOCATION: server/services/session_event_stream.py
============================================================================
PURPOSE:
    Replay-then-tail SSE framing for durable generation progress events.
ROLE IN PROJECT:
    Lets clients reconnect with Last-Event-ID without owning generation lifetime.
    - Replays rows after cursor, then polls for new events
    - Emits keepalives; never cancels jobs or deletes sessions on disconnect
KEY COMPONENTS:
    - stream_session_events: Async SSE frame generator
    - format_sse_frame: Single-event SSE encoder
DEPENDENCIES:
    - External: asyncio, json, typing
    - Internal: server.schemas.generation
USAGE:
    async for frame in stream_session_events(session_id, cursor, ...):
        yield frame
============================================================================
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from server.schemas.generation import GenerationStage

TERMINAL_STAGES = frozenset(
    {
        GenerationStage.COMPLETE.value,
        GenerationStage.COMPLETE_DEGRADED.value,
        GenerationStage.CANCELLED.value,
        GenerationStage.FAILED.value,
        "COMPLETE",
        "COMPLETE_DEGRADED",
        "CANCELLED",
        "FAILED",
    }
)

TERMINAL_EVENT_TYPES = frozenset(
    {
        "generation_complete",
        "generation_cancelled",
    }
)

SleepFn = Callable[[float], Awaitable[None]]


def _event_type_value(event: Any) -> str:
    event_type = getattr(event, "event_type", None)
    if event_type is None:
        return ""
    value = getattr(event_type, "value", event_type)
    return str(value)


def _payload_dict(event: Any) -> dict[str, Any]:
    payload = getattr(event, "payload", None)
    if payload is None:
        return {}
    if hasattr(payload, "model_dump"):
        dumped = payload.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {"value": dumped}
    if isinstance(payload, dict):
        return payload
    return {}


def _created_at_str(event: Any) -> str:
    created = getattr(event, "created_at", None)
    if isinstance(created, datetime):
        return created.isoformat()
    if created is None:
        return ""
    return str(created)


def _stage_from_public(public: Any) -> Optional[str]:
    if public is None:
        return None
    if isinstance(public, dict):
        stage = public.get("stage")
        return stage.value if hasattr(stage, "value") else stage
    stage = getattr(public, "stage", None)
    if stage is None:
        return None
    return stage.value if hasattr(stage, "value") else str(stage)


def format_sse_frame(
    *,
    event_id: int,
    event_type: str,
    data: dict[str, Any],
    retry_ms: int = 2000,
) -> str:
    """Encode one SSE event frame."""
    body = json.dumps(data, separators=(",", ":"), default=str)
    return (
        f"id: {event_id}\n"
        f"event: {event_type}\n"
        f"retry: {retry_ms}\n"
        f"data: {body}\n\n"
    )


async def stream_session_events(
    *,
    session_id: str,
    cursor: int,
    event_store: Any,
    job_store: Any,
    sleep: Optional[SleepFn] = None,
    heartbeat_seconds: float = 15.0,
    poll_seconds: float = 0.5,
) -> AsyncIterator[str]:
    """Replay events after cursor, then tail until terminal stage/event.

    Never cancels generation tasks or deletes sessions on client disconnect.
    """
    sleeper: SleepFn = sleep or asyncio.sleep
    current = cursor
    last_heartbeat = asyncio.get_event_loop().time()

    try:
        while True:
            rows = event_store.list_after(session_id, current, limit=100)
            if rows:
                for event in rows:
                    event_id = int(event.id)
                    event_type = _event_type_value(event)
                    public = job_store.to_public_by_session(session_id)
                    if hasattr(public, "model_dump"):
                        generation = public.model_dump(mode="json")
                    else:
                        generation = public
                    envelope = {
                        "id": event_id,
                        "session_id": session_id,
                        "event_type": event_type,
                        "payload": _payload_dict(event),
                        "generation": generation,
                        "created_at": _created_at_str(event),
                    }
                    yield format_sse_frame(
                        event_id=event_id,
                        event_type=event_type,
                        data=envelope,
                    )
                    current = event_id
                    if event_type in TERMINAL_EVENT_TYPES:
                        return
                continue

            public = job_store.to_public_by_session(session_id)
            stage = _stage_from_public(public)
            if stage in TERMINAL_STAGES:
                return

            now = asyncio.get_event_loop().time()
            if heartbeat_seconds <= 0 or (now - last_heartbeat) >= heartbeat_seconds:
                yield ": keepalive\n\n"
                last_heartbeat = now

            await sleeper(poll_seconds if heartbeat_seconds > 0 else 0)
    except asyncio.CancelledError:
        return
