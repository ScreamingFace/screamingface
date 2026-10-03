"""The method-owner Budget records and the charge rule (OME-1289 E4a gap-closure, unit 12; BU#1-7).

FEATURE: ``screamingface.budget.v1`` records and one pure charge rule. E4c reads ``remaining`` and
writes charges and refusals; E4a declares no Budget on any request.
STORY: as the E4c call layer, I charge each call at its ORIGINAL cost (a cache hit included), so a
budget-gated route spends and replays the same way.
INVARIANT defended: ``remaining = max(cap - spent, 0)``; ``None`` is unpriced and never zero; sums
are exact (``0.1 + 0.2 == 0.3``); a state is equal to the fold of its own charges.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from test_signal_accounting import _attempt, _cache, _cost, _hit, _miss

from screamingface_engine.budget import (
    Budget,
    BudgetCharge,
    BudgetRefusal,
    BudgetState,
    charge,
)
from screamingface_engine.operation_accounting import SignalAccounting
from screamingface_engine.world.accounting import (
    retained_operation_accounting,
    signal_accounting_from_aigw,
)


def _usd(amount: float | None) -> SignalAccounting:
    return SignalAccounting(cost_usd=amount)


def _spend(state: BudgetState, *amounts: float | None, cached: bool = False) -> BudgetState:
    for index, amount in enumerate(amounts, start=1):
        state = state.apply(
            operation_id=f"op_model_{index}",
            member_id=f"member_{index}",
            stage="model",
            signals=_usd(amount),
            cached=cached,
        )
    return state


def _start(unit: Any = "usd", cap: float = 0.01) -> BudgetState:
    return BudgetState.start(Budget(unit=unit, cap=cap))


# --- BU#1 -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("unit", "cap"),
    [
        ("usd", 0.0),
        ("usd", -1.0),
        ("usd", float("nan")),
        ("usd", float("inf")),
        ("usd", True),
        ("tokens", 10.5),
        ("eur", 1.0),
    ],
    ids=["zero", "negative", "nan", "inf", "bool", "fractional-tokens", "unit"],
)
def test_budget_rejects_invalid_caps(unit: Any, cap: Any) -> None:
    with pytest.raises(ValidationError):
        Budget(unit=unit, cap=cap)


def test_a_state_with_an_invalid_cap_is_rejected() -> None:
    with pytest.raises(ValidationError, match="whole number"):
        BudgetState(
            unit="tokens",
            cap=10.5,
            spent=0.0,
            remaining=10.5,
            unpriced_charges=0,
            charges=[],
            refused=[],
        )


def test_a_whole_token_cap_builds() -> None:
    assert Budget(unit="tokens", cap=1000.0).cap == 1000.0


# --- BU#2 -------------------------------------------------------------------------------------


def test_usd_charges_decrement_remaining() -> None:
    state = _spend(_start(cap=0.01), 0.002, 0.003, 0.001)

    assert state.spent == 0.006
    assert state.remaining == 0.004
    assert [c.remaining_after for c in state.charges] == [0.008, 0.005, 0.004]
    assert [c.source for c in state.charges] == ["live", "live", "live"]


# --- BU#3 -------------------------------------------------------------------------------------


def test_cache_hit_charges_original_cost() -> None:
    signals = signal_accounting_from_aigw(_hit(), _cache("hit"))

    state = _start(cap=0.01).apply(
        operation_id="op_model_1",
        member_id="member_1",
        stage="model",
        signals=signals,
        cached=True,
    )

    assert state.charges[0].amount == 0.0042
    assert state.charges[0].source == "cache_reference"
    # CHAR: the retained accounting of the same hit still says the hit cost nothing now.
    retained = retained_operation_accounting(
        request_model="openrouter/m", usage=None, aigw=_hit(), cache=_cache("hit")
    )
    assert retained.usage.cost_usd == "0"


# --- BU#4 -------------------------------------------------------------------------------------


def test_token_budget_charges_in_plus_out() -> None:
    signals = SignalAccounting(tokens_in=120.0, tokens_out=30.0)

    state = _start("tokens", 1000.0).apply(
        operation_id="op_model_1", member_id=None, stage="judge", signals=signals, cached=False
    )

    assert state.charges[0].amount == 150.0
    assert state.remaining == 850.0
    for one_side in (SignalAccounting(tokens_in=120.0), SignalAccounting(tokens_out=30.0)):
        assert charge(one_side, "tokens", cached=False) == (None, "unpriced")


# --- BU#5 -------------------------------------------------------------------------------------


def test_unpriced_charge_counts_but_does_not_spend() -> None:
    before = _spend(_start(cap=0.01), 0.002)

    after = _spend(before, None)

    unpriced = after.charges[1]
    assert (unpriced.amount, unpriced.source) == (None, "unpriced")
    assert after.spent == before.spent
    assert after.remaining == before.remaining
    assert after.unpriced_charges == 1
    assert unpriced.remaining_after == before.remaining


# --- BU#6 -------------------------------------------------------------------------------------


def test_overrun_keeps_remaining_at_zero() -> None:
    state = _spend(_start(cap=0.005), 0.004, 0.003)

    assert state.remaining == 0.0
    assert state.spent == 0.007
    assert state.spent > state.cap
    assert state.charges[-1].remaining_after == 0.0


# --- BU#7 -------------------------------------------------------------------------------------


def test_cached_replay_gives_same_charges() -> None:
    miss = _miss([_attempt(tokens=(120, 30), latency_ms=850, cost=_cost("0.0042"))])
    live = signal_accounting_from_aigw(miss, _cache("miss"))
    replay = signal_accounting_from_aigw(_hit(), _cache("hit"))
    assert live == replay

    first = _start().apply(
        operation_id="op_model_1", member_id="member_1", stage="model", signals=live, cached=False
    )
    second = _start().apply(
        operation_id="op_model_1", member_id="member_1", stage="model", signals=replay, cached=True
    )

    assert first.charges[0].amount == second.charges[0].amount
    assert first.charges[0].remaining_after == second.charges[0].remaining_after
    assert (first.charges[0].source, second.charges[0].source) == ("live", "cache_reference")


# --- BU#10 ------------------------------------------------------------------------------------


def test_charges_sum_exactly_in_decimal() -> None:
    assert 0.1 + 0.2 != 0.3

    state = _spend(_start(cap=1.0), 0.1, 0.2)

    assert state.spent == 0.3
    assert state.remaining == 0.7
    tampered = state.model_dump_json().replace('"spent":0.3,', '"spent":0.30000000000000004,')
    assert tampered != state.model_dump_json()
    with pytest.raises(ValidationError, match="spent"):
        BudgetState.model_validate_json(tampered)


def test_charge_returns_an_exact_decimal() -> None:
    amount, source = charge(_usd(0.1), "usd", cached=False)

    assert amount == Decimal("0.1")
    assert source == "live"


# --- record rules -----------------------------------------------------------------------------


def _charge(**overrides: Any) -> BudgetCharge:
    fields: dict[str, Any] = {
        "operation_id": "op_model_1",
        "member_id": "member_1",
        "stage": "model",
        "amount": 0.1,
        "source": "live",
        "remaining_after": 0.9,
    }
    return BudgetCharge(**{**fields, **overrides})


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": None, "source": "live"},
        {"amount": 0.1, "source": "unpriced"},
        {"amount": -0.1},
        {"remaining_after": -1.0},
        {"member_id": "model_1"},
        {"member_id": "member_0"},
        {"operation_id": ""},
        {"stage": "combine"},
    ],
    ids=[
        "none-live",
        "priced-unpriced",
        "negative-amount",
        "negative-remaining",
        "bad-member",
        "member-zero",
        "empty-operation",
        "stage",
    ],
)
def test_a_charge_record_refuses_a_bad_field(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _charge(**overrides)


def test_an_unpriced_charge_and_a_run_level_charge_build() -> None:
    assert _charge(amount=None, source="unpriced").amount is None
    assert _charge(member_id=None).member_id is None


def test_a_refusal_has_one_reason_and_never_changes_spent() -> None:
    with pytest.raises(ValidationError):
        BudgetRefusal(
            operation_id="op_model_1",
            member_id="member_1",
            stage="model",
            estimated=0.02,
            reason="over_budget",  # type: ignore[arg-type]
        )
    refusal = BudgetRefusal(
        operation_id="op_model_2",
        member_id="member_2",
        stage="model",
        estimated=0.02,
        reason="would_exceed_cap",
    )
    state = _spend(_start(cap=0.01), 0.002)

    refused = BudgetState(**{**state.__dict__, "refused": [refusal]})

    assert refused.spent == state.spent
    assert refused.remaining == state.remaining
    with pytest.raises(ValidationError):
        BudgetRefusal(
            operation_id="op_model_2",
            member_id="member_2",
            stage="model",
            estimated=-0.02,
            reason="would_exceed_cap",
        )
