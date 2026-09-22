"""What a submitted run cost is worth (OME-1252, OME-1251 D4).

A cached run spends almost nothing, so submitting its spend publishes it as free and hands it
the cheapest slot on the Pareto frontier — that is OME-1143. PR #930 made the engine measure
what each cache hit avoided; this module covers the Client finally reading it and telling the
board whether the amount beside it can be believed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

import screamingface as sf
from screamingface._engine.contract import _accumulated, _span
from screamingface.errors import ExecutionError


def _span_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "model",
        "kind": "client",
        "gen_ai.operation.name": "chat",
        "start": "2026-09-22T12:00:00Z",
        "end": "2026-09-22T12:00:01Z",
        "status": "ok",
    }
    payload.update(overrides)
    return payload


def _envelope() -> dict[str, object]:
    return {
        "id": "evt-1",
        "run_id": "run-1",
        "sequence": 1,
        "timestamp": datetime(2026, 9, 22, 12, tzinfo=UTC),
        "source": "url4://node/root",
    }


def test_a_span_carries_both_saved_cost_amounts_off_the_wire() -> None:
    # The whole premise of this unit: the data already arrives, and the parser used to drop it.
    span = _span(
        _envelope(),
        _span_payload(cache_saved_cost_usd="0.031", cache_saved_cost_archive_usd="0.500"),
    )

    assert span.cache_saved_cost_usd == Decimal("0.031")
    assert span.cache_saved_cost_archive_usd == Decimal("0.500")


def test_an_absent_saved_cost_stays_absent_rather_than_becoming_zero() -> None:
    """INVARIANT: `None` is not `Decimal(0)`.

    "Nothing priceable was saved" and "a hit worth nothing" are different claims, and the
    run-level derivation reads exactly that difference to tell `partial` from `unavailable`.
    Defaulting to zero would make every run look like it had evidence.
    """
    span = _span(_envelope(), _span_payload())

    assert span.cache_saved_cost_usd is None
    assert span.cache_saved_cost_archive_usd is None


def test_a_span_refuses_a_negative_saved_cost() -> None:
    """Counterfactual money shares money's domain.

    A negative would poison a run total the board reads as evidence about what a recipe costs to
    reproduce. Rejected at the PARSER, as `ExecutionError` — the shared decimal reader already
    enforces the domain, so a malformed frame is refused before the dataclass is built. `Span`
    keeps its own guard for values constructed directly rather than decoded.
    """
    with pytest.raises(ExecutionError, match="finite non-negative"):
        _span(_envelope(), _span_payload(cache_saved_cost_usd="-1"))

    with pytest.raises(ValueError, match="finite non-negative"):
        sf.events.Span(
            id="evt-1",
            run_id="run-1",
            sequence=1,
            timestamp=datetime(2026, 9, 22, 12, tzinfo=UTC),
            source="url4://node/root",
            name="model",
            operation="chat",
            start=datetime(2026, 9, 22, 12, tzinfo=UTC),
            end=datetime(2026, 9, 22, 12, 0, 1, tzinfo=UTC),
            cache_saved_cost_usd=Decimal("-1"),
        )


def test_accumulating_keeps_absent_distinct_from_zero() -> None:
    assert _accumulated(None, None) is None
    assert _accumulated(None, Decimal("0")) == Decimal("0")
    assert _accumulated(Decimal("0.5"), Decimal("0.25")) == Decimal("0.75")
    assert _accumulated(Decimal("0.5"), None) == Decimal("0.5")


def test_the_two_provenances_are_never_summed_into_a_third() -> None:
    """Structural, mirroring the guards the engine and url4 already carry.

    url4 keeps them as two differently-named fields "precisely so the two can never be summed —
    a single amount plus a label invites a consumer to add the labels away" (PRD S5). A third
    field here holding their total would defeat both guards from downstream.
    """
    saved_cost_fields = {
        name for name in sf.events.Span.__dataclass_fields__ if "saved_cost" in name
    }

    assert saved_cost_fields == {"cache_saved_cost_usd", "cache_saved_cost_archive_usd"}


def test_a_priced_run_is_complete_and_sends_its_amount() -> None:
    from test_leaderboards import _result_costing

    from screamingface._scoreboard.leaderboards import _submission

    result = _result_costing("1.250000")
    payload = _submission(result)

    assert result.run_cost_status == "complete"
    assert payload["run_cost_status"] == "complete"
    assert payload["run_cost_usd"] == "1.250000"


def test_an_unpriced_run_sends_a_status_and_no_amount() -> None:
    """INVARIANT: the amount and its status travel as a validated PAIR.

    The board refuses `complete` without an amount and an amount beside any other status, so a
    mismatched pair here only moves a 422 from submit time into the field.
    """
    from test_leaderboards import _result_costing

    from screamingface._scoreboard.leaderboards import _submission

    result = _result_costing(None)
    payload = _submission(result)

    assert result.run_cost_status == "unavailable"
    assert payload["run_cost_status"] == "unavailable"
    assert payload["run_cost_usd"] is None


def test_a_status_cannot_contradict_the_amount_beside_it() -> None:
    from test_leaderboards import _candidate_result

    base = _candidate_result()
    with pytest.raises(ValueError, match="must carry a cost"):
        sf.CandidateResult(
            benchmark=base.benchmark,
            run_id=base.run_id,
            started_at=base.started_at,
            completed_at=base.completed_at,
            name=base.name,
            kind=base.kind,
            url4=base.url4,
            models=base.models,
            operations=base.operations,
            score=base.score,
            coverage=base.coverage,
            metrics=dict(base.metrics),
            cases=base.cases,
            members=base.members,
            failures=base.failures,
            usage=sf.Usage(),
            run_cost_status="complete",
        )


def test_an_omitted_status_is_inferred_from_the_amount() -> None:
    """The status is a fact ABOUT the amount, so a caller who gave an amount has said enough.

    A literal default would have to be wrong for one of the two cases — `"complete"` was, for
    every unpriced fixture in the suite. `partial` is never inferred: it needs cache evidence an
    amount alone cannot carry, so only the evaluation path can name it.
    """
    from test_leaderboards import _result_costing

    assert _result_costing("2.000000").run_cost_status == "complete"
    assert _result_costing(None).run_cost_status == "unavailable"
