"""A cached run publishes its full cost when every hit is priced (OME-1463, D7 on OME-1251).

FEATURE (OME-1463, spec 2026-10-02-OME-1463-archive-cost): the published cost is the run's spend
plus what its cache hits would have cost, archive-matched prices included. The SDK sends the parts;
the board sums them (OME-1382).
STORY: as a submitter whose run was served from the seeded cache, my row shows what the run costs,
not a fake $0 and not a blank.

INVARIANT (D3 of the spec): `complete` only with proof that no hit was unpriced. The proof is the
Engine's run summary (`cache.saved_cost.unpriced_hits`); without it, any hit sends `partial`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from test_cached_run_not_complete import _decode, _events, _summary
from test_leaderboards import _candidate_result

import screamingface as sf
from screamingface._scoreboard.leaderboards import _submission

_UNPRICED = "cache.saved_cost.unpriced_hits"


# --- The decoder reads the proof -----------------------------------------------------------------


def test_the_real_engine_summary_says_no_hit_was_unpriced() -> None:
    assert _decode(_events()).cache_unpriced_hits == 0


def test_the_summary_count_of_unpriced_hits_is_carried() -> None:
    events = _events()
    attributes = _summary(events)["data"]["attributes"]
    # A consistent summary: 3 hits, 1 priced by the provider, 2 with no price. Review round 1 made
    # the count conditional on the summary agreeing with itself, so the setup states all of it.
    attributes["cache.hits"] = 3
    attributes[_UNPRICED] = 2

    assert _decode(events).cache_unpriced_hits == 2


def test_a_summary_without_the_count_leaves_it_unknown() -> None:
    """WHY unknown and not zero: an older Engine, or a summary it dropped, proves nothing."""
    events = _events()
    del _summary(events)["data"]["attributes"][_UNPRICED]

    assert _decode(events).cache_unpriced_hits is None


@pytest.mark.parametrize("value", [-1, True, 1.5, "0"])
def test_a_malformed_unpriced_count_is_refused(value: object) -> None:
    events = _events()
    _summary(events)["data"]["attributes"][_UNPRICED] = value

    with pytest.raises(sf.ExecutionError):
        _decode(events)


# --- The result carries both ---------------------------------------------------------------------


def _result(
    *,
    cost: str | None = "0.004000",
    saved: str | None = None,
    archive: str | None = None,
    cache_hits: int = 0,
    unpriced: object = None,
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
        cache_saved_cost_usd=saved,
        cache_saved_cost_archive_usd=archive,
        cache_hits=cache_hits,
        cache_unpriced_hits=unpriced,  # type: ignore[arg-type]
    )


def test_a_result_carries_and_exports_the_archive_saving_and_unpriced_count() -> None:
    result = _result(cost="0", archive="1.250000", cache_hits=4, unpriced=0)

    assert result.cache_saved_cost_archive_usd == Decimal("1.250000")
    assert result.cache_unpriced_hits == 0
    exported: dict[str, Any] = result.to_dict()
    assert exported["cache_saved_cost_archive_usd"] == "1.250000"
    assert exported["cache_unpriced_hits"] == 0


def test_an_absent_archive_saving_and_unknown_count_export_as_null() -> None:
    exported = _result().to_dict()

    assert exported["cache_saved_cost_archive_usd"] is None
    assert exported["cache_unpriced_hits"] is None


@pytest.mark.parametrize("value", [-1, True, 1.5, "0"])
def test_a_result_refuses_an_invalid_unpriced_count(value: object) -> None:
    with pytest.raises(ValueError, match="cache_unpriced_hits"):
        _result(cache_hits=1, unpriced=value)


def test_a_result_refuses_an_invalid_archive_saving() -> None:
    with pytest.raises(ValueError, match="cache_saved_cost_archive_usd"):
        _result(cache_hits=1, archive="-0.5")


# --- The published pair (spec table) -------------------------------------------------------------


def test_a_fully_priced_cached_run_is_complete_with_its_spend() -> None:
    """D2: every hit priced, spend priced -> complete. The amount is the SPEND; the board adds the
    savings (OME-1382), so the SDK never pre-adds them."""
    payload = _submission(_result(cost="0.010000", archive="1.250000", cache_hits=4, unpriced=0))

    assert payload["run_cost_status"] == "complete"
    assert Decimal(str(payload["run_cost_usd"])) == Decimal("0.010000")
    assert payload["cache_saved_cost_archive_usd"] == "1.250000"


def test_both_savings_travel_side_by_side_never_summed() -> None:
    payload = _submission(
        _result(cost="0", saved="0.500000", archive="1.250000", cache_hits=6, unpriced=0)
    )

    assert payload["run_cost_status"] == "complete"
    assert Decimal(str(payload["run_cost_usd"])) == Decimal("0")
    assert payload["cache_saved_cost_usd"] == "0.500000"
    assert payload["cache_saved_cost_archive_usd"] == "1.250000"


def test_any_unpriced_hit_keeps_the_run_partial_with_no_amount() -> None:
    """D3: one hit without a price means the total is unknown, never that piece counted as $0."""
    payload = _submission(_result(cost="0.010000", archive="1.250000", cache_hits=4, unpriced=1))

    assert payload["run_cost_status"] == "partial"
    assert payload["run_cost_usd"] is None
    assert payload["cache_saved_cost_archive_usd"] == "1.250000"


def test_no_run_summary_means_no_proof_and_partial() -> None:
    """INVARIANT: the Engine may drop the summary under backpressure. No proof, no `complete`."""
    payload = _submission(_result(cost="0.010000", archive="1.250000", cache_hits=4, unpriced=None))

    assert payload["run_cost_status"] == "partial"
    assert payload["run_cost_usd"] is None


def test_priced_hits_with_an_unpriced_spend_stay_partial() -> None:
    payload = _submission(_result(cost=None, archive="1.250000", cache_hits=4, unpriced=0))

    assert payload["run_cost_status"] == "partial"
    assert payload["run_cost_usd"] is None


def test_an_uncached_run_is_unchanged_and_sends_no_archive_key() -> None:
    payload = _submission(_result(cost="0.829580", cache_hits=0))

    assert payload["run_cost_status"] == "complete"
    assert Decimal(str(payload["run_cost_usd"])) == Decimal("0.829580")
    assert "cache_saved_cost_archive_usd" not in payload


# --- Review round 1 (2026-10-03): the summary is the authority for the money too ---------------
#
# P1: the proof that no hit was unpriced came from the run summary, but the amounts came from span
# frames. The engine tallies a hit's saving on the run summary BEFORE checking that the span exists
# (`executor._fold_response`), so an unknown span keeps the run-level money and produces no span
# total. A run could then claim `complete` with no saving at all and rank at its bare $0 spend.

_SAVED = "cache.saved_cost_usd"
_ARCHIVE = "cache.saved_cost_archive_usd"
_REPORTED_HITS = "cache.saved_cost.reported_hits"
_ARCHIVE_HITS = "cache.saved_cost.archive_hits"


def _hit_span(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(
        e for e in events if e["type"].endswith("span") and e["data"].get("cache_status") == "hit"
    )


def test_a_saving_missing_from_the_spans_is_taken_from_the_summary() -> None:
    """The reviewer's case: a hit whose span the engine never opened still saved money."""
    events = _events()
    _hit_span(events)["data"]["cache_saved_cost_usd"] = None

    outcome = _decode(events)

    assert outcome.cache_saved_cost_usd == Decimal("0.012345")
    assert outcome.cache_unpriced_hits == 0


