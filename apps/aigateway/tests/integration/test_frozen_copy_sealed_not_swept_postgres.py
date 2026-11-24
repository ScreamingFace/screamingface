"""PostgreSQL proof that an old seal cannot resurrect a swept copy (OME-1947, PR #1911 finding 1).

During a mixed-version rollout an image before 0018 can run beside the new one. Its seal sets
`status = 'sealed'` on each copy that is not sealed. The reviewer's order: the new sweep marks a
copy `abandoned`, the old image seals it, the new purge then deletes every entry of a row that
says `sealed`. Migration 0018 adds `ck_frozen_copies_sealed_not_swept`, so the old seal fails
with an integrity error and the copy stays `abandoned`, also when earlier purge chunks have
already committed.

Run with: ``AIGW_TEST_PG=1 uv run pytest -m needs_postgres``
"""

from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import sys
from collections.abc import Callable, Coroutine, Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from testcontainers.postgres import PostgresContainer
from tortoise import connections
from tortoise.exceptions import IntegrityError

from aigateway.config import Settings
from aigateway.core.frozen_copy.models import FrozenCopy, FrozenCopyEntry
from aigateway.core.frozen_copy.store import FrozenCopyStore
from aigateway.core.frozen_copy.sweep import FrozenCopySweep, IdleRule, database_now
from aigateway.main import create_app

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]
_IDLE_SECONDS = 86_400
_CONSTRAINT = "ck_frozen_copies_sealed_not_swept"
# The seal of an image before 0018, reduced to its write: it seals each copy that is not sealed.
_OLD_SEAL_SQL = (
    "UPDATE frozen_copies SET status = 'sealed', sealed_at = now(), entries = entry_seq "
    "WHERE id = $1 AND status <> 'sealed'"
)


def _tortoise(database_url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", *args],
        cwd=_APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
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
        _tortoise(database_url, "migrate")
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
    portal = client.portal
    assert portal is not None
    return portal.call(call)


async def _no_sleep(_delay: float) -> None:
    return None


def _sweep(*, chunk_size: int = 500) -> FrozenCopySweep:
    return FrozenCopySweep(
        [IdleRule(open_idle_seconds=_IDLE_SECONDS)],
        max_entries=100_000,
        chunk_size=chunk_size,
        sleep=_no_sleep,
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


async def _old_seal(copy_id: UUID) -> int:
    updated, _ = await connections.get("default").execute_query(_OLD_SEAL_SQL, [copy_id])
    return int(updated)


def test_the_reviewer_interleaving_keeps_the_copy_abandoned(pg_client: TestClient) -> None:
    """Mark, one purge chunk commits, the old seal, then the rest of the purge."""
    copy_id = _seed(pg_client, 5)
    sweep = _sweep(chunk_size=2)

    async def _mark() -> str:
        return await IdleRule(open_idle_seconds=_IDLE_SECONDS).mark(copy_id, await database_now())

    assert _run(pg_client, _mark) == "marked"
    assert _run(pg_client, lambda: sweep.purge_chunk(copy_id)) == 2

    with pytest.raises(IntegrityError, match=_CONSTRAINT):
        _run(pg_client, lambda: _old_seal(copy_id))

    copy, entries = _state(pg_client, copy_id)
    assert copy.status == "abandoned"
    assert copy.sealed_at is None
    assert entries == 3

    _run(pg_client, lambda: sweep.run_pass(trigger="command"))

    copy, entries = _state(pg_client, copy_id)
    assert copy.status == "abandoned"
    assert copy.sealed_at is None
    assert copy.purged_at is not None
    assert entries == 0


def test_an_old_seal_before_the_mark_still_wins(pg_client: TestClient) -> None:
    """The reverse order is unchanged: a seal that commits first keeps the copy sealed."""
    copy_id = _seed(pg_client, 2)

    assert _run(pg_client, lambda: _old_seal(copy_id)) == 1
    _run(pg_client, lambda: _sweep().run_pass(trigger="command"))

    copy, entries = _state(pg_client, copy_id)
    assert copy.status == "sealed"
    assert copy.swept_at is None
    assert entries == 2


def test_0018_installs_the_check_constraint(pg_client: TestClient) -> None:
    async def _go() -> list[dict[str, Any]]:
        return await connections.get("default").execute_query_dict(
            "SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint "
            "WHERE conrelid = 'frozen_copies'::regclass AND contype = 'c'"
        )

    rows = _run(pg_client, _go)

    assert [row["conname"] for row in rows] == [_CONSTRAINT]
    assert "sealed" in rows[0]["def"]
    assert "swept_at IS NULL" in rows[0]["def"]


def test_0018_downgrade_drops_the_constraint_and_upgrade_restores_it(
    postgres_database_url: str,
) -> None:
    """Runs last in this module: it leaves the database migrated again."""

    async def _names() -> list[str]:
        conn = await asyncpg.connect(postgres_database_url)
        try:
            rows = await conn.fetch(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'frozen_copies'::regclass AND contype = 'c'"
            )
            return [row["conname"] for row in rows]
        finally:
            await conn.close()

    _tortoise(postgres_database_url, "downgrade", "models", "0017_drop_migration_note")
    assert asyncio.run(_names()) == []

    _tortoise(postgres_database_url, "migrate")
    assert asyncio.run(_names()) == [_CONSTRAINT]
