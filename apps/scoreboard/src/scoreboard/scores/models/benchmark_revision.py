"""Every revision a benchmark has had, when the board first saw it, and its Case count."""

from __future__ import annotations

from tortoise import fields

from .base import BaseScoreboardModel


class BaseBenchmarkRevision(BaseScoreboardModel):
    """FEATURE: OME-1708 — the revision selector on each leaderboard.

    `Benchmark` keeps only the CURRENT revision and Case count, and a bump overwrites both. This
    row keeps each revision's own record, so a past revision's board can still rank complete
    runs against that revision's Case count (OME-1056) after the benchmark has moved on.
    """

    class Meta:
        abstract = True

    # WHY an integer key: the row is derived bookkeeping, and an auto-increment key lets the
    # migration backfill with one portable INSERT … SELECT instead of generating UUIDs per row.
    id = fields.IntField(primary_key=True)
    revision = fields.CharField(max_length=64)
    first_seen_at = fields.DatetimeField()
    # WHY: rows the migration backfilled carry the earliest submission's time, not the moment the
    # board learned the revision; the page labels those dates "about".
    first_seen_inferred = fields.BooleanField(default=False)
    # INVARIANT: the Case count this revision's board ranks by. Recorded from the Engine when the
    # board first sees the revision and never rewritten once recorded. NULL means unknown, and a
    # board with no count filters nothing, the same rule as `Benchmark.case_count`.
    case_count = fields.IntField(null=True)
    # WHY: a backfilled count is the largest question count among the revision's results. A run
    # can never exceed its revision's Cases and a partial run reports fewer, but if every result
    # is partial the inference is too small; this flag lets the page say so.
    case_count_inferred = fields.BooleanField(default=False)


class BenchmarkRevision(BaseBenchmarkRevision):
    class Meta:
        table = "benchmark_revisions"
        unique_together = (("benchmark", "revision"),)

    # WHY cascade: these rows describe a benchmark and mean nothing without it; retiring or
    # purging a benchmark (retire_benchmark.py, purge_private_benchmark.py) must not be blocked.
    benchmark = fields.ForeignKeyField(
        "models.Benchmark",
        related_name="revisions",
        on_delete=fields.OnDelete.CASCADE,
    )
