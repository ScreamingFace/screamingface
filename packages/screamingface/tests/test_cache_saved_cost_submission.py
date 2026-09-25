"""What the cache saved, carried from the run to the board (OME-1326, OME-1251 D5).

The SDK already summed the provider-reported saving across a run's spans (OME-1252), read it once
to tell `partial` from `unavailable`, and dropped it. The board half (OME-1325, PR #1055) stores it
beside the spend, and the board adds the two at the point of use. This module covers the Client
carrying the number the rest of the way: onto `CandidateResult`, into its export, and onto the
submission.
"""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import httpx
import pytest
from test_client_run import REPLAY_URL4, _engine, _ReplayTransport
from test_leaderboards import _candidate_result

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._scoreboard.leaderboards import _submission
from screamingface.report import RunCostStatus


def _result(
    *,
    cost: str | None = None,
    saved: Decimal | str | None = None,
    status: RunCostStatus | None = None,
) -> sf.CandidateResult:
    base = _candidate_result()
    return sf.CandidateResult(
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
        usage=sf.Usage(cost_usd=None if cost is None else Decimal(cost)),
        run_cost_status=status,
        cache_saved_cost_usd=saved,
    )


# --- The submission ------------------------------------------------------------------------------


def test_a_saving_is_sent_as_a_decimal_string() -> None:
    """INVARIANT: a STRING on the wire, like `run_cost_usd`.

    `json=` raises TypeError on a raw Decimal, and a float would lose precision on the board's
    DECIMAL(12, 6) column. Both are invisible to a test that only checks presence.
    """
    payload = _submission(_result(cost="0.010000", saved=Decimal("1.234567")))

    assert payload["cache_saved_cost_usd"] == "1.234567"
    assert isinstance(payload["cache_saved_cost_usd"], str)
    json.dumps(payload)


def test_a_saving_of_zero_is_sent_rather_than_dropped() -> None:
    """Zero is evidence: a priceable hit that was worth nothing. Absent means nothing was seen."""
    payload = _submission(_result(saved=Decimal("0")))

    assert payload["cache_saved_cost_usd"] == "0"
    assert payload["run_cost_status"] == "partial"


def test_a_run_with_no_saving_sends_no_key_at_all() -> None:
    """INVARIANT: absent, never `null`.

    An uncached run's payload stays byte-for-byte what it was before this unit, so the exhaustive
    key-set guard in `test_leaderboards.py` holds without an edit. It also bounds a mis-ordered
    release: a board that does not know the field 422s only runs that actually carry a saving.
    """
    for result in (_result(cost="0.5"), _result()):
        payload = _submission(result)
        assert "cache_saved_cost_usd" not in payload


def test_spend_and_saving_travel_separately_and_are_never_summed() -> None:
    """INVARIANT (OME-1251 D5): the board adds them at the point of use; the Client never does."""
    payload = _submission(_result(cost="0.250000", saved=Decimal("1.750000")))

    assert payload["run_cost_usd"] == "0.250000"
    assert payload["cache_saved_cost_usd"] == "1.750000"
    assert "2.000000" not in json.dumps(payload)


# --- The result ----------------------------------------------------------------------------------


def test_a_saving_without_a_cost_infers_partial() -> None:
    """The saving IS the cache evidence `partial` needs, so a caller who gave it has said enough.

    This mirrors the board, which derives `partial` for the same pair (PR #1055).
    """
    assert _result(saved=Decimal("0.5")).run_cost_status == "partial"


def test_a_priced_run_keeps_its_saving_and_stays_complete() -> None:
    result = _result(cost="0.25", saved=Decimal("1.75"))

    assert result.run_cost_status == "complete"
    assert result.cache_saved_cost_usd == Decimal("1.75")


def test_unavailable_cannot_carry_a_saving() -> None:
    """INVARIANT: the board refuses `unavailable` beside any saving, zero included.

    Refusing it here keeps the 422 out of the field, as the cost/status pair already does.
    """
    for saved in (Decimal("0"), Decimal("0.5")):
        with pytest.raises(ValueError, match="unavailable"):
            _result(saved=saved, status="unavailable")


