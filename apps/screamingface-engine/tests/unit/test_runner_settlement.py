"""The run child's Candidate outcome (OME-1785, E5 P1 spec R3): classified by the one
classifier, with the summary's exact cost, and withheld when the child's frames were dropped."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from screamingface_engine import job_env
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.run_evidence import NO_TERMINAL_FRAME
from screamingface_engine.runner import main
from screamingface_engine.runner.summary import RunSummary
from screamingface_engine.tracing.span_tree import Span
from url4.streaming.protocol import (
    OutboundFrame,
    TerminatedData,
    TerminatedEvent,
    source_for,
)
from url4.streaming.protocol.taxonomy import ErrorInfo

pytestmark = pytest.mark.asyncio

TOPIC = "t-settled"
PARAMS = SimpleNamespace(topic=TOPIC, url4="'hi'", deadline_s=1.0, client_version=None)


class _Publisher:
    def __init__(self, *, dropped: bool = False) -> None:
        self.frames: list[OutboundFrame] = []
        self._dropped = dropped

    async def ensure_stream(self, topic: str) -> None:
        return None

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        self.frames.append(event)

    async def flush(self) -> None:
        return None

    def dropped(self, topic: str) -> bool:
        return self._dropped


class _Sink:
    def emit(self, span: Span) -> None:
        return None

    def close(self) -> None:
        return None


def _executor(cost: Decimal | None) -> Any:
    return SimpleNamespace(
        last_summary=lambda: RunSummary(outcome="failed", trace_id=None, cost_usd=cost)
    )


def _ending(status: Any, code: str | None = None) -> Any:
    async def fake_run(publisher: Any, *args: Any, **kwargs: Any) -> None:
        error = None if code is None else ErrorInfo(code=code, message="details")
        await publisher.publish(
            TOPIC,
            TerminatedEvent(
                id="t",
                source=source_for(TOPIC),
                subject=TOPIC,
                data=TerminatedData(status=status, error=error),
            ),
        )

    return fake_run


@pytest.fixture(autouse=True)
def _quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "_log_terminal", lambda *a, **k: None)


async def test_the_outcome_carries_the_frames_code_and_the_summarys_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "run", _ending("failed", "provider_error"))

    outcome = await main._run_and_log(_executor(Decimal("0.42")), _Publisher(), PARAMS, None)  # type: ignore[arg-type]  # noqa: SLF001

    assert outcome == CandidateOutcome("failed", "provider_error", Decimal("0.42"))


async def test_a_run_with_no_terminal_frame_settles_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def silent_run(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(main, "run", silent_run)

    outcome = await main._run_and_log(_executor(None), _Publisher(), PARAMS, None)  # type: ignore[arg-type]  # noqa: SLF001

    assert outcome == CandidateOutcome("failed", NO_TERMINAL_FRAME)


@pytest.fixture
def _process(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_run_process` with no world, no executor and no url4: a scripted success."""
    monkeypatch.setenv(job_env.TOPIC, TOPIC)
    monkeypatch.setenv(job_env.EXPRESSION, "'hi'")
    monkeypatch.setenv(job_env.RECLAIM_OWNER, "worker")
    monkeypatch.delenv(job_env.TRACEPARENT, raising=False)
    monkeypatch.setattr(main, "build_executor", lambda *a, **k: _executor(Decimal("1")))
    monkeypatch.setattr(main, "span_sink", lambda env: _Sink())
    monkeypatch.setattr(main, "run", _ending("succeeded"))


@pytest.mark.usefixtures("_process")
async def test_the_process_returns_the_outcome_when_its_frames_landed() -> None:
    outcome = await main._run_process(_Publisher())  # type: ignore[arg-type]  # noqa: SLF001

    assert outcome == CandidateOutcome("succeeded", None, Decimal("1"))


@pytest.mark.usefixtures("_process")
async def test_a_run_whose_frames_were_dropped_returns_no_outcome() -> None:
    """INVARIANT (spec R3): a tombstone won the claim race, so the run's frame never landed."""
    outcome = await main._run_process(_Publisher(dropped=True))  # type: ignore[arg-type]  # noqa: SLF001

    assert outcome is None


async def test_the_warm_child_reports_before_a_teardown_that_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHY: the run is over once `SETTLED` can be written; a failing teardown must not lose it."""
    import io
    import os

    from screamingface_engine import child_protocol

    async def failing_teardown() -> None:
        raise RuntimeError("the world would not close")

    async def warm_up(environ: Any) -> main.WarmState:
        return main.WarmState(publisher=_Publisher(), world_ok=True, world_aclose=failing_teardown)

    async def run_process(publisher: Any, shared: Any = None, report: Any = None) -> None:
        report(CandidateOutcome("succeeded", None, Decimal("2")))

    monkeypatch.setattr(main, "warm_up", warm_up)
    monkeypatch.setattr(main, "_run_process", run_process)
    read_fd, write_fd = os.pipe()
    environ = {child_protocol.CONTROL_FD_ENV: str(write_fd)}
    stdin = io.BytesIO(child_protocol.encode_spec({}, io_concurrency=1))

    with pytest.raises(RuntimeError, match="would not close"):
        await main._warm_process(environ, stdin)  # noqa: SLF001

    with os.fdopen(read_fd, "rb") as control:
        lines = control.read().splitlines(keepends=True)
    assert child_protocol.decode_settled(lines[-1]) == child_protocol.Settled(
        "succeeded", None, Decimal("2")
    )


@pytest.mark.usefixtures("_process")
async def test_the_outcome_is_reported_before_the_span_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHY: the relay's exit exports spans over the network; a kill during it must not cost the
    outcome of a run whose frames are already out."""
    events: list[str] = []

    class _Relay:
        def __init__(self, publisher: Any, *args: Any, **kwargs: Any) -> None:
            self._publisher = publisher

        def __enter__(self) -> Any:
            return self._publisher

        def __exit__(self, *exc: object) -> None:
            events.append("spans exported")

    monkeypatch.setattr(main, "SpanRelay", _Relay)

    await main._run_process(  # noqa: SLF001
        _Publisher(),  # type: ignore[arg-type]
        report=lambda outcome: events.append(f"reported {outcome.status}"),
    )

    assert events == ["reported succeeded", "spans exported"]
