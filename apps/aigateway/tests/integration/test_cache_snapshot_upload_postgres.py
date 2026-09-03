"""Postgres evidence for the admin cache-snapshot loader (OME-952).

The COPY/merge engine is pinned HERE, against the dialect it exists for, because every
property it guarantees is a Postgres property: the COPY text round trip (byte-identical
``response_json`` after re-feeding a real ``pg_dump``), the merge's column split (content
from the snapshot, identity and serving history from the live row), the replace guard, and
the staging lifecycle. The unit modules pin the DECISIONS around these; this module pins the
behaviour itself, using a genuine ``pg_dump`` of a populated table as its fixture — no
hand-crafted approximation of the format, the format.

Run with: ``AIGW_TEST_PG=1 uv run pytest -m needs_postgres``
"""

from __future__ import annotations

import asyncio
import hashlib
import json
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

from aigateway.core.request_cache.bulk_loader import (
    ReplaceGuardBlocked,
    StagedRowCountMismatch,
    load_snapshot,
)
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.store import RequestCacheWrite, TortoiseRequestCacheStore
from aigateway.core.request_cache.upload_job import CacheUploadRunner, UploadAcceptance
from aigateway.db import close_db, init_db

pytestmark = pytest.mark.needs_postgres

_APP_DIR = Path(__file__).resolve().parents[2]


def _database_url(postgres: PostgresContainer) -> str:
    return (
        f"postgres://{postgres.username}:{quote(postgres.password, safe='')}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}"
        f"/{postgres.dbname}"
    )


