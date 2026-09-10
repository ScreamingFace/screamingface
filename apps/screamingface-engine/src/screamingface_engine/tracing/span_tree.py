"""Wire span frames -> a span tree. Pure, total, and it never fabricates (OME-1130).

INPUT IS THE WIRE, NOT THE OBSERVER SEAM. `OME-1130`'s description points at
`url4/observe.py`'s `NodeStarted`/`NodeFinished`, and that is the RUNNER's in-process
observation seam — the control-plane relay never sees those objects. It sees published
CloudEvents: `SpanEvent` carrying `SpanData`. Building on `url4.observe` here also fails
`test_only_engine_extensions_import_url4`, which confines the url4 ENGINE to Runner adapters and
Benchmark extensions while exempting `url4.streaming` as the shared wire contract. The guard
caught it; this module is built on the wire.

Three consequences of that, all load-bearing:

* **No started/finished pairing.** The runner emits ONE `SpanEvent` per completed span
  (`executor.py::_RunState._finish`), so a span arrives whole.
* **Identity lives on the ENVELOPE, not the payload.** `traceparent` carries
  `00-<trace_id>-<span_id>-01`; the parent edge rides `tracestate` as `url4.parent=<span_id>`.
* **A missing `tracestate` MEANS the root is the parent** — `lifecycle._trace_fields` omits it
  when `parent is None or parent == root_span_id`. Absent is information here, not a gap.

WHY the timing is better than `OME-1130` assumed: the ticket says durations must come from
envelope publish times and warns they carry publish latency. They do not. `SpanData` carries its
own `start`/`end`, captured in the runner when the observation event arrives
(`executor.py:358`, `datetime.now(UTC)`), so a duration is the node's own, not a publish
artifact. It is still observation time rather than exact `resolve` boundaries — but the
publish-latency caveat the ticket asks to be written down does not apply.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from url4.streaming.protocol import SpanEvent

_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")
_PARENT_RE = re.compile(r"(?:^|,)\s*url4\.parent=([0-9a-f]{16})\s*(?:,|$)")
_ALL_ZERO_TRACE = "0" * 32
_ALL_ZERO_SPAN = "0" * 16


@dataclass(frozen=True, slots=True)
class Span:
    """One node evaluation, as the wire stated it."""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    operation: str
    start_time: datetime
    end_time: datetime | None
    status: str
    provider: str | None = None
    request_model: str | None = None
    response_model: str | None = None

    @property
    def is_root_child(self) -> bool:
        """No `url4.parent` on the wire means the run's root span is the parent."""
        return self.parent_span_id is None


@dataclass(frozen=True, slots=True)
class SpanTree:
    """Everything the frames said, including what they could not say.

    `undecodable` is part of the RESULT rather than a logged warning: a consumer deciding
    whether a trace is complete needs to know frames were skipped, and an exporter that
    silently dropped them would ship a tree that looks whole.
    """

    trace_id: str | None
    spans: tuple[Span, ...]
    undecodable: int


def _identity(traceparent: str | None) -> tuple[str, str] | None:
    """The (trace_id, span_id) a traceparent states, or None if it states none usably.

    The all-zero rejections are the same two Phase 1 applies (`aigateway.w3c_trace`,
    `url4.streaming.trace`): an all-zero id is valid hex, parses cleanly, and correlates
    nothing. Admitting one would put a span in the UI under an id that can never join anything.
    """
    match = _TRACEPARENT_RE.match(traceparent) if traceparent else None
    if match is None:
        return None
    trace_id, span_id = match.group(1), match.group(2)
    if trace_id == _ALL_ZERO_TRACE or span_id == _ALL_ZERO_SPAN:
        return None
    return trace_id, span_id


def _parent(tracestate: str | None) -> str | None:
    if not tracestate:
        return None
    match = _PARENT_RE.search(tracestate)
    return match.group(1) if match else None


def build_span_tree(frames: Sequence[SpanEvent]) -> SpanTree:
    """Fold published span frames into the tree they describe.

    INVARIANT — never fabricate. A frame whose `traceparent` will not parse is COUNTED and
    skipped, never given a synthesised id: a span under an invented trace id would appear in
    the UI as a real run that never happened, which is worse than a visibly short trace.
    """
    spans: list[Span] = []
    undecodable = 0
    trace_id: str | None = None

    for frame in frames:
        identity = _identity(frame.traceparent)
        if identity is None:
            undecodable += 1
            continue
        frame_trace, span_id = identity
        trace_id = trace_id or frame_trace
        data = frame.data
        spans.append(
            Span(
                trace_id=frame_trace,
                span_id=span_id,
                parent_span_id=_parent(frame.tracestate),
                name=data.name,
                operation=data.operation,
                start_time=data.start,
                end_time=data.end,
                status=data.status,
                provider=data.provider,
                request_model=data.request_model,
                response_model=data.response_model,
            )
        )

    return SpanTree(trace_id=trace_id, spans=tuple(spans), undecodable=undecodable)


__all__ = ["Span", "SpanTree", "build_span_tree"]
