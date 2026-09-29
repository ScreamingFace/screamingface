from __future__ import annotations

import uuid

from tortoise import fields

from .base import BaseScoreboardModel


class BaseReportedResult(BaseScoreboardModel):
    """FEATURE: OME-1307 (E14) — one reported run of a head (original or replay), erd.md §2.2.

    INVARIANT: the I-R1 and I-R2 "all set or all null" rules are NOT database constraints in this
    unit. SB-submit enforces them in code.
    """

    class Meta:
        abstract = True

    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    is_original = fields.BooleanField()
    reporter = fields.CharField(max_length=255, null=True)
    run_id = fields.CharField(max_length=128, null=True, unique=True)
    trace_id = fields.CharField(max_length=32, null=True)
    score = fields.FloatField()
    total_questions = fields.IntField()
    correct_questions = fields.IntField(null=True)
    run_cost_usd = fields.DecimalField(max_digits=12, decimal_places=6, null=True)
    run_cost_status = fields.CharField(max_length=16, null=True)
    cache_saved_cost_usd = fields.DecimalField(max_digits=12, decimal_places=6, null=True)
    models = fields.JSONField(null=True)
    ran_with_providers = fields.JSONField(null=True)
    answer_seed = fields.IntField(null=True)
    client_name = fields.CharField(max_length=128, null=True)
    client_version = fields.CharField(max_length=64, null=True)
    client_platform = fields.CharField(max_length=32, null=True)
    submitted_at = fields.DatetimeField(auto_now_add=True)
    cache_version_id = fields.UUIDField(null=True, unique=True)  # I-R4
    cache_version_sha256 = fields.CharField(max_length=64, null=True)
    cache_entry_count = fields.IntField(null=True)
    cache_call_count = fields.IntField(null=True)
    cache_coverage_status = fields.CharField(max_length=16, null=True)
    replay_hits = fields.IntField(null=True)
    replay_misses = fields.IntField(null=True)
    # C4 replay.repeated_key_collapses (RP-D5); cross-plan fix, SB-submit G3.
    replay_repeated_key_collapses = fields.IntField(null=True)


class ReportedResult(BaseReportedResult):
    class Meta:
        table = "reported_result"
        # WHY the key attribute `head_id` and not `head`: the index resolver uses
        # `field.source_field or name`; for the relation `head` Tortoise overwrites `source_field`
        # with the attribute name `head_id`, which is not a column. `head_id` resolves to the
        # column `score_id`.
        indexes = (("head_id", "submitted_at"),)

    # WHY named `head` and not `score`: the result number is already `score` (erd.md §2.2).
    # WHY related_name=False on every FK to Score: a reverse relation adds a key to
    # `Score._meta.fields_map`, and the append-only CHAR guard
    # `test_every_score_field_reaches_at_least_one_read_dto` then fails.
    # WHY CASCADE: `delete_scores`, `purge_private_benchmark` and `retire_benchmark` delete Score
    # rows with the ORM, and every score has a child row; RESTRICT would break all three tools.
    head = fields.ForeignKeyField(
        "models.Score",
        source_field="score_id",
        related_name=False,
        on_delete=fields.OnDelete.CASCADE,
    )
    # WHY RESTRICT (OD-S2): it keeps I-R2; `delete_scores` fails loudly for a score whose result
    # another run replayed.
    replayed_from = fields.ForeignKeyField(
        "models.ReportedResult",
        source_field="replayed_from_result_id",
        related_name=False,
        null=True,
        on_delete=fields.OnDelete.RESTRICT,
    )
    pinned_baseline = fields.ForeignKeyField(
        "models.ReportedResult",
        source_field="pinned_baseline_result_id",
        related_name=False,
        null=True,
        on_delete=fields.OnDelete.RESTRICT,
    )
