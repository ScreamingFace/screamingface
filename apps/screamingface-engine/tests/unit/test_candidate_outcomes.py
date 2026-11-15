"""E5 P1 spec R3: a `CandidateOutcome` and its wire form on `url4-candidate-outcomes`.

FEATURE: first-class Runs (OME-1785).
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from screamingface_engine.candidate_outcomes import (
    CandidateOutcome,
    decode_outcome,
    encode_outcome,
)


@pytest.mark.parametrize(
    "outcome",
    [
        CandidateOutcome("succeeded", cost_usd=Decimal("0.000123456789")),
        CandidateOutcome("failed", error_code="provider_error"),
        CandidateOutcome("timed_out"),
        CandidateOutcome("stopped", cost_usd=Decimal("0")),
    ],
)
def test_an_outcome_round_trips_with_its_exact_cost(outcome: CandidateOutcome) -> None:
    assert decode_outcome(encode_outcome("t" * 64, outcome)) == ("t" * 64, outcome)


def test_the_cost_travels_as_a_decimal_string() -> None:
    """INVARIANT: cost is exact only (spec R3); a float on the wire would round it."""
    payload = json.loads(
        encode_outcome("topic", CandidateOutcome("succeeded", None, Decimal("0.1")))
    )

    assert payload["cost_usd"] == "0.1"


@pytest.mark.parametrize(
    ("status", "error_code", "cost"),
    [
        ("lost", None, None),  # only reconcile writes `lost`, never an outcome
        ("pending", None, None),
        ("succeeded", None, Decimal("-1")),
        ("succeeded", None, Decimal("NaN")),
        ("succeeded", None, Decimal("Infinity")),
    ],
)
def test_an_outcome_refuses_what_no_terminal_frame_can_say(
    status: str, error_code: str | None, cost: Decimal | None
) -> None:
    with pytest.raises(ValueError):
        CandidateOutcome(status, error_code, cost)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"[]",
        b'{"status": "succeeded"}',
        b'{"topic": "", "status": "succeeded"}',
        b'{"topic": "t", "status": "lost"}',
        b'{"topic": "t", "status": []}',
        b'{"topic": "t", "status": {}}',
        b'{"topic": "t", "status": "succeeded", "cost_usd": 0.1}',
        b'{"topic": "t", "status": "succeeded", "cost_usd": "abc"}',
        b'{"topic": "t", "status": "succeeded", "error_code": 7}',
    ],
)
def test_a_malformed_payload_is_refused(payload: bytes) -> None:
    with pytest.raises(ValueError):
        decode_outcome(payload)
