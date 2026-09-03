"""A partial run must not rank against a complete one (OME-1056).

FEATURE: OME-1056 / OME-867. A run covering fewer cases than the benchmark defines is a valid
Report but not a comparable one, and it is ADVANTAGED rather than merely admitted: fewer cases
makes a perfect score easier. Before this, a one-case IFEval run scoring 1.0 held rank 1 over a
541-case run scoring 0.85.

INVARIANT: only the RANKING changes. A partial run stays accepted, stored, and readable through
history, score id and the submission response — a participant running `limit=1` to prove the
submission path works is a supported workflow, and the client already warns them (OME-922).
"""

from __future__ import annotations

import pytest

from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

REV = "0b88a52b5f10a6d9"
FULL = 541


def _submission(spec_id: str, score: float, total_questions: int) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id="ifeval",
        benchmark_revision=REV,
        spec_id=spec_id,
        url4_expression=f"url4://{spec_id}",
        submitted_by="participant@example.test",
        score=score,
        total_questions=total_questions,
        ran_with_providers=["openrouter"],
    )


async def _board(case_count: int | None) -> ScoreStore:
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id="ifeval",
        display_name="IFEval",
        revision=REV,
        case_count=case_count,
    )
    return store


async def test_a_partial_run_does_not_rank_against_a_complete_one(tortoise_db: None) -> None:
    # The reproduction this ticket was opened from, verbatim.
    store = await _board(FULL)
    await store.submit(_submission("honest-full-run", 0.85, FULL))
    await store.submit(_submission("one-case-run", 1.00, 1))

    ranked = [entry.spec_id for entry in await store.leaderboard("ifeval", top_n=50)]

    assert ranked == ["honest-full-run"]


async def test_a_run_matching_the_registered_count_ranks(tortoise_db: None) -> None:
    store = await _board(FULL)
    await store.submit(_submission("complete", 0.5, FULL))

    assert [e.spec_id for e in await store.leaderboard("ifeval", top_n=50)] == ["complete"]


async def test_one_case_short_does_not_rank(tortoise_db: None) -> None:
    # BOUNDARY: the predicate is "fewer than registered", not "suspiciously few".
    store = await _board(FULL)
    await store.submit(_submission("almost", 0.99, FULL - 1))

    assert await store.leaderboard("ifeval", top_n=50) == []


async def test_a_board_with_no_registered_count_ranks_everything(tortoise_db: None) -> None:
    # INVARIANT: mirrors the existing revision rule — a benchmark that declares no count
    # filters nothing, so legacy and non-Engine boards are untouched by this change.
    store = await _board(None)
    await store.submit(_submission("one-case-run", 1.00, 1))

    assert [e.spec_id for e in await store.leaderboard("ifeval", top_n=50)] == ["one-case-run"]


async def test_a_partial_run_is_still_readable(tortoise_db: None) -> None:
    # INVARIANT: this is the half that keeps `limit=1` testing viable. Excluding a row from the
    # RANKING must not hide it from the person who submitted it, or the warning in OME-922
    # ("your submission is partial") would be describing a submission that vanished.
    store = await _board(FULL)
    outcome = await store.submit(_submission("one-case-run", 1.00, 1))

    assert outcome.score.total_questions == 1
    history = await store.list_for_spec(benchmark_id="ifeval", spec_id="one-case-run")
    assert [row.spec_id for row in history] == ["one-case-run"]


async def test_a_specs_complete_run_survives_its_own_higher_scoring_partial(
    tortoise_db: None,
) -> None:
    # INVARIANT: the coverage filter runs INSIDE the window, beside the revision filter.
    #
    # The ranking assigns row_number() per (spec_id, revision) ordered by score, then keeps
    # rn == 1. Filter partial rows AFTER that window and this spec's partial run — which scored
    # HIGHER — takes rn == 1, so the outer filter drops the whole spec and its complete run
    # disappears from the board. The participant did the full run and vanishes because they also
    # smoke-tested. SQL evaluates WHERE before window functions, so the excluded row never gets a
    # row_number at all; this test is what proves the filter stayed on that side.
    store = await _board(FULL)
    await store.submit(_submission("same-spec", 0.60, FULL))
    await store.submit(_submission("same-spec", 1.00, 1))

    ranked = await store.leaderboard("ifeval", top_n=50)

    assert [(e.spec_id, e.score) for e in ranked] == [("same-spec", 0.60)]


async def test_over_reporting_the_case_count_still_ranks(tortoise_db: None) -> None:
    """`>=` is deliberate, so a run claiming MORE cases than registered still ranks.

    WHY pinned: `_build_leaderboard_query` carries a paragraph explaining the choice, and nothing
    exercised it — tightening the predicate to `==` (or rejecting `!=`) passed the whole suite
    while dropping every complete run whose board count had gone stale, which is the failure that
    comment exists to prevent.

    AIDEV-NOTE: this is ALSO the shape of the remaining hole, recorded rather than hidden.
    `total_questions` is client-declared and validated only `> 0`, so a one-case run POSTing 541
    passes this predicate and ranks. Closing that needs attestation at WRITE time, which is not
    this ticket's scope — the read-time filter is a guard against honest partial runs, not a
    defence against a forged scope (OME-1056).
    """
    store = await _board(FULL)
    await store.submit(_submission("claims-more", 0.5, FULL + 10))

    assert [e.spec_id for e in await store.leaderboard("ifeval", top_n=50)] == ["claims-more"]


async def test_a_reseed_without_a_count_keeps_the_stored_one(tortoise_db: None) -> None:
    """An omitted `case_count` means "leave it alone", never "forget how big this benchmark is".

    Seeding runs on every deploy. Writing None unconditionally NULLed a stored count, which drops
    the coverage predicate from the ranking query and lets partial runs rank again — with no log
    line and a green deploy. `visibility` is guarded the same way and for the same reason.
    """
    store = await _board(FULL)
    await store.register_benchmark(benchmark_id="ifeval", display_name="IFEval", revision=REV)
    await store.submit(_submission("honest-full-run", 0.85, FULL))
    await store.submit(_submission("one-case-run", 1.00, 1))

    ranked = [entry.spec_id for entry in await store.leaderboard("ifeval", top_n=50)]

    assert ranked == ["honest-full-run"], (
        "a re-seed that did not mention case_count wiped the stored count, so the coverage "
        "filter stopped applying"
    )


async def test_an_explicit_count_still_corrects_a_wrong_one(tortoise_db: None) -> None:
    # The guard must not make the column write-once: a mis-seeded count has to be fixable.
    store = await _board(1)
    await store.register_benchmark(
        benchmark_id="ifeval", display_name="IFEval", revision=REV, case_count=FULL
    )
    await store.submit(_submission("one-case-run", 1.00, 1))

    assert await store.leaderboard("ifeval", top_n=50) == []
