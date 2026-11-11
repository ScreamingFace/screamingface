from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("models", "0023_baseline_history")]

    initial = False

    operations = [
        ops.CreateModel(
            name="SourceHealth",
            fields=[
                (
                    "source_key",
                    fields.CharField(primary_key=True, unique=True, db_index=True, max_length=64),
                ),
                ("source_url", fields.CharField(max_length=2048)),
                ("available", fields.BooleanField()),
                ("checked_at", fields.DatetimeField(auto_now=False, auto_now_add=False)),
                (
                    "last_available_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
            ],
            options={"table": "external_source_health", "app": "models", "pk_attr": "source_key"},
            bases=["BaseSourceHealth"],
        ),
    ]
