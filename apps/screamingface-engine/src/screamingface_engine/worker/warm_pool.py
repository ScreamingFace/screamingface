"""The warm child pool (uniform executor PRD 03, erd.md §3–§4, contracts.md C5).

Each worker keeps up to ``size`` child processes that already did their per-process work
(Python start-up, the imports, the broker connection, the world config) and wait for a run on
stdin. On a claim the worker hands the run to one of them over a pipe; the child runs ONE run
and exits, and the pool starts a replacement. With ``size=0`` a child is spawned on the claim
and goes through the same READY → spec → ACK protocol.

WHY one run per child, never reused: the process is the isolation unit — its own `RLIMIT_AS`,
a kill that always works, an environment that belongs to one caller (OME-1089). A child that
received a spec is never returned to the pool (erd.md §4 invariant).

State table (erd.md §4): spawning → warm (READY) → assigned (spec written) → running (ACK) →
exited. Any exit before ACK is safe to retry: no run code has run yet (WC-D2).
"""

import asyncio
import contextlib
import logging
import os
import sys
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from screamingface_engine import child_protocol, job_env
from screamingface_engine.client_provenance import CLIENT_VERSION_ENV

logger = logging.getLogger(__name__)

DEFAULT_READY_TIMEOUT_S = 60.0
DEFAULT_ACK_TIMEOUT_S = 10.0
BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 30.0
SPAWN_FAILED = "spawn_failed"
"""The terminal code when no child could take the run (erd.md §4, WC-D2)."""
_READ_LIMIT = 64 * 1024


class LaunchFailed(Exception):
    """No child could take the run. `code` names the terminal frame the worker publishes."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _Process(Protocol):
    """The slice of an asyncio subprocess the pool uses."""

    pid: int
    stdin: Any
    stdout: Any
    stderr: Any

    @property
    def returncode(self) -> int | None: ...

    async def wait(self) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


@dataclass
class WarmHandle:
    """One spawned child: the process and the reader of its control pipe."""

    proc: _Process
    control: asyncio.StreamReader
    spawned_at: float = field(default_factory=time.monotonic)


SpawnWarm = Callable[[], Awaitable[WarmHandle]]


class _PoolMetrics(Protocol):
    """The worker metrics the pool reports into (see `worker.metrics`)."""

    warm_children: Any
    warm_spawn_failures: Any
    handoff_latency_s: Any
    child_boot_s: Any


class _Retry(Exception):
    """The child died between the spec write and the ACK: a new child may take the run."""


def deploy_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The environment a warm child starts with: the worker's own, minus anything per-run.

    WHY strip: a warm child starts before its run is known, and every per-run value arrives in
    the RUN_SPEC. A per-run key left in the worker's environment (an operator's stray export)
    would otherwise reach a run whose spec does not override it.
    """
    per_run = job_env.WRITTEN_BY_APP | {job_env.IO_CONCURRENCY, CLIENT_VERSION_ENV}
    return {key: value for key, value in environ.items() if key not in per_run}


def process_spawner(
    spawn: Callable[..., Awaitable[Any]],
    *,
    memory_budget_bytes: int,
    environ: Mapping[str, str],
    worker_reclaims: bool = False,
) -> SpawnWarm:
    """The real `SpawnWarm`: the exec wrapper (own `RLIMIT_AS`) → `run --warm`, with a control
    pipe whose write end the child inherits and names in `CONTROL_FD_ENV`."""
    base = deploy_env(environ)
    if worker_reclaims:
        # The pool's worker purges each run's subject after its grace, so the child exits at
        # its terminal frame and frees its slot at once (RECLAIM_OWNER).
        base[job_env.RECLAIM_OWNER] = "worker"

    async def _spawn_warm() -> WarmHandle:
        read_fd, write_fd = os.pipe()
        try:
            proc = await spawn(
                sys.executable,
                "-m",
                "screamingface_engine.worker.exec_wrapper",
                str(memory_budget_bytes),
                "--warm",
                env={**base, child_protocol.CONTROL_FD_ENV: str(write_fd)},
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                pass_fds=(write_fd,),
            )
        except BaseException:
            os.close(read_fd)
            raise
        finally:
            # The child holds its own copy; ours must go, or the pipe never reports EOF when
            # the child dies.
            os.close(write_fd)
        reader = asyncio.StreamReader(limit=_READ_LIMIT)
        loop = asyncio.get_running_loop()
        await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), os.fdopen(read_fd, "rb", buffering=0)
        )
        return WarmHandle(proc=proc, control=reader)

    return _spawn_warm


