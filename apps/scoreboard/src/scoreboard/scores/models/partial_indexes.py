"""Partial unique indexes that Tortoise cannot declare (E14, OME-1307).

INVARIANT: byte-equal to the RunSQL in migration 0018. SCH-7 asserts it. Tests that build
their schema with `generate_schemas` apply these through `create_partial_unique_indexes`.
"""

from __future__ import annotations

from tortoise import BaseDBAsyncClient

ONE_ORIGINAL_PER_SCORE_SQL = (
    'CREATE UNIQUE INDEX IF NOT EXISTS "uidx_reported_result_one_original" '
    'ON "reported_result" ("head_id") WHERE "is_original"'
)
ONE_PUBLIC_HEAD_PER_SYSTEM_REVISION_SQL = (
    'CREATE UNIQUE INDEX IF NOT EXISTS "uidx_scores_public_head" '
    'ON "scores" ("benchmark_id", "benchmark_revision", "system_revision_id") '
    'WHERE "system_revision_id" IS NOT NULL'
)
PARTIAL_UNIQUE_INDEX_SQL: tuple[str, ...] = (
    ONE_ORIGINAL_PER_SCORE_SQL,
    ONE_PUBLIC_HEAD_PER_SYSTEM_REVISION_SQL,
)


async def create_partial_unique_indexes(connection: BaseDBAsyncClient) -> None:
    for statement in PARTIAL_UNIQUE_INDEX_SQL:
        await connection.execute_script(statement)


# AIDEV-NOTE on `uidx_scores_public_head`: a NULL `benchmark_revision` is not unique-checked (both
# engines treat NULLs as distinct). SB-submit must know this (OD-S4).
