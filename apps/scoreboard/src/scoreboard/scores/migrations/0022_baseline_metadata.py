from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    # WHY: generated against both existing migration heads. All additions are
    # nullable, so old rows and old pods remain valid during a rolling upgrade.
    dependencies = [("models", "0004_add_run_cost_usd"), ("models", "0021_score_metadata_objects")]

    initial = False

    # INVARIANT: no backfill invents a source observation date or human attribution.

    operations = [
        ops.AddField(
            model_name="Baseline",
            name="attached_by",
            field=fields.CharField(null=True, max_length=255),
        ),
        ops.AddField(
            model_name="Baseline",
            name="last_imported_at",
            field=fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
        ),
        ops.AddField(
            model_name="Baseline",
            name="metric_name",
            field=fields.CharField(null=True, max_length=128),
        ),
        ops.AddField(
            model_name="Baseline",
            name="observed_at",
            field=fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
        ),
    ]
