"""Storing a run cost that cannot be determined (OME-822, OME-1251 D1/D2/D4).

`run_cost_usd` alone cannot express "this run happened and its cost is not derivable". Required
and non-nullable, the only value such a run could send is 0 — publishing an unknown cost as free
and handing it the cheapest slot on the Pareto frontier, which is OME-1143 reintroduced by its
own fix. `run_cost_status` is what makes the refusal to guess expressible and STORABLE.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from scoreboard.scores.models import Score
from scoreboard.scores.pareto import compute_pareto_frontier_ids
from scoreboard.scores.schemas import RunCostStatus, ScoreSchema, ScoreSubmission
from scoreboard.scores.store import ScoreStore

# --- OME-822 / OME-1251 D1+D2: an unpriced row is stored as such and leaves the cost axis ------


def _cost_submission(
    *,
    spec_id: str,
    status: RunCostStatus,
    cost: str | None,
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
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["partial", "unavailable"])
async def test_an_unpriced_submission_stores_its_status_and_a_null_amount(
    tortoise_db: None,
    status: RunCostStatus,
) -> None:
    """INVARIANT: the status is PERSISTED, not just echoed in the receipt.

    `ranking_notice` is built in `_submission_response` via `model_copy` and never stored; a
    revision mismatch survives that because it can be recomputed on read against the registered
    revision. Unpriced-ness cannot be recomputed — once the amount is null, nothing else
    distinguishes "the client could not price it" from "this row predates the field". Emitting
    only the receipt would look correct in review and silently lose the evidence the frontier
    depends on.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    stored, _ = await store.submit(_cost_submission(spec_id=status, status=status, cost=None))
    row = await Score.get(id=stored.id)

    assert row.run_cost_usd is None
    assert row.run_cost_status == status


@pytest.mark.asyncio
async def test_a_priced_submission_stores_both_halves(tortoise_db: None) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    stored, _ = await store.submit(
        _cost_submission(spec_id="priced", status="complete", cost="1.500000")
    )
    row = await Score.get(id=stored.id)

    assert row.run_cost_usd == Decimal("1.500000")
    assert row.run_cost_status == "complete"


@pytest.mark.asyncio
async def test_an_unpriced_row_never_reaches_the_pareto_frontier(tortoise_db: None) -> None:
    """FEATURE (OME-1251 D2): the exclusion, asserted through the function rather than the guard.

    Reading `pareto.py`'s `if cost is not None` proves the line exists, not that an unpriced
    submission ends up outside the frontier — which is the claim the openness statistic rests
    on. This goes through `compute_pareto_frontier_ids` so a refactor that moved the guard would
    fail here.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    priced, _ = await store.submit(
        _cost_submission(spec_id="priced", status="complete", cost="5.000000")
    )
    unpriced, _ = await store.submit(
        _cost_submission(spec_id="unpriced", status="unavailable", cost=None)
    )

    entries = await store.leaderboard_pareto_inputs(
        "hle",
        registered_revision=None,
        registered_case_count=None,
    )
    frontier = compute_pareto_frontier_ids(entries)

    assert str(priced.id) in frontier
    assert str(unpriced.id) not in frontier


@pytest.mark.asyncio
async def test_a_replay_fills_the_amount_and_its_status_together(tortoise_db: None) -> None:
    """INVARIANT: never one without the other.

    Filling only the amount leaves a row whose status says the cost is unknowable while carrying
    one; filling only the status leaves `complete` with a null amount. Both are the incoherence
    the request validator refuses, reached through the replay path instead — and `_content_hash`
    excludes cost, so a replay carrying one dedups to the stored row (OME-770 D8).
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    first, _ = await store.submit(
        _cost_submission(spec_id="replayed", status="complete", cost="2.000000")
    )
    await Score.filter(id=first.id).update(run_cost_usd=None, run_cost_status=None)

    _, created = await store.submit(
        _cost_submission(spec_id="replayed", status="complete", cost="2.000000")
    )
    row = await Score.get(id=first.id)

    assert created is False
    assert row.run_cost_status == "complete"
    assert row.run_cost_usd == Decimal("2.000000")


@pytest.mark.asyncio
async def test_a_replay_cannot_move_a_published_cost(tortoise_db: None) -> None:
    # A published cost is a frontier position. Fill-only, for the same reason `models` is.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    first, _ = await store.submit(
        _cost_submission(spec_id="fixed", status="complete", cost="9.000000")
    )
    await store.submit(_cost_submission(spec_id="fixed", status="complete", cost="9.000000"))
    row = await Score.get(id=first.id)

    assert row.run_cost_usd == Decimal("9.000000")


