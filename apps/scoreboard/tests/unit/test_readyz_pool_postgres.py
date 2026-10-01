"""`/readyz` stays ready while the asyncpg request pool is saturated (OME-1452).

WHY this needs PostgreSQL: the flap the ticket names is asyncpg pool exhaustion — a probe queued
behind `maxsize` held connections past its 2 s cap. SQLite has no pool, so `test_db_pool.py` can
only show the single-connection analogue; this file holds every connection of a real pool.

WHY a self-contained connection: the same reason `test_delete_scores_postgres.py` gives
(OME-430). Runs only when SCOREBOARD_TEST_DATABASE_URL is set; skips otherwise.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack

import pytest
import pytest_asyncio
from tortoise import connections

from scoreboard.db import PoolSize, close_db, init_db
from scoreboard.routes import health

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.getenv("SCOREBOARD_TEST_DATABASE_URL", "").startswith("postgres"),
        reason="requires PostgreSQL",
    ),
]

DATABASE_URL = os.getenv("SCOREBOARD_TEST_DATABASE_URL", "")
POOL = PoolSize(minsize=1, maxsize=3)


async def _saturate(stack: AsyncExitStack) -> None:
    """Check out every connection the request pool may hand out, and keep them."""
    client = connections.get("default")
    for _ in range(POOL.maxsize):
        await stack.enter_async_context(client.acquire_connection())
    # INVARIANT of the setup: the pool really is exhausted, so a pass below is not vacuous.
    pool = client._pool  # noqa: SLF001 — the asyncpg pool; Tortoise exposes no public handle
    assert pool is not None
    assert pool.get_max_size() == POOL.maxsize
    assert pool.get_idle_size() == 0
    assert pool.get_size() == POOL.maxsize


@pytest_asyncio.fixture
async def server_db() -> AsyncIterator[None]:
    await init_db(DATABASE_URL, pool=POOL)
    try:
        yield
    finally:
        await close_db()


async def test_readyz_stays_ready_with_the_request_pool_exhausted(
    server_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # STORY: as the operator, a load spike holding every pooled connection leaves the pod Ready.
    monkeypatch.setattr(health, "PROBE_TIMEOUT_S", 0.5)

    async with AsyncExitStack() as stack:
        await _saturate(stack)
        response = await health.readyz()

    assert response.status_code == 200


async def test_a_probe_on_the_request_pool_times_out_when_it_is_exhausted(
    server_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Control: the exact flap OME-1452 describes, reproduced on the pool the probe used to share.
    monkeypatch.setattr(health, "PROBE_TIMEOUT_S", 0.5)
    monkeypatch.setattr(health, "READINESS_CONNECTION", "default")

    async with AsyncExitStack() as stack:
        await _saturate(stack)
        response = await health.readyz()

    assert response.status_code == 503
