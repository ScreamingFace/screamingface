"""Storing what a run's cache hits would have cost (OME-1325, OME-1251 D5).

A cache hit costs nothing upstream, so a cached run's `run_cost_usd` is ~0 — and because it WAS
priceable it derives `complete`, a confident label on a meaningless figure. That is OME-1143.

PR #930 records at cache-fill time what the original call cost, and OME-1252 made the SDK read it.
Nobody carried it to the board. D5 decided the shape: spend and savings travel as two separate
fields and the board adds them at the point of use, so the parts stay recomputable and the
submitter's real bill is not destroyed by a pre-summed number.

This module covers the STORE half only. Ranking on `run_cost_usd + cache_saved_cost_usd` is
phase 2 and is gated on OME-1287; the frontier is deliberately untouched here.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from scoreboard.scores.models import Score
from scoreboard.scores.schemas import RunCostStatus, ScoreSchema, ScoreSubmission
from scoreboard.scores.store import ScoreStore


def _saved_submission(
    *,
    spec_id: str,
    saved: str | None,
    cost: str | None = "2.000000",
    status: RunCostStatus = "complete",
) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id="hle",
        spec_id=spec_id,
        url4_expression=f"url4://benchmark/hle/{spec_id}",
        submitted_by="alice@example.test",
        score=0.75,
        total_questions=100,
        correct_questions=75,
        ran_with_providers=["openrouter"],
        run_cost_usd=None if cost is None else Decimal(cost),
        run_cost_status=status,
        cache_saved_cost_usd=None if saved is None else Decimal(saved),
    )


# --- the wire contract -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_submission_carrying_the_saved_cost_stores_it(tortoise_db: None) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    stored, _ = await store.submit(_saved_submission(spec_id="cached", saved="1.800000"))
    row = await Score.get(id=stored.id)

    assert row.cache_saved_cost_usd == Decimal("1.800000")
    # The spend is untouched. D5 keeps the parts separate; nothing here pre-sums them.
    assert row.run_cost_usd == Decimal("2.000000")


@pytest.mark.asyncio
async def test_omitting_the_saved_cost_stores_null_and_never_zero(tortoise_db: None) -> None:
    """INVARIANT: absent is UNKNOWN, not "saved nothing".

    A run that genuinely saved nothing is a legitimate `0`. Collapsing the two would let an
    unknown value behave like a known one — the failure `OME-770` D8 exists to prevent, and the
    one `OME-1143` is about from the other direction.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    stored, _ = await store.submit(_saved_submission(spec_id="uncached", saved=None))
    row = await Score.get(id=stored.id)

    assert row.cache_saved_cost_usd is None


@pytest.mark.asyncio
async def test_an_explicit_zero_saved_cost_stays_distinguishable_from_absent(
    tortoise_db: None,
) -> None:
    """The other half of the rule above: `0` is a claim, and it must survive as one."""
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    stored, _ = await store.submit(_saved_submission(spec_id="zero-saved", saved="0.000000"))
    row = await Score.get(id=stored.id)

    assert row.cache_saved_cost_usd == Decimal("0.000000")
    assert row.cache_saved_cost_usd is not None


@pytest.mark.parametrize("bad", ["-1.000000", "-0.000001"])
def test_a_negative_saved_cost_is_refused(bad: str) -> None:
    # Counterfactual money shares money's domain. `run_cost_usd` already enforces it; a second
    # money field that did not would be a gap the first one proves unnecessary.
    with pytest.raises(ValidationError):
        _saved_submission(spec_id="negative", saved=bad)


def test_the_saved_cost_mirrors_the_column_bounds_exactly() -> None:
    """INVARIANT: the request contract mirrors DECIMAL(12, 6), as `run_cost_usd` does.

    Seven integer digits fit SQLite and overflow Postgres, so a bound checked only locally passes
    in tests and fails in production — the exact failure `OME-770` reproduced live before pinning
    these limits.
    """
    accepted = _saved_submission(spec_id="ceiling", saved="999999.999999")
    assert accepted.cache_saved_cost_usd == Decimal("999999.999999")

    with pytest.raises(ValidationError):
        _saved_submission(spec_id="overflow", saved="1000000.000000")


