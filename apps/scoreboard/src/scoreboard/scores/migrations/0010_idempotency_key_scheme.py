from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0009_idempotency_key_namespaces"),
    ]

    initial = False

    # INVARIANT: NULLABLE, with no backfill, on purpose. NULL is the meaningful value — it marks a
    # mapping written by a replica that did not know about this column, which is precisely what an
    # old pod serving through a rollout produces. Backfilling existing rows to the current scheme
    # would assert provenance this migration cannot verify, and would re-admit exactly the poisoned
    # rows the column exists to reject (review of PR #719).
    operations = [
        ops.AddField(
            model_name="IdempotencyKey",
            name="scheme",
            field=fields.CharField(max_length=8, null=True),
        ),
    ]
