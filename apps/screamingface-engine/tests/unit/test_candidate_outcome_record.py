"""E5 P2 spec §4.3 and §4.4: a `CandidateOutcome` carries the Candidate's record.

FEATURE: a detached Run (OME-1837). STORY: as a researcher reattaching from another machine, I
get each Candidate's timing, usage and cache figures without the machine that started it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest

from screamingface_engine.candidate_outcomes import (
    MAX_OUTCOME_BYTES,
    CandidateOutcome,
    decode_outcome,
    encode_outcome,
)

RECORD = {
    "started_at": "2026-11-12T09:00:00+00:00",
    "completed_at": "2026-11-12T09:03:00+00:00",
    "usage": {"input_tokens": 1200, "output_tokens": 300},
    "cache_hits": 2,
    "client_version": "1.4.0",
    "trace_id": "0af7651916cd43dd8448eb211c80319c",
    "error": {"code": "provider_error", "message": "überlastet", "permanent": False},
}
FINISHED = datetime(2026, 11, 12, 9, 3, tzinfo=UTC)


def test_an_outcome_round_trips_with_its_record() -> None:
    outcome = CandidateOutcome("failed", "provider_error", Decimal("0.25"), FINISHED, RECORD)

    topic, decoded = decode_outcome(encode_outcome("t" * 64, outcome))

    assert topic == "t" * 64
    assert decoded.record == RECORD
    assert decoded == outcome


def test_an_outcome_without_a_record_is_todays_wire_form() -> None:
    """INVARIANT (plan E2): an outcome nobody asked a record for is byte for byte P1's."""
    outcome = CandidateOutcome("succeeded", None, Decimal("0.5"), FINISHED)

    assert encode_outcome("t1", outcome) == (
        b'{"topic":"t1","status":"succeeded","error_code":null,"cost_usd":"0.5",'
        b'"finished_at":"2026-11-12T09:03:00+00:00"}'
    )
    assert decode_outcome(encode_outcome("t1", outcome))[1].record is None


def test_a_record_does_not_make_two_outcomes_different() -> None:
    """WHY: two outcomes with one verdict are the same outcome (P1 spec R3), and a frozen
    outcome holding a dict must still hash."""
    with_record = CandidateOutcome("succeeded", finished_at=FINISHED, record=RECORD)
    without = CandidateOutcome("succeeded", finished_at=FINISHED)

    assert with_record == without
    assert hash(with_record) == hash(without)


@pytest.mark.parametrize("record", [[1, 2], "text", 3])
def test_a_record_that_is_not_an_object_is_malformed(record: object) -> None:
    body = json.loads(encode_outcome("t1", CandidateOutcome("succeeded", finished_at=FINISHED)))
    body["record"] = record

    with pytest.raises(ValueError, match="record"):
        decode_outcome(json.dumps(body).encode())


def test_a_record_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(ValueError, match="record"):
        CandidateOutcome("succeeded", record=cast(Any, ["not", "an", "object"]))


def test_a_null_record_reads_as_none() -> None:
    body = json.loads(encode_outcome("t1", CandidateOutcome("succeeded", finished_at=FINISHED)))
    body["record"] = None

    assert decode_outcome(json.dumps(body).encode())[1].record is None


def test_an_outcome_too_large_to_publish_is_refused_at_encode() -> None:
    """WHY at encode: the stream would refuse it anyway, and the producer must learn now so it
    can publish the outcome without its record (§4.3)."""
    record = {"error": {"message": "x" * MAX_OUTCOME_BYTES}}

    with pytest.raises(ValueError, match="bytes"):
        encode_outcome("t1", CandidateOutcome("failed", finished_at=FINISHED, record=record))
