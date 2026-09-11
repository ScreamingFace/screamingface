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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from url4.streaming.protocol import SpanData, SpanEvent

_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")
_PARENT_RE = re.compile(r"(?:^|,)\s*url4\.parent=([0-9a-f]{16})\s*(?:,|$)")
_ALL_ZERO_TRACE = "0" * 32
_ALL_ZERO_SPAN = "0" * 16

AttributeValue = str | int | float | bool | Sequence[str]
"""What a span attribute may hold — OTel's scalar set, narrowed to the shapes `SpanData`
actually produces (`finish_reasons` is the only sequence)."""

_STRUCTURE = frozenset({"name", "kind", "start", "end", "status"})
"""`SpanData` fields that are span STRUCTURE, not attributes — they become dedicated fields on
:class:`Span` and must not be duplicated into the attribute bag. Everything else on the payload
is an attribute, which is why :func:`_attributes` subtracts rather than enumerates: a new
`gen_ai.*` field on the protocol then flows through with no edit here."""


@dataclass(frozen=True, slots=True)
class Span:
    """One evaluation, as the wire stated it — a node's, or the run's own (the synthetic root).

    `status` deliberately carries TWO vocabularies: `SpanData.status` (`ok` | `error`) for a
    node, and `TerminatedData.status` (`succeeded` | `failed` | `stopped` | `timed_out`) for the
    root. Normalising them here would throw away the run-level distinction at the only point it
    still exists — `cancelled` is already collapsed to `error` before a node span is published,
    so the root is where "stopped" survives at all. The adapter understands both.
    """

    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    operation: str
    start_time: datetime
    end_time: datetime | None
    status: str
    kind: str = "internal"
    attributes: Mapping[str, AttributeValue] = field(default_factory=dict)

    @property
    def is_root_child(self) -> bool:
        """No `url4.parent` on the wire means the run's root span is the parent."""
        return self.parent_span_id is None


def _attributes(data: SpanData) -> Mapping[str, AttributeValue]:
    """Every non-structural payload field, under the name the PROTOCOL gives it.

    `SpanData` already declares OTel serialization aliases — `gen_ai.request.model`,
    `gen_ai.usage.input_tokens`, and so on — so the conventional attribute names are the
    protocol's own and are not re-decided here. Its deliberate NON-aliases (`refusal`,
    `cache_status`, `cache_reason`) are local extensions whose docstrings say so explicitly;
    they get a `url4.` prefix rather than a bare name, so nothing reads as a standard attribute
    that is not one.

    `exclude_none` follows OTel's absent-or-populated convention: an attribute present with a
    null value says something different from an absent one, and the wire means absent.
    """
    dumped = data.model_dump(by_alias=True, exclude_none=True)
    return {
        (key if "." in key else f"url4.{key}"): value
        for key, value in dumped.items()
        if key not in _STRUCTURE
    }


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


def identity_of(traceparent: str | None) -> tuple[str, str] | None:
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


def span_from_frame(frame: SpanEvent) -> Span | None:
    """One published frame -> one span, or ``None`` when the frame states no usable identity.

    INVARIANT — never fabricate. A frame whose `traceparent` will not parse gets no span at
    all, never a synthesised id: a span under an invented trace id would appear in the UI as a
    real run that never happened, which is worse than a visibly short trace. The CALLER decides
    what to do with the refusal (count it, log it); this function only refuses.

    Split out of :func:`build_span_tree` for the relay, which sees frames one at a time as they
    are published and cannot wait for a complete sequence.
    """
    identity = identity_of(frame.traceparent)
    if identity is None:
        return None
    trace_id, span_id = identity
    data = frame.data
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=_parent(frame.tracestate),
        name=data.name,
        operation=data.operation,
        start_time=data.start,
        end_time=data.end,
        status=data.status,
        kind=data.kind,
        attributes=_attributes(data),
    )


def build_span_tree(frames: Sequence[SpanEvent]) -> SpanTree:
    """Fold published span frames into the tree they describe.

    A batch view over :func:`span_from_frame`, for anything holding a whole run's frames at
    once; the streaming relay uses the per-frame function directly.
    """
    spans: list[Span] = []
    undecodable = 0
    trace_id: str | None = None

    for frame in frames:
        span = span_from_frame(frame)
        if span is None:
            undecodable += 1
            continue
        trace_id = trace_id or span.trace_id
        spans.append(span)

    return SpanTree(trace_id=trace_id, spans=tuple(spans), undecodable=undecodable)


__all__ = [
    "AttributeValue",
    "Span",
    "SpanTree",
    "build_span_tree",
    "identity_of",
    "span_from_frame",
]
