"""The supervisor over a launcher (uniform executor PRD 03): what changes when a run is handed
to a warm child instead of spawned cold — the hard wall's start, a cancel inside the hand-off,
and a launch that fails with a named code.
"""

import asyncio
import json
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from screamingface_engine import job_env
from screamingface_engine.worker.loop import Worker
from screamingface_engine.worker.supervisor import CANCELLED
from screamingface_engine.worker.warm_pool import LaunchFailed
from url4.streaming.protocol import TerminatedData, TerminatedEvent, source_for

pytestmark = pytest.mark.asyncio


class _Msg:
    def __init__(self, topic: str, deadline_s: float = 60) -> None:
        self.data = json.dumps(
            {
                job_env.TOPIC: topic,
                job_env.EXPRESSION: "'hi'",
                job_env.JOB_DEADLINE_S: str(deadline_s),
                job_env.STREAM_GRACE_S: "0",
            }
        ).encode()
        self.metadata = SimpleNamespace(timestamp=datetime.now(UTC))
        self.headers = None
        self.acked = False

    async def ack(self) -> None:
        self.acked = True

    async def in_progress(self) -> None:
        pass


class _Publisher:
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def last_frame(self, topic: str) -> Any:
        return self.published[-1] if self.published else None

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        self.published.append(event)

    async def flush(self) -> None:
        pass


class _Proc:
    def __init__(self, exit_after_s: float | None = None) -> None:
        self._exit_after_s = exit_after_s
        self._done = asyncio.Event()
        self.returncode: int | None = None
        self.stdout = self.stderr = None
        self.terminated = 0

    async def wait(self) -> int:
        if self._exit_after_s is not None:
            try:
                await asyncio.wait_for(self._done.wait(), self._exit_after_s)
            except TimeoutError:
                self._finish(0)
        await self._done.wait()
        assert self.returncode is not None
        return self.returncode

    def _finish(self, code: int) -> None:
        if self.returncode is None:
            self.returncode = code
        self._done.set()

    def terminate(self) -> None:
        self.terminated += 1
        self._finish(-15)

    def kill(self) -> None:
        self._finish(-9)


class _Launcher:
    """Hands out `proc` after `delay_s` (or once `gate` is set), recording each hand-off."""

    def __init__(self, proc: Any, *, delay_s: float = 0.0, gate: asyncio.Event | None = None):
        self._proc, self._delay_s, self._gate = proc, delay_s, gate
        self.launched: list[tuple[dict[str, str], int]] = []

    async def launch(self, env: Any, *, io_budget: Any) -> Any:
        if self._gate is not None:
            await self._gate.wait()
        await asyncio.sleep(self._delay_s)
        self.launched.append((dict(env), io_budget()))
        if isinstance(self._proc, Exception):
            raise self._proc
        return self._proc


