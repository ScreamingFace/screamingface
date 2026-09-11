"""Published span frames become a span tree, faithfully (OME-1130) — Phase 2's semantics.

Phase 1 made one `trace_id` greppable. This is what makes SigNoz's trace VIEW stop being empty.

The input is the WIRE, not `url4.observe`: the relay sees `SpanEvent`/`SpanData`, and identity
travels on the ENVELOPE — `traceparent` carries trace+span, `tracestate` carries the parent as
`url4.parent=`. See the module docstring for why (a layering guard enforces it).

INVARIANT under test: **the mapper never fabricates.** A frame it cannot decode is counted and
skipped, never given a synthesised id — a span under an invented trace id shows up in the UI as
a run that never happened, which is worse than a visibly short trace.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from screamingface_engine.tracing.span_tree import build_span_tree
from url4.streaming.protocol import SpanData, SpanEvent
from url4.streaming.protocol.envelope import source_for

WireStatus = Literal["ok", "error"]
"""Mirrors `SpanData.status`. NOTE the wire has only two states — `url4.observe` also has
`cancelled`, and it is collapsed before publication. A stopped run is not distinguishable
from a failed one in the trace view; that is a wire-level limitation, not a mapper one."""

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
ROOT = "00f067aa0ba902b7"
T0 = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)

_UNSET = object()
"""Distinguishes "caller said nothing" from "caller said None".

A plain `end or at(2)` default silently swallowed an explicit `end=None`, so the
unfinished-span test asserted against a fabricated end and failed for the wrong reason."""


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def span_event(
    span_id: str,
    *,
    parent: str | None = None,
    trace: str = TRACE,
    status: WireStatus = "ok",
    start: datetime | None = None,
    end: Any = _UNSET,
    traceparent: str | None = None,
) -> SpanEvent:
    return SpanEvent(
        id=f"evt-{span_id[:8]}",
        # `topic`/`node` are NOT envelope fields — they are inputs to `source_for`, which
        # builds the CloudEvents `source` URI-ref. Pydantic tolerated them as extras at
        # runtime; pyright did not, which is the better signal.
        source=source_for("t", "root"),
        sequence="1",
        time=at(0),
        traceparent=(traceparent if traceparent is not None else f"00-{trace}-{span_id}-01"),
        tracestate=f"url4.parent={parent}" if parent else None,
        data=SpanData(
            name="gpt",
            operation="chat",
            start=start or at(1),
            end=at(2) if end is _UNSET else end,
            status=status,
        ),
    )


# --- identity comes off the envelope ---------------------------------------------------------


def test_trace_and_span_ids_are_read_from_the_traceparent() -> None:
    tree = build_span_tree([span_event("a" * 16)])

    only = tree.spans[0]
    assert only.trace_id == TRACE
    assert only.span_id == "a" * 16


def test_the_parent_edge_is_read_from_tracestate() -> None:
    tree = build_span_tree([span_event("b" * 16, parent="a" * 16)])

    assert tree.spans[0].parent_span_id == "a" * 16


def test_no_tracestate_MEANS_the_root_is_the_parent() -> None:
    """`lifecycle._trace_fields` omits tracestate when the parent IS the root span.

    Absent is information here, not a gap — treating it as "unknown parent" would orphan
    every top-level node in the waterfall.
    """
    tree = build_span_tree([span_event("a" * 16)])

    assert tree.spans[0].parent_span_id is None
    assert tree.spans[0].is_root_child


def test_a_deep_chain_keeps_every_edge() -> None:
    a, b, c = "a" * 16, "b" * 16, "c" * 16
    tree = build_span_tree([span_event(a), span_event(b, parent=a), span_event(c, parent=b)])

    assert {s.span_id: s.parent_span_id for s in tree.spans} == {a: None, b: a, c: b}


# --- timing and status -----------------------------------------------------------------------


def test_timing_comes_from_the_payload_not_the_envelope() -> None:
    """OME-1130 assumed publish times; SpanData carries its own start/end.

    They are captured in the runner when the observation event arrives
    (`executor.py:358`), so a duration is the node's own rather than a publish artifact.
    """
    tree = build_span_tree([span_event("a" * 16, start=at(5), end=at(9))])

    assert (tree.spans[0].start_time, tree.spans[0].end_time) == (at(5), at(9))


def test_an_unfinished_span_keeps_a_null_end() -> None:
    """`SpanData.end` is optional; a run cut short must not get a fabricated end."""
    tree = build_span_tree([span_event("a" * 16, end=None)])

    assert tree.spans[0].end_time is None


def test_error_status_is_carried() -> None:
    tree = build_span_tree([span_event("a" * 16, status="error")])

    assert tree.spans[0].status == "error"


# --- what it refuses to invent ----------------------------------------------------------------


def test_a_frame_with_an_unparseable_traceparent_is_counted_not_invented() -> None:
    tree = build_span_tree([span_event("a" * 16, traceparent="not-a-traceparent")])

    assert tree.spans == ()
    assert tree.undecodable == 1


def test_an_all_zero_span_id_is_refused() -> None:
    """A zero id parses as hex and correlates nothing — the same trap Phase 1 rejects."""
    tree = build_span_tree([span_event("a" * 16, traceparent=f"00-{TRACE}-{'0' * 16}-01")])

    assert tree.spans == (), "an all-zero span id was admitted"
    assert tree.undecodable == 1


def test_a_garbage_tracestate_yields_no_parent_rather_than_a_wrong_one() -> None:
    frame = span_event("a" * 16)
    frame = frame.model_copy(update={"tracestate": "vendor=something-else"})

    tree = build_span_tree([frame])

    assert tree.spans[0].parent_span_id is None


def test_an_empty_stream_yields_no_spans_and_no_trace() -> None:
    tree = build_span_tree([])

    assert tree.spans == ()
    assert tree.trace_id is None
