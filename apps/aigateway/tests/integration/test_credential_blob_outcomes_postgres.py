"""PostgreSQL concurrency evidence for the credential operational outcome register.

Run with ``AIGW_TEST_PG=1 uv run pytest -m needs_postgres``.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import asyncpg  # type: ignore[import-untyped]
import pytest
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
from tortoise.migrations.api.migrate import migrate as _run_migration

from aigateway.core.credential_blob import ORMStore
from aigateway.core.credential_blob.model import CredentialBlob
from aigateway.core.secrets.local import LocalSecretStore
from aigateway.db import build_tortoise_config, close_db, init_db

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]
_SERVICE = "aigateway:openrouter:postgres-outcomes"
_ACCOUNT = "token"


def _database_url(postgres: PostgresContainer) -> str:
    return (
        f"postgres://{postgres.username}:{quote(postgres.password, safe='')}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}"
        f"/{postgres.dbname}"
    )


@pytest.fixture(scope="module")
def migrated_postgres() -> Generator[str, None, None]:
    if os.environ.get("AIGW_TEST_PG") != "1":
        pytest.skip("AIGW_TEST_PG=1 not set")
    with PostgresContainer("postgres:16-alpine", driver=None) as postgres:
        database_url = _database_url(postgres)
        subprocess.run(
            [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", "migrate"],
            cwd=_APP_DIR,
            env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
            check=True,
            capture_output=True,
            text=True,
        )
        yield database_url


@pytest.fixture(scope="module")
def postgres_at_0012() -> Generator[str, None, None]:
    if os.environ.get("AIGW_TEST_PG") != "1":
        pytest.skip("AIGW_TEST_PG=1 not set")
    with PostgresContainer("postgres:16-alpine", driver=None) as postgres:
        database_url = _database_url(postgres)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "tortoise",
                "-c",
                "aigateway.db.TORTOISE_CONFIG",
                "migrate",
                "models",
                "0012_provider_credential_slots",
            ],
            cwd=_APP_DIR,
            env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
            check=True,
            capture_output=True,
            text=True,
        )
        yield database_url


@asynccontextmanager
async def _store(database_url: str) -> AsyncIterator[ORMStore]:
    await close_db()
    await init_db(database_url)
    try:
        await CredentialBlob.all().delete()
        await CredentialBlob.create(service=_SERVICE, account=_ACCOUNT, value="ciphertext")
        yield ORMStore(LocalSecretStore(b"o" * 32))
    finally:
        await close_db()


async def _apply_migration_0013(database_url: str) -> None:
    await close_db()
    await init_db(database_url)
    try:
        await _run_migration(
            config=build_tortoise_config(database_url),
            app_labels=["models"],
            target="models.0013_credential_operational_outcomes",
        )
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_concurrent_dispatch_admissions_reserve_unique_sequences(
    migrated_postgres: str,
) -> None:
    async with _store(migrated_postgres) as store:
        observations = await asyncio.gather(
            *(store.begin_dispatch(_SERVICE, _ACCOUNT) for _ in range(16))
        )

        assert all(observation is not None for observation in observations)
        assert sorted(
            observation.dispatch_sequence for observation in observations if observation is not None
        ) == list(range(1, 17))


@pytest.mark.asyncio
async def test_out_of_order_and_prior_revision_completions_cannot_overwrite_newer_state(
    migrated_postgres: str,
) -> None:
    async with _store(migrated_postgres) as store:
        older = await store.begin_dispatch(_SERVICE, _ACCOUNT)
        newer = await store.begin_dispatch(_SERVICE, _ACCOUNT)
        assert older is not None and newer is not None

        await asyncio.gather(
            store.record_dispatch_outcome(newer, "connected"),
            store.record_dispatch_outcome(older, "needs_reauth"),
        )
        state = await store.operational_state(_SERVICE, _ACCOUNT)
        assert state is not None
        assert state.last_outcome_sequence == newer.dispatch_sequence
        assert state.outcome == "connected"

        await store.write(_SERVICE, _ACCOUNT, "replacement")
        assert await store.record_dispatch_outcome(newer, "needs_reauth") is False
        replacement = await store.operational_state(_SERVICE, _ACCOUNT)
        assert replacement is not None
        assert replacement.credential_revision == newer.credential_revision + 1
        assert replacement.outcome is None


@pytest.mark.asyncio
async def test_pre_0013_writer_resets_outcomes_without_double_incrementing_new_writes(
    migrated_postgres: str,
) -> None:
    async with _store(migrated_postgres) as store:
        observation = await store.begin_dispatch(_SERVICE, _ACCOUNT)
        assert observation is not None
        assert await store.record_dispatch_outcome(observation, "needs_reauth") is True

        old_writer = await asyncpg.connect(migrated_postgres)  # type: ignore[arg-type]
        try:
            await old_writer.execute(
                "UPDATE credential_blobs SET value = $1, ciphertext_version = $2 "
                "WHERE service = $3 AND account = $4",
                "old-binary-replacement",
                "v1",
                _SERVICE,
                _ACCOUNT,
            )
        finally:
            await old_writer.close()

        reset = await store.operational_state(_SERVICE, _ACCOUNT)
        assert reset is not None
        assert reset.credential_revision == observation.credential_revision + 1
        assert reset.next_dispatch_sequence == 0
        assert reset.last_outcome_sequence == 0
        assert reset.outcome is None
        assert reset.observed_at is None

        await store.write(_SERVICE, _ACCOUNT, "new-binary-replacement")
        current = await store.operational_state(_SERVICE, _ACCOUNT)
        assert current is not None
        assert current.credential_revision == reset.credential_revision + 1


@pytest.mark.asyncio
async def test_migration_gives_up_a_blocked_postgres_lock_queue(
    postgres_at_0012: str,
) -> None:
    blocker = await asyncpg.connect(postgres_at_0012)  # type: ignore[arg-type]
    try:
        await blocker.execute("BEGIN")
        await blocker.execute("SELECT * FROM credential_blobs")
        with pytest.raises(Exception) as caught:
            await asyncio.wait_for(_apply_migration_0013(postgres_at_0012), timeout=10.0)
    finally:
        await blocker.execute("ROLLBACK")
        await blocker.close()

    assert getattr(caught.value, "sqlstate", None) == "55P03"
    probe = await asyncpg.connect(postgres_at_0012)  # type: ignore[arg-type]
    try:
        columns = {
            row["column_name"]
            for row in await probe.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'credential_blobs'"
            )
        }
    finally:
        await probe.close()
    assert "credential_revision" not in columns
