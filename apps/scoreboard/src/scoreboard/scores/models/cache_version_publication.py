from __future__ import annotations

import uuid

from tortoise import fields

from .base import BaseScoreboardModel


class BaseCacheVersionPublication(BaseScoreboardModel):
    """FEATURE: OME-1307 (E14) — publication state of the cache version behind one result."""

    class Meta:
        abstract = True

    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    state = fields.CharField(max_length=16, default="private")
    requested_by = fields.CharField(max_length=255, null=True)
    requested_at = fields.DatetimeField(null=True)
    attempts = fields.IntField(default=0)
    next_attempt_at = fields.DatetimeField(null=True)
    lease_until = fields.DatetimeField(null=True)
    last_error = fields.CharField(max_length=512, null=True)
    release_tag = fields.CharField(max_length=64, null=True)
    release_url = fields.CharField(max_length=512, null=True)
    published_at = fields.DatetimeField(null=True)
    withdrawn_at = fields.DatetimeField(null=True)
    withdrawn_by = fields.CharField(max_length=255, null=True)
    withdrawn_reason = fields.TextField(null=True)


class CacheVersionPublication(BaseCacheVersionPublication):
    class Meta:
        table = "cache_version_publication"
        indexes = (("state", "next_attempt_at"),)

    # WHY a separate `id` primary key (plan 4.7 fallback): Tortoise 1.1.8 does not round-trip a
    # one-to-one primary key through its migration state, so `makemigrations` kept proposing an
    # `AlterModelOptions` for this model. A one-to-one column is unique, so `result_id` is still
    # one row per result.
    result = fields.OneToOneField(
        "models.ReportedResult",
        related_name="publication",
        on_delete=fields.OnDelete.CASCADE,
    )