@pytest.mark.parametrize("bad", [Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity"), "-1"])
def test_a_saving_must_be_a_finite_non_negative_decimal(bad: object) -> None:
    with pytest.raises(ValueError, match="finite non-negative"):
        _result(saved=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [0.5, 1, True])
def test_a_saving_must_not_be_a_float_or_integer(bad: object) -> None:
    with pytest.raises(TypeError, match="cache_saved_cost_usd"):
        _result(saved=bad)  # type: ignore[arg-type]


def test_a_saving_given_as_a_string_is_held_as_a_decimal() -> None:
    assert _result(saved="0.031").cache_saved_cost_usd == Decimal("0.031")


def test_a_result_with_no_saving_holds_none() -> None:
    assert _result(cost="0.5").cache_saved_cost_usd is None


# --- The export ----------------------------------------------------------------------------------


def test_the_export_keeps_the_saving() -> None:
    """INVARIANT (the PR #1017 F2 lesson): a cost field left out of `to_dict()` is lost for good.

    A reader rebuilding a result from a saved report cannot recover it. Emitted as a string, like
    `usage.cost_usd`, and always present, null when absent, so a missing key never means anything.
    """
    exported = _result(saved=Decimal("0.031")).to_dict()
    assert exported["cache_saved_cost_usd"] == "0.031"

    unsaved = _result(cost="0.5").to_dict()
    assert "cache_saved_cost_usd" in unsaved
    assert unsaved["cache_saved_cost_usd"] is None


# --- The full path -------------------------------------------------------------------------------


class _CachedReplayTransport(_ReplayTransport):
    """A replay whose run the cache served: no priced spend, a reported and an archive saving.

    The two sums differ so a pass-through reading the wrong one fails loudly.
    """

    def __init__(self, *, reported: str | None, archive: str | None) -> None:
        super().__init__()
        self._reported = reported
        self._archive = archive

    def run(self, candidate: object, on_event: object) -> _RunOutcome:
        outcome = super().run(candidate, on_event)  # type: ignore[arg-type]
        return replace(
            outcome,
            root_usage=sf.Usage(),
            cache_saved_cost_usd=None if self._reported is None else Decimal(self._reported),
            cache_saved_cost_archive_usd=None if self._archive is None else Decimal(self._archive),
        )


def _evaluate(transport: _ReplayTransport) -> sf.CandidateResult:
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=transport,
    ) as client:
        return client.evaluate(REPLAY_URL4, progress=False).candidates[0]


def test_an_evaluated_run_carries_the_reported_saving_onto_the_submission() -> None:
    result = _evaluate(_CachedReplayTransport(reported="0.031", archive="0.500"))

    assert result.cache_saved_cost_usd == Decimal("0.031")
    assert result.run_cost_status == "partial"
    payload = _submission(result)
    assert payload["cache_saved_cost_usd"] == "0.031"
    assert payload["run_cost_usd"] is None


def test_archive_money_never_reaches_the_result_or_the_board() -> None:
    """INVARIANT (OME-1251 D3): `archive_matched` is measured from a different call.

    It is not provably this run's, so it is never published, alone or added to the reported sum.
    """
    result = _evaluate(_CachedReplayTransport(reported=None, archive="0.500"))

    assert result.cache_saved_cost_usd is None
    assert result.run_cost_status == "unavailable"
    payload = _submission(result)
    assert "cache_saved_cost_usd" not in payload
    assert "0.5" not in json.dumps(payload)
    assert "0.5" not in json.dumps(result.to_dict())


def test_no_evaluated_run_pairs_unavailable_with_a_saving() -> None:
    """The board refuses the pair, so the evaluation path must never build it.

    Every reported/archive combination, zero included, lands on a pair the board accepts.
    """
    for reported in (None, "0", "0.031"):
        for archive in (None, "0", "0.500"):
            result = _evaluate(_CachedReplayTransport(reported=reported, archive=archive))
            if result.run_cost_status == "unavailable":
                assert result.cache_saved_cost_usd is None
            else:
                assert result.cache_saved_cost_usd is not None
