from tortoise import fields, migrations
from tortoise.fields.base import OnDelete
from tortoise.indexes import Index
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    initial = True

    operations = [
        ops.CreateModel(
            name="Run",
            fields=[
                (
                    "id",
                    fields.CharField(primary_key=True, unique=True, db_index=True, max_length=36),
                ),
                ("owner", fields.CharField(max_length=64)),
                ("client_key", fields.CharField(max_length=128)),
                ("benchmark", fields.CharField(max_length=255)),
                ("case_count", fields.IntField()),
                ("client_version", fields.CharField(max_length=64)),
                ("canceled", fields.BooleanField(default=False)),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=False)),
                ("last_activity_at", fields.DatetimeField(auto_now=False, auto_now_add=False)),
            ],
            options={
                "table": "runs",
                "app": "runs",
                "unique_together": (("owner", "client_key"),),
                "indexes": [Index(fields=["owner", "created_at", "id"])],
                "pk_attr": "id",
            },
            bases=["BaseRun"],
        ),
        ops.CreateModel(
            name="Candidate",
            fields=[
                (
                    "id",
                    fields.IntField(generated=True, primary_key=True, unique=True, db_index=True),
                ),
                ("index", fields.IntField()),
                ("name", fields.CharField(max_length=255)),
                ("topic", fields.CharField(null=True, unique=True, max_length=64)),
                ("state", fields.CharField(default="pending", max_length=16)),
                ("bound_at", fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                (
                    "finished_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
                ("cost_usd", fields.DecimalField(null=True, max_digits=24, decimal_places=12)),
                ("error_code", fields.CharField(null=True, max_length=128)),
                (
                    "run",
                    fields.ForeignKeyField(
                        "runs.Run",
                        source_field="run_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="candidates",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
            ],
            options={
                "table": "run_candidates",
                "app": "runs",
                "unique_together": (("run", "index"),),
                "indexes": [Index(fields=["state", "bound_at"])],
                "pk_attr": "id",
            },
            bases=["BaseCandidate"],
        ),
    ]
