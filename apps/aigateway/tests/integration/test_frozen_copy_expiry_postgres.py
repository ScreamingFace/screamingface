"""PostgreSQL proof for the expiry rule of the frozen copy sweep.

OME-1947, prd/copy-sweep.md S-4, S-14; erd.md section 2.6.

SQLite ignores `select_for_update` and has no query planner that this check can read, so the
unit suite cannot prove that a claim which commits first wins over the expiry mark, or that the
candidate query can use the index on `(status, purged_at)`. The race has a fixed order: the
claim in transaction A takes the copy row lock and waits; the test starts B and checks that B
waits on that lock; the test lets A commit; the test reads the result string of B.

The module shares one database, so each test makes its own copies.

Run with: ``AIGW_TEST_PG=1 uv run pytest -m needs_postgres``
"""

from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import sys
import time
from collections.abc import Callable, Coroutine, Generator
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
from aigateway.core.frozen_copy.sweep import database_now
from aigateway.core.frozen_copy.sweep_rules import ExpiryRule, MarkOutcome
from aigateway.main import create_app

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]
_TTL_S = 7_776_000
_TTL = timedelta(seconds=_TTL_S)
# WHY 10 s: A must commit before B gives up, or B reports "lock timeout" and the copy keeps its
# state with no check under the lock (prd/copy-sweep.md section 7).
_LONG_LOCK_MS = 10_000
# WHY bound at import: some tests patch the global asyncio.sleep.
_REAL_SLEEP = asyncio.sleep


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


def _seed_sealed(client: TestClient, entries: int, **times: datetime | None) -> UUID:
    """A sealed copy of the signed-in account; `times` overwrite its time columns."""
    owner = UUID(client.get("/v1/auth/me").json()["id"])
    for value in times.values():
        assert value is None or value.tzinfo is UTC, "pass aware UTC values to update()"

    async def _go() -> UUID:
        frozen = FrozenCopyStore(max_entry_bytes=2_000_000)
        copy = await frozen.open(owner)
        for i in range(entries):
            await frozen.capture(copy, "chat", {"q": i}, {"a": i}, 200, case_key="", occurrence=0)
        assert await frozen.seal(copy.id, owner) is not None
        if times:
            await FrozenCopy.filter(id=copy.id).update(**times)
        return copy.id

    return _run(client, _go)


def _state(client: TestClient, copy_id: UUID) -> tuple[FrozenCopy, int]:
    async def _go() -> tuple[FrozenCopy, int]:
        copy = await FrozenCopy.get(id=copy_id)
        return copy, await FrozenCopyEntry.filter(frozen_copy_id=copy_id).count()

    return _run(client, _go)


def test_s14_a_claim_that_commits_first_keeps_the_copy_sealed(pg_client: TestClient) -> None:
    copy_id = _seed_sealed(pg_client, 2, sealed_at=datetime.now(UTC) - timedelta(days=91))

    async def _claim_and_hold(locked: asyncio.Event, release: asyncio.Event) -> None:
        """Transaction A: the claim locks the copy row; the lock stays until the outer commit."""
        async with in_transaction():
            outcome = await FrozenCopyStore(max_entry_bytes=2_000_000).claim(copy_id)
            assert outcome is not None and outcome.first
            locked.set()
            await release.wait()

    async def _go() -> MarkOutcome:
        locked, release = asyncio.Event(), asyncio.Event()
        holder = asyncio.create_task(_claim_and_hold(locked, release))
        await asyncio.wait_for(locked.wait(), timeout=10)
        at = await database_now()
        rule = ExpiryRule(unclaimed_ttl_seconds=_TTL_S, lock_timeout_ms=_LONG_LOCK_MS)
        waiter = asyncio.ensure_future(rule.mark(copy_id, at))
        try:
            await _until_a_lock_waiter()
        finally:
            release.set()
        await holder
        return await waiter

    outcome = _run(pg_client, _go)

    assert outcome == "rule no longer true"
    copy, entries = _state(pg_client, copy_id)
    assert copy.status == "sealed"
    assert copy.claimed_at is not None
    assert copy.swept_at is None
    assert entries == 2


def test_s4_candidates_on_postgres_follow_the_clock_start(pg_client: TestClient) -> None:
    now = _run(pg_client, database_now).astimezone(UTC)
    x_start = now - timedelta(days=10)
    x_id = _seed_sealed(pg_client, 1, retention_from=x_start, sealed_at=now - timedelta(days=200))
    y_sealed = now - timedelta(days=10)
    y_id = _seed_sealed(pg_client, 1, sealed_at=y_sealed)
    z_id = _seed_sealed(pg_client, 1, claimed_at=now, sealed_at=now - timedelta(days=400))
    rule = ExpiryRule(unclaimed_ttl_seconds=_TTL_S)

    def _found(at: datetime) -> set[UUID]:
        async def _go() -> set[UUID]:
            return {candidate.copy_id for candidate in await rule.candidates(at)}

        # WHY the filter: the module database is shared, so other tests add their own copies.
        return _run(pg_client, _go) & {x_id, y_id, z_id}

    assert _found(now) == set()
    assert x_id not in _found(x_start + _TTL - timedelta(seconds=1))
    assert x_id in _found(x_start + _TTL)
    assert y_id not in _found(y_sealed + _TTL - timedelta(seconds=1))
    assert y_id in _found(y_sealed + _TTL)
    assert z_id not in _found(now + timedelta(days=1000))


def test_the_candidate_query_can_use_the_status_index(pg_client: TestClient) -> None:
    async def _go() -> tuple[list[dict[str, Any]], str]:
        name_rows = await connections.get("default").execute_query_dict(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'frozen_copies'"
            " AND indexdef LIKE '%(status, purged_at)%'"
        )
        async with in_transaction() as conn:
            # WHY: the test table is small, so without the SET the planner takes a sequential
            # scan; the test proves that the index can serve the query, not that it must.
            await conn.execute_script("SET LOCAL enable_seqscan = off")
            rows = (
                await ExpiryRule(unclaimed_ttl_seconds=_TTL_S)
                ._candidates_query(datetime.now(UTC))
                .using_db(conn)
                .explain(output_fmt="text")
            )
        return name_rows, "\n".join(str(row["QUERY PLAN"]) for row in rows)

    name_rows, plan = _run(pg_client, _go)

    assert len(name_rows) == 1
    assert name_rows[0]["indexname"] in plan
    assert "Seq Scan" not in plan
