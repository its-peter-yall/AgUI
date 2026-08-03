"""
============================================================================
FILE: test_checkpoint_migration.py
LOCATION: server/tests/test_checkpoint_migration.py
============================================================================
PURPOSE:
    Unit tests for public-API LangGraph checkpoint copy to Mongo.
ROLE IN PROJECT:
    TDD guard for Phase 4 checkpoint migration without private layouts.
    - Parent config wiring into aput
    - Pending writes grouped by task_id
    - Idempotent retry key stability
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.database.checkpoint_migration
USAGE:
    python -m unittest server.tests.test_checkpoint_migration -v
============================================================================
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from server.database.checkpoint_migration import copy_checkpoints


class FakeSqliteSaver:
    def __init__(self, tuples):
        self.tuples = tuples

    async def alist(self, config):
        for item in self.tuples:
            yield item


def make_checkpoint_tuple():
    return SimpleNamespace(
        config={
            "configurable": {
                "thread_id": "gen-s1",
                "checkpoint_ns": "",
                "checkpoint_id": "cp2",
            }
        },
        checkpoint={
            "id": "cp2",
            "v": 1,
            "channel_versions": {"messages": "3", "channel": 2},
            "channel_values": {"messages": [], "channel": "x"},
        },
        metadata={"step": 2},
        parent_config={
            "configurable": {
                "thread_id": "gen-s1",
                "checkpoint_ns": "",
                "checkpoint_id": "cp1",
            }
        },
        pending_writes=[
            ("task-a", "alpha", 1),
            ("task-a", "beta", 2),
            ("task-b", "gamma", 3),
        ],
    )


class CheckpointMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_copies_checkpoint_and_groups_writes_by_task(self) -> None:
        item = make_checkpoint_tuple()
        target = SimpleNamespace(
            aput=AsyncMock(),
            aput_writes=AsyncMock(),
        )
        summary = await copy_checkpoints(
            FakeSqliteSaver([item]),
            target,
        )

        write_config = target.aput.call_args.args[0]
        self.assertEqual(
            write_config["configurable"]["checkpoint_id"],
            "cp1",
        )
        new_versions = target.aput.call_args.args[3]
        self.assertEqual(
            new_versions,
            {"messages": "3", "channel": 2},
        )
        self.assertEqual(target.aput_writes.await_count, 2)
        self.assertEqual(summary.checkpoints, 1)
        self.assertEqual(summary.writes, 3)

    async def test_aput_uses_empty_versions_when_checkpoint_lacks_map(
        self,
    ) -> None:
        item = make_checkpoint_tuple()
        item.checkpoint = {"id": "cp2", "v": 1}
        target = SimpleNamespace(
            aput=AsyncMock(),
            aput_writes=AsyncMock(),
        )
        await copy_checkpoints(FakeSqliteSaver([item]), target)
        self.assertEqual(target.aput.call_args.args[3], {})

    async def test_empty_source_is_successful(self) -> None:
        target = SimpleNamespace(
            aput=AsyncMock(),
            aput_writes=AsyncMock(),
        )
        summary = await copy_checkpoints(FakeSqliteSaver([]), target)
        self.assertEqual(summary.checkpoints, 0)
        target.aput.assert_not_awaited()


class IdempotentTarget:
    def __init__(self) -> None:
        self.checkpoints: set[tuple[str, str, str]] = set()
        self.writes: set[tuple[str, str, str, str, int]] = set()

    async def aput(self, config, checkpoint, metadata, new_versions):
        values = config["configurable"]
        self.checkpoints.add(
            (
                values["thread_id"],
                values.get("checkpoint_ns", ""),
                checkpoint["id"],
            )
        )

    async def aput_writes(self, config, writes, task_id):
        values = config["configurable"]
        for index, _write in enumerate(writes):
            self.writes.add(
                (
                    values["thread_id"],
                    values.get("checkpoint_ns", ""),
                    values["checkpoint_id"],
                    task_id,
                    index,
                )
            )


class CheckpointMigrationIdempotencyTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_retry_does_not_grow_target_key_sets(self) -> None:
        item = make_checkpoint_tuple()
        target = IdempotentTarget()
        await copy_checkpoints(FakeSqliteSaver([item]), target)
        first_counts = (len(target.checkpoints), len(target.writes))
        await copy_checkpoints(FakeSqliteSaver([item]), target)
        self.assertEqual(
            (len(target.checkpoints), len(target.writes)),
            first_counts,
        )


if __name__ == "__main__":
    unittest.main()
