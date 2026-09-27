"""The warm child pool (uniform executor PRD 03): hand-off, retry, warming, drain.

A scripted fake child speaks the protocol on an in-memory control pipe, so every state-table
edge (erd.md §4) is driven without processes or sleeps.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import pytest

from screamingface_engine import child_protocol as cp
from screamingface_engine import job_env
from screamingface_engine.worker.warm_pool import (
    SPAWN_FAILED,
    LaunchFailed,
    WarmChildPool,
    WarmHandle,
    deploy_env,
)

pytestmark = pytest.mark.asyncio

RUN_ENV = {job_env.TOPIC: "t-1", job_env.EXPRESSION: "'hi'", "X_SECRET_IDENTITY": "a@x"}


class _Stdin:
    def __init__(self, child: "_FakeChild") -> None:
        self._child = child
        self.written = b""
        self.closed = False

    def write(self, data: bytes) -> None:
        if self._child.returncode is not None:
            raise BrokenPipeError()
        self.written += data

    async def drain(self) -> None:
        self._child.on_spec(self.written)

    def close(self) -> None:
        self.closed = True


@dataclass
class _FakeChild:
    """`answer` is what the child does with its spec: "ack", "refuse", or "die"."""

    pid: int
    answer: str = "ack"
    ready: bytes | None = None
    returncode: int | None = None
    control: asyncio.StreamReader = field(default_factory=asyncio.StreamReader)
    terminated: bool = False
    killed: bool = False
    stdout: Any = None
    stderr: Any = None

    def __post_init__(self) -> None:
        self.stdin = _Stdin(self)
        self._exited = asyncio.Event()
        if self.ready is None:
            self.ready = cp.encode_ready(pid=self.pid, world_ok=True)
        if self.ready:
            self.control.feed_data(self.ready)

    def on_spec(self, line: bytes) -> None:
        if self.answer == "ack":
            self.control.feed_data(cp.ACK)
        elif self.answer == "refuse":
            self.control.feed_data(cp.encode_refused("unsupported_spec_version"))
            self.exit(2)
        else:
            self.exit(1)

    def exit(self, code: int) -> None:
        self.returncode = code
        self.control.feed_eof()
        self._exited.set()

    async def wait(self) -> int:
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.exit(-15)

    def kill(self) -> None:
        self.killed = True
        self.exit(-9)


class _Spawner:
    """Hands out scripted children in order; counts spawns."""

    def __init__(self, *children: _FakeChild, fail: int = 0) -> None:
        self._children = list(children)
        self._fail = fail
        self.spawned: list[_FakeChild] = []

    async def __call__(self) -> WarmHandle:
        if self._fail:
            self._fail -= 1
            raise OSError("exec failed")
        child = self._children.pop(0)
        self.spawned.append(child)
        return WarmHandle(proc=child, control=child.control)  # type: ignore[arg-type]


class _Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        await asyncio.sleep(0)


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


async def test_a_started_pool_warms_its_children() -> None:
    """WC-H1."""
    spawner = _Spawner(_FakeChild(1), _FakeChild(2))
    pool = WarmChildPool(spawn_warm=spawner, size=2)
    pool.start()
    await _settle()
    assert pool.idle_count == 2
    await pool.drain()


async def test_supervisor_hands_off_to_warm_child_without_exec() -> None:
    """WRM-5 / WC-H2: the claim takes the WARM child; no process is started for this run."""
    warm = _FakeChild(1)
    spawner = _Spawner(warm, _FakeChild(2))
    pool = WarmChildPool(spawn_warm=spawner, size=1)
    pool.start()
    await _settle()
    assert len(spawner.spawned) == 1
    proc = await pool.launch(RUN_ENV, io_budget=lambda: 3)
    assert proc is warm
    spec = cp.decode_spec(warm.stdin.written)
    assert spec.env == RUN_ENV and spec.io_concurrency == 3
    await _settle()
    assert len(spawner.spawned) == 2  # the replacement, warmed AFTER the hand-off
    await pool.drain()


async def test_child_never_reused_after_assignment() -> None:
    """WRM-6 / WC-H3: every run gets a fresh process."""
    spawner = _Spawner(_FakeChild(1), _FakeChild(2), _FakeChild(3))
    pool = WarmChildPool(spawn_warm=spawner, size=1)
    pool.start()
    await _settle()
    first = await pool.launch(RUN_ENV, io_budget=lambda: 1)
    await _settle()
    second = await pool.launch(RUN_ENV, io_budget=lambda: 1)
    assert first is not second
    await pool.drain()


async def test_death_before_ack_retries_once_then_spawn_failed() -> None:
    """WRM-7 / WC-D2: the first death is retried on a new child; the second is final."""
    ok = WarmChildPool(spawn_warm=_Spawner(_FakeChild(1, "die"), _FakeChild(2)), size=0)
    assert (await ok.launch(RUN_ENV, io_budget=lambda: 1)).pid == 2  # type: ignore[attr-defined]

    doomed = WarmChildPool(spawn_warm=_Spawner(_FakeChild(1, "die"), _FakeChild(2, "die")), size=0)
    with pytest.raises(LaunchFailed) as exc:
        await doomed.launch(RUN_ENV, io_budget=lambda: 1)
    assert exc.value.code == SPAWN_FAILED


async def test_a_refused_spec_is_not_retried_and_names_the_code() -> None:
    """WC-D9: a new child would refuse the same spec; the frame names the reason."""
    spawner = _Spawner(_FakeChild(1, "refuse"), _FakeChild(2))
    pool = WarmChildPool(spawn_warm=spawner, size=0)
    with pytest.raises(LaunchFailed) as exc:
        await pool.launch(RUN_ENV, io_budget=lambda: 1)
    assert exc.value.code == "unsupported_spec_version"
    assert len(spawner.spawned) == 1


async def test_zero_warm_children_uses_same_protocol() -> None:
    """WRM-16 / WC-D10: spawn on claim → READY → spec → ACK."""
    child = _FakeChild(1)
    pool = WarmChildPool(spawn_warm=_Spawner(child), size=0)
    pool.start()  # a size-0 pool warms nothing
    assert pool.idle_count == 0
    assert await pool.launch(RUN_ENV, io_budget=lambda: 2) is child
    assert cp.decode_spec(child.stdin.written).io_concurrency == 2


async def test_ready_timeout_kills_child() -> None:
    """WRM-12 / WC-D6."""
    silent = _FakeChild(1, ready=b"")
    pool = WarmChildPool(spawn_warm=_Spawner(silent), size=0, ready_timeout_s=0.01)
    with pytest.raises(LaunchFailed) as exc:
        await pool.launch(RUN_ENV, io_budget=lambda: 1)
    assert exc.value.code == SPAWN_FAILED
    assert silent.killed


async def test_idle_death_counts_failure_and_replaces() -> None:
    """WRM-10 / WC-D4."""

    class _Metrics:
        def __init__(self) -> None:
            self.failures = 0
            self.warm: list[float] = []
            self.warm_spawn_failures = self
            self.warm_children = self
            self.handoff_latency_s = self.child_boot_s = self

        def inc(self) -> None:
            self.failures += 1

        def set(self, value: float) -> None:
            self.warm.append(value)

        def observe(self, value: float) -> None:
            pass

    metrics = _Metrics()
    first = _FakeChild(1)
    spawner = _Spawner(first, _FakeChild(2))
    pool = WarmChildPool(spawn_warm=spawner, size=1, sleep=_Sleeps(), metrics=metrics)  # type: ignore[arg-type]
    pool.start()
    await _settle()
    first.exit(1)
    await _settle()
    assert metrics.failures == 1
    assert pool.idle_count == 1 and len(spawner.spawned) == 2
    await pool.drain()


async def test_warm_spawn_backoff_1_2_4_to_30s() -> None:
    """WRM-11 / WC-D5: consecutive failures back off 1, 2, 4 … capped at 30 s."""
    sleeps = _Sleeps()
    spawner = _Spawner(_FakeChild(1), fail=7)
    pool = WarmChildPool(spawn_warm=spawner, size=1, sleep=sleeps)
    pool.start()
    for _ in range(500):  # until the eighth attempt warmed the child (scheduling-independent)
        if pool.idle_count == 1:
            break
        await asyncio.sleep(0)
    assert sleeps.delays == [1, 2, 4, 8, 16, 30, 30]
    assert pool.idle_count == 1
    await pool.drain()


async def test_drain_kills_idle_warm_children_first() -> None:
    """WRM-13 / WC-D7: idle children are terminated at once, and no new one is warmed."""
    children = [_FakeChild(1), _FakeChild(2), _FakeChild(3)]
    spawner = _Spawner(*children)
    pool = WarmChildPool(spawn_warm=spawner, size=2)
    pool.start()
    await _settle()
    await pool.drain()
    await _settle()
    assert [c.terminated for c in children[:2]] == [True, True]
    assert len(spawner.spawned) == 2
    assert pool.idle_count == 0


async def test_run_spec_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    """WRM-19: the spec carries the caller's identity; it goes over the pipe, never to a log."""
    caplog.set_level(logging.DEBUG)
    pool = WarmChildPool(spawn_warm=_Spawner(_FakeChild(1, "die"), _FakeChild(2, "die")), size=0)
    with pytest.raises(LaunchFailed):
        await pool.launch(RUN_ENV, io_budget=lambda: 1)
    assert "a@x" not in caplog.text and "X_SECRET_IDENTITY" not in caplog.text


