"""Retiring a benchmark is the first operator module here that DESTROYS something.

Every other one is additive (`seed`, `import_baselines`) or read-only
(`export_private_submissions`), so the tests are ordered around the risk: the refusal path is
pinned before the deletion path exists at all.

INVARIANT under every test below: a benchmark holding a score or a baseline SURVIVES. The
`on_delete=RESTRICT` foreign keys would refuse anyway; the module's job is to say WHICH rows block
it rather than hand an operator an IntegrityError traceback.
"""

from __future__ import annotations

import pytest

from scoreboard.retire_benchmark import (
    RetirementRefused,
    collect_blockers,
    retire_benchmark,
)
from scoreboard.scores.baseline_store import BaselineStore
from scoreboard.scores.models import Benchmark
from scoreboard.scores.schemas import BaselineImportRow, ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

BENCHMARK = "hle"


async def _register(store: ScoreStore, benchmark_id: str = BENCHMARK) -> None:
    await store.register_benchmark(benchmark_id=benchmark_id, display_name="News Hallucinations")


def _submission(benchmark_id: str = BENCHMARK) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id=benchmark_id,
        spec_id="spec-1",
        url4_expression="url4://benchmark/spec-1",
        submitted_by="tester@example.test",
        score=0.5,
        total_questions=100,
        correct_questions=50,
        ran_with_providers=["openai"],
    )


async def test_a_benchmark_holding_a_score_is_refused_and_survives(tortoise_db: None) -> None:
    store = ScoreStore()
    await _register(store)
    await store.submit(_submission())

    with pytest.raises(RetirementRefused) as refusal:
        await retire_benchmark(BENCHMARK)

    assert "1 score" in str(refusal.value)
    assert await Benchmark.exists(id=BENCHMARK)


async def test_a_benchmark_holding_a_baseline_is_refused_and_survives(tortoise_db: None) -> None:
    store = ScoreStore()
    await _register(store)
    await BaselineStore().import_many(
        [
            BaselineImportRow(
                benchmark_id=BENCHMARK,
                model_name="gpt-4",
                source="lmarena",
                score=0.7,
            )
        ]
    )

    with pytest.raises(RetirementRefused) as refusal:
        await retire_benchmark(BENCHMARK)

    assert "1 baseline" in str(refusal.value)
    assert await Benchmark.exists(id=BENCHMARK)


async def test_the_refusal_names_both_blockers_when_both_exist(tortoise_db: None) -> None:
    # WHY both in one message: an operator who clears only the blocker they were told about hits
    # the same refusal again. Say everything that stands in the way the first time.
    store = ScoreStore()
    await _register(store)
    await store.submit(_submission())
    await BaselineStore().import_many(
        [
            BaselineImportRow(
                benchmark_id=BENCHMARK,
                model_name="gpt-4",
                source="lmarena",
                score=0.7,
            )
        ]
    )

    with pytest.raises(RetirementRefused) as refusal:
        await retire_benchmark(BENCHMARK)

    message = str(refusal.value)
    assert "1 score" in message
    assert "1 baseline" in message


async def test_collect_blockers_counts_what_references_the_benchmark(tortoise_db: None) -> None:
    store = ScoreStore()
    await _register(store)
    await store.submit(_submission())

    blockers = await collect_blockers(BENCHMARK)

    assert blockers.scores == 1
    assert blockers.baselines == 0
    assert bool(blockers) is True


async def test_an_unreferenced_benchmark_has_no_blockers(tortoise_db: None) -> None:
    store = ScoreStore()
    await _register(store)

    blockers = await collect_blockers(BENCHMARK)

    assert bool(blockers) is False


async def test_an_unknown_benchmark_is_refused(tortoise_db: None) -> None:
    # "Already gone" and "you typed it wrong" must not look identical to someone cleaning up a
    # live board, so this is a refusal rather than a quiet success.
    with pytest.raises(LookupError):
        await retire_benchmark("no-such-benchmark")


async def test_without_confirmation_nothing_is_deleted(tortoise_db: None) -> None:
    # INVARIANT (D6): the default outcome of a correct-looking call is a REPORT. This is the one
    # operator module here that destroys, so deletion is opt-in rather than the thing that
    # happens when you get the command right.
    store = ScoreStore()
    await _register(store)

    outcome = await retire_benchmark(BENCHMARK)

    assert "would retire" in outcome
    assert await Benchmark.exists(id=BENCHMARK)


async def test_with_confirmation_an_unreferenced_benchmark_is_deleted(tortoise_db: None) -> None:
    store = ScoreStore()
    await _register(store)

    outcome = await retire_benchmark(BENCHMARK, confirmed=True)

    assert "retired" in outcome
    assert not await Benchmark.exists(id=BENCHMARK)
    assert await store.list_benchmarks() == []


async def test_retiring_twice_reports_the_second_as_unknown(tortoise_db: None) -> None:
    store = ScoreStore()
    await _register(store)
    await retire_benchmark(BENCHMARK, confirmed=True)

    with pytest.raises(LookupError):
        await retire_benchmark(BENCHMARK, confirmed=True)


async def test_only_the_named_benchmark_is_deleted(tortoise_db: None) -> None:
    # INVARIANT: exact id only. No globbing, and no "delete everything without a revision"
    # shortcut — the neighbours on this board are Engine-published and must not be at risk.
    store = ScoreStore()
    await _register(store, "hle")
    await _register(store, "livetruth")

    await retire_benchmark("hle", confirmed=True)

    assert [row.id for row in await store.list_benchmarks()] == ["livetruth"]


async def test_confirmation_does_not_override_a_refusal(tortoise_db: None) -> None:
    # --yes confirms intent to delete an UNREFERENCED benchmark. It is not a force flag, and must
    # never become the way someone discards submitted data.
    store = ScoreStore()
    await _register(store)
    await store.submit(_submission())

    with pytest.raises(RetirementRefused):
        await retire_benchmark(BENCHMARK, confirmed=True)

    assert await Benchmark.exists(id=BENCHMARK)
