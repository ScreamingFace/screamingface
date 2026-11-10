from __future__ import annotations

import uuid

from tortoise import fields

from .base import BaseScoreboardModel


class BaseBaseline(BaseScoreboardModel):
    class Meta:
        abstract = True

    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    model_name = fields.CharField(max_length=255)
    score = fields.FloatField()
    source = fields.CharField(max_length=64)
    source_url = fields.CharField(max_length=2048, null=True)
    imported_at = fields.DatetimeField(auto_now_add=True)
    # WHY: first import remains stable; a refresh records its own time separately.
    # Unknown historical provenance stays null rather than being backfilled.
    last_imported_at = fields.DatetimeField(null=True)
    metric_name = fields.CharField(max_length=128, null=True)
    observed_at = fields.DatetimeField(null=True)
    attached_by = fields.CharField(max_length=255, null=True)
    metadata = fields.JSONField(null=True)
    observation_revision = fields.IntField(default=0, db_default=0)
    observation_updated_at = fields.DatetimeField(null=True)
    # FEATURE: OME-323 — manual open/closed correction, mirrors Score.openness_override.
    # `null` defers to the classification registry; an explicit "open"/"closed" wins
    # outright.
    openness_override = fields.CharField(max_length=8, null=True)


class Baseline(BaseBaseline):
    class Meta:
        table = "baselines"
        unique_together = (("benchmark", "model_name", "source"),)

    benchmark = fields.ForeignKeyField(
        "models.Benchmark",
        related_name="baselines",
        on_delete=fields.OnDelete.RESTRICT,
    )
