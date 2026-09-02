from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from tortoise import fields
from tortoise.models import Model

if TYPE_CHECKING:
    from aigateway.core.auth.models import Account


class BaseOAuthConnection(Model):
    class Meta:
        abstract = True

    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    provider = fields.CharField(max_length=64, index=True)
    label = fields.CharField(max_length=255)
    status = fields.CharField(max_length=32, index=True)
    # db_default is required alongside default: tortoise emits a SQL DEFAULT
    # clause only for db_default, and the ADD COLUMN is NOT NULL — without it
    # the migration fails on any database with existing rows (SF-244 audit F01).
    auth_type = fields.CharField(max_length=16, default="oauth", db_default="oauth")
    identity_sub = fields.CharField(max_length=255, null=True)
    identity_email = fields.CharField(max_length=320, null=True)
    identity_name = fields.CharField(max_length=255, null=True)
    identity_raw: Any = fields.JSONField(null=True)
    credential_locator: Any = fields.JSONField()
    created_at = fields.DatetimeField(auto_now_add=True)
    last_used_at = fields.DatetimeField(null=True)
    last_refreshed_at = fields.DatetimeField(null=True)
    error_message: Any = fields.TextField(null=True)
    # INVARIANT (OME-1026 U2): the durable, strictly-advancing, NON-SECRET fence for
    # "which credential owner produced this connection's private discovery snapshots".
    # API-key creation publishes generation 1; in-place API-key replacement applies an
    # atomic F()+1 in reactivate's SAME conditional UPDATE. Generic OAuth completion and
    # refresh preserve the generation because they do not publish API-key ownership.
    # WHY not last_refreshed_at: a wall clock can assign two replacements one tick
    # (the profile-side F3 defect); an integer under the row lock cannot.
    credential_generation = fields.IntField(default=0, db_default="0")


class OAuthConnection(BaseOAuthConnection):
    class Meta:
        table = "oauth_connections"
        unique_together = (
            ("account_id", "provider", "identity_sub"),
            ("account_id", "provider", "label"),
        )

    account: fields.ForeignKeyRelation[Account] = fields.ForeignKeyField(
        "models.Account",
        related_name="oauth_connections",
        on_delete=fields.OnDelete.CASCADE,
    )

    if TYPE_CHECKING:
        account_id: uuid.UUID