def _migrate(database_url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tortoise", "-c", "aigateway.db.TORTOISE_CONFIG", "migrate"],
        cwd=_APP_DIR,
        env={**os.environ, "AIGATEWAY_DATABASE_URL": database_url},
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def migrated_postgres() -> Generator[str, None, None]:
    if os.environ.get("AIGW_TEST_PG") != "1":
        pytest.skip("AIGW_TEST_PG=1 not set")
    with PostgresContainer("postgres:16-alpine", driver=None) as postgres:
        database_url = _database_url(postgres)
        _migrate(database_url)
        yield database_url


@asynccontextmanager
async def _db(database_url: str) -> AsyncIterator[TortoiseRequestCacheStore]:
    await close_db()
    await init_db(database_url)
    raw = await asyncpg.connect(database_url)  # type: ignore[arg-type]
    try:
        await RequestCacheEntry.all().delete()
        await raw.execute("DROP TABLE IF EXISTS request_cache_entries_staging")
        yield TortoiseRequestCacheStore()
    finally:
        await raw.close()
        await close_db()


def _write(
    key_hash: str, response: dict, *, model: str = "openrouter/openai/gpt-5.5"
) -> RequestCacheWrite:
    payload = json.dumps(response, separators=(",", ":"), ensure_ascii=False)
    return RequestCacheWrite(
        key_hash=key_hash,
        prompt_hash="p" * 64,
        provider="openrouter",
        model=model,
        response=response,
        response_size_bytes=len(payload.encode()),
    )


HOSTILE_PAYLOAD = {
    "id": "cmpl-x",
    "choices": [
        {
            "message": {
                "content": (
                    'line1\nline2\twith tabs and \\ backslash and "quotes" and unicode: déjà 🚀'
                ),
            }
        }
    ],
    "usage": {"total_tokens": 42, "cost": 0.000717},
}


def _dump_table(database_url: str, out: Path) -> int:
    """A genuine single-table pg_dump — the fixture IS the production snapshot format.

    The row count is taken with the SAME slicer the loader uses, so the fixture and the
    production path cannot disagree about what a data line is.
    """
    subprocess.run(
        [
            "pg_dump",
            "--data-only",
            "--no-owner",
            "--no-privileges",
            "-t",
            "request_cache_entries",
            "--file",
            str(out),
            database_url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    from aigateway.core.request_cache.snapshot import CopyBlockSource, open_snapshot_stream

    with open_snapshot_stream(out) as stream:
        source = CopyBlockSource(stream)
        source.header()
        return sum(1 for _ in source.data_lines())


@pytest.mark.asyncio
async def test_a_real_pg_dump_round_trips_and_merges(migrated_postgres, tmp_path) -> None:
    async with _db(migrated_postgres) as store:
        # Three rows live here; the dump we will reload is taken after they exist.
        for key, response in (
            ("a" * 64, {"v": 1}),
            ("b" * 64, HOSTILE_PAYLOAD),
            ("c" * 64, {"v": 3}),
        ):
            await store.set_if_absent(_write(key, response))

        dump = tmp_path / "snapshot.sql"
        rows = _dump_table(migrated_postgres, dump)
        assert rows >= 3

        # Simulate the source deployment DIVERGING from ours: after the snapshot, we add a
        # local-only row and mutate one the snapshot also holds.
        await store.set_if_absent(_write("d" * 64, {"v": 4, "local": True}))
        await RequestCacheEntry.filter(key_hash="a" * 64).update(model="openrouter/other/model")

        outcome = await load_snapshot(
            dump,
            mode="merge",
            expected_rows=None,
            acknowledge_loss=False,
        )
        assert outcome.staged_rows >= 3
        assert outcome.live_before == 4
        assert outcome.live_after == 4  # nothing new: every dumped key already existed

        # Merge semantics: content from the snapshot, identity/history local.
        overwritten = await RequestCacheEntry.get(key_hash="a" * 64)
        assert overwritten.model == "openrouter/openai/gpt-5.5"  # snapshot wins on content
        assert overwritten.hit_count == 0  # local history survives
        kept = await RequestCacheEntry.get(key_hash="d" * 64)
        assert kept is not None  # merge never deletes a live row

        # Byte-identity: the hostile payload crossed a dump + COPY round trip untouched.
        hostile = await RequestCacheEntry.get(key_hash="b" * 64)
        decoded = json.loads(hostile.response_json)
        assert (
            decoded["choices"][0]["message"]["content"]
            == HOSTILE_PAYLOAD["choices"][0]["message"]["content"]
        )

        # Staging is cleaned out behind the load.
        raw = await asyncpg.connect(migrated_postgres)  # type: ignore[arg-type]
        try:
            staged = await raw.fetchval("SELECT count(*) FROM request_cache_entries_staging")
        finally:
            await raw.close()
        assert staged == 0


@pytest.mark.asyncio
async def test_merge_inserts_new_keys_with_fresh_ids(migrated_postgres, tmp_path) -> None:
    async with _db(migrated_postgres) as store:
        await store.set_if_absent(_write("a" * 64, {"v": 1}))
        dump = tmp_path / "snapshot.sql"
        _dump_table(migrated_postgres, dump)
        await RequestCacheEntry.all().delete()  # simulate a cold deployment receiving the snapshot

        outcome = await load_snapshot(
            dump, mode="merge", expected_rows=None, acknowledge_loss=False
        )
        assert outcome.live_before == 0
        assert outcome.live_after == outcome.staged_rows
        assert await RequestCacheEntry.all().count() == outcome.staged_rows


@pytest.mark.asyncio
async def test_replace_refuses_to_lose_newer_rows_until_acknowledged(
    migrated_postgres, tmp_path
) -> None:
    async with _db(migrated_postgres) as store:
        await store.set_if_absent(_write("a" * 64, {"v": 1}))
        dump = tmp_path / "snapshot.sql"
        _dump_table(migrated_postgres, dump)
        await store.set_if_absent(_write("b" * 64, {"v": "written after the snapshot"}))

        with pytest.raises(ReplaceGuardBlocked) as guard:
            await load_snapshot(dump, mode="replace", expected_rows=None, acknowledge_loss=False)
        assert guard.value.live == 2 and guard.value.staged == 1
        assert await RequestCacheEntry.all().count() == 2  # refused: nothing changed

        outcome = await load_snapshot(
            dump, mode="replace", expected_rows=None, acknowledge_loss=True
        )
        assert outcome.live_after == 1
        only = await RequestCacheEntry.get(key_hash="a" * 64)
        assert only is not None


@pytest.mark.asyncio
async def test_a_manifest_row_count_mismatch_refuses_before_any_live_write(
    migrated_postgres, tmp_path
) -> None:
    async with _db(migrated_postgres) as store:
        await store.set_if_absent(_write("a" * 64, {"v": 1}))
        dump = tmp_path / "snapshot.sql"
        _dump_table(migrated_postgres, dump)
        with pytest.raises(StagedRowCountMismatch):
            await load_snapshot(dump, mode="merge", expected_rows=999, acknowledge_loss=False)
        assert await RequestCacheEntry.all().count() == 1


@pytest.mark.asyncio
async def test_the_runner_end_to_end_against_real_postgres(migrated_postgres, tmp_path) -> None:
    """The route's runner, the route's digest source, real COPY: the whole unit in one flow."""
    async with _db(migrated_postgres) as store:
        await store.set_if_absent(_write("a" * 64, {"v": 1}))
        dump = tmp_path / "snapshot.sql"
        rows = _dump_table(migrated_postgres, dump)

        digest = hashlib.sha256(dump.read_bytes()).hexdigest()
        manifest = json.dumps(
            {
                "schema": "screamingface.cache-snapshot.v1",
                "generated_at": "2026-08-23",
                "row_count": rows,
                "sha256": digest,
                "revisions": {
                    "parameter_contract": "aigw-parameter-contract-2026-08b",
                    "openrouter_adapter": "openrouter-global-cache-2026-08d",
                },
            }
        ).encode()

        # Importing the plugin registers its adapter revision exactly as production wiring
        # (main.load_plugins) does — the manifest check must see the deployed constants.
        import aigateway.plugins.openrouter_provider.global_cache  # noqa: F401
        from aigateway.core.request_cache.revisions import active_cache_revisions

        assert active_cache_revisions()["openrouter_adapter"]
        runner = CacheUploadRunner(revisions=active_cache_revisions)
        record = runner.start(
            UploadAcceptance(
                upload_path=dump,
                sha256_hex=digest,
                actual_bytes=dump.stat().st_size,
                manifest_raw=manifest,
                mode="merge",
                force=False,
                acknowledge_loss=False,
                actor="admin@openmined.org",
            )
        )
        task = runner._task
        assert task is not None
        await asyncio.wait_for(asyncio.gather(task), timeout=60)
        assert record.state == "complete", record.error
        assert record.manifest_present is True
        assert record.staged_rows == rows
