import functools
from json import dumps, loads

from tortoise import fields, migrations
from tortoise.indexes import Index
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    initial = True

    operations = [
        ops.CreateModel(
            name="Report",
            fields=[
                (
                    "ref",
                    fields.CharField(primary_key=True, unique=True, db_index=True, max_length=32),
                ),
                ("idempotency_key", fields.CharField(null=True, unique=True, max_length=255)),
                (
                    "payload",
                    fields.JSONField(
                        encoder=functools.partial(dumps, separators=(",", ":")), decoder=loads
                    ),
                ),
                ("classification", fields.CharField(max_length=16)),
                ("caller_email", fields.CharField(null=True, max_length=320)),
                ("reply_to", fields.CharField(null=True, max_length=320)),
                (
                    "delivery_state",
                    fields.CharField(default="pending", db_index=True, max_length=16),
                ),
                ("attempts", fields.IntField(default=0)),
                ("next_attempt_at", fields.DatetimeField(auto_now=False, auto_now_add=False)),
                ("lease_expires_at", fields.DatetimeField(auto_now=False, auto_now_add=False)),
                ("ticket_id", fields.CharField(null=True, max_length=64)),
                ("ticket_url", fields.CharField(null=True, max_length=2048)),
                ("request_fingerprint", fields.CharField(db_index=True, max_length=64)),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=False)),
                ("updated_at", fields.DatetimeField(auto_now=True, auto_now_add=False)),
            ],
            options={
                "table": "reports",
                "app": "models",
                "indexes": [Index(fields=["delivery_state", "next_attempt_at"])],
                "pk_attr": "ref",
            },
            bases=["BaseReport"],
        ),
    ]
