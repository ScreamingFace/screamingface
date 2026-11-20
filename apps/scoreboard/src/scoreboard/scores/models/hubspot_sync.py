"""One row per score: whether the HubSpot sync has handled it, and how it went."""

from __future__ import annotations

from tortoise import fields

from .base import BaseScoreboardModel

STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

# WHY `failed` is due again: it retries with backoff until HubSpot accepts it; there is no
# give-up state (out of scope, 2026-11-19).
DUE_STATUSES = (STATUS_PENDING, STATUS_FAILED)


class BaseHubSpotSyncRecord(BaseScoreboardModel):
    """FEATURE: OME-1504 — every outside submission reaches the 😱 SOTA pipeline in HubSpot.

    The table is the queue: the submit path never calls HubSpot, so a HubSpot outage delays the
    card and never fails or slows a submission. A score with no row has not been seen yet.

    INVARIANT: no email or other personal data lives here. The address stays on `scores`, so
    deleting a score (or purging a board) removes its sync row by cascade and leaves nothing.
    """

    class Meta:
        abstract = True

    id = fields.IntField(primary_key=True)
    status = fields.CharField(max_length=16, default=STATUS_PENDING, db_index=True)
    # WHY bounded: a skip or failure reason is a short machine-readable code plus, for a HubSpot
    # error, its status. Never a response body, which could echo request data.
    reason = fields.CharField(max_length=128, null=True)
    # INVARIANT: decided ONCE, when the score is queued, against the board at that moment
    # (rule B). A retry sends the same answer a first attempt would have; a later, stronger
    # result on the board never takes it back. NULL only on `skipped` rows, which are never sent.
    sota_qualified = fields.BooleanField(null=True)
    attempts = fields.IntField(default=0)
    next_attempt_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)


class HubSpotSyncRecord(BaseHubSpotSyncRecord):
    class Meta:
        table = "hubspot_sync"

    # WHY cascade: the row describes one score and means nothing without it; `delete_scores` and
    # `purge_private_benchmark` count what is left of the scores, not the delete count, so the
    # extra cascaded rows cannot upset their checks.
    # WHY no reverse relation: `Score` stays exactly as it was, so nothing reading Score's fields
    # (its DTO guard included) sees this bookkeeping; the job reads this table directly.
    score = fields.OneToOneField(
        "models.Score",
        related_name=False,
        on_delete=fields.OnDelete.CASCADE,
    )
