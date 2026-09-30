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
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg  # type: ignore[import-untyped]
import pytest

REPO_APP = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv("SCOREBOARD_TEST_DATABASE_URL", "")
TO_0016 = "0016_score_enriched_at"

# The `scores` columns the 0019 backfill copies unchanged (`reporter` and `id` are checked apart).
COPIED_COLUMNS = (
    "score",
    "total_questions",
    "correct_questions",
    "run_cost_usd",
    "run_cost_status",
    "cache_saved_cost_usd",
    "models",
    "ran_with_providers",
    "client_name",
    "client_version",
    "client_platform",
    "submitted_at",
)
# The `reported_result` columns an original from the backfill must leave NULL.
UNSET_COLUMNS = (
    "trace_id",
    "answer_seed",
    "replayed_from_result_id",
    "pinned_baseline_result_id",
    "cache_version_id",
    "cache_version_sha256",
    "cache_entry_count",
    "cache_call_count",
    "cache_coverage_status",
    "replay_hits",
    "replay_misses",
    "replay_repeated_key_collapses",
)
# The `pg_constraint.confdeltype` code of each `reported_result` foreign key (D8): `c` is CASCADE
# and `a` is NO ACTION.
RESULT_FK_DELETE_RULES = {
    "head_id": "c",
    "replayed_from_result_id": "a",
    "pinned_baseline_result_id": "a",
}


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
        # INVARIANT: every column the backfill copies holds a distinct non-NULL value, so a
        # dropped, NULLed or swapped column, or a lossy numeric or jsonb round trip, is visible.
        await connection.execute(
            """INSERT INTO scores
               (id, version, spec_id, url4_expression, submitted_by, submitted_at,
                total_questions, correct_questions, ran_with_providers, metadata, benchmark_id,
                verified_by_screamingface, score, run_cost_usd, run_cost_status,
                cache_saved_cost_usd, models, client_name, client_version, client_platform)
               VALUES ($1, 1, 'spec', 'url4://x', 'owner@example.test', $2, 10, 7,
                       '["provider-a"]'::jsonb, $3::jsonb, 'pg-board', false, 0.5, $4, 'partial',
                       $5, '["model-a", "model-b"]'::jsonb, 'client-x', '1.2.3', 'darwin')""",
            score_id,
            datetime(2026, 2, 1, tzinfo=UTC),
            json.dumps({"run_id": "pg-run-1"}),
            Decimal("1.500000"),
            Decimal("0.250000"),
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
    head: Any
    result_fk_delete_rules: dict[str, str]


async def _result_fk_delete_rules(connection: asyncpg.Connection, schema: Any) -> dict[str, str]:
    """The `confdeltype` of each `reported_result` foreign key, keyed by its column."""
    rows = await connection.fetch(
        """SELECT a.attname AS column_name, c.confdeltype::text AS rule
           FROM pg_constraint c
           JOIN pg_namespace n ON n.oid = c.connamespace
           JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
           WHERE c.contype = 'f' AND c.conrelid = ('"' || $1 || '"."reported_result"')::regclass""",
        schema,
    )
    return {row["column_name"]: row["rule"] for row in rows}


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
            results=await connection.fetch("SELECT * FROM reported_result"),
            head=await connection.fetchrow("SELECT * FROM scores"),
            result_fk_delete_rules=await _result_fk_delete_rules(connection, schema),
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
    assert state.result_fk_delete_rules == RESULT_FK_DELETE_RULES
    assert len(state.results) == 1
    result = state.results[0]
    assert (result["id"], result["head_id"], result["is_original"], result["run_id"]) == (
        score_id,
        score_id,
        True,
        "pg-run-1",
    )
    assert result["reporter"] == state.head["submitted_by"]
    for column in COPIED_COLUMNS:
        assert result[column] == state.head[column], column
    for column in UNSET_COLUMNS:
        assert result[column] is None, column
    # WHY: the seed is distinct per column, so equality above proves no column was swapped.
    assert (result["client_name"], result["client_version"]) == ("client-x", "1.2.3")
    assert result["models"] == '["model-a", "model-b"]'
    assert result["run_cost_usd"] == Decimal("1.500000")


async def _insert_head(connection: asyncpg.Connection, board: str) -> uuid.UUID:
    score_id = uuid.uuid4()
    await connection.execute(
        """INSERT INTO scores
           (id, version, spec_id, url4_expression, submitted_by, submitted_at,
            total_questions, ran_with_providers, benchmark_id, verified_by_screamingface, score)
           VALUES ($1, 1, 'spec', 'url4://x', 'owner@example.test', $2, 10, '[]'::jsonb,
                   $3, false, 0.5)""",
        score_id,
        datetime(2026, 2, 1, tzinfo=UTC),
        board,
    )
    return score_id


async def _insert_result(
    connection: asyncpg.Connection,
    head: uuid.UUID,
    *,
    is_original: bool,
    replayed_from: uuid.UUID | None = None,
    pinned_baseline: uuid.UUID | None = None,
) -> uuid.UUID:
    result_id = uuid.uuid4()
    await connection.execute(
        """INSERT INTO reported_result
           (id, head_id, is_original, score, total_questions, submitted_at,
            replayed_from_result_id, pinned_baseline_result_id)
           VALUES ($1, $2, $3, 0.5, 10, $4, $5, $6)""",
        result_id,
        head,
        is_original,
        datetime(2026, 2, 1, tzinfo=UTC),
        replayed_from,
        pinned_baseline,
    )
    return result_id


async def _replay_fk_delete_rules(database_url: str) -> None:
    connection = await _connect(database_url)
    try:
        await connection.execute(
            """INSERT INTO benchmarks (id, display_name, visibility, created_at)
               VALUES ('pg-board', 'PG board', 'public', $1)""",
            datetime(2026, 1, 1, tzinfo=UTC),
        )
        # (a) a head whose own cluster holds a replay of its own original: the delete succeeds.
        head = await _insert_head(connection, "pg-board")
        original = await _insert_result(connection, head, is_original=True)
        await _insert_result(
            connection,
            head,
            is_original=False,
            replayed_from=original,
            pinned_baseline=original,
        )
        await connection.execute('DELETE FROM "scores" WHERE "id" = $1', head)
        assert await connection.fetchval("SELECT COUNT(*) FROM reported_result") == 0

        # (b) an original that a result in ANOTHER cluster replayed: the delete fails.
        first = await _insert_head(connection, "pg-board")
        first_original = await _insert_result(connection, first, is_original=True)
        second = await _insert_head(connection, "pg-board")
        await _insert_result(connection, second, is_original=False, replayed_from=first_original)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await connection.execute('DELETE FROM "scores" WHERE "id" = $1', first)
        assert await connection.fetchval("SELECT COUNT(*) FROM scores") == 2
        assert await connection.fetchval("SELECT COUNT(*) FROM reported_result") == 2

        # (c) an original that a result in ANOTHER cluster pinned as its baseline, replaying
        # nothing: the delete fails too, because `pinned_baseline_result_id` is NO ACTION as well.
        third = await _insert_head(connection, "pg-board")
        await _insert_result(connection, third, is_original=False, pinned_baseline=first_original)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await connection.execute('DELETE FROM "scores" WHERE "id" = $1', first)
        assert await connection.fetchval("SELECT COUNT(*) FROM scores") == 3
        assert await connection.fetchval("SELECT COUNT(*) FROM reported_result") == 3
    finally:
        await connection.close()


@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="requires PostgreSQL")
def test_sch14_replay_fks_are_no_action_on_postgres(postgres_schema_database_url: str) -> None:
    # INVARIANT (OD-S2, D8): the replay FKs are ON DELETE NO ACTION, checked at the end of the
    # statement, so the CASCADE from a head may delete a replay together with the original it
    # replays; a replay in another cluster still blocks the delete of its original.
    _migrated(postgres_schema_database_url)

    asyncio.run(_replay_fk_delete_rules(postgres_schema_database_url))
    state = asyncio.run(_inspect(postgres_schema_database_url))
    assert state.result_fk_delete_rules == RESULT_FK_DELETE_RULES
