import functools
from collections.abc import Mapping, Sequence
from json import dumps, loads
from typing import Any

from tortoise import fields, migrations
from tortoise.migrations import operations as ops
from tortoise.migrations.constraints import UniqueConstraint

# The board rows that share a frozen copy, oldest copy id first. Plain SQL that reads the same on
# SQLite and PostgreSQL, with no parameter.
_DUPLICATES_SQL = (
    'SELECT "frozen_copy_id", "id" FROM "scores" WHERE "frozen_copy_id" IN ('
    'SELECT "frozen_copy_id" FROM "scores" WHERE "frozen_copy_id" IS NOT NULL '
    'GROUP BY "frozen_copy_id" HAVING COUNT(*) > 1) ORDER BY "frozen_copy_id", "id"'
)


class DuplicateFrozenCopies(RuntimeError):
    """Two or more scores already name the same frozen copy, so the unique rule cannot be added.

    ``duplicates`` maps each copy id to the sorted ids of the scores that name it.
    """

    def __init__(self, duplicates: Mapping[str, Sequence[str]]) -> None:
        self.duplicates = {copy: list(ids) for copy, ids in duplicates.items()}
        named = "; ".join(f"{copy}: {', '.join(ids)}" for copy, ids in self.duplicates.items())
        super().__init__(
            "migration 0021 cannot make frozen_copy_id unique: "
            f"{len(self.duplicates)} frozen copies are named by more than one score ({named}). "
            "Ask the owner which score keeps each copy before deploying."
        )


async def refuse_duplicate_frozen_copies(apps: Any, schema_editor: Any) -> None:
    """Refuse, with the copy ids and the score ids, before the unique rule meets a duplicate.

    WHY a guard rather than letting the index fail: the database's own error names neither the copy
    nor the scores, and the fix is an owner decision about which score keeps each copy (plan,
    "Duplicate copy ids", option A). It runs FIRST, so a refusal leaves nothing of 0021 applied.

    AIDEV-NOTE: `collect_sql` is `tortoise sqlmigrate`, which renders without a database.
    """
    if schema_editor.collect_sql:
        return None
    rows = await schema_editor.client.execute_query_dict(_DUPLICATES_SQL)
    grouped: dict[str, list[str]] = {}
    for row in rows:
        grouped.setdefault(str(row["frozen_copy_id"]), []).append(str(row["id"]))
    if grouped:
        raise DuplicateFrozenCopies({copy: sorted(grouped[copy]) for copy in sorted(grouped)})
    return None


def _json_field() -> fields.JSONField:
    return fields.JSONField(
        null=True,
        encoder=functools.partial(dumps, separators=(",", ":")),
        decoder=loads,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0020_score_frozen_copy"),
    ]

    initial = False

    # FEATURE: OME-1596 — author and paper metadata on a score, their edit-log pairs, and one score
    # per frozen copy (the public pinned cache lookup answers with exactly one row).
    #
    # WHY nullable and NOT backfilled: no row has ever carried either object, and NULL means
    # "never sent", which every read excludes. Legacy rows keep serving and exporting as before.
    #
    # WHY the unique rule is a constraint (`unique_together` on the model) and not an AlterField:
    # on SQLite an AlterField rebuilds `scores` and drops it under the foreign keys of
    # `score_metadata_events`, `score_reproductions` and `idempotency_keys` (0008 records the
    # failure). The constraint is a CREATE UNIQUE INDEX there and an ADD CONSTRAINT on PostgreSQL;
    # both let NULL repeat.
    #
    # AIDEV-NOTE: SAFE for a rolling multi-replica rollout: old pods ignore the new columns, and an
    # old pod's insert of a second score naming an already-claimed copy fails on the index (a 503
    # there, a 422 `frozen_copy_claimed` on new pods), which is the rule this adds. Run the
    # duplicate query in the plan on dev and production BEFORE merging; the guard is the backstop.
    operations = [
        ops.RunPython(refuse_duplicate_frozen_copies, reverse_code=ops.RunPython.noop),
        ops.AddField(model_name="Score", name="authors_metadata", field=_json_field()),
        ops.AddField(model_name="Score", name="paper_metadata", field=_json_field()),
        ops.AddConstraint(
            model_name="Score",
            constraint=UniqueConstraint(fields=("frozen_copy_id",), name=None),
        ),
        ops.AddField(
            model_name="ScoreMetadataEvent", name="old_authors_metadata", field=_json_field()
        ),
        ops.AddField(
            model_name="ScoreMetadataEvent", name="new_authors_metadata", field=_json_field()
        ),
        ops.AddField(
            model_name="ScoreMetadataEvent", name="old_paper_metadata", field=_json_field()
        ),
        ops.AddField(
            model_name="ScoreMetadataEvent", name="new_paper_metadata", field=_json_field()
        ),
    ]
