"""`purged_at` is the database time of the completion update, not the start of the run (OME-1947).

Review finding 2 of pull request 1911: the run read the database clock once and passed that value
to each completion update, so a purge with pauses between chunks stored a time before its last
delete. erd.md section 2.1 defines `purged_at` as the time the sweep deleted the last entry.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from aigateway.core.frozen_copy.sweep import FrozenCopySweep, IdleRule, database_now
from tests.unit.test_frozen_copy_support import (
    account_id_of,
    run_async,
    seed_copy,
    stored_entries,
)
from tests.unit.test_frozen_copy_sweep_support import age_copy, make_entries, read_copy

_HOUR = timedelta(hours=1)
# WHY bound at import: some tests patch the global asyncio.sleep.
_REAL_SLEEP = asyncio.sleep
# WHY 50 ms: SQLite gives the database clock in milliseconds; three pauses put the last delete at
# least 100 ms after the start of the run, with no wait of seconds.
_PAUSE_S = 0.05


async def _real_pause(_delay: float) -> None:
    await _REAL_SLEEP(_PAUSE_S)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _delayed_sweep(
    monkeypatch: pytest.MonkeyPatch, *, max_entries: int
) -> tuple[FrozenCopySweep, list[datetime]]:
    """A sweep with real pauses between chunks; the list gets the database time of each delete."""
    sweep = FrozenCopySweep(
        [IdleRule(open_idle_seconds=86_400)],
        max_entries=max_entries,
        chunk_size=1,
        sleep=_real_pause,
    )
    real = sweep.purge_chunk
    deleted_at: list[datetime] = []

    async def _timed(copy_id: UUID, *, limit: int | None = None) -> int:
        deleted = await real(copy_id, limit=limit)
        if deleted > 0:
            deleted_at.append(await database_now())
        return deleted

    monkeypatch.setattr(sweep, "purge_chunk", _timed)
    return sweep, deleted_at


def _abandoned_copy(client: TestClient) -> str:
    copy_id = seed_copy(client, account_id_of(client), make_entries(3), seal=False)
    age_copy(client, copy_id, copy_age=30 * _HOUR, entry_age=25 * _HOUR)
    return copy_id


def test_purged_at_is_not_before_the_last_delete_of_a_delayed_purge(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy_id = _abandoned_copy(authenticated_client)
    sweep, deleted_at = _delayed_sweep(monkeypatch, max_entries=100_000)

    report = run_async(authenticated_client, lambda: sweep.run_pass(trigger="command"))

    copy = read_copy(authenticated_client, copy_id)
    assert report.copies_completed == 1
    assert stored_entries(authenticated_client, copy_id) == []
    assert len(deleted_at) == 3
    assert copy.purged_at is not None
    assert _utc(copy.purged_at) >= deleted_at[-1]
    # The mark time stays the time of the run: the fix changes only purged_at.
    assert copy.swept_at is not None
    assert _utc(copy.swept_at) < deleted_at[0]


def test_purged_at_is_not_before_the_last_delete_when_the_budget_ends_with_the_copy(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy_id = _abandoned_copy(authenticated_client)
    sweep, deleted_at = _delayed_sweep(monkeypatch, max_entries=3)

    report = run_async(authenticated_client, lambda: sweep.run_pass(trigger="command"))

    copy = read_copy(authenticated_client, copy_id)
    assert report.entries_purged == 3
    assert report.copies_completed == 1
    assert report.purge_stopped is None
    assert len(deleted_at) == 3
    assert copy.purged_at is not None
    assert _utc(copy.purged_at) >= deleted_at[-1]
