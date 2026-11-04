"""The pair authority marker — one row per `(account, provider)` (OME-1208, Stage B S1).

# FEATURE: OME-1138 Stage B — says how a provider-access pair is owned (`migrated` = the effective
# Connection this row names; `none` = the pair's Connections, with no reference) and which
# Connection is effective. Design: the provider-access card, "Stage B Target — Connection-Backed
# Authority".
# INVARIANT (D1): one marker per pair, enforced by the DATABASE through `unique_together` on a
# conventional single primary key — Tortoise 1.1.8 supports neither a composite primary key nor a
# partial unique index.
# INVARIANT (D2): the row carries no request defaults and no secret.
# INVARIANT: an absent row means `none` — the pair's Connections own it, served only as its one
# active row (OME-1209 §9 Q8) — and the writer floor fences every writer that changes that owner.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from tortoise import fields
from tortoise.models import Model

if TYPE_CHECKING:
    from ...auth.models import Account
    from ...oauth.models import OAuthConnection


class BaseProviderCredentialSlot(Model):
    """The marker's own fields, without relations — the interface services and mocks stand on."""

    class Meta:
        abstract = True

    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    provider = fields.CharField(max_length=64)
    # WHY monotonic: every authority-changing write is `UPDATE … WHERE generation = expected`, so a
    # stale writer — an old callback, a retried backfill — is fenced at commit time, not by an
    # in-memory lock. 0 is reserved for "no row yet": the first write creates the row at 1.
    generation = fields.IntField(default=0)
    # `none` | `migrated`. Validated by `pair_authority.PairAuthorityStore` on every write AND every
    # read — an unknown stored state is refused loudly, never read as `none`.
    migration_state = fields.CharField(max_length=16, default="none")
    # WHY the field stays (OME-1138 close-out, spec §9 Q1, two steps): no code reads or writes it
    # since L4a, so a rolled-back image still finds its column and the autodetector proposes
    # nothing. L4c drops it, with its migration, in the following gateway release.
    migration_note = fields.CharField(max_length=255, null=True)
    updated_at = fields.DatetimeField(auto_now=True)


class ProviderCredentialSlot(BaseProviderCredentialSlot):
    class Meta:
        table = "provider_credential_slots"
        unique_together = (("account_id", "provider"),)

    account: fields.ForeignKeyRelation[Account] = fields.ForeignKeyField(
        "models.Account",
        related_name="provider_credential_slots",
        on_delete=fields.OnDelete.CASCADE,
    )
    # WHY SET NULL, not RESTRICT: the application clears the reference in the same transaction
    # before a Connection row goes (card: "delete clears the effective reference before the blob
    # goes"); the database rule is the safety net for a writer that does not. A `migrated` row with
    # no effective Connection is a legitimate state — Connection-owned and empty — and never a
    # fall-back to the legacy Profile, whose still-authenticated index entry would otherwise serve
    # the old credential again.
    effective_connection: fields.ForeignKeyNullableRelation[OAuthConnection] = (
        fields.ForeignKeyField(
            "models.OAuthConnection",
            related_name="effective_for_slots",
            null=True,
            on_delete=fields.OnDelete.SET_NULL,
        )
    )
