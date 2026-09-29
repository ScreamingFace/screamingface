"""The frozen-version tables (OME-1307, GW-capture creates them; GW-freeze and GW-replay use them).

# FEATURE: OME-1307 (E14) - a cache version is the frozen set of answers of one traced run.
# INVARIANT: an entry is immutable once written; `(version_id, key_hash, blob_id)` is unique.
# WHY the entry has a UUID surrogate primary key: Tortoise 1.1.8 has no composite primary key.
# WHY the FK columns keep the native names `version_id` and `blob_id` (D8): Tortoise 1.1.8
# overwrites a custom FK `source_field` with `<attr>_id` at init, so a custom column name makes the
# autodetector propose an `AlterField` for ever. `blob_id` holds the `CacheVersionBlob.sha256`
# value.
"""

from __future__ import annotations

import uuid

from tortoise import fields
from tortoise.models import Model


class CacheVersion(Model):
    class Meta:
        table = "cache_version"
        unique_together = (("owner_account_id", "trace_id"),)
        indexes = (("status", "created_at"),)

    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    owner_account_id = fields.CharField(max_length=64)
    trace_id = fields.CharField(max_length=32)
    status = fields.CharField(max_length=16, default="frozen")
    entry_count = fields.IntField()
    call_count = fields.IntField()
    missing_count = fields.IntField()
    coverage_status = fields.CharField(max_length=16)
    archive_sha256 = fields.CharField(max_length=64)
    archive_key = fields.CharField(max_length=256)
    created_at = fields.DatetimeField(auto_now_add=True)


class CacheVersionBlob(Model):
    class Meta:
        table = "cache_version_blob"

    sha256 = fields.CharField(max_length=64, primary_key=True)
    request_json = fields.TextField()
    response_json = fields.TextField()
    metadata_json = fields.TextField(null=True)
    size_bytes = fields.IntField()


class CacheVersionEntry(Model):
    class Meta:
        table = "cache_version_entry"
        unique_together = (("version_id", "key_hash", "blob_id"),)

    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    version: fields.ForeignKeyRelation[CacheVersion] = fields.ForeignKeyField(
        "models.CacheVersion",
        related_name="entries",
        on_delete=fields.OnDelete.RESTRICT,
    )
    key_hash = fields.CharField(max_length=64)
    blob: fields.ForeignKeyRelation[CacheVersionBlob] = fields.ForeignKeyField(
        "models.CacheVersionBlob",
        to_field="sha256",
        related_name="entries",
        on_delete=fields.OnDelete.RESTRICT,
    )
    first_ordinal = fields.BigIntField()