def _worker(publisher: _Publisher, launcher: _Launcher) -> Worker:
    worker = Worker(
        queue=SimpleNamespace(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        slots=1,
        drain_grace_s=0.1,
        io_capacity=4,
        memory_budget_bytes=1024**3,
        spawn=lambda *a, **k: None,  # type: ignore[arg-type,return-value]  # replaced below
        deadline_margin_s=0.05,
        kill_grace_s=0.05,
    )
    worker._supervisor._launcher = launcher  # noqa: SLF001 - the seam under test
    return worker


async def test_hard_wall_counts_from_ack() -> None:
    """WRM-14 / WC-D8: the wall (deadline 1 s + grace 0 + margin 0.05 s) starts when the child
    has the run — a slow hand-off does not eat into the run's own deadline."""
    publisher = _Publisher()
    proc = _Proc(exit_after_s=0.8)
    worker = _worker(publisher, _Launcher(proc, delay_s=0.4))
    started = time.monotonic()
    msg = _Msg("t-wall", deadline_s=1)
    await worker._supervisor.supervise(msg)  # type: ignore[arg-type]
    assert time.monotonic() - started > 1.05  # past a wall that would count from the claim
    assert proc.terminated == 0
    assert publisher.published == []  # a clean exit: the child's own frame stands
    assert msg.acked


async def test_cancel_between_spec_and_ack_stops_once() -> None:
    """WRM-17 / WC-D11: a cancel accepted while the run is being handed off (the control loop
    answers from `_starting`) is enacted the moment the child has it — one terminal frame."""
    publisher = _Publisher()
    proc = _Proc()
    gate = asyncio.Event()
    worker = _worker(publisher, _Launcher(proc, gate=gate))
    msg = _Msg("t-cancel")
    supervising = asyncio.ensure_future(worker._supervisor.supervise(msg))  # type: ignore[arg-type]
    await asyncio.sleep(0.01)
    assert "t-cancel" in worker._starting  # noqa: SLF001 - the control loop reads this set
    worker._cancelled.add("t-cancel")  # noqa: SLF001 - what the control loop does on a cancel
    gate.set()
    await asyncio.wait_for(supervising, timeout=2.0)
    assert proc.terminated == 1
    assert len(publisher.published) == 1
    assert publisher.published[0].data.error.code == CANCELLED
    assert msg.acked


async def test_a_refused_launch_names_its_code_in_the_terminal_frame() -> None:
    """WC-D9: `LaunchFailed.code` (here `unsupported_spec_version`) is the frame's code, and
    the message is acked — a redelivery would be refused the same way."""
    publisher = _Publisher()
    failure = LaunchFailed("unsupported_spec_version", "the child refused the run spec")
    worker = _worker(publisher, _Launcher(failure))
    msg = _Msg("t-refused")
    await worker._supervisor.supervise(msg)  # type: ignore[arg-type]
    assert [f.data.error.code for f in publisher.published] == ["unsupported_spec_version"]
    assert msg.acked


async def test_io_concurrency_computed_at_handoff() -> None:
    """WRM-18: the budget handed to the child is the fair share at hand-off time."""
    publisher = _Publisher()
    launcher = _Launcher(_Proc(exit_after_s=0.0))
    worker = _worker(publisher, launcher)
    worker._supervisor._children.update({_Proc(), _Proc(), _Proc()})  # type: ignore[arg-type]  # noqa: SLF001
    await worker._supervisor.supervise(_Msg("t-io"))  # type: ignore[arg-type]
    # 3 live siblings + this run's own reservation → 4 // 4 = 1.
    assert launcher.launched[0][1] == 1


async def test_an_unknown_spec_major_version_is_refused_with_its_code() -> None:
    """erd.md §2: a message of an unknown major version fails with `unsupported_spec_version`
    and is acked; no child is started."""
    publisher = _Publisher()
    launcher = _Launcher(_Proc(exit_after_s=0.0))
    worker = _worker(publisher, launcher)
    msg = _Msg("t-v3")
    body = json.loads(msg.data)
    body[job_env.SPEC_VERSION] = "3"
    msg.data = json.dumps(body).encode()
    await worker._supervisor.supervise(msg)  # type: ignore[arg-type]
    assert [f.data.error.code for f in publisher.published] == ["unsupported_spec_version"]
    assert msg.acked and launcher.launched == []


async def test_an_unknown_spec_major_version_whose_run_already_ended_gets_no_second_frame() -> None:
    """C6: a redelivery of a run a newer worker already finished must not get a second
    terminal frame from an older worker that cannot read its version — the terminal-frame
    check runs BEFORE the version refusal, so the message is acked away with no new
    publish at all."""
    publisher = _Publisher()
    publisher.published.append(
        TerminatedEvent(
            id="already-there",
            source=source_for("t-v3-done"),
            subject="t-v3-done",
            data=TerminatedData(status="succeeded"),
        )
    )
    launcher = _Launcher(_Proc(exit_after_s=0.0))
    worker = _worker(publisher, launcher)
    msg = _Msg("t-v3-done")
    body = json.loads(msg.data)
    body[job_env.SPEC_VERSION] = "3"
    msg.data = json.dumps(body).encode()
    await worker._supervisor.supervise(msg)  # type: ignore[arg-type]
    assert len(publisher.published) == 1  # unchanged: the pre-existing terminal frame only
    assert msg.acked and launcher.launched == []
