from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0010_idempotency_key_scheme"),
    ]

    initial = False

    # FEATURE: OME-1051 — nullable and deliberately not backfilled. NULL means the client did not
    # specify a credit line, and read DTOs derive [submitted_by], preserving every existing row's
    # display. An explicit JSON list is distinguishable so a later replay can correct it.
    operations = [
        ops.AddField(
            model_name="Score",
            name="authors",
            field=fields.JSONField(null=True),
        ),
    ]