async def test_a_warm_child_starts_without_per_run_keys() -> None:
    """The worker's environment reaches a warm child minus every per-run key."""
    env = deploy_env(
        {job_env.NATS_URL: "nats://x", job_env.TOPIC: "stray", job_env.IO_CONCURRENCY: "9"}
    )
    assert env == {job_env.NATS_URL: "nats://x"}


async def test_cancel_during_the_ack_wait_kills_the_child() -> None:
    """Review finding: a supervisor cancelled after the spec write must not leave a child that
    could ACK and run unsupervised (and then run again on redelivery)."""

    class _Silent(_FakeChild):
        def on_spec(self, line: bytes) -> None:
            pass  # never ACKs

    child = _Silent(1)
    pool = WarmChildPool(spawn_warm=_Spawner(child), size=0, ack_timeout_s=30)
    launching = asyncio.ensure_future(pool.launch(RUN_ENV, io_budget=lambda: 1))
    await _settle()
    assert child.stdin.written  # the spec is out
    launching.cancel()
    with pytest.raises(asyncio.CancelledError):
        await launching
    assert child.killed


async def test_an_ack_timeout_is_final() -> None:
    """Review finding: a slow child may have ACKed and started just before the kill, so an ACK
    timeout is NOT retried on a second child (erd.md §4 has no timeout row)."""

    class _Silent(_FakeChild):
        def on_spec(self, line: bytes) -> None:
            pass

    spawner = _Spawner(_Silent(1), _FakeChild(2))
    pool = WarmChildPool(spawn_warm=spawner, size=0, ack_timeout_s=0.01)
    with pytest.raises(LaunchFailed) as exc:
        await pool.launch(RUN_ENV, io_budget=lambda: 1)
    assert exc.value.code == SPAWN_FAILED
    assert len(spawner.spawned) == 1


