"""The imported boards' evaluation envelopes — strict validators, no inference.

INVARIANT the suite defends: the aggregate reads ONLY envelopes these validators
accepted, so a malformed or misattributed row fails loudly here instead of becoming a
silently missing score. Pure data — no inspect import, runs in the extra-less gate.
"""

from __future__ import annotations

from typing import Any

import pytest

from screamingface_engine_inspect.envelopes import (
    CASE_EVALUATION_SCHEMA,
    CHECK_SCHEMA,
    bind_case_evaluation,
    decode_case_evaluation,
)


def _attempt(case_id: int = 7) -> dict[str, Any]:
    return {"schema": CHECK_SCHEMA, "case_id": case_id, "answer": "ANSWER: 42"}


def test_bind_then_decode_roundtrips() -> None:
    bound = bind_case_evaluation(7, [_attempt()])
    assert decode_case_evaluation(bound, 7) == bound
    assert bound["schema"] == CASE_EVALUATION_SCHEMA


@pytest.mark.parametrize("case_id", [True, 0, -1, "7", 1.0])
def test_non_positive_int_case_ids_are_rejected(case_id: Any) -> None:
    """bool is an int — True must never pass as case id 1 by accident."""

    with pytest.raises(ValueError, match="positive integer"):
        bind_case_evaluation(case_id, [_attempt()])


def test_attempt_for_another_case_is_rejected() -> None:
    with pytest.raises(ValueError, match="another Case"):
        bind_case_evaluation(7, [_attempt(case_id=8)])


def test_decode_refuses_unknown_fields() -> None:
    """No inference: an envelope carrying extra keys is a schema violation, not data."""

    bound = bind_case_evaluation(7, [_attempt()])
    with pytest.raises(ValueError, match="unknown fields"):
        decode_case_evaluation({**bound, "stowaway": 1}, 7)


def test_decode_refuses_a_wrong_schema_or_empty_attempts() -> None:
    bound = bind_case_evaluation(7, [_attempt()])
    with pytest.raises(ValueError, match="schema"):
        decode_case_evaluation({**bound, "schema": "something.else.v1"}, 7)
    with pytest.raises(ValueError, match="at least one attempt"):
        decode_case_evaluation({**bound, "attempts": []}, 7)
