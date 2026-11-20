"""The Client clamps an Engine span that ends before it starts; it does not abort the run.

FEATURE: a bad telemetry span never destroys a successful evaluation.
STORY: as a researcher replaying a cached run, I get my Report, instead of a bare
``ValueError: Span end cannot precede start`` for a run the Engine reported as succeeded.

WHY at the wire adapter: the public ``sf.events.Span`` keeps rejecting ``end < start`` (pinned in
``test_event_values.py``), which is right for a value type. The Engine produced the inversion
when the host stepped its wall clock back (lima-guestagent ``SyncTime``, about 211 ms), so the
adapter resolves it with a warning, as it already does for a cost total that disagrees with its
parts.

INVARIANT: clamp, never drop. The span still counts as a cache hit and still carries its saving;
dropping it would under-count a run that succeeded. The record that counts it is the Engine's,
pinned in `apps/screamingface-engine/tests/unit/test_candidate_record_evidence_rules.py`.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

import screamingface as sf
from screamingface._engine import contract as _engine_contract


def _envelope() -> dict[str, Any]:
    return {
        "id": "event_5",
        "run_id": "run_1",
        "sequence": 5,
        "timestamp": _engine_contract._timestamp("2026-10-19T12:11:49Z"),
        "source": "/trace/run_1/node/root",
        "traceparent": None,
        "tracestate": None,
    }


def _inverted_span_data() -> dict[str, object]:
    return {
        "name": "TextNode",
        "gen_ai.operation.name": "TextNode",
        "kind": "internal",
        "status": "ok",
        "start": "2026-10-19T12:11:49.000000Z",
        "end": "2026-10-19T12:11:48.789000Z",
        "cache_status": "hit",
    }


def test_an_inverted_span_is_clamped_to_zero_length_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="screamingface._engine.contract"):
        span = _engine_contract._span(_envelope(), _inverted_span_data())

    assert isinstance(span, sf.events.Span)
    assert span.end == span.start
    warnings = [
        record
        for record in caplog.records
        if record.name == "screamingface._engine.contract" and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "ends before it starts" in warnings[0].getMessage()
