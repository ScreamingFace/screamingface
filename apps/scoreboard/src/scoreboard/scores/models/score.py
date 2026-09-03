from __future__ import annotations

import uuid

from tortoise import fields

from .base import BaseScoreboardModel


class BaseScore(BaseScoreboardModel):
    class Meta:
        abstract = True

    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    version = fields.IntField(default=1)
    spec_id = fields.CharField(max_length=255, db_index=True)
    url4_expression = fields.TextField()
    submitted_by = fields.CharField(max_length=255, null=True)
    # FEATURE: OME-1051 — credit is separate from ownership. NULL means the client did not
    # specify authors, so read DTOs derive [submitted_by] for backwards compatibility; an
    # explicit JSON list is the exact credit line and is never auto-expanded.
    authors = fields.JSONField(null=True)
    submitted_at = fields.DatetimeField(auto_now_add=True)
    score = fields.FloatField()  # the exact primary score the Engine Benchmark produced
    total_questions = fields.IntField()
    correct_questions = fields.IntField(null=True)
    ran_with_providers = fields.JSONField()
    ran_at_local = fields.DatetimeField(null=True)
    client_name = fields.CharField(max_length=128, null=True)
    client_version = fields.CharField(max_length=64, null=True)
    client_platform = fields.CharField(max_length=32, null=True)
    # WHY True: a TEMPORARY placeholder, not a verification claim.
    #
    # Nothing re-runs submissions yet (OME-414 is unstarted and unstaffed), so with
    # default=False every row on the board read "unverified" permanently. Nothing
    # attests execution provenance either: the SDK takes independent engine_url and
    # scoreboard_url, and the chart ships authMode: disabled, so a submission is an
    # unattested client payload. This field therefore asserts nothing today.
    #
    # INVARIANT: the public portal must not claim more than this. index.html and
    # benchmark.html say the top row is the best *submitted* result and never call any row
    # verified or reproduced. They previously said "Verified means OpenMined independently
    # reproduced the run", which this default would have turned into a false claim on every
    # row. Change the default and that copy together, or the board lies.
    #
    # AIDEV-NOTE (OME-874): the mockup's note claimed the board filters to reproduced rows by
    # default and offered a toggle for the rest. Both describe machinery that does not exist —
    # the query never filters on this field — so the two sentences were removed and the third
    # kept with one word changed ("verified" -> "submitted"). The copy and the pool filter are
    # one change, not two: restore that wording only alongside OME-771.
    verified_by_screamingface = fields.BooleanField(default=True)
    # INVARIANT: the Engine benchmark revision this score was produced against. The
    # leaderboard partitions ranking on (spec_id, benchmark_revision) so results measured
    # against different dataset/protocol revisions never rank against each other (OME-775).
    # WHY nullable + indexed: OME-322's imported LMArena baselines never ran at any revision
    # and every row predating this change has none, so no backfill is possible; indexed
    # because it is a ranking partition key.
    # AIDEV-NOTE: the Client sends this inside the free-form `metadata` dict today; the store
    # promotes it via _resolve_benchmark_revision. Read that before changing the wire shape.
    benchmark_revision = fields.CharField(max_length=64, null=True, db_index=True)
    metadata = fields.JSONField(null=True)
    # WHY Decimal and not Float: this is money. Binary floating point cannot
    # represent it exactly, and a leaderboard that publishes a dollar figure
    # should not accumulate representation error in it. `score` above stays a
    # FloatField deliberately — a benchmark score is not currency.
    #
    # WHY these bounds: both ends of the real range have to fit. A cache-served
    # smoke run costs fractions of a cent (0.000123 is representable here), and a
    # full DRACO rerun was quoted at $3-4k, so 6 decimal places under 12 digits
    # covers 0.000001 through 999,999.999999.
    #
    # INVARIANT: NULL means "no cost was reported", which is NOT the same as 0.
    # A fully cache-served run genuinely costing nothing is a legitimate 0 (see
    # OME-767's zero-cost goal). OME-770's Pareto frontier would rank an
    # unknown-cost row as the cheapest entry if these two were ever conflated, so
    # readers and renderers must keep them distinct.
    #
    # AIDEV-NOTE: deliberately NOT part of content_hash. That hash is recipe
    # identity; cost is a property of one execution of a recipe, and two runs of
    # the same recipe can cost different amounts while still being the same
    # submission for dedup purposes (OME-391). The accepted consequence is that a
    # recipe already submitted without a cost cannot later gain one — the
    # resubmission dedups to the existing row.
    run_cost_usd = fields.DecimalField(max_digits=12, decimal_places=6, null=True)
    # INVARIANT: sha256 hex over the submission's recipe identity (benchmark, spec,
    # url4 expression, result numbers, provider order) — NOT submitted_by or client
    # metadata. Unique so the DB itself rejects a duplicate recipe, independent of
    # any client-supplied Idempotency-Key (OME-391 / C28). Nullable so this column
    # can be added to a table with pre-existing rows without a backfill migration —
    # multiple NULLs don't violate a unique constraint, and every row created from
    # here on always gets one (the store always computes it on submit).
    content_hash = fields.CharField(max_length=64, unique=True, null=True)
    # FEATURE: OME-323 — manual open/closed correction, operator-only (never set via
    # the public submission API). `null` defers to the classification registry
    # (scoreboard.classification.openness); an explicit "open"/"closed" wins outright
    # over whatever the registry would have said, without a code deploy.
    openness_override = fields.CharField(max_length=8, null=True)


class Score(BaseScore):
    class Meta:
        table = "scores"
        indexes = (
            ("benchmark_id", "score"),
            ("benchmark_id", "spec_id", "submitted_at"),
        )

    benchmark = fields.ForeignKeyField(
        "models.Benchmark",
        related_name="scores",
        on_delete=fields.OnDelete.RESTRICT,
    )
