"""Spec §5's 90-day purge, and the wiring that makes it actually run.

The wiring half matters as much as the policy half. Plan §11 conflict 12: on the pinned
starlette, a task appended to `app.router.on_startup` beside a `lifespan=` is dropped with no
exception and no warning — so a purge could pass every unit test in this file and never run once
in production. The last test closes that gap by asserting through the deployed wiring: start the
app the way `uvicorn` does, and watch an expired row disappear.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from report_intake.config import Settings
from report_intake.db import close_db, init_db
from report_intake.main import create_app
from report_intake.reports.models import Report
from report_intake.reports.pipeline import StorageUnavailable
from report_intake.reports.retention import PURGE_INTERVAL, RetentionPurge
from report_intake.reports.store import ReportStore

_RETENTION = timedelta(days=90)


def _store(clock: Any = None) -> ReportStore:
    if clock is None:
        return ReportStore(idempotency_ttl=timedelta(hours=24), retention=_RETENTION)
    return ReportStore(idempotency_ttl=timedelta(hours=24), retention=_RETENTION, clock=clock)


async def _record(store: ReportStore) -> str:
    recorded = await store.record(
        payload={"note": "old"},
        classification="envelope",
        caller_email=None,
        reply_to=None,
        idempotency_key=None,
    )
    return recorded.report.ref


class _RefusingStore:
    async def purge_expired(self, now: datetime | None = None) -> int:
        raise StorageUnavailable("the database is gone")


class _CountingStore:
    def __init__(self) -> None:
        self.sweeps = 0

    async def purge_expired(self, now: datetime | None = None) -> int:
        self.sweeps += 1
        return 0


@pytest.mark.asyncio
async def test_a_sweep_removes_rows_past_the_retention_window(storage: None) -> None:
    long_ago = datetime.now(UTC) - _RETENTION - timedelta(days=1)
    await _record(_store(clock=lambda: long_ago))

    purged = await RetentionPurge(_store()).sweep()

    assert purged == 1
    assert await Report.all().count() == 0


@pytest.mark.asyncio
async def test_a_sweep_keeps_a_row_inside_the_window(storage: None) -> None:
    await _record(_store())

    assert await RetentionPurge(_store()).sweep() == 0
    assert await Report.all().count() == 1


@pytest.mark.asyncio
async def test_a_sweep_that_cannot_reach_the_database_does_not_raise() -> None:
    """Retention is the least urgent thing this service does. A purge failure that killed the
    loop would stop retention silently and forever; one that killed the task's exception handler
    would take the process with it."""
    assert await RetentionPurge(_RefusingStore()).sweep() == 0  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_the_loop_sweeps_before_it_waits() -> None:
    """A pod restarted more often than the interval — the ordinary life of a pod during a
    rollout — would otherwise never purge anything at all."""
    store = _CountingStore()
    loop = RetentionPurge(store, interval=timedelta(days=1))  # type: ignore[arg-type]

    task = asyncio.create_task(loop.run())
    await asyncio.sleep(0)
    task.cancel()

    assert store.sweeps == 1


@pytest.mark.asyncio
async def test_the_loop_stops_when_it_is_cancelled() -> None:
    """Shutdown has to end it, or the lifespan's `finally` waits forever on a task that is
    sleeping for six hours."""
    task = asyncio.create_task(RetentionPurge(_CountingStore(), timedelta(days=1)).run())  # type: ignore[arg-type]
    await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_the_purge_runs_from_the_lifespan_rather_than_a_dropped_startup_handler(
    hermetic_environment: None, database_url: str
) -> None:
    """The plan §11/12 regression, asserted through the deployed wiring rather than by calling
    `sweep()` directly: an expired row seeded before startup is gone shortly after the app is
    serving. A purge registered on `app.router.on_startup` would leave it there forever while
    every other test in this file still passed.
    """
    long_ago = datetime.now(UTC) - _RETENTION - timedelta(days=1)
    ref = asyncio.run(_seed(database_url, clock=lambda: long_ago))
    assert _refs(database_url) == [ref]

    with TestClient(create_app(Settings(database_url=database_url))) as client:
        assert client.get("/healthz").status_code == 200
        assert _eventually_empty(database_url), "the retention purge never ran"


def test_the_lifespan_owns_the_purge_task_and_ends_it_on_shutdown(
    hermetic_environment: None, database_url: str
) -> None:
    """Owned, because the event loop keeps only a weak reference to a bare `create_task` and a
    task nobody holds can be collected mid-sweep."""
    app = create_app(Settings(database_url=database_url))

    with TestClient(app):
        task = app.state.retention_purge
        assert not task.done()

    assert task.cancelled()


def test_the_interval_is_short_enough_to_matter_and_long_enough_to_be_free() -> None:
    """Four passes a day against a 90-day window. Named here so a change to it is a change to a
    test, not a silent edit to a constant nobody reads."""
    assert PURGE_INTERVAL == timedelta(hours=6)


async def _seed(database_url: str, clock: Any) -> str:
    await init_db(database_url)
    try:
        return await _record(_store(clock=clock))
    finally:
        await close_db()


def _refs(database_url: str) -> list[str]:
    connection = sqlite3.connect(database_url.removeprefix("sqlite://"))
    try:
        return [row[0] for row in connection.execute("SELECT ref FROM reports")]
    finally:
        connection.close()


def _eventually_empty(database_url: str, timeout_s: float = 5.0) -> bool:
    """Poll rather than sleep once: the purge runs on the app's own loop in another thread, so
    the only honest assertion is "this happens", not "this has already happened"."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _refs(database_url):
            return True
        time.sleep(0.01)
    return False
