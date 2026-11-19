import functools
from json import dumps, loads
from uuid import uuid4

from tortoise import fields, migrations
from tortoise.fields.base import OnDelete
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("models", "0022_baseline_metadata")]

    initial = False

    operations = [
        ops.CreateModel(
            name="BaselineRevision",
            fields=[
                (
                    "id",
                    fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True),
                ),
                ("revision", fields.IntField()),
                (
                    "recorded_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
                (
                    "observation",
                    fields.JSONField(
                        encoder=functools.partial(dumps, separators=(",", ":")), decoder=loads
                    ),
                ),
                ("attached_by", fields.CharField(null=True, max_length=255)),
                (
                    "baseline",
                    fields.ForeignKeyField(
                        "models.Baseline",
                        source_field="baseline_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="revisions",
                        on_delete=OnDelete.RESTRICT,
                    ),
                ),
            ],
            options={
                "table": "baseline_revisions",
                "app": "models",
                "unique_together": (("baseline", "revision"),),
                "pk_attr": "id",
            },
            bases=["BaseBaselineRevision"],
        ),
        ops.AddField(
            model_name="Baseline",
            name="observation_revision",
            field=fields.IntField(default=0, db_default=0),
        ),
        ops.AddField(
            model_name="Baseline",
            name="observation_updated_at",
            field=fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
        ),
    ]
