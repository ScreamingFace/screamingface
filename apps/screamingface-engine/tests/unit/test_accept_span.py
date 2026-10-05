"""The control plane's accept span, as a value (OME-1218).

FEATURE (OME-1218): the run-submission route emits a span of its own, and forwards ITS id to
the run, so `url4.run` is a child of it — one run, one trace, one root, queue wait visible as
the gap between the two (owner decision, option 1). These tests pin the identity rules and the
never-raise invariant with no OTel and no HTTP: the sink is the `SpanSink` port, faked.
"""

from __future__ import annotations

import re

import pytest

from screamingface_engine.tracing.accept import ACCEPT_SPAN_NAME, AcceptSpan
from screamingface_engine.tracing.span_tree import Span

_TP = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-01$")
INBOUND_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
INBOUND_SPAN = "00f067aa0ba902b7"
INBOUND = f"00-{INBOUND_TRACE}-{INBOUND_SPAN}-01"


class FakeSink:
    def __init__(self, *, explode: bool = False) -> None:
        self.spans: list[Span] = []
        self._explode = explode

    def emit(self, span: Span) -> None:
        if self._explode:
            raise RuntimeError("collector exploded")
        self.spans.append(span)

    def close(self) -> None:
        return None


def test_with_no_inbound_context_the_accept_span_is_a_fresh_root() -> None:
    sink = FakeSink()

    accept = AcceptSpan.open(sink, None, topic="t")
    accept.scheduled()

    (span,) = sink.spans
    assert span.parent_span_id is None
    assert re.fullmatch(r"[0-9a-f]{32}", span.trace_id)
    assert span.trace_id != "0" * 32
    assert re.fullmatch(r"[0-9a-f]{16}", span.span_id)


def test_the_forwarded_traceparent_names_the_accept_span_not_the_inbound_one() -> None:
    """INVARIANT (owner decision, option 1): the run is handed the CURRENT span — the accept —
    so `url4.run` becomes its child. Forwarding the inbound id would make the run a sibling of
    the accept and erase the queue-wait gap the ticket exists to show."""
    sink = FakeSink()

    accept = AcceptSpan.open(sink, INBOUND, topic="t")
    accept.scheduled()

    match = _TP.match(accept.traceparent)
    assert match is not None
    (span,) = sink.spans
    assert match.group(1) == INBOUND_TRACE == span.trace_id
    assert match.group(2) == span.span_id != INBOUND_SPAN


def test_with_an_inbound_traceparent_the_accept_span_is_its_child() -> None:
    sink = FakeSink()

    AcceptSpan.open(sink, INBOUND, topic="t").scheduled()

    assert sink.spans[0].parent_span_id == INBOUND_SPAN


@pytest.mark.parametrize(
    "inbound",
    ["garbage", f"00-{'0' * 32}-{INBOUND_SPAN}-01", f"00-{INBOUND_TRACE}-{'0' * 16}-01", ""],
)
def test_an_unusable_inbound_traceparent_is_treated_as_absent(inbound: str) -> None:
    """W3C "restart": garbage never propagates — neither as a parent nor as a trace id."""
    sink = FakeSink()

    accept = AcceptSpan.open(sink, inbound, topic="t")
    accept.scheduled()

    span = sink.spans[0]
    assert span.parent_span_id is None
    assert span.trace_id not in {INBOUND_TRACE, "0" * 32}
    assert accept.traceparent == f"00-{span.trace_id}-{span.span_id}-01"


def test_the_span_describes_the_submission_route() -> None:
    sink = FakeSink()

    AcceptSpan.open(sink, None, topic="topic-1").scheduled()

    span = sink.spans[0]
    assert span.name == ACCEPT_SPAN_NAME == "url4.accept"
    assert span.kind == "server"
    assert span.status == "ok"
    assert span.end_time is not None and span.start_time <= span.end_time
    assert span.attributes["http.request.method"] == "GET"
    assert span.attributes["http.route"] == "/"
    assert span.attributes["url4.topic"] == "topic-1"
    assert span.attributes["url4.accept.outcome"] == "scheduled"
    assert "http.response.status_code" not in span.attributes


def test_a_client_refusal_is_recorded_but_is_not_a_server_error() -> None:
    """OTel HTTP server semconv: a 4xx is the caller's error, not this server's."""
    sink = FakeSink()

    AcceptSpan.open(sink, None, topic="t").refused(409)

    span = sink.spans[0]
    assert span.status == "ok"
    assert span.attributes["http.response.status_code"] == 409
    assert span.attributes["url4.accept.outcome"] == "refused"


def test_a_server_side_refusal_is_an_error() -> None:
    sink = FakeSink()

    AcceptSpan.open(sink, None, topic="t").refused(503)

    assert sink.spans[0].status == "error"
    assert sink.spans[0].attributes["http.response.status_code"] == 503


def test_the_span_ends_exactly_once() -> None:
    """The sync path ends it at enqueue; the handler's exit must not emit it a second time."""
    sink = FakeSink()

    accept = AcceptSpan.open(sink, None, topic="t")
    accept.scheduled()
    accept.refused(502)
    accept.scheduled()

    assert len(sink.spans) == 1
    assert sink.spans[0].attributes["url4.accept.outcome"] == "scheduled"


def test_a_failing_sink_never_fails_the_submission() -> None:
    """INVARIANT (as the relay's): telemetry degrades alone. A collector fault must not turn
    an accepted run into a 500."""
    accept = AcceptSpan.open(FakeSink(explode=True), None, topic="t")

    accept.scheduled()  # must not raise

    assert _TP.match(accept.traceparent)
