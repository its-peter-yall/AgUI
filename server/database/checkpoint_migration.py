"""
============================================================================
FILE: checkpoint_migration.py
LOCATION: server/database/checkpoint_migration.py
============================================================================
PURPOSE:
    Copy LangGraph checkpoints between savers via public APIs only.
ROLE IN PROJECT:
    Phase 4 SQLite→Mongo checkpoint migration without private document layout.
    - Reads CheckpointTuple values through source.alist
    - Writes via target.aput and target.aput_writes
KEY COMPONENTS:
    - CheckpointMigrationSummary: counts of checkpoints and writes copied
    - copy_checkpoints: backend-neutral async copy helper
DEPENDENCIES:
    - External: None (stdlib only)
    - Internal: None
USAGE:
    summary = await copy_checkpoints(sqlite_saver, mongo_saver)
============================================================================
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CheckpointMigrationSummary:
    checkpoints: int
    writes: int


async def copy_checkpoints(
    source: Any,
    target: Any,
) -> CheckpointMigrationSummary:
    """Copy saver tuples using backend-neutral LangGraph APIs."""

    checkpoint_count = 0
    write_count = 0
    async for item in source.alist(None):
        configurable = item.config["configurable"]
        write_config = {
            "configurable": {
                "thread_id": configurable["thread_id"],
                "checkpoint_ns": configurable.get("checkpoint_ns", ""),
            }
        }
        if item.parent_config is not None:
            parent = item.parent_config["configurable"]
            write_config["configurable"]["checkpoint_id"] = (
                parent["checkpoint_id"]
            )
        # CheckpointTuple does not expose new_versions separately; the
        # channel version map lives on the checkpoint document itself.
        # Passing full map keeps blob-based savers (and future targets)
        # able to materialize every channel value after migrate.
        checkpoint = item.checkpoint
        new_versions = dict(checkpoint.get("channel_versions") or {})
        await target.aput(
            write_config,
            checkpoint,
            item.metadata,
            new_versions,
        )
        checkpoint_count += 1

        by_task: dict[str, list[tuple[str, Any]]] = defaultdict(list)
        for task_id, channel, value in item.pending_writes or []:
            by_task[task_id].append((channel, value))
            write_count += 1
        for task_id, writes in by_task.items():
            await target.aput_writes(item.config, writes, task_id)

    return CheckpointMigrationSummary(
        checkpoints=checkpoint_count,
        writes=write_count,
    )