async def test_an_oversized_spec_is_refused_before_any_child_sees_it() -> None:
    child = _FakeChild(1)
    pool = WarmChildPool(spawn_warm=_Spawner(child), size=0)
    huge = {**RUN_ENV, "BIG": "x" * cp.MAX_SPEC_BYTES}
    with pytest.raises(LaunchFailed) as exc:
        await pool.launch(huge, io_budget=lambda: 1)
    assert exc.value.code == "spec_too_large"
    assert child.stdin.written == b""


async def test_the_pool_refills_after_a_claim_spawn_completes() -> None:
    """Review finding: an on-demand spawn counts in `_spawning`; when it ends, the replenisher
    must look again instead of sleeping until the next claim."""
    spawner = _Spawner(_FakeChild(1), _FakeChild(2), _FakeChild(3))
    pool = WarmChildPool(spawn_warm=spawner, size=1)
    launching = asyncio.ensure_future(pool.launch(RUN_ENV, io_budget=lambda: 1))
    pool.start()
    await launching
    await _settle()
    assert pool.idle_count == 1
    await pool.drain()


async def test_a_spawn_in_flight_at_drain_is_killed() -> None:
    """erd.md §4: spawning × drain → kill."""
    slow = _FakeChild(1, ready=b"")  # never READY
    pool = WarmChildPool(spawn_warm=_Spawner(slow), size=1, ready_timeout_s=30)
    pool.start()
    await _settle()
    await pool.drain()
    assert slow.killed


