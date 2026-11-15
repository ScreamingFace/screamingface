"""E5 P1 spec R3: a cost is checked and stored the same way whatever the ambient Decimal context
(OME-1785). WHY: any library may change the process's or task's context, and the outcome writer
drops only a `ValueError` as malformed; anything else would stop it."""

from __future__ import annotations

import json
from decimal import Context, Decimal, Inexact, InvalidOperation, Rounded, localcontext

import pytest

from screamingface_engine.candidate_outcomes import (
    CandidateOutcome,
    decode_outcome,
    encode_outcome,
    stored_cost,
)


def _wire(cost: str) -> bytes:
    body = json.loads(encode_outcome("topic", CandidateOutcome("succeeded")))
    body["cost_usd"] = cost
    return json.dumps(body).encode()


def test_trapped_rounding_signals_do_not_reach_the_writer() -> None:
    with localcontext(Context(traps=[Inexact, Rounded])):
        _, outcome = decode_outcome(_wire("5E-13"))

        assert outcome.cost_usd is not None
        assert stored_cost(outcome.cost_usd) == Decimal("1E-12")


def test_a_low_precision_context_still_refuses_a_cost_that_rounds_onto_the_bound() -> None:
    with (
        localcontext(Context(prec=24, traps=[InvalidOperation])),
        pytest.raises(ValueError, match="cost"),
    ):
        decode_outcome(_wire("999999999999.9999999999999"))


def test_a_low_precision_context_without_traps_never_stores_nan() -> None:
    with localcontext(Context(prec=1, traps=[])):
        outcome = CandidateOutcome("succeeded", cost_usd=Decimal("123.456789"))

        assert outcome.cost_usd is not None
        assert stored_cost(outcome.cost_usd) == Decimal("123.456789000000")
