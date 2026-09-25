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

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from scoreboard.export_private_submissions import collect_submissions, format_jsonl_bytes
from scoreboard.scores.models import Score
from scoreboard.scores.schemas import RunCostStatus, ScoreSubmission
from scoreboard.scores.store import ScoreStore


def _saved_submission(
    *,
    spec_id: str,
    saved: str | None,
    cost: str | None = "2.000000",
    status: RunCostStatus | None = "complete",
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
    """INVARIANT (spec 3.1): the pairing rule is ONE-WAY, and this is the direction it must NOT
    enforce — refusing it would 422 the SDK released today.

    A `partial` run has a reported saved-cost sum by definition, so `partial` beside a null saved
    cost looks incoherent and a validator refusing it looks correct. But `OME-1252` ships the
    status and NOT this field; `OME-1326` adds it later. Between those two releases every
    `partial` submission legitimately carries a status with no saved cost, for weeks.

    This is the `OME-822` P1-1 finding exactly — a rule true of the final contract, enforced
    before clients can satisfy it, deadlocks the rollout. The OTHER direction is enforced:
    `unavailable` beside a saving is refused — see
    `test_unavailable_beside_a_saved_cost_is_refused`.
    """
    submission = _saved_submission(
        spec_id="partial-no-saved", saved=None, cost=None, status="partial"
    )

    assert submission.run_cost_status == "partial"
    assert submission.cache_saved_cost_usd is None


# --- review round 1 (PR #1055): one execution, one snapshot -------------------------------------
#
# The first version of this module filled `cache_saved_cost_usd` on its own at replay, and two of
# its tests asserted that as correct. Review showed it combines figures from two DIFFERENT runs:
# an original that spent $2 with no saved figure, then a fully cached replay that spent $0 and
# saved $2, left the old $2 spend beside the new $2 saving — a $4 reproduction cost that never
# existed. Spend, status and saving describe ONE execution and move as one snapshot.


def test_unavailable_beside_a_saved_cost_is_refused() -> None:
    """INVARIANT: `unavailable` means NO cost evidence, so a saving beside it is a contradiction.

    This is the one-way rule the staged rollout does allow. `partial` + null saving must stay
    accepted (the SDK released before OME-1326 sends the status without this field), but
    `unavailable` + a saving can never come from a correct client: the SDK derives `partial`
    whenever the reported sum is present — including when it is 0 — so the rule is "any non-null
    saving", not "> 0". Older clients never send the field, so nothing deployed can trip it.
    """
    for saved in ("1.800000", "0.000000"):
        with pytest.raises(ValidationError, match="unavailable"):
            _saved_submission(
                spec_id=f"contradiction-{saved}", saved=saved, cost=None, status="unavailable"
            )


@pytest.mark.asyncio
async def test_a_replay_fills_the_whole_cost_snapshot_when_none_was_stored(
    tortoise_db: None,
) -> None:
    """A legacy-shaped row — no amount, no status, no saving — gains all three from ONE replay.

    `_content_hash` excludes cost (`OME-770` D8), so this is the only way such a row gains a
    cost at all. All three come from the same submission, so they describe the same execution.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    first, _ = await store.submit(
        _saved_submission(spec_id="snapshot", saved=None, cost=None, status=None)
    )
    _, created = await store.submit(
        _saved_submission(spec_id="snapshot", saved="1.800000", cost="0.200000")
    )
    row = await Score.get(id=first.id)

    assert created is False
    assert row.run_cost_usd == Decimal("0.200000")
    assert row.run_cost_status == "complete"
    assert row.cache_saved_cost_usd == Decimal("1.800000")


@pytest.mark.asyncio
async def test_a_replay_never_combines_costs_from_two_executions(tortoise_db: None) -> None:
    """INVARIANT: the reproduction cost is never assembled from two different runs.

    The review's reproduction, verbatim. The original spent $2 and reported no saving; a later
    fully cached run of the same recipe spent $0 and saved $2. Filling the saving alone would
    leave `run_cost_usd + cache_saved_cost_usd` at $4 — a figure neither run produced, and one
    phase 2 would rank on.

    Consequence accepted: a row that already holds a spend never gains a saving by replay. The
    saving arrives on FIRST submission, from clients that send all three fields together.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    first, _ = await store.submit(_saved_submission(spec_id="two-runs", saved=None))
    await store.submit(_saved_submission(spec_id="two-runs", saved="2.000000", cost="0.000000"))
    row = await Score.get(id=first.id)

    assert row.run_cost_usd == Decimal("2.000000")
    assert row.cache_saved_cost_usd is None


@pytest.mark.asyncio
async def test_a_replay_cannot_replace_a_stored_saved_cost(tortoise_db: None) -> None:
    """FILL ONLY, never replace — the rule `models` and the cost pair already carry."""
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    first, _ = await store.submit(_saved_submission(spec_id="published", saved="1.800000"))
    _, created = await store.submit(_saved_submission(spec_id="published", saved="9.000000"))
    row = await Score.get(id=first.id)

    assert created is False
    assert row.cache_saved_cost_usd == Decimal("1.800000")


# --- through the PRODUCTION projection -------------------------------------------------------
#
# The first version asserted export behaviour with `ScoreSchema.model_validate(row, ...)` on the
# ORM row. Production never does that: every receipt, list and export goes through
# `_score_to_schema()`, which did not copy this field — so it was stored and never left the
# database, and a purge-certifying export would omit data the purge deletes. These go through the
# real paths.


@pytest.mark.asyncio
async def test_the_submit_receipt_carries_the_saved_cost(tortoise_db: None) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    stored, _ = await store.submit(_saved_submission(spec_id="receipt", saved="1.800000"))

    assert stored.cache_saved_cost_usd == Decimal("1.800000")
    assert stored.model_dump(mode="json")["cache_saved_cost_usd"] == "1.800000"


@pytest.mark.asyncio
async def test_the_private_export_carries_the_saved_cost(tortoise_db: None) -> None:
    """INVARIANT: the bytes a purge certifies contain the data the purge deletes."""
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    await store.submit(_saved_submission(spec_id="exported", saved="1.800000"))

    row = json.loads(format_jsonl_bytes(await collect_submissions("hle")))

    # Compared as a VALUE, not a string. The private export dumps in python mode and serialises
    # with `default=str`, so a cost appears as `str(Decimal)` of what the database returned —
    # `run_cost_usd` beside it exports as "2", not "2.000000". The new field matches the existing
    # one exactly; the textual form is a pre-existing property of this export, not of this field.
    assert Decimal(row["cache_saved_cost_usd"]) == Decimal("1.800000")
    assert Decimal(row["run_cost_usd"]) == Decimal("2.000000")


@pytest.mark.asyncio
async def test_the_private_export_omits_the_key_when_no_saving_is_stored(
    tortoise_db: None,
) -> None:
    """INVARIANT: `exclude_if`, not a null value — through the real export this time.

    An always-present key changes EVERY historical digest, so a previously certified export stops
    authorising its own purge with no row having changed. The `OME-1181` Q2 trap.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    await store.submit(_saved_submission(spec_id="legacy-shaped", saved=None))

    exported = format_jsonl_bytes(await collect_submissions("hle")).decode()

    assert "cache_saved_cost_usd" not in exported


# --- review round 2 (PR #1055) -----------------------------------------------------------------


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_saved_cost_is_refused(bad: str) -> None:
    """`allow_inf_nan=False` is on the field, and until now nothing pinned it.

    A non-finite value reaching the store is the failure `OME-770` reproduced live for
    `run_cost_usd`: it passes a `ge=0` comparison or fails it unpredictably, then raises inside
    `quantize()` and surfaces as a 500 instead of a 422.
    """
    with pytest.raises(ValidationError):
        _saved_submission(spec_id=f"non-finite-{bad}", saved=bad)


def test_an_absent_status_beside_only_a_saving_derives_partial() -> None:
    """INVARIANT: a saving is cost evidence, so an absent status beside one cannot stay absent.

    Null status means "predates cost reporting" — a legacy-shaped row. A submission carrying this
    field is by definition not legacy, so leaving the status null would write a row that lies
    about its own age. Worse, replay could never repair it: the snapshot fill requires all three
    existing fields to be null.

    `partial` is exactly what the SDK derives for this shape — unpriced, with a reported saving —
    so the board resolving it the same way keeps the two ends agreeing.
    """
    submission = _saved_submission(
        spec_id="derive-partial", saved="1.250000", cost=None, status=None
    )

    assert submission.run_cost_status == "partial"
    assert submission.run_cost_usd is None


def test_an_absent_status_beside_an_amount_still_derives_complete() -> None:
    """The existing rule is unchanged when a saving sits beside the amount: an amount IS the claim
    `complete` makes, whatever the cache saved."""
    submission = _saved_submission(spec_id="derive-complete", saved="1.250000", status=None)

    assert submission.run_cost_status == "complete"


def test_an_absent_status_with_neither_amount_stays_absent() -> None:
    """Only a submission with NO cost evidence stays legacy-shaped."""
    submission = _saved_submission(spec_id="derive-none", saved=None, cost=None, status=None)

    assert submission.run_cost_status is None


@pytest.mark.asyncio
async def test_a_derived_partial_row_is_stored_coherently(tortoise_db: None) -> None:
    """Through the store, the derived row carries a status, no amount, and its saving — the same
    shape an explicit `partial` produces, so nothing downstream can tell them apart."""
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    stored, _ = await store.submit(
        _saved_submission(spec_id="stored-partial", saved="1.250000", cost=None, status=None)
    )
    row = await Score.get(id=stored.id)

    assert row.run_cost_status == "partial"
    assert row.run_cost_usd is None
    assert row.cache_saved_cost_usd == Decimal("1.250000")
