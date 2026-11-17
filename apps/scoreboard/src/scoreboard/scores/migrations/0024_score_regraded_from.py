from tortoise import fields, migrations
from tortoise.fields.base import OnDelete
from tortoise.migrations import operations as ops
from tortoise.migrations.constraints import UniqueConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0023_baseline_history"),
    ]

    initial = False

    # FEATURE: OME-1909 — a re-graded score names the score it was re-graded from, and who did it.
    #
    # WHY nullable and NOT backfilled: no row has ever been re-graded, and NULL means "an ordinary
    # submission". Legacy rows keep serving and exporting exactly as before (the read schema
    # excludes a null link).
    #
    # WHY the rule is one re-grade per (source, revision): a re-grade row has no pinned cache, so
    # after the next grading change only the root source can be replayed again, once under each
    # later revision. A re-grade always carries its revision (the route refuses one that is not
    # the board's registered revision), so NULL never weakens the pair.
    #
    # WHY that rule is a constraint and not `unique=True` on the field: the same reason 0021
    # records. On SQLite a unique column cannot be added in place, so Tortoise
    # would REBUILD `scores` and drop it under the tables whose foreign keys point here. The
    # constraint is a CREATE UNIQUE INDEX there and an ADD CONSTRAINT on PostgreSQL; both let NULL
    # repeat. The foreign key itself is an in-place ADD COLUMN ... REFERENCES on both.
    #
    # AIDEV-NOTE: SAFE for a rolling multi-replica rollout: old pods ignore the new columns, and no
    # existing row can violate the new index because every existing value is NULL.
    operations = [
        ops.AddField(
            model_name="Score",
            name="regraded_by",
            field=fields.CharField(null=True, max_length=255),
        ),
        ops.AddField(
            model_name="Score",
            name="regraded_from",
            field=fields.ForeignKeyField(
                "models.Score",
                source_field="regraded_from_id",
                null=True,
                db_constraint=True,
                to_field="id",
                related_name=False,
                on_delete=OnDelete.SET_NULL,
            ),
        ),
        ops.AddConstraint(
            model_name="Score",
            constraint=UniqueConstraint(fields=("regraded_from", "benchmark_revision"), name=None),
        ),
    ]
