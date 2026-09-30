"""FS-1 — a public Idempotency-Key of 129 to 255 characters works with clustering on (C4).

FEATURE: OME-1307 (E14). C4 says the Idempotency-Key is "unchanged" and is now enforced by the
unique `ReportedResult.run_id`. INVARIANT: the flag must not change which keys are accepted, so
`run_id` is as wide as `IdempotencyKey.key` (VARCHAR(255)). A key longer than the column made
Tortoise raise a `ValidationError` at the `run_id` lookup: an unhandled 500 that the SDK retries.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from httpx import AsyncClient

from scoreboard.scores.models import IdempotencyKey, ReportedResult
from tests.unit.submissions._receipts import post_score
from tests.unit.test_migration_e14_schema import _migrated


@pytest.mark.asyncio
@pytest.mark.parametrize("length", [128, 129, 200, 255])
async def test_a_public_key_up_to_255_characters_is_accepted_and_replays(
    clustered_cf_client: AsyncClient, length: int
) -> None:
    key = "k" * length

    first = await post_score(clustered_cf_client, key=key)
    again = await post_score(clustered_cf_client, key=key)

    assert first.status_code == 201, first.text
    assert again.status_code == 200, again.text
    assert again.json()["reported_result"]["id"] == first.json()["reported_result"]["id"]
    assert await ReportedResult.filter(run_id=key).count() == 1


def test_run_id_is_as_wide_as_the_legacy_idempotency_key_column() -> None:
    run_id = ReportedResult._meta.fields_map["run_id"]
    legacy = IdempotencyKey._meta.fields_map["key"]

    assert getattr(run_id, "max_length") == getattr(legacy, "max_length") == 255


def test_the_migrated_column_is_varchar_255(tmp_path: Path) -> None:
    database = tmp_path / "scoreboard.sqlite3"
    _migrated(database)

    connection = sqlite3.connect(database)
    columns = connection.execute('PRAGMA table_info("reported_result")')
    declared = {row[1]: row[2] for row in columns}
    connection.close()

    assert declared["run_id"].upper() == "VARCHAR(255)"
