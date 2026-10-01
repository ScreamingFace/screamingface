from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0015_score_cache_saved_cost"),
    ]

    initial = False

    # FEATURE: OME-1145 — when a replay last filled a field the frontier reads.
    #
    # WHY nullable and deliberately NOT backfilled: no enrichment time was ever recorded, so none
    # can be recovered. NULL makes the trend fall back to `submitted_at`, which is what it did
    # before this column existed; only enrichments from here on are dated.
    operations = [
        ops.AddField(
            model_name="Score",
            name="enriched_at",
            field=fields.DatetimeField(null=True),
        ),
    ]
