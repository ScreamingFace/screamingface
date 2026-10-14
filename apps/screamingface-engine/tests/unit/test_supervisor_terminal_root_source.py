"""Every terminal frame the worker writes ends the client's run (OME-1607).

A client ends a run only on a `Terminated` whose `source` is the run's ROOT node — the source of
the root `Spawned` frame the child's `lifecycle.run` publishes. The supervisor writes a terminal
frame of its own whenever the child did not (a crash, an OOM kill, the hard wall, a drain, a
cancel, a refused or failed launch, a run expired in the queue). Before OME-1607 those frames
carried the TRANSPORT source `/trace/<topic>`, so the SDK accepted them as a non-root frame and
kept waiting: a run whose child died stayed "waiting" in the notebook for ever.

These tests pin ONE root for one run: the supervisor's frame and the child's lifecycle use the
same node, `RUN_ROOT_NODE`. A run whose child never STARTED (expired in the queue, a failed
launch) has no root node at all — no root `Spawned` was ever published — so its frame keeps the
transport source; a client of such a run ends on the first terminal it reads.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from screamingface_engine import job_env
from screamingface_engine.runner import main as runner_main
from screamingface_engine.subjects import RUN_ROOT_NODE
from screamingface_engine.worker.loop import Worker
from screamingface_engine.worker.supervisor import CANCELLED, CHILD_EXITED
from screamingface_engine.worker.warm_pool import LaunchFailed
from url4.streaming.protocol import source_for

pytestmark = pytest.mark.asyncio


class _Msg:
    def __init__(self, topic: str, *, deadline_s: float = 60, queued_for_s: float = 0.0) -> None:
        self.data = json.dumps(
            {
                job_env.TOPIC: topic,
                job_env.EXPRESSION: "'hi'",
                job_env.JOB_DEADLINE_S: str(deadline_s),
                job_env.STREAM_GRACE_S: "0",
            }
        ).encode()
        self.metadata = SimpleNamespace(
            timestamp=datetime.now(UTC) - timedelta(seconds=queued_for_s), num_delivered=1
        )
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
    """A child that exits with `code` after `after_s`, or when signalled."""

    def __init__(self, code: int | None = None, after_s: float = 0.0) -> None:
        self._code, self._after_s = code, after_s
        self._done = asyncio.Event()
        self.returncode: int | None = None
        self.stdout = self.stderr = None

    async def wait(self) -> int:
        if self._code is not None:
            await asyncio.sleep(self._after_s)
            self._finish(self._code)
        await self._done.wait()
        assert self.returncode is not None
        return self.returncode

    def _finish(self, code: int) -> None:
        if self.returncode is None:
            self.returncode = code
        self._done.set()

    def terminate(self) -> None:
        self._finish(-15)

    def kill(self) -> None:
        self._finish(-9)


class _Launcher:
    def __init__(self, proc: Any, gate: asyncio.Event | None = None) -> None:
        self._proc, self._gate = proc, gate

    async def launch(self, env: Any, *, io_budget: Any) -> Any:
        if self._gate is not None:
            await self._gate.wait()
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


def _root(topic: str) -> str:
    return source_for(topic, RUN_ROOT_NODE)


async def test_a_crashed_child_s_terminal_frame_has_the_root_source() -> None:
    publisher = _Publisher()
    worker = _worker(publisher, _Launcher(_Proc(code=1)))
    msg = _Msg("t-crash")
    await worker._supervisor.supervise(msg)  # type: ignore[arg-type]
    [frame] = publisher.published
    assert frame.data.error.code == CHILD_EXITED
    assert frame.source == _root("t-crash")
    assert msg.acked


async def test_an_oom_killed_child_s_terminal_frame_has_the_root_source() -> None:
    publisher = _Publisher()
    worker = _worker(publisher, _Launcher(_Proc(code=137)))
    await worker._supervisor.supervise(_Msg("t-oom"))  # type: ignore[arg-type]
    [frame] = publisher.published
    assert frame.data.error.code == "oom_killed"
    assert frame.source == _root("t-oom")


async def test_a_run_past_its_hard_wall_ends_with_the_root_source() -> None:
    publisher = _Publisher()
    worker = _worker(publisher, _Launcher(_Proc()))  # never exits on its own
    await asyncio.wait_for(
        worker._supervisor.supervise(_Msg("t-wall", deadline_s=0.1)),  # type: ignore[arg-type]
        timeout=5,
    )
    [frame] = publisher.published
    assert frame.data.status == "timed_out"
    assert frame.source == _root("t-wall")


async def test_a_cancelled_run_ends_with_the_root_source() -> None:
    publisher = _Publisher()
    gate = asyncio.Event()
    worker = _worker(publisher, _Launcher(_Proc(), gate=gate))
    supervising = asyncio.ensure_future(worker._supervisor.supervise(_Msg("t-cancel")))  # type: ignore[arg-type]
    await asyncio.sleep(0.01)
    worker._cancelled.add("t-cancel")  # noqa: SLF001 - what the control loop does on a cancel
    gate.set()
    await asyncio.wait_for(supervising, timeout=2)
    [frame] = publisher.published
    assert frame.data.error.code == CANCELLED
    assert frame.source == _root("t-cancel")


async def test_a_failed_launch_keeps_the_transport_source() -> None:
    """The child never started: there is no root node to name."""
    publisher = _Publisher()
    failure = LaunchFailed("spawn_failed", "the child never became ready")
    worker = _worker(publisher, _Launcher(failure))
    await worker._supervisor.supervise(_Msg("t-launch"))  # type: ignore[arg-type]
    [frame] = publisher.published
    assert frame.source == source_for("t-launch")


async def test_a_run_expired_in_the_queue_keeps_the_transport_source() -> None:
    """Never claimed into a child: there is no root node to name."""
    publisher = _Publisher()
    worker = _worker(publisher, _Launcher(_Proc(code=0)))
    await worker._supervisor.supervise(_Msg("t-expired", deadline_s=1, queued_for_s=3600))  # type: ignore[arg-type]
    [frame] = publisher.published
    assert frame.data.error.code == "queue_expired"
    assert frame.source == source_for("t-expired")


async def test_the_child_s_lifecycle_runs_under_the_same_root_node(monkeypatch) -> None:
    """The other half of "one run, one root": the child's `lifecycle.run` publishes its root
    `Spawned` under `RUN_ROOT_NODE` — the node the supervisor names. Passed explicitly, so a
    change of `lifecycle.run`'s default can never split the two."""
    seen: dict[str, Any] = {}

    async def fake_run(*args: Any, **kwargs: Any) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(runner_main, "run", fake_run)
    monkeypatch.setattr(runner_main, "_log_terminal", lambda *a, **k: None)
    params = SimpleNamespace(topic="t-child", url4="'hi'", deadline_s=1.0, client_version=None)
    await runner_main._run_and_log(SimpleNamespace(), SimpleNamespace(), params, None)  # type: ignore[arg-type]  # noqa: SLF001
    assert seen["node"] == RUN_ROOT_NODE
