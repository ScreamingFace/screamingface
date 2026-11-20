"""PostgreSQL race evidence for the frozen copy sweep (OME-1947, prd/copy-sweep.md section 7).

SQLite ignores `select_for_update`, so the unit suite cannot prove the row lock of the mark, the
`lock_timeout` of the idle rule, or the `SKIP LOCKED` chunk delete. Each race here has a fixed
order: transaction A takes the copy row lock and waits; the test starts B and checks that B waits
on that lock; the test lets A commit; the test reads the result string of B. A test that only
starts two tasks at the same time would pass with no lock at all.

The module shares one database (the `tortoise migrate` subprocess also proves migration 0018 on
Postgres), so each test makes its own copies.

Run with: ``AIGW_TEST_PG=1 uv run pytest -m needs_postgres``
"""

from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Coroutine, Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from testcontainers.postgres import PostgresContainer
from tortoise import connections
from tortoise.transactions import in_transaction

from aigateway.config import Settings
from aigateway.core.frozen_copy.models import FrozenCopy, FrozenCopyEntry
from aigateway.core.frozen_copy.store import FrozenCopyStore
from aigateway.core.frozen_copy.sweep import (
    FrozenCopySweep,
    IdleRule,
    MarkOutcome,
    database_now,
)
from aigateway.main import create_app

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]
_IDLE_SECONDS = 86_400
# WHY 10 s: A must commit before B gives up, or B reports "lock timeout" and the copy keeps its
# state with no check under the lock (prd/copy-sweep.md section 7).
_LONG_LOCK_MS = 10_000
_SHORT_LOCK_MS = 300
# WHY bound at import: some tests patch the global asyncio.sleep.
_REAL_SLEEP = asyncio.sleep
# The chunk delete of `FrozenCopySweep.purge_chunk` on Postgres, run by hand in transaction A.
_PURGE_CHUNK_SQL = (
    "DELETE FROM frozen_copy_entries WHERE id IN (SELECT id FROM frozen_copy_entries "
    "WHERE frozen_copy_id = $1 LIMIT $2 FOR UPDATE SKIP LOCKED)"
)


@pytest.fixture(scope="module")
def postgres_database_url() -> Generator[str, None, None]:
    if os.environ.get("AIGW_TEST_PG") != "1":
        pytest.skip("AIGW_TEST_PG=1 not set")
    with PostgresContainer("postgres:16-alpine", driver=None) as postgres:
        database_url = (
            f"postgres://{postgres.username}:{quote(postgres.password, safe='')}"
            f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}"
            f"/{postgres.dbname}"
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "tortoise",
                "-c",
                "aigateway.db.TORTOISE_CONFIG",
                "migrate",
            ],
            cwd=_APP_DIR,
            env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
            check=True,
            capture_output=True,
            text=True,
        )
        yield database_url


@pytest.fixture
def pg_client(postgres_database_url: str) -> Generator[TestClient, None, None]:
    settings = Settings(
        database_url=SecretStr(postgres_database_url),
        admin_password=SecretStr("test-admin-password"),
        jwt_secret=SecretStr("x" * 32),
        provisioning_token=SecretStr("p" * 32),
        secret_key=SecretStr(base64.b64encode(b"k" * 32).decode()),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        login = client.post(
            "/v1/auth/login",
            json={"username": "admin", "password": "test-admin-password"},
        )
        assert login.status_code == 200, login.text
        client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})
        yield client


