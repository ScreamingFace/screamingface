"""CV-5: the capture index row is thin. A body is inline only for `unstored` and `bypass`.

FEATURE: OME-1307 (E14) - `capture_record` maps one call to one `CaptureRecord`.
INVARIANT (CV-D8): no field ever holds prompt text except `request_material`, and a response body
is inline only for the inline outcomes with a key. `version_hit` is in `INLINE_OUTCOMES` by OD-7;
GW-replay asserts it, so the parametrization below does not include it.
"""

from __future__ import annotations

import json
from typing import cast

import pytest

from aigateway.core.cache_versions.capture import capture_record
from aigateway.core.cache_versions.ports import (
    CAPTURE_OUTCOMES,
    INLINE_OUTCOMES,
    CaptureKey,
    CaptureOutcome,
)

_KEY = CaptureKey(key_hash="ab" * 32, material='{"prompt":"secret prompt text"}')
_RESPONSE = {"id": "resp-1", "choices": [{"message": {"content": "café — ünï"}}]}
_TRACE = "d4" * 16

_OUTCOMES: list[CaptureOutcome] = ["hit", "stored", "unstored", "bypass", "error"]


@pytest.mark.parametrize("outcome", _OUTCOMES)
@pytest.mark.parametrize("keyed", [True, False], ids=["keyed", "unkeyed"])
def test_capture_index_row_is_thin_body_inline_only_for_unstored_and_bypass(
    outcome: CaptureOutcome, keyed: bool
) -> None:
    key = _KEY if keyed else None

    record = capture_record(
        account_id="acct", trace_id=_TRACE, outcome=outcome, key=key, response=_RESPONSE
    )

    assert (record.account_id, record.trace_id, record.outcome) == ("acct", _TRACE, outcome)
    assert record.key_hash == (_KEY.key_hash if keyed else None)
    assert record.request_material == (_KEY.material if keyed else None)
    body_expected = keyed and outcome in {"unstored", "bypass"}
    if body_expected:
        # Compact JSON, non-ASCII kept as is: the exact text that a reader parses back.
        assert record.response_json == json.dumps(
            _RESPONSE, separators=(",", ":"), ensure_ascii=False
        )
        assert json.loads(record.response_json or "") == _RESPONSE
    else:
        assert record.response_json is None
    assert _KEY.material not in (record.response_json or "")


def test_capture_record_keeps_no_body_when_the_response_is_not_a_dict() -> None:
    record = capture_record(
        account_id="acct",
        trace_id=_TRACE,
        outcome="bypass",
        key=_KEY,
        response=["not", "a", "dict"],
    )

    assert record.response_json is None


def test_capture_record_rejects_an_unknown_outcome() -> None:
    with pytest.raises(ValueError):
        capture_record(
            account_id="acct",
            trace_id=_TRACE,
            outcome=cast(CaptureOutcome, "mystery"),
            key=_KEY,
            response=None,
        )


def test_capture_record_lets_a_serialisation_error_propagate() -> None:
    # WHY: the route helper counts it as a capture failure; swallowing it here would hide it.
    with pytest.raises(ValueError):
        capture_record(
            account_id="acct",
            trace_id=_TRACE,
            outcome="bypass",
            key=_KEY,
            response={"score": float("nan")},
        )


def test_the_outcome_vocabulary_is_closed() -> None:
    assert CAPTURE_OUTCOMES == {"hit", "stored", "unstored", "bypass", "version_hit", "error"}
    assert INLINE_OUTCOMES == {"unstored", "bypass", "version_hit"}
