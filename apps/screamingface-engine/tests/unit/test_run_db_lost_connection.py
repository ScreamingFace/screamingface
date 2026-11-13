"""E5 P2 spec R1: what Postgres raises through Tortoise when it drops a query's connection.

FEATURE: a detached Run (OME-1837). STORY: as a researcher whose Run is being started while the
database restarts, my Candidates wait and start, and none fails for the database's blip.

WHY real backends killed: `UNAVAILABLE_ERRORS` names asyncpg classes that Tortoise lets through
unwrapped, and only a real lost connection shows which ones it does.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
)
from tortoise import connections
from tortoise.transactions import in_transaction

from screamingface_engine.runs.db import CONNECTION, UNAVAILABLE_ERRORS

pytestmark = pytest.mark.asyncio

_POSTGRES = [db for db in DATABASES if db.id == "postgres"]


@pytest_asyncio.fixture(params=_POSTGRES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


async def _kill_others(url: str) -> None:
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE pid <> pg_backend_pid() AND datname = current_database()"
        )
    finally:
        await conn.close()


async def _plain() -> None:
    await connections.get(CONNECTION).execute_query("SELECT pg_sleep(4)")


async def _in_transaction() -> None:
    async with in_transaction(CONNECTION) as conn:
        await conn.execute_query("SELECT pg_sleep(4)")


@pytest.mark.parametrize("query", [_plain, _in_transaction], ids=["plain", "in-transaction"])
async def test_a_query_whose_connection_is_dropped_raises_an_unavailable_error(
    registry: Registry, query: Callable[[], Awaitable[None]]
) -> None:
    task = asyncio.ensure_future(query())
    await asyncio.sleep(0.6)
    await _kill_others(registry.url)

    with pytest.raises(UNAVAILABLE_ERRORS):
        await task