@dataclass
class _Idle:
    handle: WarmHandle
    watcher: asyncio.Task[None]
    forwarder: asyncio.Task[None]


class WarmChildPool:
    """Keeps up to `size` warm children and hands each claimed run to exactly one of them."""

    def __init__(
        self,
        *,
        spawn_warm: SpawnWarm,
        size: int,
        ready_timeout_s: float = DEFAULT_READY_TIMEOUT_S,
        ack_timeout_s: float = DEFAULT_ACK_TIMEOUT_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        metrics: _PoolMetrics | None = None,
    ) -> None:
        if size < 0:
            raise ValueError(f"warm pool size must be >= 0, got {size}")
        self._spawn_warm = spawn_warm
        self._size = size
        self._ready_timeout_s = ready_timeout_s
        self._ack_timeout_s = ack_timeout_s
        self._sleep = sleep
        self._metrics = metrics
        self._idle: list[_Idle] = []
        self._spawning = 0
        self._consecutive_failures = 0
        self._draining = False
        self._wake = asyncio.Event()
        self._replenisher: asyncio.Task[None] | None = None

    # --- lifecycle ---------------------------------------------------------------------------

    def start(self) -> None:
        """Start keeping `size` children warm. Idempotent."""
        if self._replenisher is None and self._size > 0:
            self._replenisher = asyncio.create_task(self._replenish_forever())

    async def drain(self) -> None:
        """Stop warming and terminate every IDLE child at once (WC-D7). Running children are
        the supervisor's; they follow the worker's drain rules.

        A spawn the replenisher has in flight is cancelled with it, and `_spawn_ready` kills
        that child on the way out (erd.md §4: spawning × drain → kill).
        """
        self._draining = True
        self._wake.set()
        if self._replenisher is not None:
            self._replenisher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._replenisher
        idle, self._idle = self._idle, []
        for entry in idle:
            entry.watcher.cancel()
            entry.forwarder.cancel()
            _signal(entry.handle.proc, terminate=True)
        await asyncio.gather(*(_reap_bounded(entry.handle.proc) for entry in idle))
        self._report()

    @property
    def idle_count(self) -> int:
        return len(self._idle)

    # --- the hand-off ------------------------------------------------------------------------

    async def launch(self, env: Mapping[str, str], *, io_budget: Callable[[], int]) -> _Process:
        """Hand the run to a warm child (or one spawned now) and return it once it ACKed.

        `io_budget` is read at the hand-off itself — after any wait for a READY — so the fair
        share divides by the runs alive when the run starts (WRM-18).

        Retries ONCE on a new child when the first EXITS before its ACK — no run code has run
        (WC-D2). Everything else is final, because a retry could run the run twice or hand the
        caller's spec to a second process for nothing: a refused spec (a new child refuses it
        too), a spec over the limit (checked before any child sees it), and an ACK timeout (a
        slow child may have ACKed and started in the instant before the kill).
        Raises `LaunchFailed` when no child took the run.
        """
        claimed = time.monotonic()
        for attempt in (1, 2):
            handle = await self._take()
            try:
                proc = await self._hand_off(handle, env, io_budget)
            except _Retry as exc:
                logger.warning("warm child died before its ACK (attempt %d): %s", attempt, exc)
                continue
            if self._metrics is not None:
                self._metrics.handoff_latency_s.observe(time.monotonic() - claimed)
            return proc
        raise LaunchFailed(SPAWN_FAILED, "no child took the run: two children died before the ACK")

    async def _take(self) -> WarmHandle:
        """An idle warm child, or a child spawned for this claim (and awaited to READY)."""
        while self._idle:
            entry = self._idle.pop(0)
            entry.watcher.cancel()
            entry.forwarder.cancel()
            try:
                # The idle forwarder must be GONE before the supervisor reads the same streams.
                await asyncio.gather(entry.forwarder, return_exceptions=True)
            except BaseException:
                # Cancelled here, the child is in no registry any more: it must not outlive us.
                _signal(entry.handle.proc)
                raise
            self._report()
            self._wake.set()
            if entry.handle.proc.returncode is None:
                return entry.handle
        try:
            return await self._spawn_ready()
        except _WARM_FAILURES as exc:
            self._count_failure()
            raise LaunchFailed(SPAWN_FAILED, f"could not start a child: {exc}") from exc

    async def _hand_off(
        self, handle: WarmHandle, env: Mapping[str, str], io_budget: Callable[[], int]
    ) -> _Process:
        proc = handle.proc
        # INVARIANT: the spec goes over the private pipe and NOWHERE else — it carries the
        # caller's identity and profile, so no log line may include it (WRM-19).
        line = child_protocol.encode_spec(dict(env), io_concurrency=io_budget())
        if len(line) > child_protocol.MAX_SPEC_BYTES:
            # Checked HERE, before any child sees it: the child would refuse it, but it reads
            # only the limit — the rest of the write breaks the pipe, which reads as a crash
            # and would hand the caller's spec to a second child.
            _signal(proc)
            raise LaunchFailed("spec_too_large", f"the run spec is {len(line)} bytes")
        try:
            proc.stdin.write(line)
            await proc.stdin.drain()
            proc.stdin.close()
            answer = await asyncio.wait_for(handle.control.readline(), self._ack_timeout_s)
        except (BrokenPipeError, ConnectionResetError) as exc:
            await _reap_bounded(proc)
            raise _Retry(f"stdin closed: {exc!r}") from exc
        except TimeoutError:
            await _reap_bounded(proc)
            raise LaunchFailed(SPAWN_FAILED, "the child did not ACK its run in time") from None
        except BaseException:
            # Cancelled (a sibling failed and the TaskGroup unwound) with the spec already
            # written: a child that ACKs now would run with nobody supervising it, and the
            # message would be redelivered and run again. Kill it; do not wait.
            _signal(proc)
            raise
        if answer == child_protocol.ACK:
            return proc
        code = child_protocol.refused_code(answer)
        await _reap_bounded(proc)
        if code is not None:
            raise LaunchFailed(code, f"the child refused the run spec: {code}")
        raise _Retry(f"no ACK, got {answer[:40]!r}")

    # --- warming -----------------------------------------------------------------------------

    async def _spawn_ready(self) -> WarmHandle:
        """Spawn one child and wait for its READY (bounded by `ready_timeout_s`, WC-D6)."""
        self._spawning += 1
        try:
            handle = await self._spawn_warm()
            try:
                line = await asyncio.wait_for(handle.control.readline(), self._ready_timeout_s)
                ready = child_protocol.decode_ready(line)
            except BaseException as exc:
                _signal(handle.proc)
                if isinstance(exc, _WARM_FAILURES):
                    await _log_last_words(handle.proc)
                raise
            if not ready.world_ok:
                # WC-D3: the child stays usable — the run will publish its own failure when
                # it builds the world.
                logger.warning("warm child %d reports a world config error", ready.pid)
            self._consecutive_failures = 0
            if self._metrics is not None:
                self._metrics.child_boot_s.observe(time.monotonic() - handle.spawned_at)
            return handle
        finally:
            self._spawning -= 1
            # A spawn for a CLAIM also counts in `_spawning`, and may have put the replenisher
            # to sleep; now that it is done, the replenisher must look again.
            self._wake.set()

    async def _replenish_forever(self) -> None:
        """Keep `size` children warm; back off 1, 2, 4 … 30 s after consecutive failures.

        WHY catch everything: this task lives beside the supervisors, and `drain()` awaits it —
        an unexpected error escaping here would land in the worker's TaskGroup at drain and
        cancel every running supervisor (the N-3 cascade). Log and keep warming.
        """
        while not self._draining:
            missing = self._size - len(self._idle) - self._spawning
            if missing <= 0:
                self._wake.clear()
                await self._wake.wait()
                continue
            # WHY a parallel batch (kind B4 finding): one spawn at a time refilled a pod's pool
            # at 1 / boot time (~1.4 s in kind), slower than back-to-back claims used it, so the
            # pool ran dry and every call paid a cold boot. While spawns FAIL, one at a time, so
            # the backoff below paces a broken spawn rather than a burst of them.
            batch = 1 if self._consecutive_failures else missing
            outcomes = await asyncio.gather(*(self._warm_one() for _ in range(batch)))
            if self._draining:
                return
            if not all(outcomes):
                await self._backoff("warm spawn failed")

    async def _warm_one(self) -> bool:
        """Start one warm child and park it; False when it failed (counted)."""
        try:
            handle = await self._spawn_ready()
        except Exception as exc:
            if not isinstance(exc, _WARM_FAILURES):
                logger.exception("warm spawn failed unexpectedly")
            logger.warning("warm spawn failed: %r", exc)
            self._count_failure()
            return False
        if self._draining:
            _signal(handle.proc)
            return True
        self._park(handle)
        return True

    def _park(self, handle: WarmHandle) -> None:
        entry = _Idle(
            handle=handle,
            watcher=asyncio.create_task(self._watch_idle(handle)),
            forwarder=asyncio.create_task(_forward_idle_output(handle.proc)),
        )
        self._idle.append(entry)
        self._report()

    async def _watch_idle(self, handle: WarmHandle) -> None:
        """An idle child that exits is a warm failure, and is replaced (WC-D4)."""
        await handle.proc.wait()
        for entry in self._idle:
            if entry.handle is handle:
                self._idle.remove(entry)
                entry.forwarder.cancel()
                break
        else:
            return
        self._report()
        self._count_failure()
        await self._backoff(f"idle warm child {handle.proc.pid} exited {handle.proc.returncode}")

    def _count_failure(self) -> None:
        if self._metrics is not None:
            self._metrics.warm_spawn_failures.inc()
        self._consecutive_failures += 1

    async def _backoff(self, why: str) -> None:
        logger.warning("%s", why)
        delay = min(BACKOFF_MAX_S, BACKOFF_START_S * 2 ** (self._consecutive_failures - 1))
        await self._sleep(delay)
        self._wake.set()

    def _report(self) -> None:
        if self._metrics is not None:
            self._metrics.warm_children.set(len(self._idle))


