"""Create the pair authority marker table ``provider_credential_slots`` (OME-1208, Stage B S1).

UPGRADE. One ``CREATE TABLE`` plus its indexes: the primary key's, the ``(account_id, provider)``
uniqueness index (D1 — one marker per pair, enforced by the database; Tortoise 1.1.8 has neither a
composite primary key nor a partial unique index) and the two foreign-key indexes. No existing
table is touched or rebuilt on either dialect, so the standalone indexes SQLite drops with a
rebuilt table are not at risk here. The table is created EMPTY: an absent row means the legacy
Profile owns the pair, so every pair keeps today's behaviour until the migration tool writes.

The marker follows its account (``ON DELETE CASCADE``) and lets go of a deleted Connection
(``ON DELETE SET NULL``) rather than blocking the delete: the application clears the reference in
the same transaction before a Connection row goes, and the database rule is the safety net.

DOWNGRADE. ``DROP TABLE provider_credential_slots`` — nothing else references it, so nothing else
moves. Pinned by ``test_0012_downgrade_drops_only_the_marker_table``.

ROLLBACK OF THE FEATURE (R1, D5) is NOT this downgrade: a migrated pair returns to legacy
authority by resetting its marker row while every blob stays. Dropping the table is only for a
rollback of the schema itself.

AUTHORING NOTE. Generated with ``tortoise makemigrations -n provider_credential_slots models`` and
then edited: ``bases`` is spelled ``["Model"]`` like every earlier ``CreateModel`` here, and the
autodetector's second proposal — ``AlterField`` on ``OAuthConnection.account`` — is DROPPED. That
proposal is pre-existing drift between migration 0002's foreign-key spelling and the projected
state (the autodetector proposes it with this model absent, too); it is unrelated to the marker,
and applying it would rebuild ``oauth_connections`` on SQLite, which drops that table's standalone
indexes (the defect 0009–0011 document). It is recorded in the OME-1208 ledger for a separate
decision. The foreign keys below keep the generated ``source_field`` / ``to_field`` /
``db_constraint`` spelling so the projected state equals the model and ``makemigrations`` stays
silent about the marker (``test_autodetector_proposes_no_marker_change``).
"""

from uuid import uuid4

from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("models", "0011_cache_entry_metadata")]

    operations = [
        ops.CreateModel(
            name="ProviderCredentialSlot",
            fields=[
                (
                    "id",
                    fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True),
                ),
                ("provider", fields.CharField(max_length=64)),
                ("generation", fields.IntField(default=0)),
                ("migration_state", fields.CharField(default="none", max_length=16)),
                ("migration_note", fields.CharField(null=True, max_length=255)),
                ("updated_at", fields.DatetimeField(auto_now=True, auto_now_add=False)),
                (
                    "account",
                    fields.ForeignKeyField(
                        "models.Account",
                        source_field="account_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="provider_credential_slots",
                        on_delete=fields.OnDelete.CASCADE,
                    ),
                ),
                (
                    "effective_connection",
                    fields.ForeignKeyField(
                        "models.OAuthConnection",
                        source_field="effective_connection_id",
                        null=True,
                        db_constraint=True,
                        to_field="id",
                        related_name="effective_for_slots",
                        on_delete=fields.OnDelete.SET_NULL,
                    ),
                ),
            ],
            options={
                "table": "provider_credential_slots",
                "app": "models",
                "pk_attr": "id",
                "unique_together": (("account_id", "provider"),),
            },
            bases=["Model"],
        ),
    ]
