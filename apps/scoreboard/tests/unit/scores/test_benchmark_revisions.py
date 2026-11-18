"""Every revision a benchmark has had is remembered, with when it was seen and its Case count.

FEATURE: OME-1708 — the revision selector on each leaderboard. Before this, `Benchmark` held only
the current revision and Case count, and a bump overwrote both, so an older revision's board had
no count to check completeness against.

STORY: as a researcher, after a benchmark's revision moves, I can still open the previous
revision's board, ranked against that revision's own Case count.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scoreboard.scores.models import BenchmarkRevision
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio


async def _rows(benchmark_id: str) -> list[BenchmarkRevision]:
    return await BenchmarkRevision.filter(benchmark_id=benchmark_id).order_by("first_seen_at")


async def test_registering_a_revision_records_it_once_with_its_case_count(
    tortoise_db: None,
) -> None:
    store = ScoreStore()
    before = datetime.now(UTC)

    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="rev-a", case_count=12032)

    [row] = await _rows("mmlu_pro")
    assert (row.revision, row.case_count, row.case_count_inferred) == ("rev-a", 12032, False)
    assert row.first_seen_inferred is False
    assert row.first_seen_at >= before


async def test_registering_the_same_revision_again_keeps_the_first_record(
    tortoise_db: None,
) -> None:
    # INVARIANT: the seed job runs on every deploy; the date a revision was first seen must not
    # move to the latest deploy, or every label would read "since today".
    store = ScoreStore()
    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="rev-a", case_count=12032)
    [first] = await _rows("mmlu_pro")

    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="rev-a", case_count=12032)

    [again] = await _rows("mmlu_pro")
    assert (again.id, again.first_seen_at) == (first.id, first.first_seen_at)


async def test_a_bump_adds_a_row_and_leaves_the_old_revision_untouched(
    tortoise_db: None,
) -> None:
    # INVARIANT: the old revision's Case count survives the bump; it is what its board ranks by.
    store = ScoreStore()
    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="rev-a", case_count=12032)

    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="rev-b", case_count=12000)

    rows = await _rows("mmlu_pro")
    assert [(row.revision, row.case_count) for row in rows] == [
        ("rev-a", 12032),
        ("rev-b", 12000),
    ]


async def test_the_engine_count_replaces_an_inferred_count_but_never_a_recorded_one(
    tortoise_db: None,
) -> None:
    # WHY: the migration infers old counts from results (largest question count). When the Engine
    # still publishes that revision, its own count is authoritative and replaces the inference;
    # a count the Engine already gave is never rewritten.
    store = ScoreStore()
    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="rev-a", case_count=12032)
    await BenchmarkRevision.filter(benchmark_id="mmlu_pro").update(
        case_count=200, case_count_inferred=True
    )

    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="rev-a", case_count=12032)
    [row] = await _rows("mmlu_pro")
    assert (row.case_count, row.case_count_inferred) == (12032, False)

    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="rev-a", case_count=1)
    [row] = await _rows("mmlu_pro")
    assert (row.case_count, row.case_count_inferred) == (12032, False)


async def test_a_benchmark_without_a_revision_records_nothing(tortoise_db: None) -> None:
    # Legacy and non-Engine boards have no revision; they keep working with no history row.
    await ScoreStore().register_benchmark("hle", "HLE")

    assert await _rows("hle") == []


async def test_a_recorded_revision_with_no_count_is_filled_when_the_engine_gives_one(
    tortoise_db: None,
) -> None:
    store = ScoreStore()
    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="rev-a", case_count=None)

    await store.register_benchmark("mmlu_pro", "MMLU-Pro", revision="rev-a", case_count=12032)

    [row] = await _rows("mmlu_pro")
    assert (row.case_count, row.case_count_inferred) == (12032, False)
    assert row.first_seen_at < datetime.now(UTC) + timedelta(seconds=1)
