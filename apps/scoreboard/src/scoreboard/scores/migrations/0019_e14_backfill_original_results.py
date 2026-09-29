import json
from typing import Any

from tortoise import migrations
from tortoise.migrations import operations as ops

_MAX_RUN_ID_LENGTH = 128

# WHY `id` = the score id: the backfill must be deterministic and must need no UUID function
# (SQLite has none). A later uuid4 cannot collide in practice.
# WHY NOT EXISTS: this is the idempotency rule of erd.md section 6.3 — a head that already has an
# original result is skipped, so a rerun (or a back-and-forward migration) adds nothing.
_INSERT_ORIGINALS_SQL = """
INSERT INTO "reported_result" (
  "id", "head_id", "is_original", "reporter", "run_id", "trace_id",
  "score", "total_questions", "correct_questions",
  "run_cost_usd", "run_cost_status", "cache_saved_cost_usd",
  "models", "ran_with_providers", "answer_seed",
  "client_name", "client_version", "client_platform", "submitted_at")
SELECT s."id", s."id", TRUE, s."submitted_by", NULL, NULL,
  s."score", s."total_questions", s."correct_questions",
  s."run_cost_usd", s."run_cost_status", s."cache_saved_cost_usd",
  s."models", s."ran_with_providers", NULL,
  s."client_name", s."client_version", s."client_platform", s."submitted_at"
FROM "scores" s
WHERE NOT EXISTS (
  SELECT 1 FROM "reported_result" r WHERE r."head_id" = s."id" AND r."is_original")
"""


def _decode_metadata(metadata: Any) -> dict[str, Any]:
    """The score's metadata as a dict; NULL, malformed or non-object metadata reads as empty."""
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            return {}
    return metadata if isinstance(metadata, dict) else {}


def _metadata_run_id(metadata: Any) -> str | None:
    """The `metadata.run_id` of one score row, or None when it is absent or unusable."""
    value = _decode_metadata(metadata).get("run_id")
    usable = (
        isinstance(value, str) and value.strip() == value and 0 < len(value) <= _MAX_RUN_ID_LENGTH
    )
    return value if usable else None


async def _insert_originals(client: Any) -> None:
    await client.execute_script(_INSERT_ORIGINALS_SQL)


async def _run_id_pairs(client: Any) -> list[tuple[str, Any]]:
    """(run_id, score id) pairs to write: the FIRST score by (submitted_at, id) per value.

    INVARIANT: `reported_result.run_id` is UNIQUE, so a later duplicate stays NULL rather than
    failing the whole migration on deploy. A value another result already holds is skipped too.
    """
    taken = {
        row["run_id"]
        for row in await client.execute_query_dict(
            'SELECT "run_id" FROM "reported_result" WHERE "run_id" IS NOT NULL'
        )
    }
    rows = await client.execute_query_dict(
        'SELECT "id", "metadata", "submitted_at" FROM "scores" ORDER BY "submitted_at", "id"'
    )
    pairs: list[tuple[str, Any]] = []
    for row in rows:
        run_id = _metadata_run_id(row["metadata"])
        if run_id is None or run_id in taken:
            continue
        taken.add(run_id)
        pairs.append((run_id, row["id"]))
    return pairs


async def _apply_run_ids(client: Any, dialect: str, pairs: list[tuple[str, Any]]) -> None:
    marks = ("?", "?") if dialect == "sqlite" else ("$1", "$2")
    statement = (
        f'UPDATE "reported_result" SET "run_id" = {marks[0]} '
        f'WHERE "id" = {marks[1]} AND "is_original" AND "run_id" IS NULL'
    )
    for run_id, score_id in pairs:
        await client.execute_query(statement, [run_id, score_id])


async def _backfill(apps, schema_editor) -> None:
    client = schema_editor.client
    await _insert_originals(client)
    await _apply_run_ids(client, schema_editor.DIALECT, await _run_id_pairs(client))


async def _noop(apps, schema_editor) -> None:
    # The rows are harmless after a schema rollback of this step.
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0018_e14_registry_and_results_tables"),
        # WHY: the backfill SQL reads `scores.run_cost_usd`, which 0004 adds. 0004 is a leaf off the
        # main chain, so 0018 -> 0017 -> 0016 does not reach it.
        ("models", "0004_add_run_cost_usd"),
    ]

    initial = False

    # FEATURE: OME-1307 (E14) — every existing head gets one original reported result, copied from
    # its score row, so "every head has an original" holds from the day E14 deploys.
    #
    # AIDEV-NOTE: SAFE for a rolling multi-replica rollout — it only adds rows. A private-board
    # score gets an original too, which is correct: every head has one.
    operations = [
        ops.RunPython(_backfill, reverse_code=_noop),
    ]
