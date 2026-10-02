from __future__ import annotations

import uuid

from tortoise import fields
from tortoise.models import Model


class BaseCredentialBlob(Model):
    class Meta:
        abstract = True

    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    service = fields.CharField(max_length=255, index=True)
    account = fields.CharField(max_length=255, index=True)
    value = fields.TextField()
    # Encoding version stamped at write time (SF-221). The read path uses this
    # metadata together with the self-describing value prefix to reject corrupt or
    # wrong-provider blobs before plaintext legacy fallback. Nullable so the
    # migration can ADD COLUMN to an already-populated table without a backfill;
    # legacy pre-encryption rows carry NULL ("unknown version") until their next
    # write stamps "v1".
    #
    # NOTE: the ``default="v1"`` is ORM-side only — Tortoise emits no SQL DEFAULT,
    # so any row created outside ORMStore.write (and every pre-existing row) is
    # NULL, not "v1". Future rotation tooling must treat NULL as
    # "pre-encryption/unknown" rather than assume "v1" (e.g.
    # ``WHERE ciphertext_version IS NULL OR ciphertext_version != 'vN'``).
    ciphertext_version = fields.CharField(max_length=16, null=True, default="v1")
    credential_revision = fields.BigIntField(default=1, db_default=1)
    next_dispatch_sequence = fields.BigIntField(default=0, db_default=0)
    last_outcome_sequence = fields.BigIntField(default=0, db_default=0)
    last_operational_outcome = fields.CharField(max_length=32, null=True)
    last_outcome_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)


class CredentialBlob(BaseCredentialBlob):
    class Meta:
        table = "credential_blobs"
        unique_together = (("service", "account"),)