def _run[T](client: TestClient, call: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run a coroutine on the app's own event loop, where Tortoise is initialised."""
    portal = client.portal
    assert portal is not None
    return portal.call(call)


async def _yield_sleep(_delay: float) -> None:
    await _REAL_SLEEP(0)


def _sweep(*, lock_timeout_ms: int = _LONG_LOCK_MS, chunk_size: int = 500) -> FrozenCopySweep:
    return FrozenCopySweep(
        [IdleRule(open_idle_seconds=_IDLE_SECONDS, lock_timeout_ms=lock_timeout_ms)],
        max_entries=100_000,
        chunk_size=chunk_size,
        sleep=_yield_sleep,
    )


def _seed(client: TestClient, entries: int) -> UUID:
    """An open copy of the signed-in account whose copy row and entries are 25 h old."""
    owner = UUID(client.get("/v1/auth/me").json()["id"])

    async def _go() -> UUID:
        frozen = FrozenCopyStore(max_entry_bytes=2_000_000)
        copy = await frozen.open(owner)
        for i in range(entries):
            await frozen.capture(copy, "chat", {"q": i}, {"a": i}, 200, case_key="", occurrence=0)
        old = datetime.now(UTC) - timedelta(hours=25)
        await FrozenCopy.filter(id=copy.id).update(created_at=old)
        await FrozenCopyEntry.filter(frozen_copy_id=copy.id).update(created_at=old)
        return copy.id

    return _run(client, _go)


def _state(client: TestClient, copy_id: UUID) -> tuple[FrozenCopy, int]:
    async def _go() -> tuple[FrozenCopy, int]:
        copy = await FrozenCopy.get(id=copy_id)
        return copy, await FrozenCopyEntry.filter(frozen_copy_id=copy_id).count()

    return _run(client, _go)


def _mark(client: TestClient, copy_id: UUID) -> MarkOutcome:
    async def _go() -> MarkOutcome:
        rule = IdleRule(open_idle_seconds=_IDLE_SECONDS, lock_timeout_ms=_LONG_LOCK_MS)
        return await rule.mark(copy_id, await database_now())

    return _run(client, _go)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _lock_waiters() -> int:
    rows = await connections.get("default").execute_query_dict(
        "SELECT count(*) AS n FROM pg_stat_activity"
        " WHERE wait_event_type = 'Lock' AND datname = current_database()"
    )
    return int(rows[0]["n"])


async def _until_a_lock_waiter() -> None:
    deadline = time.monotonic() + 10
    while await _lock_waiters() < 1:
        assert time.monotonic() < deadline, "B never waited on the copy row lock"
        await _REAL_SLEEP(0.02)


async def _hold_lock(
    copy_id: UUID,
    locked: asyncio.Event,
    release: asyncio.Event,
    write: Callable[[FrozenCopy], Awaitable[None]],
) -> None:
    """Transaction A: lock the copy row, wait for the test, write, commit."""
    async with in_transaction():
        copy = await FrozenCopy.filter(id=copy_id).select_for_update().first()
        assert copy is not None
        locked.set()
        await release.wait()
        await write(copy)


def _race(
    client: TestClient,
    copy_id: UUID,
    write: Callable[[FrozenCopy], Awaitable[None]],
    b: Callable[[], Awaitable[MarkOutcome]],
) -> MarkOutcome:
    """A holds the lock; B starts and waits on it; A commits first; the result of B."""

    async def _go() -> MarkOutcome:
        locked, release = asyncio.Event(), asyncio.Event()
        holder = asyncio.create_task(_hold_lock(copy_id, locked, release, write))
        await asyncio.wait_for(locked.wait(), timeout=10)
        waiter = asyncio.ensure_future(b())
        try:
            await _until_a_lock_waiter()
        finally:
            release.set()
        await holder
        return await waiter

    return _run(client, _go)


def _late_mark(copy_id: UUID) -> Callable[[], Awaitable[MarkOutcome]]:
    async def _go() -> MarkOutcome:
        rule = IdleRule(open_idle_seconds=_IDLE_SECONDS, lock_timeout_ms=_LONG_LOCK_MS)
        return await rule.mark(copy_id, await database_now())

    return _go


async def _capture_one(copy: FrozenCopy) -> None:
    """The writes of `FrozenCopyStore.capture` under the lock A already holds."""
    copy.entry_seq += 1
    await copy.save(update_fields=["entry_seq"])
    await FrozenCopyEntry.create(
        frozen_copy_id=copy.id,
        kind="chat",
        case_key="",
        request_digest="d" * 64,
        request_json={"q": "late"},
        response_json={"a": "late"},
        status_code=200,
        seq=copy.entry_seq,
        occurrence=0,
    )


async def _seal(copy: FrozenCopy) -> None:
    """The writes of `FrozenCopyStore.seal` under the lock A already holds."""
    copy.entries = await FrozenCopyEntry.filter(frozen_copy_id=copy.id).count()
    copy.status = "sealed"
    copy.sealed_at = datetime.now(UTC)
    await copy.save(update_fields=["entries", "status", "sealed_at"])


def test_database_now_is_aware_utc(pg_client: TestClient) -> None:
    now = _run(pg_client, database_now)

    assert now.tzinfo is not None
    assert abs(now - datetime.now(UTC)) < timedelta(seconds=60)


def test_a_capture_that_commits_first_keeps_the_copy_open(pg_client: TestClient) -> None:
    copy_id = _seed(pg_client, 2)

    outcome = _race(pg_client, copy_id, _capture_one, _late_mark(copy_id))

    assert outcome == "rule no longer true"
    copy, entries = _state(pg_client, copy_id)
    assert copy.status == "open"
    assert copy.swept_at is None
    assert copy.entry_seq == 3
    assert entries == 3


def test_a_seal_that_commits_first_keeps_the_copy_sealed(pg_client: TestClient) -> None:
    copy_id = _seed(pg_client, 2)

    outcome = _race(pg_client, copy_id, _seal, _late_mark(copy_id))

    assert outcome == "rule no longer true"
    copy, entries = _state(pg_client, copy_id)
    assert copy.status == "sealed"
    assert copy.swept_at is None
    assert copy.entries == 2
    assert entries == 2


def test_two_marks_of_one_copy_mark_it_one_time(pg_client: TestClient) -> None:
    copy_id = _seed(pg_client, 2)
    first_mark_at = _run(pg_client, database_now) - timedelta(seconds=5)

    async def _first_mark(copy: FrozenCopy) -> None:
        copy.status = "abandoned"
        copy.swept_at = first_mark_at
        copy.entries = copy.entry_seq
        await copy.save(update_fields=["status", "swept_at", "entries"])

    outcome = _race(pg_client, copy_id, _first_mark, _late_mark(copy_id))

    assert outcome == "rule no longer true"
    copy, entries = _state(pg_client, copy_id)
    assert copy.status == "abandoned"
    assert _aware(copy.swept_at) == first_mark_at
    assert entries == 2

    other_id = _seed(pg_client, 1)

    async def _both() -> list[MarkOutcome]:
        rule = IdleRule(open_idle_seconds=_IDLE_SECONDS, lock_timeout_ms=_LONG_LOCK_MS)
        at = await database_now()
        return list(await asyncio.gather(rule.mark(other_id, at), rule.mark(other_id, at)))

    assert sorted(_run(pg_client, _both)) == ["marked", "rule no longer true"]
    other, _ = _state(pg_client, other_id)
    assert other.status == "abandoned"


def test_a_mark_skips_a_copy_whose_lock_is_held_too_long(pg_client: TestClient) -> None:
    copy_id = _seed(pg_client, 2)

    async def _no_write(_copy: FrozenCopy) -> None:
        return None

    async def _go() -> tuple[MarkOutcome, dict[str, dict[str, int]]]:
        locked, release = asyncio.Event(), asyncio.Event()
        holder = asyncio.create_task(_hold_lock(copy_id, locked, release, _no_write))
        await asyncio.wait_for(locked.wait(), timeout=10)
        try:
            rule = IdleRule(open_idle_seconds=_IDLE_SECONDS, lock_timeout_ms=_SHORT_LOCK_MS)
            outcome = await rule.mark(copy_id, await database_now())
            report = await _sweep(lock_timeout_ms=_SHORT_LOCK_MS).run_pass(trigger="command")
        finally:
            release.set()
        await holder
        return outcome, report.skipped

    outcome, skipped = _run(pg_client, _go)

    assert outcome == "lock timeout"
    assert skipped == {"abandoned": {"lock timeout": 1}}
    copy, entries = _state(pg_client, copy_id)
    assert copy.status == "open"
    assert copy.swept_at is None
    assert entries == 2


class _Rollback(Exception):
    """Ends transaction A with a rollback."""


def test_two_purges_delete_each_entry_one_time(pg_client: TestClient) -> None:
    copy_id = _seed(pg_client, 7)
    assert _mark(pg_client, copy_id) == "marked"

    async def _drain(sweep: FrozenCopySweep) -> int:
        total = 0
        while (deleted := await sweep.purge_chunk(copy_id)) > 0:
            total += deleted
            await _yield_sleep(0)
        return total

    async def _two_purges() -> list[int]:
        first, second = _sweep(chunk_size=2), _sweep(chunk_size=2)
        return list(await asyncio.gather(_drain(first), _drain(second)))

    assert sum(_run(pg_client, _two_purges)) == 7
    _, entries = _state(pg_client, copy_id)
    assert entries == 0

    held_id = _seed(pg_client, 2)
    assert _mark(pg_client, held_id) == "marked"

    async def _held_purge() -> tuple[int, int, bool]:
        locked, release = asyncio.Event(), asyncio.Event()
        held: list[int] = []

        async def _holder() -> None:
            try:
                async with in_transaction() as conn:
                    deleted, _ = await conn.execute_query(_PURGE_CHUNK_SQL, [held_id, 10])
                    held.append(deleted)
                    locked.set()
                    await release.wait()
                    raise _Rollback
            except _Rollback:
                return None

        holder = asyncio.create_task(_holder())
        await asyncio.wait_for(locked.wait(), timeout=10)
        try:
            sweep = _sweep(chunk_size=2)
            purged = await sweep.purge_chunk(held_id)
            finished = await sweep.finish_purge(held_id, await database_now())
        finally:
            release.set()
        await holder
        return held[0], purged, finished

    assert _run(pg_client, _held_purge) == (2, 0, False)
    copy, entries = _state(pg_client, held_id)
    assert copy.purged_at is None
    assert entries == 2

    _run(pg_client, lambda: _sweep().run_pass(trigger="command"))

    copy, entries = _state(pg_client, held_id)
    assert copy.purged_at is not None
    assert entries == 0