def test_a_legacy_row_emits_no_status_on_the_wire() -> None:
    """INVARIANT: absent stays absent, like `models` and `ranking_notice` beside it.

    `ScoreSchema` feeds the private JSONL export whose exact bytes authorize a purge. Emitting
    `"run_cost_status": null` would change every export saved before this field existed, with no
    underlying row having changed, so a previously certified export could no longer authorize
    its own purge — the Q2 trap OME-1181 hit.
    """
    row = ScoreSchema(
        id=uuid4(),
        version=1,
        benchmark_id="hle",
        benchmark_revision="rev-1",
        spec_id="legacy",
        url4_expression="url4://benchmark/hle/legacy",
        submitted_by="alice@example.test",
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        score=0.75,
        total_questions=100,
        correct_questions=75,
        ran_with_providers=["openrouter"],
        ran_at_local=None,
        client_name=None,
        client_version=None,
        client_platform=None,
        verified_by_screamingface=True,
        metadata=None,
        openness_override=None,
        run_cost_usd=None,
    )

    assert "run_cost_status" not in json.loads(row.model_dump_json())


# --- Review of PR #841, 2026-09-22: two P1 findings, both reproduced before being fixed --------


@pytest.mark.asyncio
async def test_a_deployed_client_payload_still_submits(tortoise_db: None) -> None:
    """P1: the documented deploy order was impossible, and this is the case that proved it.

    The deployed SDK sends `run_cost_usd` and NO status
    (`packages/screamingface/.../leaderboards.py:445` on main). A required status would 422 every
    live submission the moment this deploys — including payloads carrying a perfectly good cost —
    and the client cannot ship first either, because an older board is `extra="forbid"`.

    So the field is optional for now (`OME-1258` flips it), and an absent status beside an amount
    resolves to `complete`. That resolution is not a guess: an amount IS the claim the status
    would make.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    legacy = ScoreSubmission(
        benchmark_id="hle",
        spec_id="deployed-client",
        url4_expression="url4://benchmark/hle/deployed-client",
        submitted_by="alice@example.test",
        score=0.75,
        total_questions=100,
        correct_questions=75,
        ran_with_providers=["openrouter"],
        run_cost_usd=Decimal("3.000000"),
    )
    stored, _ = await store.submit(legacy)
    row = await Score.get(id=stored.id)

    assert row.run_cost_usd == Decimal("3.000000")
    assert row.run_cost_status == "complete"


def test_an_absent_status_with_no_amount_stays_absent() -> None:
    # The legacy-shaped row. The board genuinely does not know whether the client looked, so it
    # must not claim `unavailable` on the client's behalf. `OME-1258` is what starts refusing it.
    submission = ScoreSubmission(
        benchmark_id="hle",
        spec_id="silent",
        url4_expression="url4://benchmark/hle/silent",
        submitted_by="alice@example.test",
        score=0.75,
        total_questions=100,
        correct_questions=75,
        ran_with_providers=["openrouter"],
    )

    assert submission.run_cost_usd is None
    assert submission.run_cost_status is None


@pytest.mark.asyncio
async def test_a_replay_cannot_erase_a_migrated_priced_amount(tortoise_db: None) -> None:
    """P1: a null STATUS is not proof the amount is unfilled.

    Migration `0014` leaves the status null on every pre-existing row, INCLUDING rows carrying a
    real published amount. Gating the fill on the status alone treated such a row as empty, so
    the first same-owner replay overwrote both — an `unavailable` replay erasing a published
    `9.000000`, a `complete` one moving a frontier position.

    The earlier cannot-move-cost test could not catch this: it built a post-migration row whose
    status was already `complete`, which is not the production state. This builds the real one.
    """
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    first, _ = await store.submit(
        _cost_submission(spec_id="migrated", status="complete", cost="9.000000")
    )
    # Exactly what migration 0014 leaves behind: money published, label absent.
    await Score.filter(id=first.id).update(run_cost_status=None)

    await store.submit(_cost_submission(spec_id="migrated", status="unavailable", cost=None))
    row = await Score.get(id=first.id)

    assert row.run_cost_usd == Decimal("9.000000")


@pytest.mark.asyncio
async def test_a_replay_heals_a_migrated_rows_missing_label(tortoise_db: None) -> None:
    # The amount is the sentinel; the status is a label on it. A migrated priced row can recover
    # its label without asking the client, because an amount IS the claim `complete` makes — so
    # the population OME-1258 inherits is already correct.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    first, _ = await store.submit(
        _cost_submission(spec_id="healed", status="complete", cost="4.000000")
    )
    await Score.filter(id=first.id).update(run_cost_status=None)

    await store.submit(_cost_submission(spec_id="healed", status="complete", cost="4.000000"))
    row = await Score.get(id=first.id)

    assert row.run_cost_status == "complete"
    assert row.run_cost_usd == Decimal("4.000000")
