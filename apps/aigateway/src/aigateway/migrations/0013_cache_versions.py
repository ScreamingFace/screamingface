"""Create the five E14 cache-version tables (OME-1307, GW-capture).

UPGRADE. Five ``CREATE TABLE`` plus their indexes: ``request_cache_prompt``,
``cache_capture_entry`` (with the ``(account_id, trace_id, ordinal)`` index and the ``(key_hash)``
index for the prune anti-join), ``cache_version`` (unique ``(owner_account_id, trace_id)``, and the
``(status, created_at)`` exporter index), ``cache_version_blob`` and ``cache_version_entry`` (unique
``(version_id, key_hash, blob_id)``, which also serves the replay lookup by
``(version_id, key_hash)``). Expand-only: no existing table is touched or rebuilt, so the standalone
indexes SQLite drops with a rebuilt table are not at risk. All five tables are created EMPTY.

DOWNGRADE. Drop exactly the five tables, in reverse dependency order (the entry table first).
Pinned by ``test_0013_downgrade_drops_only_the_five_tables``.

ROLLBACK. Run the downgrade only for a rollback of the schema itself. It destroys every capture row
and every frozen version. To stop capture without a schema change, set
``AIGW_CACHE_VERSIONS_ENABLED=false``.

WHY TEXT and not JSONB (plan OD-3): the live cache stores TEXT, and JSONB rewrites number and key
forms, which can break the reproducible ``archive_sha256`` (erd.md 3.5).

WHY the capture primary key is a BIGINT ``ordinal`` (plan OD-4): the database gives an exact arrival
order across gateway replicas without a clock or a lock. There is no UUID ``id`` (erd.md 3.2
differs).

WHY ``cache_capture_entry.key_hash`` is NULL for an unkeyable call (plan OD-2): a streaming call
has a capture row and no key (erd.md 3.2 says NOT NULL).

WHY ``cache_version_entry`` has a UUID surrogate primary key: Tortoise 1.1.8 has no composite
primary key, so the ``(version_id, key_hash, blob_id)`` rule is a unique index.

AUTHORING NOTE. Generated with ``tortoise makemigrations -n cache_versions models`` and then
edited. The autodetector's extra proposal, ``AlterField`` on ``OAuthConnection.account``, is
DROPPED. That is the pre-existing drift that the 0012 docstring records; applying it would rebuild
``oauth_connections`` on SQLite and drop that table's standalone indexes.

The two foreign keys keep the Tortoise native column names ``version_id`` and ``blob_id`` (decision
D8). Tortoise 1.1.8 overwrites a custom FK ``source_field`` with ``<attr>_id`` at init, so a custom
column name would make the autodetector propose an ``AlterField`` for ever. ``blob_id`` holds the
``CacheVersionBlob.sha256`` value (erd.md 3.4 differs).
"""

from uuid import uuid4

from tortoise import fields, migrations
from tortoise.fields.base import OnDelete
from tortoise.indexes import Index
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("models", "0012_provider_credential_slots")]

    initial = False

    operations = [
        ops.CreateModel(
            name="CacheCaptureEntry",
            fields=[
                (
                    "ordinal",
                    fields.BigIntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                ("account_id", fields.CharField(max_length=64)),
                ("trace_id", fields.CharField(max_length=32)),
                ("key_hash", fields.CharField(null=True, max_length=64)),
                ("outcome", fields.CharField(max_length=16)),
                ("response_json", fields.TextField(null=True, unique=False)),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
            ],
            options={
                "table": "cache_capture_entry",
                "app": "models",
                "indexes": [
                    Index(fields=["account_id", "trace_id", "ordinal"]),
                    Index(fields=["key_hash"]),
                ],
                "pk_attr": "ordinal",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="CacheVersion",
            fields=[
                (
                    "id",
                    fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True),
                ),
                ("owner_account_id", fields.CharField(max_length=64)),
                ("trace_id", fields.CharField(max_length=32)),
                ("status", fields.CharField(default="frozen", max_length=16)),
                ("entry_count", fields.IntField()),
                ("call_count", fields.IntField()),
                ("missing_count", fields.IntField()),
                ("coverage_status", fields.CharField(max_length=16)),
                ("archive_sha256", fields.CharField(max_length=64)),
                ("archive_key", fields.CharField(max_length=256)),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
            ],
            options={
                "table": "cache_version",
                "app": "models",
                "unique_together": (("owner_account_id", "trace_id"),),
                "indexes": [Index(fields=["status", "created_at"])],
                "pk_attr": "id",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="CacheVersionBlob",
            fields=[
                (
                    "sha256",
                    fields.CharField(primary_key=True, unique=True, db_index=True, max_length=64),
                ),
                ("request_json", fields.TextField(unique=False)),
                ("response_json", fields.TextField(unique=False)),
                ("metadata_json", fields.TextField(null=True, unique=False)),
                ("size_bytes", fields.IntField()),
            ],
            options={"table": "cache_version_blob", "app": "models", "pk_attr": "sha256"},
            bases=["Model"],
        ),
        ops.CreateModel(
            name="CacheVersionEntry",
            fields=[
                (
                    "id",
                    fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True),
                ),
                (
                    "version",
                    fields.ForeignKeyField(
                        "models.CacheVersion",
                        source_field="version_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="entries",
                        on_delete=OnDelete.RESTRICT,
                    ),
                ),
                ("key_hash", fields.CharField(max_length=64)),
                (
                    "blob",
                    fields.ForeignKeyField(
                        "models.CacheVersionBlob",
                        source_field="blob_id",
                        db_constraint=True,
                        to_field="sha256",
                        related_name="entries",
                        on_delete=OnDelete.RESTRICT,
                    ),
                ),
                ("first_ordinal", fields.BigIntField()),
            ],
            options={
                "table": "cache_version_entry",
                "app": "models",
                "unique_together": (("version_id", "key_hash", "blob_id"),),
                "pk_attr": "id",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="RequestCachePrompt",
            fields=[
                (
                    "key_hash",
                    fields.CharField(primary_key=True, unique=True, db_index=True, max_length=64),
                ),
                ("request_json", fields.TextField(unique=False)),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
            ],
            options={"table": "request_cache_prompt", "app": "models", "pk_attr": "key_hash"},
            bases=["Model"],
        ),
    ]
