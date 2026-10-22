"""The ORIGINAL call's numbers, kept for combine signals (OME-1289 E4a gap-closure, unit 1).

FEATURE: ``Answer.signals`` carry the cost, latency and tokens of the call that made a member's
text, and a replay from the cache must give the same numbers as the first run.
INVARIANT defended (erd 4.3): ``OperationAccounting`` keeps its cache-hit zeros -- a hit costs
nothing now -- while ``SignalAccounting`` reads the cache reference, which holds the original call.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

import pytest

from screamingface_engine.combine.ports import ACCOUNTING_SIGNALS
from screamingface_engine.operation_accounting import (
    SignalAccounting,
    combine_signal_accounting,
)
from screamingface_engine.world.accounting import (
    signal_accounting_from_aigw,
)
from screamingface_engine.world.cache_readback import CacheOutcome, CacheStatus


def _cache(status: CacheStatus | None, *, retried: bool = False) -> CacheOutcome:
    return CacheOutcome(status=status, reason=None, key=None, age_s=None, retried=retried)


def _cost(amount: str = "0.002", unit: str = "openrouter_credits", status: str = "reported") -> Any:
    return {"status": status, "amount": amount, "unit": unit, "source": "x"}


def _attempt(
    *,
    outcome: str = "succeeded",
    tokens: tuple[int, int] = (10, 4),
    latency_ms: int = 30,
    cost: Any = None,
) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "provider": "openrouter",
        "response_model": "m",
        "latency_ms": latency_ms,
        "usage": {"input": {"total": tokens[0]}, "output": {"total": tokens[1]}},
        "direct_cost": _cost() if cost is None else cost,
    }


def _miss(
    attempts: Any,
    *,
    capture_status: str = "complete",
    omitted_attempts: int = 0,
) -> dict[str, Any]:
    return {
        "usage_accounting": {
            "capture_status": capture_status,
            "omitted_attempts": omitted_attempts,
            "attempts": attempts,
            "cache": {"status": "miss", "reference": None},
        }
    }


def _hit(
    *,
    tokens: tuple[int, int] = (120, 30),
    latency_ms: int | None = 850,
    cost: Any = None,
) -> dict[str, Any]:
    reference: dict[str, Any] = {
        "usage": {"input": {"total": tokens[0]}, "output": {"total": tokens[1]}},
        "direct_cost": _cost("0.0042") if cost is None else cost,
        "latency": {"provider_latency_ms": latency_ms},
    }
    return {
        "usage_accounting": {
            "capture_status": "not_applicable",
            "omitted_attempts": 0,
            "attempts": [],
            "cache": {"status": "hit", "reference": reference},
        }
    }


_NOTHING = SignalAccounting(None, None, None, None)


# --- SG#2 / SG#3 ------------------------------------------------------------------------------


def test_signal_accounting_reads_cache_reference_on_hit() -> None:
    assert signal_accounting_from_aigw(_hit(), _cache("hit")) == SignalAccounting(
        0.0042, 850.0, 120.0, 30.0
    )
    archive = _hit(cost=_cost("0.5", "usd", "archive_matched"))
    assert signal_accounting_from_aigw(archive, _cache("hit")).cost_usd == 0.5
    no_reference = {"usage_accounting": {"cache": {"status": "hit", "reference": None}}}
    assert signal_accounting_from_aigw(no_reference, _cache("hit")) == _NOTHING


@pytest.mark.parametrize(
    "cost",
    [
        _cost("0.1", "unit_unknown"),
        _cost("0.1", "eur"),
        _cost("0.1", "usd", "absent"),
        {"status": "reported"},
    ],
    ids=["unit-unknown", "other-currency", "absent-status", "no-amount"],
)
def test_unpriced_hit_gives_none_cost(cost: Any) -> None:
    result = signal_accounting_from_aigw(_hit(cost=cost), _cache("hit"))
    assert result == SignalAccounting(None, 850.0, 120.0, 30.0)


def test_a_retried_hit_still_gives_the_reference_numbers() -> None:
    # A retry changes no number (OME-1687); a signal wants the original call's numbers, which the
    # reference holds exactly (F8).
    result = signal_accounting_from_aigw(_hit(), _cache("hit", retried=True))
    assert result == SignalAccounting(0.0042, 850.0, 120.0, 30.0)


# --- SG#19 (unit part) ------------------------------------------------------------------------


def test_miss_takes_the_final_successful_attempt() -> None:
    failed = _attempt(outcome="provider_error", tokens=(5, 0), latency_ms=40, cost=_cost("0.0005"))
    won = _attempt()
    aigw = _miss([failed, won])
    expected = SignalAccounting(0.002, 30.0, 10.0, 4.0)
    assert signal_accounting_from_aigw(aigw, _cache("miss")) == expected
    assert signal_accounting_from_aigw(aigw, _cache("miss", retried=True)) == expected
    assert signal_accounting_from_aigw(aigw, _cache("bypass")) == expected
    assert signal_accounting_from_aigw(aigw, _cache(None)) == expected
    later_failure = _miss([won, failed])  # the LAST succeeded attempt, not the last attempt
    assert signal_accounting_from_aigw(later_failure, _cache("miss")) == expected
    earlier_success = _attempt(tokens=(1, 1), latency_ms=5, cost=_cost("0.0001"))
    two_wins = _miss([earlier_success, won])  # the LAST succeeded attempt is the one that counts
    assert signal_accounting_from_aigw(two_wins, _cache("miss")) == expected


@pytest.mark.parametrize(
    "aigw",
    [
        _miss([_attempt()], capture_status="partial"),
        _miss([_attempt()], omitted_attempts=1),
        _miss([_attempt(outcome="provider_error")]),
        _miss([_attempt(), "not a mapping"]),
        _miss("not a list"),
        {"usage_accounting": None},
        7,
    ],
    ids=[
        "partial", "omitted", "no-success", "bad-attempt", "bad-attempts", "null-accounting",
        "int",
    ],
)  # fmt: skip
def test_incomplete_or_garbage_evidence_gives_none_and_never_raises(aigw: Any) -> None:
    assert signal_accounting_from_aigw(aigw, _cache("miss")) == _NOTHING
    assert signal_accounting_from_aigw(aigw, _cache("hit")) == _NOTHING


def test_missing_pieces_of_one_attempt_make_only_those_fields_none() -> None:
    bare = {"outcome": "succeeded", "usage": {"input": {"total": 7}}}
    result = signal_accounting_from_aigw(_miss([bare]), _cache("miss"))
    assert result == SignalAccounting(None, None, 7.0, None)


# --- the numbers are plain floats -------------------------------------------------------------


def test_as_signals_uses_the_accounting_keys_in_order() -> None:
    signals = SignalAccounting(1.5, 2.0, 3.0, 4.0).as_signals()
    assert tuple(signals) == ACCOUNTING_SIGNALS
    assert signals == {"cost_usd": 1.5, "latency_ms": 2.0, "tokens_in": 3.0, "tokens_out": 4.0}
    assert SignalAccounting().as_signals() == dict.fromkeys(ACCOUNTING_SIGNALS)
    read = signal_accounting_from_aigw(_hit(), _cache("hit")).as_signals()
    assert all(isinstance(number, float) for number in read.values())


# --- the fold over tool-loop rounds -----------------------------------------------------------


def test_combine_signal_accounting_is_contagious_and_order_free() -> None:
    assert combine_signal_accounting([]) == _NOTHING
    rounds = [
        SignalAccounting(0.1, 10.0, 5.0, 1.0),
        SignalAccounting(0.2, None, 6.0, 2.0),
        SignalAccounting(0.3, 30.0, 7.0, None),
    ]
    folded = combine_signal_accounting(rounds)
    assert folded == SignalAccounting(math.fsum([0.1, 0.2, 0.3]), None, 18.0, None)
    for ordering in itertools.permutations(rounds):
        assert combine_signal_accounting(ordering) == folded
    values = [0.1] * 7 + [1e16, -1e16]
    sums = {
        combine_signal_accounting([SignalAccounting(cost_usd=v) for v in ordering]).cost_usd
        for ordering in itertools.islice(itertools.permutations(values), 200)
    }
    assert len(sums) == 1
    one = SignalAccounting(1.0, 2.0, 3.0, 4.0)
    assert combine_signal_accounting([one]) == one
