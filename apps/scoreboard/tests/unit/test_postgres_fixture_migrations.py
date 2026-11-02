"""OME-430: real PostgreSQL isolation and migration-created deduplication constraints."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from tortoise import Tortoise

from scoreboard.db import build_tortoise_config
from scoreboard.scores.models import Benchmark

pytestmark = pytest.mark.skipif(
    not os.getenv("SCOREBOARD_TEST_DATABASE_URL"), reason="requires PostgreSQL"
)


@pytest.mark.asyncio
@pytest.mark.parametrize("iteration", [1, 2])
async def test_shared_fixture_uses_a_fresh_postgres_schema(
    tortoise_db: None, iteration: int
) -> None:
    assert Tortoise.get_connection("default").capabilities.dialect == "postgres"
    assert await Benchmark.all().count() == 0
    await Benchmark.create(id="isolation-sentinel", display_name=f"Iteration {iteration}")
    assert await Benchmark.all().count() == 1


async def _unique_hash_indexes(database_url: str) -> list[dict[str, object]]:
    await Tortoise.init(config=build_tortoise_config(database_url))
    try:
        return await Tortoise.get_connection("default").execute_query_dict(
            """SELECT idx.relname AS indexname
               FROM pg_index AS i
               JOIN pg_class AS tbl ON tbl.oid = i.indrelid
               JOIN pg_namespace AS ns ON ns.oid = tbl.relnamespace
               JOIN pg_class AS idx ON idx.oid = i.indexrelid
               JOIN pg_attribute AS attr ON attr.attrelid = tbl.oid
                 AND attr.attname = 'content_hash'
               WHERE ns.nspname = current_schema() AND tbl.relname = 'scores'
                 AND i.indisunique AND i.indisvalid AND i.indisready
                 AND i.indpred IS NULL AND i.indexprs IS NULL
                 AND i.indnkeyatts = 1 AND i.indkey[0] = attr.attnum"""
        )
    finally:
        await Tortoise.close_connections()


def test_real_postgres_migrations_create_unique_content_hash(
    postgres_schema_database_url: str,
) -> None:
    # WHY: generate_schemas proves model declarations, not deployable migration history.
    app = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "tortoise", "-c", "scoreboard.db.TORTOISE_CONFIG", "migrate"],
        cwd=app,
        env={**os.environ, "SCOREBOARD_DATABASE_URL": postgres_schema_database_url},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert asyncio.run(_unique_hash_indexes(postgres_schema_database_url))


async def _install_probe_index(database_url: str, definition: str) -> None:
    await Tortoise.init(config=build_tortoise_config(database_url))
    try:
        connection = Tortoise.get_connection("default")
        await connection.execute_script("CREATE TABLE scores (content_hash TEXT, other TEXT)")
        await connection.execute_script(definition)
    finally:
        await Tortoise.close_connections()


@pytest.mark.parametrize(
    "definition,qualifies",
    [
        ("CREATE INDEX probe ON scores (content_hash)", False),
        ("CREATE UNIQUE INDEX probe ON scores (content_hash) WHERE other IS NOT NULL", False),
        ("CREATE UNIQUE INDEX probe ON scores (content_hash, other)", False),
        ("CREATE UNIQUE INDEX probe ON scores (lower(content_hash))", False),
        ("CREATE UNIQUE INDEX probe ON scores (content_hash)", True),
    ],
)
def test_index_check_requires_global_single_column_uniqueness(
    postgres_schema_database_url: str, definition: str, qualifies: bool
) -> None:
    # WHY: a partial/composite/expression index cannot enforce this deduplication contract.
    asyncio.run(_install_probe_index(postgres_schema_database_url, definition))
    found = asyncio.run(_unique_hash_indexes(postgres_schema_database_url))
    assert found == ([{"indexname": "probe"}] if qualifies else [])
