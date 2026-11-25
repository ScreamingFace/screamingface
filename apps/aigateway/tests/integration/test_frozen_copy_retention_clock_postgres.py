"""S-33 on Postgres: migration 0019 stamps each sealed copy with one aware UTC time (OME-1947,
spec erd.md section 5, prd/copy-sweep.md S-33).

This module has its own container: the sweep tests share one module database, and a downgrade
there would remove a column under them.

Run with: ``AIGW_TEST_PG=1 uv run pytest -m needs_postgres``
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]
_PREVIOUS = "0018_frozen_copy_retention"
_READ_SCRIPT = """
import asyncio, json, sys
from tortoise import Tortoise
from aigateway.db import build_tortoise_config

async def main():
    await Tortoise.init(config=build_tortoise_config(sys.argv[1]), _enable_global_fallback=True)
    try:
        from aigateway.core.frozen_copy.models import FrozenCopy
        rows = []
        for copy in await FrozenCopy.all():
            value = copy.retention_from
            rows.append({"id": str(copy.id), "status": copy.status,
                         "value": None if value is None else value.isoformat(),
                         "aware": value is not None and value.tzinfo is not None})
        print(json.dumps(rows))
    finally:
        await Tortoise.close_connections()

asyncio.run(main())
"""


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


def _tortoise(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", *args],
        cwd=_APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


def _read_through_model(database_url: str) -> dict[str, dict[str, object]]:
    result = subprocess.run(
        [sys.executable, "-c", _READ_SCRIPT, database_url],
        cwd=_APP_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads(result.stdout.strip().splitlines()[-1])
    return {row["id"]: row for row in rows}


async def _seed(database_url: str) -> tuple[UUID, UUID, UUID]:
    account_id = uuid4()
    sealed_a, sealed_b, open_c = uuid4(), uuid4(), uuid4()
    created = datetime(2026, 1, 1, tzinfo=UTC)
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(
            "insert into accounts (id, username, password_hash, created_at, is_active)"
            " values ($1, 'u1', 'x', now(), true)",
            account_id,
        )
        for copy_id, status, sealed_at in (
            (sealed_a, "sealed", datetime(2026, 1, 2, tzinfo=UTC)),
            (sealed_b, "sealed", datetime(2026, 1, 3, tzinfo=UTC)),
            (open_c, "open", None),
        ):
            await conn.execute(
                "insert into frozen_copies"
                " (id, account_id, status, entries, entry_seq, created_at, sealed_at)"
                " values ($1, $2, $3, 0, 0, $4, $5)",
                copy_id,
                account_id,
                status,
                created,
                sealed_at,
            )
    finally:
        await conn.close()
    return sealed_a, sealed_b, open_c


async def _is_nullable(database_url: str) -> str:
    conn = await asyncpg.connect(database_url)
    try:
        return await conn.fetchval(
            "select is_nullable from information_schema.columns"
            " where table_name = 'frozen_copies' and column_name = 'retention_from'"
        )
    finally:
        await conn.close()


def test_0019_stamps_each_sealed_copy_on_postgres(postgres_database_url: str) -> None:
    url = postgres_database_url
    _tortoise(url, "downgrade", "models", _PREVIOUS)
    sealed_a, sealed_b, open_c = asyncio.run(_seed(url))
    started = datetime.now(UTC)
    _tortoise(url, "migrate")
    ended = datetime.now(UTC)

    rows = _read_through_model(url)
    row_a, row_b = rows[str(sealed_a)], rows[str(sealed_b)]
    assert row_a["aware"] is True
    assert row_b["aware"] is True
    value = row_a["value"]
    assert isinstance(value, str)
    assert row_b["value"] == value
    assert started <= datetime.fromisoformat(value) <= ended
    assert rows[str(open_c)]["value"] is None
    assert asyncio.run(_is_nullable(url)) == "YES"
