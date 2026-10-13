"""The SDK mirror of the Budget records (OME-1289 E4a gap-closure, unit 12; BU#1 SDK).

FEATURE: ``screamingface.budget`` holds the four ``screamingface.budget.v1`` records as frozen
values with the same field order and rules as the Engine's ``screamingface_engine.budget``. It has
no charge rule: the E4c call layer is the producer, and the Engine's own tests pin the arithmetic.
INVARIANT defended: a state is equal to the fold of its own charges, so a decoded ledger can never
disagree with itself; a bad record names the field.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from screamingface.budget import (
    Budget,
    BudgetCharge,
    BudgetRefusal,
    BudgetState,
)


def _charge(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "operation_id": "op_model_1",
        "member_id": "member_1",
        "stage": "model",
        "amount": 0.002,
        "source": "live",
        "remaining_after": 0.008,
    }
    return {**fields, **overrides}


def _state() -> dict[str, Any]:
    second = _charge(operation_id="op_model_2", member_id="member_2", amount=0.003)
    second["remaining_after"] = 0.005
    third = _charge(operation_id="op_model_3", member_id=None, amount=None, source="unpriced")
    third["remaining_after"] = 0.005
    return {
        "unit": "usd",
        "cap": 0.01,
        "spent": 0.005,
        "remaining": 0.005,
        "unpriced_charges": 1,
        "charges": [_charge(), second, third],
        "refused": [
            {
                "operation_id": "op_model_4",
                "member_id": "member_4",
                "stage": "model",
                "estimated": 0.02,
                "reason": "would_exceed_cap",
            }
        ],
    }


# --- BU#1 SDK ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("unit", "cap", "error"),
    [
        ("usd", 0.0, ValueError),
        ("usd", -1.0, ValueError),
        ("usd", float("nan"), ValueError),
        ("usd", True, TypeError),
        ("tokens", 10.5, ValueError),
        ("eur", 1.0, ValueError),
    ],
    ids=["zero", "negative", "nan", "bool", "fractional-tokens", "unit"],
)
def test_budget_rejects_invalid_caps(unit: Any, cap: Any, error: type[Exception]) -> None:
    with pytest.raises(error):
        Budget(unit=unit, cap=cap)


def test_a_state_with_an_invalid_cap_is_rejected() -> None:
    wire = {**_state(), "unit": "tokens", "cap": 10.5}

    with pytest.raises(ValueError, match="whole number"):
        BudgetState.from_dict(wire)


def test_a_whole_token_cap_builds() -> None:
    assert Budget(unit="tokens", cap=1000.0).cap == 1000.0
    assert Budget(unit="tokens", cap=1000).cap == 1000.0  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": None, "source": "live"},
        {"amount": 0.1, "source": "unpriced"},
        {"amount": -0.1},
        {"remaining_after": -1.0},
        {"member_id": "model_1"},
        {"operation_id": ""},
        {"stage": "combine"},
        {"source": "cached"},
    ],
    ids=[
        "none-live",
        "priced-unpriced",
        "negative-amount",
        "negative-remaining",
        "bad-member",
        "empty-operation",
        "stage",
        "source",
    ],
)
def test_a_charge_record_refuses_a_bad_field(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        BudgetCharge(**_charge(**overrides))


def test_a_refusal_has_one_reason_and_a_non_negative_estimate() -> None:
    wire = _state()["refused"][0]

    assert BudgetRefusal(**wire).estimated == 0.02
    with pytest.raises(ValueError):
        BudgetRefusal(**{**wire, "reason": "over_budget"})
    with pytest.raises(ValueError):
        BudgetRefusal(**{**wire, "estimated": -0.02})


# --- the ledger -------------------------------------------------------------------------------


def test_budget_state_round_trips_and_refuses_bad_ledgers() -> None:
    wire = _state()

    state = BudgetState.from_dict(wire)

    assert json.dumps(state.to_dict()) == json.dumps(wire)
    assert state.spent == 0.005 and state.unpriced_charges == 1
    assert isinstance(state.charges, tuple) and isinstance(state.refused, tuple)


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda w: w.update(spent=0.30000000000000004), "fold"),
        (lambda w: w.update(remaining=0.0), "fold"),
        (lambda w: w.update(unpriced_charges=0), "fold"),
        (lambda w: w["charges"][1].update(remaining_after=0.004), "remaining_after"),
        (lambda w: w.update(extra=1), "extra"),
        (lambda w: w.pop("refused"), "refused"),
        (lambda w: w["charges"][0].update(extra=1), "extra"),
        (lambda w: w["charges"][0].pop("stage"), "stage"),
        (lambda w: w["refused"][0].pop("reason"), "reason"),
    ],
    ids=[
        "spent",
        "remaining",
        "unpriced",
        "remaining-after",
        "extra-key",
        "missing-key",
        "charge-extra",
        "charge-missing",
        "refusal-missing",
    ],
)
def test_a_tampered_state_names_the_problem(change: Any, match: str) -> None:
    wire = _state()
    change(wire)

    with pytest.raises(ValueError, match=match):
        BudgetState.from_dict(wire)


def test_a_state_reads_from_a_mapping_only() -> None:
    with pytest.raises(TypeError):
        BudgetState.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        BudgetState.from_dict({**_state(), "charges": "x"})