def test_the_summary_amounts_win_over_disagreeing_span_totals() -> None:
    events = _events()
    _hit_span(events)["data"]["cache_saved_cost_usd"] = "0.000001"

    assert _decode(events).cache_saved_cost_usd == Decimal("0.012345")


def test_the_summary_carries_the_archive_total() -> None:
    events = _events()
    attributes = _summary(events)["data"]["attributes"]
    attributes[_REPORTED_HITS], attributes[_ARCHIVE_HITS] = 0, 1
    del attributes[_SAVED]
    attributes[_ARCHIVE] = "2.383944"
    _hit_span(events)["data"]["cache_saved_cost_usd"] = None

    outcome = _decode(events)

    assert outcome.cache_saved_cost_usd is None
    assert outcome.cache_saved_cost_archive_usd == Decimal("2.383944")
    assert outcome.cache_unpriced_hits == 0


@pytest.mark.parametrize(
    "corrupt",
    [
        # The coverage counts do not add up to the hits.
        lambda a: a.__setitem__(_REPORTED_HITS, 0),
        # A provenance has hits but no amount.
        lambda a: a.pop(_SAVED),
        # An amount with no hits behind it.
        lambda a: a.__setitem__(_ARCHIVE, "1.000000"),
        # The coverage counts are missing entirely.
        lambda a: (a.pop(_REPORTED_HITS), a.pop(_ARCHIVE_HITS)),
    ],
    ids=["counts-do-not-sum", "hits-without-amount", "amount-without-hits", "counts-missing"],
)
def test_an_inconsistent_summary_proves_nothing(corrupt: Any) -> None:
    """INVARIANT: fail CLOSED. A summary that contradicts itself cannot certify `complete`."""
    events = _events()
    corrupt(_summary(events)["data"]["attributes"])

    assert _decode(events).cache_unpriced_hits is None


def test_more_hit_spans_than_the_summary_counted_proves_nothing() -> None:
    """The final hit count must be the summary's own; a span hit it never tallied is unaccounted."""
    events = _events()
    for event in events:
        if event["type"].endswith("span") and event["data"].get("cache_status") is None:
            event["data"]["cache_status"] = "hit"
            break

    outcome = _decode(events)

    assert outcome.cache_hits == 2
    assert outcome.cache_unpriced_hits is None


@pytest.mark.parametrize("value", ["-1", "NaN", "abc", 0.5])
def test_a_malformed_summary_amount_is_refused(value: object) -> None:
    events = _events()
    _summary(events)["data"]["attributes"][_SAVED] = value

    with pytest.raises(sf.ExecutionError):
        _decode(events)


def test_a_complete_submission_never_drops_the_summarys_saving() -> None:
    """End to end, the reviewer's case: decoded with the span's saving lost, then published.

    Before the fix this sent `complete` with no saving at all, which the board would rank at the
    bare $0 spend although the run summary held a real saving.
    """
    events = _events()
    _hit_span(events)["data"]["cache_saved_cost_usd"] = None
    outcome = _decode(events)
    result = _result(
        cost="0",
        saved=None if outcome.cache_saved_cost_usd is None else str(outcome.cache_saved_cost_usd),
        cache_hits=outcome.cache_hits,
        unpriced=outcome.cache_unpriced_hits,
    )

    payload = _submission(result)

    assert payload["run_cost_status"] == "complete"
    assert payload["cache_saved_cost_usd"] == "0.012345"
