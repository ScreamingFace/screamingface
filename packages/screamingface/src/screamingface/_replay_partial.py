"""Rebuild a published run's url4 for its first n cases (OME-1613, spec §4, Q4, Q9, Q10).

FEATURE: OME-1613 — `evaluate(pinned_cache=…, limit=n)` replays the first n cases of a published
run at $0. A pinned cache keys each answer by the case and its Attempt, never by the case count, so
the first n cases of the run find their answers. But n is written into the url4 in several places
that vary by benchmark, so the url4 is rebuilt by the Engine, never edited.

INVARIANT (Q9): a rebuild is trusted only if the Engine still builds the published run exactly. The
SDK rebuilds the whole run at its published case count first and requires the same parsed recipe as
the published url4. A newer benchmark revision or a changed protocol fails that check, and the
partial replay is refused before any run, instead of missing the copy case by case.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from url4 import build

from screamingface._evaluation.linking import _prepare_benchmark
from screamingface._evaluation.url4 import _candidate_text
from screamingface.errors import PlanningError

if TYPE_CHECKING:
    from screamingface._engine.benchmark import AsyncBenchmarkResources, BenchmarkResources
    from screamingface._scoreboard.replay_reads import PublishedScore

_CANNOT_REBUILD = (
    "This Engine can no longer rebuild that run for a partial replay (the benchmark revision or "
    "its protocol changed since the capture). Replay the whole run without limit=."
)


def limit_value(value: object) -> int | None:
    """The checks that need no published score, so they run before any request."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("limit must be an integer")
    if value < 1:
        raise ValueError("limit must be at least 1")
    return value


def partial_limit(value: int | None, published: PublishedScore | None) -> int | None:
    """`limit=n` is a proper subset of a published run: 1 <= n < its case count."""

    if value is None:
        return None
    if published is None:
        # WHY refused: with no published score the SDK knows no benchmark id. Reading it out of
        # the url4's route text would be a text match over the recipe.
        raise ValueError("limit= needs a published score; replay an unsubmitted capture in full")
    if not 1 <= value < published.total_questions:
        raise ValueError(
            f"limit must be at least 1 and below the published run's {published.total_questions} "
            "cases; omit it for a full replay"
        )
    return value


def _linked(benchmark_url4: str, candidate: str) -> str:
    return _prepare_benchmark(benchmark_url4).bind(candidate).url4


def _require_same_run(rebuilt: str, published_tree: object) -> None:
    if build(rebuilt) != published_tree:
        raise PlanningError(_CANNOT_REBUILD, code="partial_replay_unavailable", permanent=True)


def partial_url4_sync(resources: BenchmarkResources, published: PublishedScore, limit: int) -> str:
    published_tree = build(published.url4)
    candidate = _candidate_text(published_tree)
    whole = resources.load(published.benchmark_id, published.total_questions)
    _require_same_run(_linked(whole.url4, candidate), published_tree)
    return _linked(resources.load(published.benchmark_id, limit).url4, candidate)


async def partial_url4_async(
    resources: AsyncBenchmarkResources, published: PublishedScore, limit: int
) -> str:
    published_tree = build(published.url4)
    candidate = _candidate_text(published_tree)
    # Both catalog reads are independent; the guard still runs before any run is scheduled.
    whole, subset = await asyncio.gather(
        resources.load(published.benchmark_id, published.total_questions),
        resources.load(published.benchmark_id, limit),
    )
    _require_same_run(_linked(whole.url4, candidate), published_tree)
    return _linked(subset.url4, candidate)


__all__ = ["limit_value", "partial_limit", "partial_url4_async", "partial_url4_sync"]