async def test_missing_warm_children_are_started_in_parallel() -> None:
    """kind B4 finding: a pool of 3 refills all three at once, not one boot after another."""
    started: list[int] = []
    gate = asyncio.Event()

    class _SlowSpawner(_Spawner):
        async def __call__(self) -> WarmHandle:
            started.append(len(started))
            await gate.wait()
            return await super().__call__()

    pool = WarmChildPool(
        spawn_warm=_SlowSpawner(_FakeChild(1), _FakeChild(2), _FakeChild(3)), size=3
    )
    pool.start()
    await _settle()
    assert len(started) == 3  # all three are booting before any is READY
    gate.set()
    await _settle()
    assert pool.idle_count == 3
    await pool.drain()


async def test_idle_children_plus_busy_runs_never_exceed_the_slots() -> None:
    """kind K8 finding: a pod sized for `slots` child processes keeps no idle child in a slot a
    run holds — two of two slots busy means no warm child at all, and a freed slot refills."""
    busy = 2
    spawner = _Spawner(_FakeChild(1), _FakeChild(2), _FakeChild(3))
    pool = WarmChildPool(spawn_warm=spawner, size=2, slots=2, busy=lambda: busy)
    pool.start()
    await _settle()
    assert pool.idle_count == 0
    assert spawner.spawned == []

    busy = 1
    pool.wake()
    await _settle()
    assert pool.idle_count == 1

    busy = 0
    pool.wake()
    await _settle()
    assert pool.idle_count == 2
    await pool.drain()


async def test_a_claim_takes_a_warm_spawn_in_flight_instead_of_spawning_another() -> None:
    """kind K8 finding: at pod boot, a claim waits for the warm child already booting; it does
    not boot a second child beside it (that doubled the pod's children and OOM-killed it)."""
    gate = asyncio.Event()

    class _GatedSpawner(_Spawner):
        async def __call__(self) -> WarmHandle:
            await gate.wait()
            return await super().__call__()

    spawner = _GatedSpawner(_FakeChild(1), _FakeChild(2))
    busy = 0
    pool = WarmChildPool(spawn_warm=spawner, size=1, slots=1, busy=lambda: busy)
    pool.start()
    await _settle()  # the warm spawn is in flight, blocked on the gate
    busy = 1  # the worker counts the claim as soon as it takes the message
    launch = asyncio.ensure_future(pool.launch(RUN_ENV, io_budget=lambda: 1))
    await _settle()
    gate.set()
    proc = await asyncio.wait_for(launch, 5)

    assert proc.pid == 1  # type: ignore[attr-defined]
    assert len(spawner.spawned) == 1
    await pool.drain()


async def test_a_claim_spawns_its_own_child_when_the_warm_spawn_fails() -> None:
    gate = asyncio.Event()

    class _GatedSpawner(_Spawner):
        async def __call__(self) -> WarmHandle:
            await gate.wait()
            return await super().__call__()

    sleeps = _Sleeps()
    spawner = _GatedSpawner(_FakeChild(1, "die"), _FakeChild(2))
    pool = WarmChildPool(spawn_warm=spawner, size=1, slots=1, sleep=sleeps)
    pool.start()
    await _settle()
    launch = asyncio.ensure_future(pool.launch(RUN_ENV, io_budget=lambda: 1))
    await _settle()
    gate.set()
    proc = await asyncio.wait_for(launch, 5)

    assert proc.pid == 2  # type: ignore[attr-defined]
    await pool.drain()


async def test_two_claims_take_one_warm_spawn_and_one_own_spawn() -> None:
    """The `_warming > _waiting` count: one warm spawn in flight serves ONE waiting claim; the
    second claim spawns its own child instead of waiting for a spawn nobody will make."""
    gate = asyncio.Event()

    class _GatedSpawner(_Spawner):
        async def __call__(self) -> WarmHandle:
            await gate.wait()
            return await super().__call__()

    busy = 0
    spawner = _GatedSpawner(_FakeChild(1), _FakeChild(2))
    pool = WarmChildPool(spawn_warm=spawner, size=1, slots=2, busy=lambda: busy)
    pool.start()
    await _settle()  # one warm spawn in flight
    busy = 2
    first = asyncio.ensure_future(pool.launch(RUN_ENV, io_budget=lambda: 1))
    second = asyncio.ensure_future(pool.launch(RUN_ENV, io_budget=lambda: 1))
    await _settle()
    gate.set()
    procs = await asyncio.wait_for(asyncio.gather(first, second), 5)

    assert sorted(proc.pid for proc in procs) == [1, 2]  # type: ignore[attr-defined]
    assert len(spawner.spawned) == 2
    await pool.drain()
