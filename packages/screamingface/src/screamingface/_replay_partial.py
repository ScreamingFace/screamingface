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
from typing import TYPE_CHECKING, NoReturn

from url4 import build

from screamingface._evaluation.linking import _prepare_benchmark
from screamingface._evaluation.url4 import _candidate_text
from screamingface.errors import PlanningError

if TYPE_CHECKING:
    from screamingface._engine.benchmark import AsyncBenchmarkResources, BenchmarkResources
    from screamingface._evaluation.benchmark import _BenchmarkResource
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


def _refuse() -> NoReturn:
    raise PlanningError(_CANNOT_REBUILD, code="partial_replay_unavailable", permanent=True)


def _checked_subset(
    whole: _BenchmarkResource,
    subset: _BenchmarkResource,
    published: PublishedScore,
    published_tree: object,
    limit: int,
) -> str:
    """The subset's url4, only if both catalog reads describe the published run.

    INVARIANT (review, #1519): the whole run rebuilt at its published case count must be the same
    parsed recipe as the published url4, AND the subset must come from that same catalog generation:
    the published benchmark revision and the same installed case count (the Engine sends the
    installed `case_count` on every read; the selection is `selected_case_count`). A subset served
    by another generation (a rolling deploy, a changed catalog) is refused before any run, never
    replayed unchecked.
    WHY this is enough: a subset the catalog builds differently at the same revision can only miss
    the pinned cache, which answers byte-identical requests alone, so it fails loudly
    (`frozen_copy_miss`), never as a false replay.
    """
    candidate = _candidate_text(published_tree)
    if build(_linked(whole.url4, candidate)) != published_tree:
        _refuse()
    revisions = {whole.info.revision, subset.info.revision}
    if (
        revisions != {published.benchmark_revision}
        or subset.info.case_count != whole.info.case_count
    ):
        _refuse()
    return _linked(subset.url4, candidate)


def partial_url4_sync(resources: BenchmarkResources, published: PublishedScore, limit: int) -> str:
    published_tree = build(published.url4)
    whole = resources.load(published.benchmark_id, published.total_questions)
    subset = resources.load(published.benchmark_id, limit)
    return _checked_subset(whole, subset, published, published_tree, limit)


async def partial_url4_async(
    resources: AsyncBenchmarkResources, published: PublishedScore, limit: int
) -> str:
    published_tree = build(published.url4)
    # Both catalog reads are independent; both are checked before any run is scheduled.
    whole, subset = await asyncio.gather(
        resources.load(published.benchmark_id, published.total_questions),
        resources.load(published.benchmark_id, limit),
    )
    return _checked_subset(whole, subset, published, published_tree, limit)


__all__ = ["limit_value", "partial_limit", "partial_url4_async", "partial_url4_sync"]
