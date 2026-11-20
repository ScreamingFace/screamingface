"""E5 P2 spec R12: the migration that adds a detached Run's columns keeps P1's Runs reading as
they did.

FEATURE: a detached Run (OME-1837). INVARIANT: a Run that P1 canceled still reads `canceled`
after the migration, because P2 reads the cancel from `stopped_by`, not the flag.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from run_registry_support import ORPHAN_GRACE, T0, Clock, make_store

from screamingface_engine.runs import db
from screamingface_engine.runs.records import owner_key

pytestmark = pytest.mark.asyncio

ALICE = owner_key("alice@example.org")
RUN_ID = "run_" + "d" * 32


async def _migrate_to(url: str, name: str | None) -> None:
    from tortoise.context import TortoiseContext
    from tortoise.migrations.executor import MigrationExecutor, MigrationTarget

    context = TortoiseContext()
    with db.using(context):
        try:
            await context.init(config=db.build_tortoise_config(url))
            executor = MigrationExecutor(context.connections.get(db.CONNECTION), db.apps(url))
            targets = None if name is None else [MigrationTarget(app_label=db.APP_LABEL, name=name)]
            await executor.migrate(targets)
        finally:
            await context.close_connections()


async def test_a_run_p1_canceled_still_reads_canceled(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite3"
    url = f"sqlite://{path}"
    await _migrate_to(url, "0002_candidate_stop_owed")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO runs (id, owner, client_key, benchmark, case_count, client_version,"
            " canceled, created_at, last_activity_at) VALUES (?, ?, 'k', 'gsm8k', 1, '1.0',"
            " 1, ?, ?)",
            (RUN_ID, ALICE, T0.isoformat(), T0.isoformat()),
        )
        conn.execute(
            'INSERT INTO run_candidates (run_id, "index", name, state, finished_at, stop_owed)'
            " VALUES (?, 0, 'alpha', 'stopped', ?, 0)",
            (RUN_ID, T0.isoformat()),
        )

    await _migrate_to(url, None)

    await db.init_db(url)
    try:
        record = await make_store(Clock(), True, T0, ORPHAN_GRACE).get(ALICE, RUN_ID)
    finally:
        await db.close_db()
    assert record is not None
    assert (record.state, record.stopped_by, record.detached) == ("canceled", "canceled", False)
    assert record.candidates[0].start is None


async def test_a_run_p1_cancels_after_the_migration_still_reads_canceled(tmp_path: Path) -> None:
    """R12, R15: while a deploy rolls, the App from before P2 still cancels by its flag alone,
    after the migration has run. Such a Run must read `canceled`, not `interrupted`."""
    path = tmp_path / "runs.sqlite3"
    url = f"sqlite://{path}"
    await _migrate_to(url, None)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO runs (id, owner, client_key, benchmark, case_count, client_version,"
            " canceled, created_at, last_activity_at, detached) VALUES (?, ?, 'k', 'gsm8k', 1,"
            " '1.0', 1, ?, ?, 0)",
            (RUN_ID, ALICE, T0.isoformat(), T0.isoformat()),
        )
        conn.execute(
            'INSERT INTO run_candidates (run_id, "index", name, state, finished_at, stop_owed)'
            " VALUES (?, 0, 'alpha', 'stopped', ?, 0)",
            (RUN_ID, T0.isoformat()),
        )

    await db.init_db(url)
    try:
        record = await make_store(Clock(), True, T0, ORPHAN_GRACE).get(ALICE, RUN_ID)
    finally:
        await db.close_db()
    assert record is not None
    assert (record.state, record.stopped_by) == ("canceled", "canceled")
