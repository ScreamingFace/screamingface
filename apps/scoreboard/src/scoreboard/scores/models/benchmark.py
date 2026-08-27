from __future__ import annotations

from tortoise import fields

from .base import BaseScoreboardModel


class BaseBenchmark(BaseScoreboardModel):
    class Meta:
        abstract = True

    id = fields.CharField(max_length=64, primary_key=True)
    display_name = fields.CharField(max_length=255)
    description = fields.TextField(null=True)
    # A short editorial line — what this benchmark is actually about — shown as the portal
    # catalogue's "Focus" column (OME-874). Editorial copy, not derived from the Engine, so it
    # is nullable: a benchmark can ship without one and the cell renders an em dash.
    focus = fields.CharField(max_length=120, null=True)
    # AIDEV-NOTE: editorial copy, seeded by an operator through SCOREBOARD_SEED_BENCHMARKS.
    # Deployed environments keep their own values file, so adding a value here does not
    # propagate on its own — the platform team syncs it (same caveat as `revision`).
    dataset_url = fields.CharField(max_length=2048, null=True)
    # INVARIANT: mirrors the Engine benchmark's immutable REVISION — a sha256 over its
    # dataset + protocol (+ verifier) revisions. It identifies *what was measured*, so two
    # revisions of one benchmark are not comparable results (OME-775).
    # WHY nullable: the retained legacy demo entries (hle/livetruth/livetruth-latest) have no
    # Engine revision, so this column is added without a backfill.
    revision = fields.CharField(max_length=64, null=True)
    # INVARIANT (OME-894): privacy is a property of the BENCHMARK, enforced in the API on every
    # read path — not a portal concern. The portal is static JS against a public API, so hiding
    # rows in the page would leave `curl /v1/leaderboard/{id}` serving the whole board.
    # WHY a default and NOT nullable: an unknown visibility must not resolve to private by
    # accident (the entry challenge becomes unreadable) or public by accident (it leaks).
    # `public` preserves today's behaviour for every existing row, so no backfill is needed.
    # WHY nullable despite always being written: tightening this to NOT NULL has no native
    # SQLite equivalent, so Tortoise rebuilds the table and DROPs the old one — which fails with
    # "FOREIGN KEY constraint failed" on any board that already holds a score or baseline
    # (reproduced in review of PR #719). The constraint bought nothing: `default` guarantees a
    # value on every write, and a NULL from a pre-migration row reads as public, which is exactly
    # what the backfill asserts. Readers coerce via benchmark_to_schema.
    visibility = fields.CharField(max_length=16, default="public", null=True)
    created_at = fields.DatetimeField(auto_now_add=True)


class Benchmark(BaseBenchmark):
    class Meta:
        table = "benchmarks"
