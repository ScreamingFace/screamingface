"""Retiring a benchmark is the first operator module here that DESTROYS something.

Every other one is additive (`seed`, `import_baselines`) or read-only
(`export_private_submissions`), so the tests are ordered around the risk: the refusal path is
pinned before the deletion path exists at all.

INVARIANT under every test below: a benchmark holding a score or a baseline SURVIVES. The
`on_delete=RESTRICT` foreign keys would refuse anyway; the module's job is to say WHICH rows block
it rather than hand an operator an IntegrityError traceback.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from scoreboard.retire_benchmark import (
    Blockers,
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
        run_cost_usd=Decimal("1.000000"),
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


# --- review round: Engine-owned benchmarks and the check/delete race -------------------------


async def test_an_engine_owned_benchmark_is_refused_by_default(tortoise_db: None) -> None:
    # WHY refuse: deleting an Engine-published benchmark does not achieve what the operator
    # asked for — the next seed reads the Engine catalogue and recreates it. Demonstrated in
    # review. Silently performing a deletion that undoes itself is worse than refusing.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="draco", display_name="DRACO", revision="rev-1")

    with pytest.raises(RetirementRefused) as refusal:
        await retire_benchmark("draco", confirmed=True)

    assert "Engine" in str(refusal.value)
    assert await Benchmark.exists(id="draco")


async def test_an_engine_owned_benchmark_can_be_retired_with_the_override(
    tortoise_db: None,
) -> None:
    # INVARIANT: the override exists for the one legitimate case — the Engine STOPPED publishing
    # it, so seeding will not recreate it, but seeding also never deletes, so the row would
    # otherwise be stranded forever. A blanket refusal would make that unreachable.
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id="draco-3pass", display_name="DRACO 3-Pass", revision="rev-1"
    )

    outcome = await retire_benchmark("draco-3pass", confirmed=True, include_engine_owned=True)

    assert "retired" in outcome
    assert not await Benchmark.exists(id="draco-3pass")


async def test_the_override_does_not_bypass_the_reference_refusal(tortoise_db: None) -> None:
    # INVARIANT: no flag on this module is a route to destroying submitted data.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="draco", display_name="DRACO", revision="rev-1")
    await store.submit(_submission("draco"))

    with pytest.raises(RetirementRefused) as refusal:
        await retire_benchmark("draco", confirmed=True, include_engine_owned=True)

    assert "1 score" in str(refusal.value)
    assert await Benchmark.exists(id="draco")


async def test_a_reference_added_after_the_check_is_a_refusal_not_a_traceback(
    tortoise_db: None,
) -> None:
    # The module exists to replace an IntegrityError traceback with a readable refusal. A score
    # inserted between collect_blockers() and the DELETE would otherwise defeat that: the
    # RESTRICT foreign key raises, and main() catches only LookupError and RetirementRefused.
    store = ScoreStore()
    await _register(store)

    real_collect = retire_benchmark.__globals__["collect_blockers"]

    calls = {"n": 0}

    async def _stale_blockers(benchmark_id: str):
        # First call reports "nothing references it" and races a submission in before the
        # DELETE. Later calls tell the truth, so the re-check can name what actually landed —
        # which is how a real race behaves.
        calls["n"] += 1
        if calls["n"] == 1:
            await store.submit(_submission())
            return Blockers(scores=0, baselines=0)
        return await real_collect(benchmark_id)

    retire_benchmark.__globals__["collect_blockers"] = _stale_blockers
    try:
        with pytest.raises(RetirementRefused) as refusal:
            await retire_benchmark(BENCHMARK, confirmed=True)
    finally:
        retire_benchmark.__globals__["collect_blockers"] = real_collect

    assert "1 score" in str(refusal.value)
    assert await Benchmark.exists(id=BENCHMARK)


# --- review round 2: the delete must confirm it actually deleted ------------------------------
# Same family as the check/delete race already fixed: reporting success for something that did
# not happen. Raised by @HupBaHa on PR #726.


async def test_a_benchmark_vanishing_before_the_revision_read_is_a_refusal(
    tortoise_db: None,
) -> None:
    # `Benchmark.get()` raises DoesNotExist if the row went while we were deciding — a third
    # unhandled path alongside the two already covered, and main() catches neither.
    store = ScoreStore()
    await _register(store)
    real_collect = retire_benchmark.__globals__["collect_blockers"]

    async def _delete_it(benchmark_id: str):
        await Benchmark.filter(id=benchmark_id).delete()
        return Blockers(scores=0, baselines=0)

    retire_benchmark.__globals__["collect_blockers"] = _delete_it
    try:
        with pytest.raises(RetirementRefused):
            await retire_benchmark(BENCHMARK, confirmed=True)
    finally:
        retire_benchmark.__globals__["collect_blockers"] = real_collect


async def test_a_delete_matching_no_rows_is_not_reported_as_retired(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT: `QuerySet.delete()` returns a row count. Ignoring it means a benchmark that
    # disappeared concurrently still prints "retired" — success reported for a no-op.
    store = ScoreStore()
    await _register(store)
    stale = await Benchmark.get(id=BENCHMARK)

    async def _stale_read(**kwargs: object):
        # The guard read succeeds, then the row goes before the DELETE runs.
        await Benchmark.filter(id=BENCHMARK).delete()
        return stale

    monkeypatch.setattr(Benchmark, "get_or_none", _stale_read)

    with pytest.raises(RetirementRefused) as refusal:
        await retire_benchmark(BENCHMARK, confirmed=True)

    assert "matched 0 rows" in str(refusal.value)


async def test_a_revision_appearing_after_the_guard_is_not_deleted(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT: the Engine-ownership guard must hold at the DELETE, not only at the read. A
    # benchmark that gains a revision in between must not be removed by a call that refused to
    # touch Engine-owned rows.
    store = ScoreStore()
    await _register(store)
    stale = await Benchmark.get(id=BENCHMARK)  # revision is None here

    async def _stale_read(**kwargs: object):
        await Benchmark.filter(id=BENCHMARK).update(revision="rev-appeared")
        return stale

    monkeypatch.setattr(Benchmark, "get_or_none", _stale_read)

    with pytest.raises(RetirementRefused):
        await retire_benchmark(BENCHMARK, confirmed=True)

    assert await Benchmark.exists(id=BENCHMARK)
