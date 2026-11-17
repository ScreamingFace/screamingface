"""Immutable source observations, separate from the current ranked baseline."""

from __future__ import annotations

import uuid

from tortoise import fields

from .base import BaseScoreboardModel


class BaseBaselineRevision(BaseScoreboardModel):
    class Meta:
        abstract = True

    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    revision = fields.IntField()
    # WHY: the start of a legacy observation is unknown; its first import date
    # cannot stand in for an unknown intervening edit date.
    recorded_at = fields.DatetimeField(null=True)
    observation = fields.JSONField()
    attached_by = fields.CharField(max_length=255, null=True)


class BaselineRevision(BaseBaselineRevision):
    class Meta:
        table = "baseline_revisions"
        unique_together = (("baseline", "revision"),)

    baseline = fields.ForeignKeyField(
        "models.Baseline",
        related_name="revisions",
        on_delete=fields.OnDelete.RESTRICT,
    )
