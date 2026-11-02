"""The child's `SETTLED` line: its Candidate outcome, sent to the worker before it exits
(OME-1785, E5 P1 spec R3)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from screamingface_engine import child_protocol
from screamingface_engine.child_protocol import Settled, decode_settled, encode_settled


@pytest.mark.parametrize(
    "settled",
    [
        Settled("succeeded", None, Decimal("0.000123456789")),
        Settled("failed", "provider_error", None),
        Settled("timed_out", "deadline_exceeded", Decimal("12.5")),
        Settled("stopped", None, None),
    ],
)
def test_a_settled_line_round_trips(settled: Settled) -> None:
    line = encode_settled(settled)

    assert line.startswith(b"SETTLED ") and line.endswith(b"\n")
    assert decode_settled(line) == settled


def test_the_cost_travels_as_a_decimal_string() -> None:
    """WHY: a JSON number is a float to most readers, and a float cannot hold an exact cost."""
    line = encode_settled(Settled("succeeded", None, Decimal("0.1")))

    assert b'"cost_usd":"0.1"' in line


@pytest.mark.parametrize(
    "line",
    [
        b"ACK\n",
        b"SETTLED not json\n",
        b"SETTLED []\n",
        b'SETTLED {"status": 7}\n',
        b'SETTLED {"status": "succeeded", "error_code": 7}\n',
        b'SETTLED {"status": "succeeded", "cost_usd": 0.1}\n',
        b'SETTLED {"status": "succeeded", "cost_usd": "lots"}\n',
    ],
)
def test_a_malformed_settled_line_is_refused(line: bytes) -> None:
    with pytest.raises(child_protocol.ProtocolError):
        decode_settled(line)
