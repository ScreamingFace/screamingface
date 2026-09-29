from __future__ import annotations

import uuid

from tortoise import fields

from .base import BaseScoreboardModel


class BaseScoreMetadataEvent(BaseScoreboardModel):
    """FEATURE: OME-1307 (E14a) — audit row for one metadata edit of a score (erd.md §2.5).

    INVARIANT: append-only. No code updates or deletes a row; the only delete is the cascade from
    its score.
    """

    class Meta:
        abstract = True

    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    # INVARIANT (D5): production (cloudflare_headers) always stores the verified X-User-Email.
    # NULL only in the auth_mode=disabled dev/local fallback, where no verified identity exists.
    actor = fields.CharField(max_length=255, null=True)
    at = fields.DatetimeField(auto_now_add=True)
    from_revision = fields.IntField()
    to_revision = fields.IntField()
    before = fields.JSONField()  # {"authors": list[str] | None, "paper_url": str | None}
    after = fields.JSONField()  # same shape


class ScoreMetadataEvent(BaseScoreMetadataEvent):
    class Meta:
        table = "score_metadata_event"
        unique_together = (("score", "to_revision"),)

    score = fields.ForeignKeyField(
        "models.Score", related_name=False, on_delete=fields.OnDelete.CASCADE
    )
