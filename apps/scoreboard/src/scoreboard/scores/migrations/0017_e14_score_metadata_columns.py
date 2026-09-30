from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0016_score_enriched_at"),
    ]

    initial = False

    # FEATURE: OME-1307 (E14) — score metadata columns and the per-board redistribution switch.
    #
    # WHY `db_default` and NOT the 0008 pattern (nullable add plus backfill): Tortoise 1.1.8 emits
    # `ADD COLUMN ... NOT NULL DEFAULT 1` when `db_default` is set. SQLite and PostgreSQL both
    # accept a NOT NULL column with a constant default on a populated table, so no nullable phase
    # is needed. An old pod that omits the column on INSERT gets the database default.
    #
    # AIDEV-NOTE: SAFE for a rolling multi-replica rollout — expand-only (new columns with a
    # default or NULL; nothing renamed or dropped). See "Breaking migrations and multi-replica
    # rollouts" in apps/scoreboard/DEPLOYMENT.md.
    operations = [
        ops.AddField(
            model_name="Score",
            name="paper_url",
            field=fields.CharField(null=True, max_length=2048),
        ),
        ops.AddField(
            model_name="Score",
            name="metadata_revision",
            field=fields.IntField(default=1, db_default=1),
        ),
        ops.AddField(
            model_name="Score",
            name="metadata_updated_at",
            field=fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
        ),
        ops.AddField(
            model_name="Score",
            name="system_revision_id",
            field=fields.UUIDField(null=True),
        ),
        ops.AddField(
            model_name="Benchmark",
            name="redistributable",
            field=fields.BooleanField(default=False, db_default=False),
        ),
    ]
