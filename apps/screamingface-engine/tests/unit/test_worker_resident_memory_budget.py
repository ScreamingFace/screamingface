"""A run is held to a RESIDENT memory budget, not only to an address-space cap (OME-1607).

`RLIMIT_AS` (the exec wrapper) bounds VIRTUAL address space. Native libraries reserve address
space they never touch — pyarrow's mimalloc pool reserves 1 GiB on its first allocation, OpenBLAS
a buffer per node CPU — so on aks-prod a judged run died of `MemoryError` with only 459 MiB
resident. The pod's cgroup limit, the number the chart sizes per slot, counts RESIDENT memory. The
worker therefore watches each run's resident memory (its whole process tree) and stops a run that
goes past `worker_resident_budget_bytes` with a named, permanent failure, before the pod's cgroup
OOM-kills it or a co-tenant. The address-space cap stays as the backstop for a runaway allocation.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from screamingface_engine import job_env
from screamingface_engine.config import Settings
from screamingface_engine.subjects import RUN_ROOT_NODE
from screamingface_engine.worker.loop import Worker
from screamingface_engine.worker.memory_watch import process_tree_rss_bytes
from screamingface_engine.worker.supervisor import CHILD_EXITED, MEMORY_BUDGET_EXCEEDED
from url4.streaming.protocol import source_for

pytestmark = pytest.mark.asyncio


# --- reading a run's resident memory from /proc -------------------------------------------------


def _fake_proc(root: Path, pid: int, ppid: int, rss_kib: int, comm: str = "python3") -> None:
    entry = root / str(pid)
    entry.mkdir()
    # `comm` may hold spaces and parentheses; the parser must split at the LAST ')'.
    (entry / "stat").write_text(f"{pid} ({comm}) S {ppid} {pid} {pid} 0 -1 4194560 0 0\n")
    (entry / "status").write_text(
        f"Name:\t{comm}\nPid:\t{pid}\nPPid:\t{ppid}\nVmRSS:\t{rss_kib} kB\n"
    )


async def test_a_run_s_resident_memory_is_its_whole_process_tree(tmp_path: Path) -> None:
    _fake_proc(tmp_path, 1, 0, 50_000)  # the worker itself
    _fake_proc(tmp_path, 10, 1, 300_000)  # the run's child
    _fake_proc(tmp_path, 11, 10, 20_000, comm="tool (sandbox) x")  # a process the run started
    _fake_proc(tmp_path, 12, 11, 1_000)  # ...and its child
    _fake_proc(tmp_path, 20, 1, 400_000)  # a sibling run: not counted
    assert process_tree_rss_bytes(10, proc=tmp_path) == (300_000 + 20_000 + 1_000) * 1024


async def test_an_exited_run_or_a_missing_proc_reads_as_unknown(tmp_path: Path) -> None:
    _fake_proc(tmp_path, 1, 0, 50_000)
    assert process_tree_rss_bytes(10, proc=tmp_path) is None
    assert process_tree_rss_bytes(10, proc=tmp_path / "absent") is None


# --- the supervisor stops a run over its resident budget ------------------------------------------


class _Msg:
    def __init__(self, topic: str) -> None:
        self.data = json.dumps(
            {
                job_env.TOPIC: topic,
                job_env.EXPRESSION: "'hi'",
                job_env.JOB_DEADLINE_S: "60",
                job_env.STREAM_GRACE_S: "0",
            }
        ).encode()
        self.metadata = SimpleNamespace(timestamp=datetime.now(UTC), num_delivered=1)
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
        return None

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        self.published.append(event)

    async def flush(self) -> None:
        pass


class _Proc:
    """A child with a pid; exits with `code` after `after_s`, or on a signal."""

    def __init__(self, pid: int, code: int | None = None, after_s: float = 0.0, stderr: Any = None):
        self.pid = pid
        self._code, self._after_s = code, after_s
        self._done = asyncio.Event()
        self.returncode: int | None = None
        self.stdout = None
        self.stderr = stderr
        self.terminated = 0

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
        self.terminated += 1
        self._finish(-15)

    def kill(self) -> None:
        self._finish(-9)


class _Launcher:
    def __init__(self, procs: dict[str, _Proc]) -> None:
        self._procs = procs

    async def launch(self, env: Any, *, io_budget: Any) -> Any:
        return self._procs[env[job_env.TOPIC]]


def _worker(publisher: _Publisher, procs: dict[str, _Proc], *, budget: int | None, reads: Any):
    worker = Worker(
        queue=SimpleNamespace(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        slots=2,
        drain_grace_s=0.1,
        io_capacity=4,
        memory_budget_bytes=4 * 1024**3,
        resident_budget_bytes=budget,
        spawn=lambda *a, **k: None,  # type: ignore[arg-type,return-value]  # replaced below
        deadline_margin_s=0.05,
        kill_grace_s=0.05,
    )
    supervisor = worker._supervisor
    supervisor._launcher = _Launcher(procs)  # noqa: SLF001 - the seams under test
    supervisor._memory.read = reads  # noqa: SLF001
    supervisor._memory.poll_s = 0.01  # noqa: SLF001
    return worker


async def test_a_run_over_its_resident_budget_is_stopped_with_a_named_permanent_failure() -> None:
    publisher = _Publisher()
    proc = _Proc(pid=10)  # never exits on its own
    readings = iter([50, 80, 150])
    worker = _worker(publisher, {"t-big": proc}, budget=100, reads=lambda pid: next(readings, 150))
    msg = _Msg("t-big")
    await asyncio.wait_for(worker._supervisor.supervise(msg), timeout=5)  # type: ignore[arg-type]
    [frame] = publisher.published
    assert frame.data.status == "failed"
    assert frame.data.error.code == MEMORY_BUDGET_EXCEEDED
    assert frame.data.error.permanent is True
    # The message tells the operator what was measured, the limit, and which value raises it.
    assert "150" in frame.data.error.message and "100" in frame.data.error.message
    assert "runnerPool.perRunCharge.memoryLimitMi" in frame.data.error.message
    assert frame.source == source_for("t-big", RUN_ROOT_NODE)
    assert proc.terminated == 1
    assert msg.acked  # not redelivered: the same run would fail the same way


async def test_only_the_run_over_budget_is_stopped_its_sibling_finishes() -> None:
    publisher = _Publisher()
    big, small = _Proc(pid=10), _Proc(pid=20, code=0, after_s=0.1)
    rss = {10: 500, 20: 10}
    worker = _worker(publisher, {"t-big": big, "t-small": small}, budget=100, reads=rss.get)
    big_msg, small_msg = _Msg("t-big"), _Msg("t-small")
    await asyncio.wait_for(
        asyncio.gather(
            worker._supervisor.supervise(big_msg),  # type: ignore[arg-type]
            worker._supervisor.supervise(small_msg),  # type: ignore[arg-type]
        ),
        timeout=5,
    )
    assert [f.data.error.code for f in publisher.published] == [MEMORY_BUDGET_EXCEEDED]
    assert small.terminated == 0 and small.returncode == 0
    assert big_msg.acked and small_msg.acked


async def test_a_run_within_its_budget_is_left_alone() -> None:
    publisher = _Publisher()
    proc = _Proc(pid=10, code=0, after_s=0.1)
    worker = _worker(publisher, {"t-ok": proc}, budget=100, reads=lambda pid: 99)
    await asyncio.wait_for(worker._supervisor.supervise(_Msg("t-ok")), timeout=5)  # type: ignore[arg-type]
    assert publisher.published == [] and proc.terminated == 0


async def test_an_unreadable_reading_never_stops_a_run() -> None:
    """No `/proc` (macOS, a sandbox) or a vanished pid reads as unknown — never as over budget."""
    publisher = _Publisher()
    proc = _Proc(pid=10, code=0, after_s=0.1)
    worker = _worker(publisher, {"t-unknown": proc}, budget=100, reads=lambda pid: None)
    await asyncio.wait_for(worker._supervisor.supervise(_Msg("t-unknown")), timeout=5)  # type: ignore[arg-type]
    assert publisher.published == [] and proc.terminated == 0


async def test_without_a_resident_budget_nothing_is_watched() -> None:
    publisher = _Publisher()
    proc = _Proc(pid=10, code=0, after_s=0.05)

    def unexpected(pid: int) -> int:
        raise AssertionError("no budget configured: the run's memory must not be read")

    worker = _worker(publisher, {"t-off": proc}, budget=None, reads=unexpected)
    await asyncio.wait_for(worker._supervisor.supervise(_Msg("t-off")), timeout=5)  # type: ignore[arg-type]
    assert publisher.published == []


async def test_an_address_space_memory_error_is_named_in_the_child_exited_message() -> None:
    """The `RLIMIT_AS` backstop: a child that dies of `MemoryError` keeps the `child_exited`
    code (Linux CI pins it), and its message now says what happened and which value to raise."""
    stderr = asyncio.StreamReader()
    stderr.feed_data(b"Traceback (most recent call last):\n  ...\nMemoryError\n")
    stderr.feed_eof()
    publisher = _Publisher()
    proc = _Proc(pid=10, code=1, after_s=0.05, stderr=stderr)
    worker = _worker(publisher, {"t-as": proc}, budget=None, reads=lambda pid: None)
    await asyncio.wait_for(worker._supervisor.supervise(_Msg("t-as")), timeout=5)  # type: ignore[arg-type]
    [frame] = publisher.published
    assert frame.data.error.code == CHILD_EXITED
    assert "MemoryError" in frame.data.error.message
    assert "URL4_CLOUD_WORKER_MEMORY_BUDGET_BYTES" in frame.data.error.message


async def test_the_resident_budget_is_read_from_the_environment(monkeypatch) -> None:
    monkeypatch.delenv("URL4_CLOUD_WORKER_RESIDENT_BUDGET_BYTES", raising=False)
    assert Settings().worker_resident_budget_bytes is None
    monkeypatch.setenv("URL4_CLOUD_WORKER_RESIDENT_BUDGET_BYTES", str(1024**3))
    assert Settings().worker_resident_budget_bytes == 1024**3
