from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0016_score_enriched_at"),
    ]

    initial = False

    # FEATURE: OME-1382 / OME-1251 D7 — the archive-matched cache saving, stored beside the
    # reported one and never merged into it.
    #
    # WHY nullable and NOT backfilled: no row has ever carried this figure, and NULL ("not
    # reported") is a different fact from 0. Legacy rows keep serving exactly what they served.
    operations = [
        ops.AddField(
            model_name="Score",
            name="cache_saved_cost_archive_usd",
            field=fields.DecimalField(max_digits=12, decimal_places=6, null=True),
        ),
    ]
