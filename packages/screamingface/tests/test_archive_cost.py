"""A cached run publishes its full cost when every hit is priced (OME-1463, D7 on OME-1251).

FEATURE (OME-1463, spec 2026-10-02-OME-1463-archive-cost): the published cost is the run's spend
plus what its cache hits would have cost, archive-matched prices included. The SDK sends the parts;
the board sums them (OME-1382).
STORY: as a submitter whose run was served from the seeded cache, my row shows what the run costs,
not a fake $0 and not a blank.

INVARIANT (D3 of the spec): `complete` only with proof that no hit was unpriced. The proof is the
Engine's run summary (`cache.saved_cost.unpriced_hits`); without it, any hit sends `partial`.
Reading that proof from the run is the Engine's fold's rule, pinned in
`apps/screamingface-engine/tests/unit/test_candidate_record_evidence_rules.py`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from test_leaderboards import _candidate_result

import screamingface as sf
from screamingface._scoreboard.leaderboards import _submission

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
