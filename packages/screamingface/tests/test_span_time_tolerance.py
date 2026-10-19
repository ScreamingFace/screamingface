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
dropping it would under-count a run that succeeded.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import screamingface as sf
from screamingface._engine import contract as _engine_contract
from screamingface._engine.contract import _RunState

_REPO_ROOT = Path(__file__).resolve().parents[3]
# The real Engine stream for a run whose only model call was a cache hit (see
# `test_cache_hit_contract.py`); read by repository path, the Engine is not a dependency.
RUN_EVENTS = (
    _REPO_ROOT / "apps/screamingface-engine/tests/unit/data/cache_hit_contract/run_events.json"
)
_URL4 = "/openrouter/anthropic/claude-fable-5(ctx)!go"
_SAVED = Decimal("0.012345")
_STEP = timedelta(milliseconds=211)


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


def _stream_with_inverted_hit_span() -> list[dict[str, Any]]:
    """The real cache-hit stream, with its hit span ending one clock step before it starts.

    The root's cache summary is emptied (an older engine, or a summary dropped under
    backpressure) so the run's hit count and saving come from the SPANS alone: a dropped span
    would then show as zero hits and no saving.
    """
    events = json.loads(RUN_EVENTS.read_text(encoding="utf-8"))
    for event in events:
        data = event["data"]
        if event["type"] == "ai.url4.span" and data.get("cache_status") == "hit":
            start = _engine_contract._timestamp(data["start"])
            data["end"] = (start - _STEP).isoformat().replace("+00:00", "Z")
        elif event["type"] == "ai.url4.log":
            data["attributes"] = {}
    return events


def test_an_inverted_hit_span_still_counts_its_hit_and_its_saving() -> None:
    state = _RunState(_URL4)
    outcome = None
    for event in _stream_with_inverted_hit_span():
        accepted = state.accept(json.dumps(event))
        if accepted.outcome is not None:
            outcome = accepted.outcome

    assert outcome is not None, "the stream never produced a root outcome"
    assert outcome.cache_hits == 1
    assert outcome.cache_saved_cost_usd == _SAVED
