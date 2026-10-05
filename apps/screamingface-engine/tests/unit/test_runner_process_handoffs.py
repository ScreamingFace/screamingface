"""The two hand-offs `_run_process` makes that no other test pinned (OME-1462).

Both survived mutation of the full suite after #1215/#1216:

* `SpanRelay(..., traceparent=traceparent)` — the ONLY production line that tells the relay
  which span the run was handed, i.e. what makes `url4.run` a child of `url4.accept`. The
  relay's own tests (`test_span_relay_parent.py`) prove the relay honours a handed parent;
  nothing proved the entrypoint hands it one.
* `run_and_reclaim(..., retain=...)` on the no-pool path — without it the runner purges a
  failed run's subject at the grace, and its post-mortem is gone within a minute (OME-946).
  `test_failed_run_evidence_retention.py` drives `run_and_reclaim` with a `retain` it builds
  itself; nothing proved `_run_process` passes one.

These tests drive `_run_process` itself, with the world, the executor and the url4 run swapped
for fakes at the module seams, so each fails the moment its keyword disappears.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from screamingface_engine import job_env
from screamingface_engine.runner import main
from screamingface_engine.tracing.relay import ROOT_SPAN_NAME
from screamingface_engine.tracing.span_tree import Span
from url4.streaming.interfaces import EventPublisher
from url4.streaming.protocol import (
    OutboundFrame,
    StartedData,
    StartedEvent,
    TerminatedData,
    TerminatedEvent,
)
from url4.streaming.protocol.envelope import source_for

pytestmark = pytest.mark.asyncio

TOPIC = "handoff-topic"
TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
RUN_ROOT = "00f067aa0ba902b7"
ACCEPT = "b7ad6b7169203331"
T0 = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)


class _Sink:
    def __init__(self) -> None:
        self.spans: list[Span] = []

    def emit(self, span: Span) -> None:
        self.spans.append(span)

    def close(self) -> None:
        return None


class _Publisher:
    """The raw JetStream publisher's surface `_run_process` touches."""

    def __init__(self) -> None:
        self.frames: list[OutboundFrame] = []
        self.calls: list[str] = []

    async def ensure_stream(self, topic: str) -> None:
        return None

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        self.frames.append(event)

    async def flush(self) -> None:
        self.calls.append("flush")

    async def last_frame(self, topic: str) -> OutboundFrame | None:
        return self.frames[-1] if self.frames else None

    async def delete_stream(self, topic: str) -> None:
        self.calls.append(f"delete:{topic}")

    async def trim_retained(self, topic: str) -> None:
        self.calls.append(f"trim:{topic}")


def _frames(status: str) -> tuple[StartedEvent, TerminatedEvent]:
    """What `lifecycle.run` publishes for a run: its own root span id in the SAME trace."""
    traceparent = f"00-{TRACE}-{RUN_ROOT}-01"
    started = StartedEvent(
        id="s",
        source=source_for(TOPIC, "root"),
        time=T0,
        subject=TOPIC,
        sequence="1",
        traceparent=traceparent,
        data=StartedData(url4="x"),
    )
    terminated = TerminatedEvent(
        id="t",
        source=source_for(TOPIC, "root"),
        time=T0 + timedelta(seconds=1),
        subject=TOPIC,
        sequence="2",
        traceparent=traceparent,
        data=TerminatedData(status=status),  # type: ignore[arg-type]
    )
    return started, terminated


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> tuple[_Publisher, _Sink]:
    """`_run_process`'s seams replaced: no world, no executor, no url4 — a scripted run."""
    sink = _Sink()
    publisher = _Publisher()
    monkeypatch.setenv(job_env.TOPIC, TOPIC)
    monkeypatch.setenv(job_env.EXPRESSION, "'hi'")
    monkeypatch.setenv(job_env.TRACEPARENT, f"00-{TRACE}-{ACCEPT}-01")
    monkeypatch.setenv(job_env.STREAM_GRACE_S, "0")
    monkeypatch.delenv(job_env.RECLAIM_OWNER, raising=False)
    monkeypatch.setattr(main, "build_executor", lambda *a, **k: object())
    monkeypatch.setattr(main, "span_sink", lambda env: sink)
    return publisher, sink


def _script(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    async def _run_and_log(
        executor: Any, relay: EventPublisher, params: Any, traceparent: str | None
    ) -> None:
        for frame in _frames(status):
            await relay.publish(params.topic, frame)

    monkeypatch.setattr(main, "_run_and_log", _run_and_log)


async def test_the_run_root_is_exported_as_a_child_of_the_accept_span(
    wired: tuple[_Publisher, _Sink], monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT (OME-1218 option 1): one run is one trace with one root — `url4.run` hangs
    under the `url4.accept` span whose id the App rendered into `URL4_CLOUD_TRACEPARENT`.

    Kills the mutation `SpanRelay(publisher, sink)` (dropping `traceparent=`): the relay then
    has no handed parent and exports `url4.run` as an orphan root.
    """
    publisher, sink = wired
    monkeypatch.setenv(job_env.RECLAIM_OWNER, "worker")
    _script(monkeypatch, "succeeded")

    await main._run_process(publisher)  # type: ignore[arg-type]  # noqa: SLF001

    (root,) = [s for s in sink.spans if s.name == ROOT_SPAN_NAME]
    assert root.trace_id == TRACE
    assert root.span_id == RUN_ROOT
    assert root.parent_span_id == ACCEPT


async def test_the_no_pool_path_never_deletes_a_failed_runs_subject(
    wired: tuple[_Publisher, _Sink], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FEATURE (OME-946): post-mortem of a failed run on the no-pool path, where the runner
    reclaims its own subject.

    Kills the mutation that drops `retain=` from `run_and_reclaim(...)`: without it the
    runner purges the subject at the grace, whatever the run's ending.
    """
    publisher, _ = wired
    _script(monkeypatch, "failed")

    await main._run_process(publisher)  # type: ignore[arg-type]  # noqa: SLF001

    assert not [c for c in publisher.calls if c.startswith("delete:")]


async def test_the_no_pool_path_still_purges_a_successful_runs_subject(
    wired: tuple[_Publisher, _Sink], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the test above: the wiring reads the tail, it does not just skip the
    purge — a success keeps the 60 s purge (prompt-bearing frames are not retained)."""
    publisher, _ = wired
    _script(monkeypatch, "succeeded")

    await main._run_process(publisher)  # type: ignore[arg-type]  # noqa: SLF001

    assert publisher.calls == [f"delete:{TOPIC}"]


async def test_the_no_pool_path_caps_a_failed_runs_subject(
    wired: tuple[_Publisher, _Sink], monkeypatch: pytest.MonkeyPatch
) -> None:
    """OME-1462: the retained subject is not left whole — the publisher's cap is applied."""
    publisher, _ = wired
    _script(monkeypatch, "failed")

    await main._run_process(publisher)  # type: ignore[arg-type]  # noqa: SLF001

    assert publisher.calls == [f"trim:{TOPIC}"]
