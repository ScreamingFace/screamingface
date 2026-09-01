from __future__ import annotations

from tortoise import fields

from .base import BaseScoreboardModel


class BaseIdempotencyKey(BaseScoreboardModel):
    class Meta:
        abstract = True

    key = fields.CharField(max_length=255, primary_key=True)
    expires_at = fields.DatetimeField(db_index=True)
    # FEATURE: OME-894 — which code wrote this mapping. NULL means "written by a replica that did
    # not know about this column", which is exactly what an old pod serving through a rollout does.
    #
    # INVARIANT: the `sfp-`/`sfu-` namespaces are SERVER-owned, but `main` stores client keys
    # verbatim — so an old replica can bind a predictable `sfp-` token to an attacker-chosen row.
    # With a forged `submitted_by` on a PUBLIC target, the ownership branch then honoured it for the
    # verified owner it named, returning the attacker's row in place of the victim's own private
    # submission. Reproduced in review of PR #719. A reserved-namespace mapping is only honoured
    # when this column says WE wrote it; nothing a client can send sets it.
    scheme = fields.CharField(max_length=8, null=True)


class IdempotencyKey(BaseIdempotencyKey):
    class Meta:
        table = "idempotency_keys"

    score = fields.ForeignKeyField(
        "models.Score",
        related_name="idempotency_keys",
        on_delete=fields.OnDelete.CASCADE,
    )