def test_a_partial_run_without_a_saved_cost_is_still_accepted() -> None:
    """INVARIANT (spec 3.1): there is NO pairing rule between the status and this field, and
    adding one would 422 the SDK released today.

    A `partial` run has a reported saved-cost sum by definition, so `partial` beside a null saved
    cost looks incoherent and a validator refusing it looks correct. But `OME-1252` ships the
    status and NOT this field; `OME-1326` adds it later. Between those two releases every
    `partial` submission legitimately carries a status with no saved cost, for weeks.

    This is the `OME-822` P1-1 finding exactly — a rule true of the final contract, enforced
    before clients can satisfy it, deadlocks the rollout. If the rule is ever wanted it belongs
    beside `OME-1258`'s flip, not here.
    """
    submission = _saved_submission(
        spec_id="partial-no-saved", saved=None, cost=None, status="partial"
    )

    assert submission.run_cost_status == "partial"
    assert submission.cache_saved_cost_usd is None


# --- replay ------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_replay_fills_a_saved_cost_the_row_lacks(tortoise_db: None) -> None:
    """`_content_hash` excludes cost (`OME-770` D8), so a row stored before this field gains one
    only here. Without the fill, a submitter who re-runs is deduplicated to their old row and the
    figure is discarded — leaving a permanent population the reproduction cost cannot be computed
    for.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    first, _ = await store.submit(_saved_submission(spec_id="fillable", saved=None))
    assert (await Score.get(id=first.id)).cache_saved_cost_usd is None

    _, created = await store.submit(_saved_submission(spec_id="fillable", saved="1.800000"))
    row = await Score.get(id=first.id)

    assert created is False
    assert row.cache_saved_cost_usd == Decimal("1.800000")


@pytest.mark.asyncio
async def test_a_replay_cannot_replace_a_stored_saved_cost(tortoise_db: None) -> None:
    """FILL ONLY, never replace — the rule `models` and the cost pair already carry.

    Once phase 2 ranks on `run_cost_usd + cache_saved_cost_usd`, this value is half a frontier
    position. Enrichment fills a gap; it does not arbitrate between two claims.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    first, _ = await store.submit(_saved_submission(spec_id="published", saved="1.800000"))
    _, created = await store.submit(_saved_submission(spec_id="published", saved="9.000000"))
    row = await Score.get(id=first.id)

    assert created is False
    assert row.cache_saved_cost_usd == Decimal("1.800000")


@pytest.mark.asyncio
async def test_filling_the_saved_cost_does_not_disturb_the_amount_or_its_status(
    tortoise_db: None,
) -> None:
    """The three cost fields are independent on the replay path.

    `OME-822` P1-2 was exactly this class of bug from the other side: a fill gated on the wrong
    sentinel moved a neighbouring published value. A row with a published amount must keep it
    while this field is filled beside it.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    first, _ = await store.submit(_saved_submission(spec_id="neighbour", saved=None))
    await store.submit(_saved_submission(spec_id="neighbour", saved="1.800000"))
    row = await Score.get(id=first.id)

    assert row.cache_saved_cost_usd == Decimal("1.800000")
    assert row.run_cost_usd == Decimal("2.000000")
    assert row.run_cost_status == "complete"


# --- the export digest -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_row_without_the_saved_cost_exports_without_the_key(tortoise_db: None) -> None:
    """INVARIANT: `exclude_if`, not merely a null value.

    `ScoreSchema` feeds the byte-exact JSONL export whose digest authorises a private-board purge.
    An always-present key changes EVERY historical digest, so a previously certified export stops
    authorising its own purge — with no row having changed. That is the `OME-1181` Q2 trap, and
    it has bitten this codebase once already.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    stored, _ = await store.submit(_saved_submission(spec_id="legacy-shaped", saved=None))
    row = await Score.get(id=stored.id)
    exported = ScoreSchema.model_validate(row, from_attributes=True).model_dump(mode="json")

    assert "cache_saved_cost_usd" not in exported


@pytest.mark.asyncio
async def test_a_row_with_the_saved_cost_exports_it_as_a_decimal_string(
    tortoise_db: None,
) -> None:
    """Money crosses the wire as a fixed-scale STRING, never a float — `OME-770` 2.4, so the form
    is identical on SQLite and Postgres.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    stored, _ = await store.submit(_saved_submission(spec_id="exported", saved="1.800000"))
    row = await Score.get(id=stored.id)
    exported = ScoreSchema.model_validate(row, from_attributes=True).model_dump(mode="json")

    assert exported["cache_saved_cost_usd"] == "1.800000"
