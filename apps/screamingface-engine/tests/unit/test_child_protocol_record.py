"""E5 P2 spec R5 and §4.3: the child reports its Candidate's record on its `SETTLED` line.

FEATURE: a detached Run (OME-1837).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from screamingface_engine.candidate_record import fit_record
from screamingface_engine.child_protocol import (
    ProtocolError,
    Settled,
    decode_settled,
    encode_settled,
)

FINISHED = datetime(2026, 11, 12, 9, 3, tzinfo=UTC)
RECORD = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "candidate_runs" / "failure.json").read_text()
)["record"]
# The worker's control-pipe read limit (`worker/warm_pool.py`).
CONTROL_LINE_LIMIT = 64 * 1024


def test_a_settled_line_round_trips_with_its_record() -> None:
    settled = Settled("failed", "provider_error", Decimal("0.5"), FINISHED, RECORD)

    decoded = decode_settled(encode_settled(settled))

    assert decoded == settled
    assert decoded.record == RECORD


def test_a_settled_line_without_a_record_is_todays() -> None:
    """INVARIANT (plan E2): a run nobody asked a record for reports exactly as before."""
    line = encode_settled(Settled("succeeded", None, Decimal("0.1"), FINISHED))

    assert line == (
        b'SETTLED {"status":"succeeded","error_code":null,"cost_usd":"0.1",'
        b'"finished_at":"2026-11-12T09:03:00+00:00"}\n'
    )
    assert decode_settled(line).record is None


def test_a_record_that_is_not_an_object_is_malformed() -> None:
    body = {"status": "succeeded", "error_code": None, "cost_usd": None, "record": [1]}
    body["finished_at"] = FINISHED.isoformat()

    with pytest.raises(ProtocolError, match="record"):
        decode_settled(b"SETTLED " + json.dumps(body).encode() + b"\n")


def test_a_record_with_a_huge_error_text_fits_the_control_pipe() -> None:
    record = json.loads(json.dumps(RECORD))
    record["error"]["message"] = "ü" * 100 * 1024
    record["error"]["details"]["error"]["message"] = record["error"]["message"]

    fitted = fit_record(record)
    assert fitted is not None
    line = encode_settled(Settled("failed", "provider_error", None, FINISHED, fitted))

    assert len(line) < CONTROL_LINE_LIMIT
    assert decode_settled(line).record == fitted
