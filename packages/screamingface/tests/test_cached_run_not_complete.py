"""A cached run is never published as a complete cost (spec 2026-09-30-cached-run-not-complete).

FEATURE (OME-1441): stop publishing fake $0 costs. A cache hit spends nothing upstream, so a
cached run's spend is at or near $0, and the board ranks on spend until `OME-1382`.
STORY: as a reader of the leaderboard, a row's cost is either what the run really cost or absent,
never a cache replay's $0 shown as exact.

INVARIANT (D1, owner 2026-09-30): a submission from a run with ANY cache hit is `partial` with no
amount. The local result keeps its true spend and status: only the published claim changes.
"""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_client_run import REPLAY_URL4, _engine, _ReplayTransport
from test_leaderboards import _candidate_result

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._engine.contract import _RunState
from screamingface._scoreboard.leaderboards import _submission

_REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_EVENTS = (
    _REPO_ROOT / "apps/screamingface-engine/tests/unit/data/cache_hit_contract/run_events.json"
)
# The expression the Engine ran to produce the stream; `_RunState` identifies the root by it.
_URL4 = "/openrouter/anthropic/claude-fable-5(ctx)!go"


def _events() -> list[dict[str, Any]]:
    return json.loads(RUN_EVENTS.read_text(encoding="utf-8"))


def _decode(events: list[dict[str, Any]]) -> _RunOutcome:
    state = _RunState(_URL4)
    outcome = None
    for event in events:
        accepted = state.accept(json.dumps(event))
        if accepted.outcome is not None:
            outcome = accepted.outcome
    assert outcome is not None, "the stream never produced a root outcome"
    return outcome


def _is_summary(event: dict[str, Any]) -> bool:
    return event["type"] == "ai.url4.log" and "cache.hits" in event["data"].get("attributes", {})


def _summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(e for e in events if _is_summary(e))


def _without_summary(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same stream with the summary's cache counts stripped.

    WHY strip rather than drop the event: the stream is sequence-numbered, and a gap stops the
    decoder from ever reaching the terminal frame."""
    attributes = _summary(events)["data"]["attributes"]
    for key in [k for k in attributes if k.startswith("cache.")]:
        del attributes[key]
    return events


# --- Counting the run's hits ---------------------------------------------------------------------


def test_the_real_engine_stream_reports_its_one_hit() -> None:
    assert _decode(_events()).cache_hits == 1


def test_the_run_summary_wins_over_spans_that_hide_hits() -> None:
    """WHY: a span keeps only its LAST call's cache outcome (engine `executor.py`), so a span whose
    first call hit and whose later call missed reads `miss`. The run summary counts every round
    trip, so it is the authority whenever it is larger."""
    events = _events()
    _summary(events)["data"]["attributes"]["cache.hits"] = 5

    assert _decode(events).cache_hits == 5


def test_hit_spans_count_when_the_engine_sends_no_summary() -> None:
    """An engine that sends no cache summary still marks hit spans; they are the fallback."""
    assert _decode(_without_summary(_events())).cache_hits == 1


def test_a_run_that_never_touched_the_cache_counts_zero() -> None:
    events = _without_summary(_events())
    for event in events:
        if event["type"] == "ai.url4.span" and event["data"].get("cache_status") == "hit":
            event["data"]["cache_status"] = "bypass"

    assert _decode(events).cache_hits == 0


def test_a_malformed_summary_count_is_refused() -> None:
    events = _events()
    _summary(events)["data"]["attributes"]["cache.hits"] = -1

    with pytest.raises(sf.ExecutionError):
        _decode(events)


# --- The result carries the count ----------------------------------------------------------------


class _HitTransport(_ReplayTransport):
    """The replay Candidate, as if two of its calls had been served from the cache.

    The replay itself reports no usage, so the outcome also gets a priced spend: the local-result
    test needs an amount to show that the rule leaves it alone."""

    def run(self, candidate: object, on_event: object) -> _RunOutcome:
        outcome = super().run(candidate, on_event)  # type: ignore[arg-type]
        return replace(outcome, root_usage=sf.Usage(cost_usd=Decimal("0.004")), cache_hits=2)


def _evaluate() -> sf.Report:
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=_HitTransport(),
    ) as client:
        return client.evaluate(REPLAY_URL4, progress=False)


def test_a_live_result_carries_the_runs_hit_count_and_exports_it() -> None:
    (result,) = _evaluate().candidates

    assert result.cache_hits == 2
    assert result.to_dict()["cache_hits"] == 2


def test_the_local_result_keeps_its_true_spend_and_status() -> None:
    """INVARIANT: the rule changes what is PUBLISHED, never the local report. What the run spent
    is still a fact, and `complete` still pairs with that amount locally."""
    (result,) = _evaluate().candidates

    assert result.usage.cost_usd is not None
    assert result.run_cost_status == "complete"


@pytest.mark.parametrize("value", [-1, True, 1.5, "2"])
def test_a_result_refuses_an_invalid_hit_count(value: object) -> None:
    base = _candidate_result()
    with pytest.raises(ValueError, match="cache_hits"):
        _result(base, cache_hits=value)


# --- The submission ------------------------------------------------------------------------------


def _result(
    base: sf.CandidateResult | None = None,
    *,
    cost: str | None = "0.004000",
    saved: str | None = None,
    cache_hits: object = 0,
) -> sf.CandidateResult:
    base = base or _candidate_result()
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
        cache_hits=cache_hits,  # type: ignore[arg-type]
    )


def test_a_cached_run_is_submitted_as_partial_with_no_amount() -> None:
    payload = _submission(_result(cost="0", cache_hits=1))

    assert payload["run_cost_status"] == "partial"
    assert payload["run_cost_usd"] is None


def test_a_partly_cached_run_is_partial_too() -> None:
    """D1: ANY hit. A mostly real spend with one cached call is still not the whole cost."""
    payload = _submission(_result(cost="4.500000", cache_hits=1))

    assert payload["run_cost_status"] == "partial"
    assert payload["run_cost_usd"] is None


def test_a_cached_runs_saving_is_still_sent() -> None:
    """`partial` beside a saving is a pair the board accepts (`partial` = saving evidence)."""
    payload = _submission(_result(cost="0", saved="0.012345", cache_hits=1))

    assert payload["run_cost_status"] == "partial"
    assert payload["cache_saved_cost_usd"] == "0.012345"


def test_an_uncached_run_submits_its_cost_exactly_as_before() -> None:
    """A `no-store` run bypasses every call and hits none: its real spend publishes as complete."""
    payload = _submission(_result(cost="0.829580", cache_hits=0))

    assert payload["run_cost_status"] == "complete"
    assert Decimal(str(payload["run_cost_usd"])) == Decimal("0.829580")


def test_an_unpriced_cached_run_is_partial_too() -> None:
    """INVARIANT (D1): ANY hit means `partial`, whether or not the spend was priced. The status
    sent is then a function of the hit count alone: `partial` means "the cache served some calls,
    so no amount is published", which is the rule the board-side follow-up enforces (`OME-1442`).
    """
    payload = _submission(_result(cost=None, cache_hits=3))

    assert payload["run_cost_status"] == "partial"
    assert payload["run_cost_usd"] is None


def test_an_unpriced_uncached_run_stays_unavailable() -> None:
    """`unavailable` keeps its meaning for a run the cache never served: the spend itself could
    not be priced."""
    payload = _submission(_result(cost=None, cache_hits=0))

    assert payload["run_cost_status"] == "unavailable"
    assert payload["run_cost_usd"] is None
