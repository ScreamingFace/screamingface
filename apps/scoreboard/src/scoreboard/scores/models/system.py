from __future__ import annotations

import uuid

from tortoise import fields

from .base import BaseScoreboardModel


class BaseSystem(BaseScoreboardModel):
    """FEATURE: OME-1307 (E14) — a named system that heads cluster under, by revision."""

    class Meta:
        abstract = True

    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    name = fields.CharField(max_length=64, unique=True)  # normalized, erd.md §2.3.1
    owner = fields.CharField(max_length=255)
    created_at = fields.DatetimeField(auto_now_add=True)


class System(BaseSystem):
    class Meta:
        table = "system"


class BaseSystemRevision(BaseScoreboardModel):
    """FEATURE: OME-1307 (E14) — one fingerprinted revision of a system (erd.md §2.3)."""

    class Meta:
        abstract = True

    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    revision = fields.IntField()
    # INVARIANT: one revision per fingerprint across all systems (erd.md §2.3).
    fingerprint = fields.CharField(max_length=64, unique=True)
    candidate_url4 = fields.TextField()
    declared_by = fields.CharField(max_length=255)
    created_at = fields.DatetimeField(auto_now_add=True)


class SystemRevision(BaseSystemRevision):
    class Meta:
        table = "system_revision"
        unique_together = (("system", "revision"),)

    system = fields.ForeignKeyField(
        "models.System", related_name="revisions", on_delete=fields.OnDelete.RESTRICT
    )
