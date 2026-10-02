"""The archive-matched cache saving: accepted, stored, exported, and summed (OME-1382, D7).

FEATURE: `OME-1251` D7 (owner, 2026-10-02, reverses D3). What a cached run's hits would have cost
counts both provenances: `reported` (the provider priced the original call) and `archive_matched`
(measured from another call of the same model and kind). The draco-3pass seed archive is entirely
`archive_matched`, so under D3 those runs could never publish a cost.

INVARIANT: the board stores the two savings as SEPARATE fields beside the spend and adds the three
at the point of use. Nothing stores a pre-summed figure.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
import pytest_asyncio
from pydantic import ValidationError

from scoreboard.export_private_submissions import collect_submissions, format_jsonl_bytes
from scoreboard.scores.models import Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

BOARD = "draco-3pass"
REV = "rev-1"


def _submission(**cost: object) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id=BOARD,
        spec_id="seeded",
        url4_expression="url4://seeded",
        submitted_by="tester@example.test",
        score=0.6,
        total_questions=100,
        ran_with_providers=["openrouter"],
        metadata={"benchmark_revision": REV},
        **cost,  # type: ignore[arg-type]
    )


# --- The contract --------------------------------------------------------------------------------


def test_a_complete_submission_may_carry_an_archive_saving() -> None:
    submission = _submission(
        run_cost_usd=Decimal("0"),
        run_cost_status="complete",
        cache_saved_cost_archive_usd=Decimal("4.250000"),
    )

    assert submission.cache_saved_cost_archive_usd == Decimal("4.250000")


def test_an_archive_saving_beside_unavailable_is_refused() -> None:
    """INVARIANT: like the reported saving, any archive saving is cost evidence."""
    with pytest.raises(ValidationError, match="archive_usd must be absent .* cost evidence"):
        _submission(run_cost_status="unavailable", cache_saved_cost_archive_usd=Decimal("0"))


def test_only_an_archive_saving_with_no_status_resolves_to_partial() -> None:
    """Cost evidence, so not a legacy-shaped row; the same rule the reported saving follows."""
    assert _submission(cache_saved_cost_archive_usd=Decimal("1")).run_cost_status == "partial"


@pytest.mark.parametrize("bad", ["-0.01", "NaN", "Infinity"])
def test_an_archive_saving_must_be_finite_and_non_negative(bad: str) -> None:
    with pytest.raises(ValidationError):
        _submission(cache_saved_cost_archive_usd=Decimal(bad))


# --- Storage, receipt and export -----------------------------------------------------------------


@pytest_asyncio.fixture
async def board(tortoise_db: None) -> None:
    await ScoreStore().register_benchmark(
        benchmark_id=BOARD, display_name="Draco 3-pass", revision=REV, case_count=100
    )


@pytest.mark.asyncio
async def test_the_archive_saving_is_stored_and_on_the_receipt(board: None) -> None:
    outcome = await ScoreStore().submit(
        _submission(
            run_cost_usd=Decimal("0.010000"),
            run_cost_status="complete",
            cache_saved_cost_usd=Decimal("1.000000"),
            cache_saved_cost_archive_usd=Decimal("3.990000"),
        )
    )

    stored = await Score.get(id=outcome.score.id)
    assert stored.cache_saved_cost_archive_usd == Decimal("3.990000")
    assert outcome.score.cache_saved_cost_archive_usd == Decimal("3.990000")
    # The receipt reports what is STORED: the spend, never the derived sum.
    assert outcome.score.run_cost_usd == Decimal("0.010000")


@pytest.mark.asyncio
async def test_the_export_carries_the_archive_saving_when_present(board: None) -> None:
    await ScoreStore().submit(
        _submission(
            run_cost_usd=Decimal("0"),
            run_cost_status="complete",
            cache_saved_cost_archive_usd=Decimal("4.250000"),
        )
    )

    (row,) = map(json.loads, format_jsonl_bytes(await collect_submissions(BOARD)).splitlines())

    assert Decimal(row["cache_saved_cost_archive_usd"]) == Decimal("4.250000")
    assert Decimal(row["run_cost_usd"]) == Decimal("0")


@pytest.mark.asyncio
async def test_the_export_omits_an_absent_archive_saving(board: None) -> None:
    """INVARIANT (the `OME-1181` Q2 trap): an always-present null key would change the bytes of
    every export made before this field existed, and a certified export could no longer
    authorise its own purge."""
    await ScoreStore().submit(_submission(run_cost_usd=Decimal("2"), run_cost_status="complete"))

    (row,) = map(json.loads, format_jsonl_bytes(await collect_submissions(BOARD)).splitlines())

    assert "cache_saved_cost_archive_usd" not in row


# --- Replay: one execution, one snapshot ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_replay_fills_the_archive_saving_with_the_rest_of_an_empty_snapshot(
    board: None,
) -> None:
    first = await ScoreStore().submit(_submission())
    replay = await ScoreStore().submit(
        _submission(
            run_cost_usd=Decimal("0"),
            run_cost_status="complete",
            cache_saved_cost_archive_usd=Decimal("4.250000"),
        )
    )

    assert replay.created is False
    stored = await Score.get(id=first.score.id)
    assert (stored.run_cost_usd, stored.run_cost_status, stored.cache_saved_cost_archive_usd) == (
        Decimal("0"),
        "complete",
        Decimal("4.250000"),
    )


@pytest.mark.asyncio
async def test_a_replay_never_adds_an_archive_saving_to_a_priced_row(board: None) -> None:
    """INVARIANT (OME-1325): spend, status and savings describe ONE execution.

    An original that spent $2, replayed by a fully cached run that spent $0 and saved $2 in the
    archive, must not become a $4 row neither run produced.
    """
    first = await ScoreStore().submit(
        _submission(run_cost_usd=Decimal("2"), run_cost_status="complete")
    )
    await ScoreStore().submit(
        _submission(
            run_cost_usd=Decimal("0"),
            run_cost_status="complete",
            cache_saved_cost_archive_usd=Decimal("2"),
        )
    )

    stored = await Score.get(id=first.score.id)
    assert stored.run_cost_usd == Decimal("2")
    assert stored.cache_saved_cost_archive_usd is None


@pytest.mark.asyncio
async def test_a_stored_archive_saving_alone_blocks_a_replay_fill(board: None) -> None:
    """INVARIANT: the snapshot is filled only when ALL its cost fields are empty, archive included.

    Through the API an archive saving always arrives with a status, so this row can only come from
    a direct write (an import, a restore, a hand repair). Even then a replay must not graft another
    execution's spend onto this row's archive saving.
    """
    first = await ScoreStore().submit(_submission())
    await Score.filter(id=first.score.id).update(cache_saved_cost_archive_usd=Decimal("4.250000"))

    await ScoreStore().submit(_submission(run_cost_usd=Decimal("2"), run_cost_status="complete"))

    stored = await Score.get(id=first.score.id)
    assert (stored.run_cost_usd, stored.run_cost_status) == (None, None)
    assert stored.cache_saved_cost_archive_usd == Decimal("4.250000")
