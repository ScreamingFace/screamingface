from __future__ import annotations

import uuid

from tortoise import fields

from .base import BaseScoreboardModel


class BaseScoreMetadataEvent(BaseScoreboardModel):
    class Meta:
        abstract = True

    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    # FEATURE: OME-1307 — the verified identity that made the change. It is always the submitter,
    # because only the submitter may edit (and only a same-owner resubmit reaches the replay path).
    edited_by = fields.CharField(max_length=255)
    edited_at = fields.DatetimeField(auto_now_add=True)
    # `patch` (PATCH /v1/scores/{id}) or `resubmit` (the same-owner correction path in the store).
    source = fields.CharField(max_length=16)
    # INVARIANT: the RAW stored values before and after, so NULL authors stay NULL here (a read
    # derives [submitted_by], the log does not). A field the request did not change has equal old
    # and new values.
    old_authors = fields.JSONField(null=True)
    new_authors = fields.JSONField(null=True)
    old_paper_url = fields.TextField(null=True)
    new_paper_url = fields.TextField(null=True)


class ScoreMetadataEvent(BaseScoreMetadataEvent):
    class Meta:
        table = "score_metadata_events"
        indexes = (("score_id", "edited_at"),)

    # INVARIANT: only the owner reads these rows through the API (they hold author emails the owner
    # may have removed on purpose), and operators read them through the database.
    score = fields.ForeignKeyField(
        "models.Score",
        # WHY no reverse relation: nothing reads `score.metadata_events` (the store queries the
        # event table by `score_id`), and a reverse relation would be one more `Score` field that
        # every read-DTO guard has to know about.
        related_name=False,
        on_delete=fields.OnDelete.CASCADE,
    )
