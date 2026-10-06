from __future__ import annotations

import uuid

from tortoise import fields

from .base import BaseScoreboardModel


class BaseScoreReproduction(BaseScoreboardModel):
    class Meta:
        abstract = True

    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    # FEATURE: OME-1307 — the verified identity that recorded the replay. Any identity may record,
    # including the submitter; the board cannot prove a replay ran, so the record names who says so.
    reproduced_by = fields.CharField(max_length=255)
    reproduced_at = fields.DatetimeField(auto_now_add=True)
    # The replay run's id from the client. Unique per score, so a retry is not counted twice.
    run_id = fields.CharField(max_length=128)
    # INVARIANT: equal to the score's `cache_revision` (the route refuses anything else), kept on
    # the row so a record states the revision it replayed even if the score row is corrected.
    cache_revision = fields.CharField(max_length=32, null=True)
    client_version = fields.CharField(max_length=64, null=True)


class ScoreReproduction(BaseScoreReproduction):
    class Meta:
        table = "score_reproductions"
        unique_together = (("score", "run_id"),)

    # INVARIANT: a row exists only for an EXACT replay of a `complete` score. Failed replays are
    # never recorded, and there is no per-identity cap.
    score = fields.ForeignKeyField(
        "models.Score",
        # WHY no reverse relation: the count is derived by querying this table on `score_id`, and a
        # reverse relation would be one more `Score` field that every read-DTO guard has to know
        # about (the same reasoning as `ScoreMetadataEvent.score`).
        related_name=False,
        on_delete=fields.OnDelete.CASCADE,
    )
