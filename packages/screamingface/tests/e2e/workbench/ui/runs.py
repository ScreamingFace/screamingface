"""Launch the workbench pytest lane from the UI: one run at a time, streamed, group-cancellable.

The UI never executes notebooks itself (spec §2 D4): a run is exactly the CI lane,
``pytest tests/e2e/workbench/test_notebooks.py``, with the workbench env vars set and its own
output root ``<root>/runs/<id>``.

Lifecycle of a run:

- **Spawn** in a new session, so its process group holds pytest, the kernel and the Engine.
- **Read**: a daemon thread appends stdout lines (capped at ``LINE_CAP``; oldest dropped and
  counted) and wakes ``follow``ers.
- **End**: a second daemon thread waits for pytest to exit. Stragglers still in the group (a
  kernel that outlived pytest, holding stdout open) are killed after ``drain_grace``, so a run
  never hangs on "running" after pytest is gone (Review Focus 1).
- **Cancel** interrupts the group first. WHY SIGINT and not SIGTERM: pytest turns SIGINT into
  ``KeyboardInterrupt`` and runs fixture teardown — ``targets.local_stack``'s ``down``, the only
  thing that stops the runtime, which ``screamingface up`` detaches into its own session. On
  SIGTERM, Python's default action kills pytest outright and no teardown runs (checked by
  ``test_cancel_runs_pytest_teardown``). SIGTERM, then SIGKILL, follow if the group lingers.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

KNOWN_UI_TARGETS = ("replay", "local")
LINE_CAP = 20_000  # per run, held in memory; read at append time so tests can lower it

_TEST_FILE = "tests/e2e/workbench/test_notebooks.py"
_STEM = re.compile(r"^[a-z0-9_-]+$")
# Stems that match _STEM but are pytest -k operators: they would break the expression.
_K_KEYWORDS = frozenset({"and", "or", "not"})
_KEY_ENV = "OPENROUTER_API_KEY"
_PAID_ENV = "SCREAMINGFACE_TEST_PAID"

Spawn = Callable[[list[str], dict[str, str], Path], "subprocess.Popen[str]"]


class RunRejected(ValueError):
    """The request is invalid or fails the paid gate (HTTP 400; the message is the reason)."""


class RunBusy(RuntimeError):
    """A run is already active (HTTP 409): the local target binds fixed ports."""


@dataclass(frozen=True)
class RunRequest:
    target: str  # in KNOWN_UI_TARGETS
    notebooks: tuple[str, ...]  # stems; empty = all
    confirm_paid: bool = False


@dataclass
class Run:
    id: str
    request: RunRequest
    out_dir: Path  # <root>/runs/<id>
    lines: list[str] = field(default_factory=list[str])  # the newest LINE_CAP lines
    dropped: int = 0  # lines dropped from the front; absolute index of lines[0]
    returncode: int | None = None  # None while running
    cancelled: bool = False


@dataclass
class _Live:
    run: Run
    process: subprocess.Popen[str]
    cond: threading.Condition = field(default_factory=threading.Condition)
    eof: threading.Event = field(default_factory=threading.Event)

    def ended(self, timeout: float | None) -> bool:
        with self.cond:
            return self.cond.wait_for(lambda: self.run.returncode is not None, timeout)


def _spawn(argv: list[str], env: dict[str, str], cwd: Path) -> subprocess.Popen[str]:
    # WHY errors="replace": a stray non-UTF-8 byte must not kill the reader (and strand the run).
    return subprocess.Popen(
        argv,
        env=env,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        start_new_session=True,
    )


def _signal_group(pgid: int, sig: signal.Signals) -> None:
    # The group outlives a reaped leader while any member remains; empty → ProcessLookupError.
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _validate(request: RunRequest, environ: Mapping[str, str]) -> None:
    if request.target not in KNOWN_UI_TARGETS:
        raise RunRejected(
            f"unknown target {request.target!r}; choose one of {', '.join(KNOWN_UI_TARGETS)}"
        )
    for stem in request.notebooks:
        if not _STEM.fullmatch(stem) or stem in _K_KEYWORDS:
            raise RunRejected(
                f"invalid notebook name {stem!r} (expected [a-z0-9_-]+, not and/or/not)"
            )
    if request.target == "local" and not request.confirm_paid:
        raise RunRejected("the local target spends real tokens; confirm it to start the run")
    if request.target == "local" and not environ.get(_KEY_ENV):
        raise RunRejected(f"{_KEY_ENV} is not set in the UI's environment; the local run needs it")


class RunManager:
    """Owns the runs launched from this UI process; at most one is active at a time."""

    def __init__(
        self,
        root: Path,
        *,
        workdir: Path,
        environ: Mapping[str, str],
        spawn: Spawn = _spawn,
        interrupt_grace: float = 30.0,
        terminate_grace: float = 15.0,
        drain_grace: float = 2.0,
    ) -> None:
        self._root = root
        self._workdir = workdir
        self._environ = dict(environ)
        self._spawn = spawn
        # WHY 30 s before SIGTERM: interrupt-driven teardown stops the Engine and runs `down`.
        self._graces = (interrupt_grace, terminate_grace)
        self._drain_grace = drain_grace
        self._lock = threading.Lock()
        self._runs: dict[str, _Live] = {}

    def command(self, request: RunRequest, out_dir: Path) -> tuple[list[str], dict[str, str]]:
        """The pytest argv and env for ``request``; raises ``RunRejected`` on a bad request."""
        _validate(request, self._environ)
        argv = [sys.executable, "-m", "pytest", _TEST_FILE, "-v", "-rs"]
        if request.notebooks:
            argv += ["-k", " or ".join(request.notebooks)]
        env = dict(self._environ)
        # WHY pop: an inherited opt-in must not make a keyless replay launch paid.
        env.pop(_PAID_ENV, None)
        env.update(
            {
                "SCREAMINGFACE_TEST_E2E": "1",
                "SCREAMINGFACE_WORKBENCH_TARGET": request.target,
                "SCREAMINGFACE_WORKBENCH_OUT": str(out_dir),
                "SCREAMINGFACE_WORKBENCH_REQUIRE_ALL": "1",
            }
        )
        if request.target == "local":
            env[_PAID_ENV] = "1"
        return argv, env

    def start(self, request: RunRequest) -> Run:
        with self._lock:
            if any(live.run.returncode is None for live in self._runs.values()):
                raise RunBusy("a run is already active; wait for it or cancel it")
            run_id, out_dir = self._new_id()
            argv, env = self.command(request, out_dir)
            out_dir.mkdir(parents=True)
            try:
                process = self._spawn(argv, env, self._workdir)
            except BaseException:
                # Not registered, so the slot stays free; drop the empty dir so the bundle
                # list does not show a run that never started.
                shutil.rmtree(out_dir, ignore_errors=True)
                raise
            live = _Live(Run(run_id, request, out_dir), process)
            self._runs[run_id] = live
        threading.Thread(target=self._read, args=(live,), daemon=True).start()
        threading.Thread(target=self._reap, args=(live,), daemon=True).start()
        return live.run

    def get(self, run_id: str) -> Run:
        return self._runs[run_id].run

    def cancel(self, run_id: str) -> Run:
        """Interrupt, then terminate, then kill the run's process group; returns once it ended."""
        live = self._runs[run_id]
        with live.cond:
            # WHY only the first caller escalates: a second SIGINT while pytest is in fixture
            # teardown aborts it, and `down` (the only thing that stops a local runtime) never
            # runs. A repeated cancel (double click, retried POST) just waits for the end.
            first = not live.run.cancelled and live.process.poll() is None
            if first:
                live.run.cancelled = True
        if first:
            for sig, grace in zip((signal.SIGINT, signal.SIGTERM), self._graces, strict=True):
                _signal_group(live.process.pid, sig)
                if live.ended(grace):
                    return live.run
            _signal_group(live.process.pid, signal.SIGKILL)
        live.ended(None)
        return live.run

    def follow(self, run_id: str, start: int) -> Iterator[str]:
        """Lines from absolute index ``start`` (clamped to the oldest held); ends with the run."""
        return self._follow(self._runs[run_id], start)

    @staticmethod
    def _follow(live: _Live, start: int) -> Iterator[str]:
        run, index = live.run, start
        while True:
            with live.cond:
                live.cond.wait_for(
                    lambda: run.dropped + len(run.lines) > index or run.returncode is not None
                )
                first = max(index, run.dropped)
                batch = run.lines[first - run.dropped :]
                finished = run.returncode is not None
            index = first + len(batch)
            yield from batch
            if finished and not batch:
                return

    def _new_id(self) -> tuple[str, Path]:
        while True:
            run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
            out_dir = self._root / "runs" / run_id
            if run_id not in self._runs and not out_dir.exists():
                return run_id, out_dir

    @staticmethod
    def _read(live: _Live) -> None:
        run, stdout = live.run, live.process.stdout
        try:
            for raw in stdout if stdout is not None else ():
                with live.cond:
                    run.lines.append(raw.rstrip("\r\n"))
                    excess = len(run.lines) - LINE_CAP
                    if excess > 0:
                        del run.lines[:excess]
                        run.dropped += excess
                    live.cond.notify_all()
        except (OSError, ValueError):
            pass  # the pipe went away mid-read; the reaper still ends the run
        finally:
            live.eof.set()

    def _reap(self, live: _Live) -> None:
        returncode = live.process.wait()
        drained = live.eof.wait(self._drain_grace)
        # pytest is gone; whatever is left in its group (a kernel holding stdout open, say) is
        # an orphan of this run. Not sent when the group is empty (ProcessLookupError).
        _signal_group(live.process.pid, signal.SIGKILL)
        if not drained:
            live.eof.wait(self._drain_grace)
        with live.cond:
            live.run.returncode = returncode
            live.cond.notify_all()
