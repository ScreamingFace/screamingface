"""A span's end never precedes its start, whatever the host does to the wall clock.

FEATURE: wire spans the SDK can always accept.
STORY: as a researcher replaying a cached run, my evaluation finishes, instead of the SDK
aborting a run the Engine reported as succeeded because one span said it ended before it began.

INVARIANT: `start` is a wall-clock ANCHOR and the duration is MONOTONIC, so `end >= start` holds
by construction. CLOCK_REALTIME is not monotonic: on the kind-on-Colima stack lima-guestagent's
`SyncTime` steps the guest clock back about 211 ms every 10 s, and most spans last about 2 us
(both events drain from the bridge in one batch), so a step between `NodeStarted` and
`NodeFinished` used to publish `end` about 211 ms BEFORE `start`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import screamingface_engine.runner.executor as executor
from screamingface_engine.runner.executor import _RunState
from url4.observe import NodeFinished, NodeStarted
from url4.streaming.protocol import SpanData

_SPAN = "a" * 16
_T0 = datetime(2026, 10, 19, 12, 11, 49, tzinfo=UTC)
_MONOTONIC_STEP_S = 0.002


def _install_clocks(monkeypatch: pytest.MonkeyPatch, wall_step: timedelta) -> None:
    """Every wall reading moves by `wall_step`; every monotonic reading moves forward 2 ms.

    The two clocks disagree on purpose: the one a span's duration follows is the one that wins.
    """
    wall_reads = 0
    monotonic_reads = 0

    class _SteppedWall(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:  # type: ignore[override]
            nonlocal wall_reads
            reading = _T0 + wall_step * wall_reads
            wall_reads += 1
            return reading

    def _monotonic() -> float:
        nonlocal monotonic_reads
        reading = 100.0 + _MONOTONIC_STEP_S * monotonic_reads
        monotonic_reads += 1
        return reading

    # The module imports the `datetime` class by name and `import time`, so both seams
    # are module attributes; replacing `time` with a namespace keeps the global module untouched.
    monkeypatch.setattr(executor, "datetime", _SteppedWall)
    monkeypatch.setattr(executor, "time", SimpleNamespace(monotonic=_monotonic))


def _span(state: _RunState, *, open_first: bool = True) -> SpanData:
    if open_first:
        state.map(NodeStarted(span_id=_SPAN, parent_span_id=None, node_kind="TextNode", detail=""))
    frames = state.map(NodeFinished(span_id=_SPAN, status="ok", engine_seq=1))
    return next(f.payload for f in frames if isinstance(f.payload, SpanData))


def test_a_backward_wall_step_inside_a_span_does_not_invert_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The observed trigger: lima-guestagent's SyncTime step of about 211 ms landing between the
    # span's two events.
    _install_clocks(monkeypatch, wall_step=-timedelta(milliseconds=211))

    span = _span(_RunState())

    assert span.end is not None
    assert span.end >= span.start
    assert span.end - span.start == timedelta(microseconds=2000)


def test_a_finish_for_a_span_never_opened_ends_where_it_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No start was recorded, so no duration is known: the fallback claims none rather than one
    # made of two wall readings that a step can put out of order.
    _install_clocks(monkeypatch, wall_step=-timedelta(milliseconds=211))

    span = _span(_RunState(), open_first=False)

    assert span.end == span.start


def test_a_forward_wall_step_does_not_inflate_the_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The same seam in the other direction: a step forward is not time the node spent.
    _install_clocks(monkeypatch, wall_step=timedelta(seconds=5))

    span = _span(_RunState())

    assert span.end is not None
    assert span.end - span.start == timedelta(microseconds=2000)
