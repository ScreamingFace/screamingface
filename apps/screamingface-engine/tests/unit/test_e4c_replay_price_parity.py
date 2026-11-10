"""A live call and its frozen-copy replay give the budget the same numbers (E4c, OME-1291).

FEATURE: one price source live and on replay (E4c ans:Q21b, budget BU-27). A budget Gate reads
``SignalAccounting`` of each earlier call. Live, that is the last succeeded attempt of a complete
capture; on a replay, the gateway renders that attempt as ``cache.reference``
(``aigateway.plugins.taxonomy.entry_metadata.cache_reference_from_captured_aigw``). So a replay
always takes the branch the live run took.
"""

from __future__ import annotations

from typing import Any

import pytest

from screamingface_engine.operation_accounting import SignalAccounting
from screamingface_engine.world.accounting import signal_accounting_from_aigw
from screamingface_engine.world.cache_readback import CacheOutcome, CacheStatus


def _cache(status: CacheStatus) -> CacheOutcome:
    return CacheOutcome(status=status, reason=None, key=None, age_s=None, retried=False)


def _usage(tokens_in: int, tokens_out: int) -> dict[str, Any]:
    return {
        "status": "complete",
        "source": "provider_raw_response",
        "input": {"total": tokens_in, "uncached": tokens_in},
        "output": {"total": tokens_out},
    }


def _attempt(outcome: str, cost: dict[str, Any], *, tokens: int, latency_ms: int) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "provider": "openrouter",
        "response_model": "m",
        "latency_ms": latency_ms,
        "usage": _usage(tokens, tokens // 4),
        "direct_cost": cost,
    }


def _live(attempts: list[Any], *, capture_status: str = "complete", omitted: int = 0) -> Any:
    return {
        "usage_accounting": {
            "capture_status": capture_status,
            "omitted_attempts": omitted,
            "attempts": attempts,
            "cache": {"status": "miss", "reference": None},
        }
    }


def _replay(live: Any) -> Any:
    """The replay block the gateway renders for ``live``: its priced attempt as the reference."""
    accounting = live["usage_accounting"]
    attempts = accounting["attempts"]
    succeeded = [a for a in attempts if isinstance(a, dict) and a["outcome"] == "succeeded"]
    priced = (
        accounting["capture_status"] == "complete"
        and accounting["omitted_attempts"] == 0
        and all(isinstance(a, dict) for a in attempts)
        and succeeded
    )
    reference = None
    if priced:
        chosen = succeeded[-1]
        reference = {
            "kind": "cached_final_response",
            "coverage": "final_successful_response_only",
            "incurred_in_current_request": False,
            "usage": {**chosen["usage"], "source": "cached_converted_response"},
            "direct_cost": chosen["direct_cost"],
            "latency": {"provider_latency_ms": chosen["latency_ms"]},
        }
    return {
        "usage_accounting": {
            "capture_status": "complete",
            "omitted_attempts": 0,
            "attempts": [],
            "cache": {"status": "hit", "reference": reference},
        },
        "request_economics": {"direct_cost_status": "not_applicable"},
        "frozen_copy_replay": True,
    }


def _cost(status: str, amount: str | None = "0.002") -> dict[str, Any]:
    return {"status": status, "amount": amount, "unit": "usd", "source": "x"}


_FAILED = _attempt("provider_error", _cost("unavailable", None), tokens=0, latency_ms=5)
_CASES = {
    "reported": _live([_attempt("succeeded", _cost("reported"), tokens=120, latency_ms=40)]),
    "archive-matched": _live(
        [_attempt("succeeded", _cost("archive_matched", "0.5"), tokens=80, latency_ms=10)]
    ),
    "unavailable-cost": _live(
        [_attempt("succeeded", _cost("unavailable", None), tokens=64, latency_ms=12)]
    ),
    "openrouter-credits": _live(
        [
            _attempt(
                "succeeded",
                {**_cost("reported", "0.3"), "unit": "openrouter_credits"},
                tokens=32,
                latency_ms=7,
            )
        ]
    ),
    "retry": _live(
        [_FAILED, _attempt("succeeded", _cost("reported", "0.004"), tokens=200, latency_ms=90)]
    ),
    "partial": _live(
        [_attempt("succeeded", _cost("reported"), tokens=120, latency_ms=40)],
        capture_status="partial",
    ),
    "omitted": _live(
        [_attempt("succeeded", _cost("reported"), tokens=120, latency_ms=40)], omitted=1
    ),
    "not-a-mapping": _live(
        ["garbage", _attempt("succeeded", _cost("reported"), tokens=120, latency_ms=40)]
    ),
    "no-success": _live([_FAILED]),
}


@pytest.mark.parametrize("live", list(_CASES.values()), ids=list(_CASES))
def test_live_and_replay_signal_accounting_are_equal(live: Any) -> None:
    live_numbers = signal_accounting_from_aigw(live, _cache("miss"))
    replay_numbers = signal_accounting_from_aigw(_replay(live), _cache("hit"))

    assert replay_numbers == live_numbers


def test_a_priced_live_call_stays_priced_on_replay() -> None:
    # Guards the parity test above from passing on two empty readings.
    numbers = signal_accounting_from_aigw(_replay(_CASES["retry"]), _cache("hit"))

    assert numbers == SignalAccounting(
        cost_usd=0.004, latency_ms=90.0, tokens_in=200.0, tokens_out=50.0
    )
