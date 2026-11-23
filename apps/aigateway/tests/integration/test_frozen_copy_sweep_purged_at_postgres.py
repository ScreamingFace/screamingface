"""PostgreSQL evidence that `purged_at` is the database time of the completion update (OME-1947).

Review finding 2 of pull request 1911: a delayed probe on PostgreSQL stored a `purged_at` before
the end of the purge, because the run passed the time it read at its start to each completion
update. Here the pause between chunks is real, and the test reads the database clock after each
delete.

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

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from testcontainers.postgres import PostgresContainer

from aigateway.config import Settings
from aigateway.core.frozen_copy.models import FrozenCopy, FrozenCopyEntry
from aigateway.core.frozen_copy.store import FrozenCopyStore
from aigateway.core.frozen_copy.sweep import FrozenCopySweep, IdleRule, database_now
from aigateway.main import create_app

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]
# WHY bound at import: some tests patch the global asyncio.sleep.
_REAL_SLEEP = asyncio.sleep
# WHY 300 ms: longer than the configured 200 ms pause, short enough for a fast test; the run
# reads its time before the first of three such pauses.
_PAUSE_S = 0.3


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
            [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", "migrate"],
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
    with TestClient(create_app(settings)) as client:
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


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _real_pause(_delay: float) -> None:
    await _REAL_SLEEP(_PAUSE_S)


def _seed_idle_copy(client: TestClient, entries: int) -> UUID:
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


def test_purged_at_is_not_before_the_last_delete_of_a_delayed_purge(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy_id = _seed_idle_copy(pg_client, 3)
    sweep = FrozenCopySweep(
        [IdleRule(open_idle_seconds=86_400)],
        max_entries=100_000,
        chunk_size=1,
        sleep=_real_pause,
    )
    real = sweep.purge_chunk
    deleted_at: list[datetime] = []

    async def _timed(chunk_copy_id: UUID, *, limit: int | None = None) -> int:
        deleted = await real(chunk_copy_id, limit=limit)
        if deleted > 0 and chunk_copy_id == copy_id:
            deleted_at.append(await database_now())
        return deleted

    monkeypatch.setattr(sweep, "purge_chunk", _timed)

    _run(pg_client, lambda: sweep.run_pass(trigger="command"))

    async def _read() -> tuple[FrozenCopy, int]:
        copy = await FrozenCopy.get(id=copy_id)
        return copy, await FrozenCopyEntry.filter(frozen_copy_id=copy_id).count()

    copy, entries = _run(pg_client, _read)
    assert entries == 0
    assert len(deleted_at) == 3
    assert copy.purged_at is not None
    assert _aware(copy.purged_at) >= deleted_at[-1]
    # The mark time stays the time of the run: the fix changes only purged_at.
    assert copy.swept_at is not None
    assert _aware(copy.swept_at) < deleted_at[0]
