"""Create the frozen-copy tables (OME-1307, design §3).

UPGRADE. Two ``CREATE TABLE`` plus the replay-lookup index on ``frozen_copy_entries``. No existing
table is touched or rebuilt, so no standalone index of another table is at risk.

DOWNGRADE. ``DROP TABLE`` of both, entries first. Nothing else references them.

AUTHORING NOTE. Generated with ``tortoise makemigrations -n frozen_copies models`` and then
edited, the way 0012 was: ``bases`` is spelled ``["Model"]``, and the autodetector's third
proposal — ``AlterField`` on ``OAuthConnection.account`` — is DROPPED. That is the pre-existing
drift between 0002's foreign-key spelling and the projected state (see 0012); applying it would
rebuild ``oauth_connections`` on SQLite and drop that table's standalone indexes. The foreign keys
below keep the generated ``source_field`` / ``to_field`` / ``db_constraint`` spelling so the
projected state equals the models and ``makemigrations`` stays silent about them
(``test_autodetector_proposes_no_frozen_copy_change``).
"""

from uuid import uuid4

from tortoise import fields, migrations
from tortoise.indexes import Index
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("models", "0013_credential_operational_outcomes")]

    operations = [
        ops.CreateModel(
            name="FrozenCopy",
            fields=[
                (
                    "id",
                    fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True),
                ),
                (
                    "account",
                    fields.ForeignKeyField(
                        "models.Account",
                        source_field="account_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="frozen_copies",
                        on_delete=fields.OnDelete.CASCADE,
                    ),
                ),
                ("status", fields.CharField(default="open", max_length=16)),
                ("entries", fields.IntField(default=0)),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                (
                    "sealed_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
            ],
            options={"table": "frozen_copies", "app": "models", "pk_attr": "id"},
            bases=["Model"],
        ),
        ops.CreateModel(
            name="FrozenCopyEntry",
            fields=[
                (
                    "id",
                    fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True),
                ),
                (
                    "frozen_copy",
                    fields.ForeignKeyField(
                        "models.FrozenCopy",
                        source_field="frozen_copy_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="entry_rows",
                        on_delete=fields.OnDelete.CASCADE,
                    ),
                ),
                ("kind", fields.CharField(max_length=8)),
                ("request_digest", fields.CharField(max_length=64)),
                ("request_json", fields.JSONField()),
                ("response_json", fields.JSONField()),
                ("status_code", fields.IntField()),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
            ],
            options={
                "table": "frozen_copy_entries",
                "app": "models",
                "indexes": [
                    Index(fields=["frozen_copy_id", "kind", "request_digest", "created_at"])
                ],
                "pk_attr": "id",
            },
            bases=["Model"],
        ),
    ]
