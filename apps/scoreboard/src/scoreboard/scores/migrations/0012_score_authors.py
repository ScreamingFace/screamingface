from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        # Renumbered 0011 -> 0012 on rebase: main landed 0011_benchmark_case_count while this
        # branch was out, and both claimed 0011 with the same parent — two heads at one level,
        # which git cannot see because they are differently-named files.
        ("models", "0011_benchmark_case_count"),
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
