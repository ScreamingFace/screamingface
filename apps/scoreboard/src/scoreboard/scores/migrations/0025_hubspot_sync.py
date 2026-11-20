# FEATURE: OME-1504 — the HubSpot sync's queue table, one row per score. No data: the job's first
# run queues existing scores itself, so a dry run can review them before anything is sent.
from tortoise import fields, migrations
from tortoise.fields.base import OnDelete
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("models", "0024_benchmark_revisions")]

    initial = False

    operations = [
        ops.CreateModel(
            name="HubSpotSyncRecord",
            fields=[
                (
                    "id",
                    fields.IntField(generated=True, primary_key=True, unique=True, db_index=True),
                ),
                ("status", fields.CharField(default="pending", db_index=True, max_length=16)),
                ("reason", fields.CharField(null=True, max_length=128)),
                ("sota_qualified", fields.BooleanField(null=True)),
                ("attempts", fields.IntField(default=0)),
                (
                    "next_attempt_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                ("updated_at", fields.DatetimeField(auto_now=True, auto_now_add=False)),
                (
                    "score",
                    fields.OneToOneField(
                        "models.Score",
                        source_field="score_id",
                        db_constraint=True,
                        to_field="id",
                        related_name=False,
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
            ],
            options={"table": "hubspot_sync", "app": "models", "pk_attr": "id"},
            bases=["BaseHubSpotSyncRecord"],
        ),
    ]
