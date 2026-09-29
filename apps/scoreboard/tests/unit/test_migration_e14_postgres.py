"""E14 (OME-1307) migrations 0017-0019 on PostgreSQL: the chain applies to a populated database.

WHY this needs PostgreSQL: the `system_revision_id` foreign key exists only there (SQLite cannot add
a constraint to an existing table), and the partial unique indexes and the NOT NULL `db_default`
columns must be proven on the engine production runs. Runs only when SCOREBOARD_TEST_DATABASE_URL
is set; skips otherwise.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg  # type: ignore[import-untyped]
import pytest

REPO_APP = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv("SCOREBOARD_TEST_DATABASE_URL", "")
TO_0016 = "0016_score_enriched_at"


def _migrate(database_url: str, target: str | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "tortoise", "-c", "scoreboard.db.TORTOISE_CONFIG", "migrate"]
    if target is not None:
        command += ["models", target]
    return subprocess.run(
        command,
        cwd=REPO_APP,
        env={
            "PATH": "/usr/bin:/bin",
            "SCOREBOARD_DATABASE_URL": database_url,
            "PYTHONPATH": str(REPO_APP / "src"),
        },
        capture_output=True,
        text=True,
        timeout=180,
    )


def _migrated(database_url: str, target: str | None = None) -> None:
    result = _migrate(database_url, target)
    assert result.returncode == 0, result.stdout + result.stderr


async def _connect(database_url: str) -> asyncpg.Connection:
    # WHY: the fixture URL carries `?schema=<name>`, which Tortoise reads but asyncpg does not.
    parts = urlsplit(database_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    schema = query.pop("schema")
    plain = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    return await asyncpg.connect(plain, server_settings={"search_path": schema})


async def _seed(database_url: str) -> uuid.UUID:
    score_id = uuid.uuid4()
    connection = await _connect(database_url)
    try:
        await connection.execute(
            """INSERT INTO benchmarks (id, display_name, visibility, created_at)
               VALUES ('pg-board', 'PG board', 'public', $1)""",
            datetime(2026, 1, 1, tzinfo=UTC),
        )
        await connection.execute(
            """INSERT INTO scores
               (id, version, spec_id, url4_expression, submitted_by, submitted_at,
                total_questions, ran_with_providers, metadata, benchmark_id,
                verified_by_screamingface, score)
               VALUES ($1, 1, 'spec', 'url4://x', 'owner@example.test', $2, 10, '[]'::jsonb,
                       $3::jsonb, 'pg-board', false, 0.5)""",
            score_id,
            datetime(2026, 2, 1, tzinfo=UTC),
            json.dumps({"run_id": "pg-run-1"}),
        )
    finally:
        await connection.close()
    return score_id


@dataclass
class _Inspection:
    revision: int | None
    redistributable: bool | None
    constraint_delete_action: str | None
    indexes: set[str]
    results: list[Any]


async def _inspect(database_url: str) -> _Inspection:
    connection = await _connect(database_url)
    try:
        schema = await connection.fetchval("SELECT current_schema()")
        return _Inspection(
            revision=await connection.fetchval("SELECT metadata_revision FROM scores"),
            redistributable=await connection.fetchval("SELECT redistributable FROM benchmarks"),
            constraint_delete_action=await connection.fetchval(
                """SELECT confdeltype::text FROM pg_constraint c
                   JOIN pg_namespace n ON n.oid = c.connamespace
                   WHERE c.conname = 'fk_scores_system_revision' AND n.nspname = $1""",
                schema,
            ),
            indexes={
                row["indexname"]
                for row in await connection.fetch(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = $1", schema
                )
            },
            results=await connection.fetch(
                'SELECT "id", "score_id", "is_original", "run_id" FROM reported_result'
            ),
        )
    finally:
        await connection.close()


@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="requires PostgreSQL")
def test_sch12_migrations_apply_on_postgres(postgres_schema_database_url: str) -> None:
    _migrated(postgres_schema_database_url, TO_0016)
    _migrated(postgres_schema_database_url, "0004_add_run_cost_usd")
    score_id = asyncio.run(_seed(postgres_schema_database_url))

    _migrated(postgres_schema_database_url)

    state = asyncio.run(_inspect(postgres_schema_database_url))
    assert state.revision == 1
    assert state.redistributable is False
    # INVARIANT: PostgreSQL gets the real foreign key the plain UUID column cannot declare
    # (OD-S1); `r` is ON DELETE RESTRICT.
    assert state.constraint_delete_action == "r"
    assert {"uidx_reported_result_one_original", "uidx_scores_public_head"} <= state.indexes
    assert len(state.results) == 1
    result = state.results[0]
    assert (result["id"], result["score_id"], result["is_original"], result["run_id"]) == (
        score_id,
        score_id,
        True,
        "pg-run-1",
    )