_WARM_FAILURES = (OSError, child_protocol.ProtocolError, TimeoutError, ValueError)
"""How warming fails in the expected ways: the exec failed, the child died or wrote garbage
before READY, READY was late, or a line passed the read limit (`ValueError`)."""
_REAP_TIMEOUT_S = 5.0
_LAST_WORDS_BYTES = 4096


def _signal(proc: _Process, *, terminate: bool = False) -> None:
    """SIGTERM or SIGKILL a child that may already be gone (the V-1 policy in `loop.py`)."""
    if proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        if terminate:
            proc.terminate()
        else:
            proc.kill()


async def _reap_bounded(proc: _Process) -> None:
    """Kill (if needed) and wait for a child, bounded: a reap must not eat the drain grace."""
    _signal(proc)
    try:
        await asyncio.wait_for(proc.wait(), _REAP_TIMEOUT_S)
    except TimeoutError:
        logger.warning("child %d did not exit within %.0fs of a kill", proc.pid, _REAP_TIMEOUT_S)


async def _log_last_words(proc: _Process) -> None:
    """Log what a child that failed before READY wrote to stderr — its traceback, usually —
    so the operator sees more than "expected a READY line"."""
    stream = proc.stderr
    if stream is None:
        return
    with contextlib.suppress(Exception):
        tail = await asyncio.wait_for(stream.read(_LAST_WORDS_BYTES), 1.0)
        if tail:
            logger.warning(
                "warm child %d failed before READY: %s",
                proc.pid,
                tail.decode(errors="replace").strip(),
            )


async def _forward_idle_output(proc: _Process) -> None:
    """Drain an idle child's stdout/stderr into the worker's log, so a chatty warm-up cannot
    fill the pipe and stall. Cancelled at hand-off; the supervisor forwards from then on."""

    async def _drain(stream: Any, level: int) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                return
            logger.log(level, "warm child %d %s", proc.pid, line.decode(errors="replace").rstrip())

    await asyncio.gather(_drain(proc.stdout, logging.INFO), _drain(proc.stderr, logging.WARNING))


__all__ = [
    "SPAWN_FAILED",
    "LaunchFailed",
    "WarmChildPool",
    "WarmHandle",
    "deploy_env",
    "process_spawner",
]
