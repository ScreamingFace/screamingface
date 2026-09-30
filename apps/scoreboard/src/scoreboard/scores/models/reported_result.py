from __future__ import annotations

import uuid

from tortoise import fields

from .base import IDEMPOTENCY_KEY_MAX_LEN, BaseScoreboardModel


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
    # INVARIANT (FS-1): as wide as `IdempotencyKey.key`. A public key is stored as sent and is the
    # run id, so a narrower column made a 129 to 255 character key a 500 with clustering on.
    run_id = fields.CharField(max_length=IDEMPOTENCY_KEY_MAX_LEN, null=True, unique=True)
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
        # WHY the key attribute `head_id`: the index resolver uses `field.source_field or name`, and
        # for the relation `head` Tortoise sets `source_field` to `head_id`, the real column (D8).
        indexes = (("head_id", "submitted_at"),)

    # WHY named `head` and not `score`: the result number is already `score` (erd.md §2.2).
    # WHY no `source_field` on any FK here (D8): Tortoise 1.1.8 overwrites an FK `source_field` with
    # `<attr>_id` at init (`tortoise/apps.py:205`), so a custom column would split the migration
    # state from the database. The native columns are `head_id`, `replayed_from_result_id` and
    # `pinned_baseline_result_id`, the erd.md §2.2 names.
    # WHY related_name=False on every FK to Score: a reverse relation adds a key to
    # `Score._meta.fields_map`, and the append-only CHAR guard
    # `test_every_score_field_reaches_at_least_one_read_dto` then fails.
    # WHY CASCADE: `delete_scores`, `purge_private_benchmark` and `retire_benchmark` delete Score
    # rows with the ORM, and every score has a child row; RESTRICT would break all three tools.
    head = fields.ForeignKeyField(
        "models.Score",
        related_name=False,
        on_delete=fields.OnDelete.CASCADE,
    )
    # WHY NO_ACTION and not RESTRICT (OD-S2, D8): SQLite checks RESTRICT at once, row by row, also
    # inside the CASCADE from the head, so the delete of a head whose own cluster holds a replay of
    # its own original would fail. NO_ACTION is checked at the end of the statement on both
    # engines. INVARIANT: a replay in ANOTHER cluster still blocks the delete of its original, so
    # I-R2 holds; `delete_scores` fails loudly only for a score whose result another cluster's run
    # replayed.
    replayed_from_result = fields.ForeignKeyField(
        "models.ReportedResult",
        related_name=False,
        null=True,
        on_delete=fields.OnDelete.NO_ACTION,
    )
    pinned_baseline_result = fields.ForeignKeyField(
        "models.ReportedResult",
        related_name=False,
        null=True,
        on_delete=fields.OnDelete.NO_ACTION,
    )
