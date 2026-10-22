"""Subprocess plumbing shared by the harness boot modules (OME-961, internal).

Mental model: each stack service runs from its OWN uv project's virtualenv, as a
child process on a loopback port, with a scrubbed environment (unlike
``screamingface up``, which serves everything from the SDK's one environment — this
harness isolates per-app dependency trees on purpose). Tests never share a venv with
the gateway or the engine, so the SDK package's dependency tree stays untouched (the
decisive argument against a path dep, recorded in the OME-961 ledger).

INVARIANT — the clean-environment rule: a child gets ``clean_env()`` plus exactly the
variables its harness sets, NEVER the caller's shell. A developer with a real
``OPENROUTER_API_KEY`` exported must get byte-identical behavior to CI: replay hits
from the cache, loud 404s on misses, zero provider traffic. Spend stays impossible by
construction, not by discipline.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import httpx

_HERE: Final = Path(__file__).resolve()

#: Variables a child process legitimately needs to run Python from a venv. No secrets,
#: no provider keys, no AIGW_/AIGATEWAY_/URL4_ leakage from the developer's shell.
_ENV_PASSTHROUGH: Final = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")

STARTUP_TIMEOUT_SECONDS: Final = 90.0


def repo_root() -> Path:
    """The monorepo checkout root (…/screamingface), found from this file's location."""
    # parents: harness → e2e → tests → screamingface → packages → <repo root>
    root = _HERE.parents[5]
    if not (root / "apps" / "aigateway").is_dir():
        raise RuntimeError(f"monorepo root not found above {_HERE}")
    return root


def clean_env(extra: dict[str, str]) -> dict[str, str]:
    """A from-scratch child environment: passthrough basics + ``extra``, nothing else."""
    base = {name: value for name in _ENV_PASSTHROUGH if (value := os.environ.get(name))}
    return {**base, **extra}


#: The only names a caller may add through a ``telemetry`` seam (unit 6, Task 3).
TELEMETRY_PREFIX: Final = "OTEL_"
_TRACES_PATH: Final = "/v1/traces"


def checked_telemetry(telemetry: Mapping[str, str] | None) -> dict[str, str]:
    """``telemetry`` as a plain dict, refusing any name outside ``OTEL_*``.

    WHY a refusal and not a filter: the seam exists to point a child at an OTLP receiver. A
    caller handing it ``OPENROUTER_API_KEY`` or ``AIGW_AUTH_MODE`` is a bug that would break
    the clean-environment rule, and silently dropping it would hide the bug.
    """
    env = dict(telemetry or {})
    foreign = sorted(name for name in env if not name.startswith(TELEMETRY_PREFIX))
    if foreign:
        raise ValueError(f"telemetry may set only {TELEMETRY_PREFIX}* variables, got {foreign}")
    return env


def telemetry_env(receiver_url: str | None, *, service: str) -> dict[str, str]:
    """The ``OTEL_*`` variables that point one service at an OTLP/HTTP receiver, or ``{}``.

    ``receiver_url`` is the traces URL (``…/v1/traces``, what ``OtlpReceiver.start`` returns).
    WHY it is turned into a base: ``OTEL_EXPORTER_OTLP_ENDPOINT`` is a BASE that both the
    engine (``tracing.otlp._endpoint``) and the OTel SDK the gateway uses extend with
    ``/v1/traces``; the full URL would post to ``/v1/traces/v1/traces``.
    """
    if not receiver_url:
        return {}
    return {
        "OTEL_EXPORTER_OTLP_ENDPOINT": receiver_url.removesuffix(_TRACES_PATH),
        "OTEL_SERVICE_NAME": service,
    }


def free_port() -> int:
    """Ask the OS for a currently free loopback port (bind-then-release)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def sync_project(project_dir: Path, extras: tuple[str, ...] = ()) -> None:
    """``uv sync`` the app's own venv, with ``extras`` (idempotent; slow only on a fresh
    worktree)."""
    extra_flags: list[str] = [flag for extra in extras for flag in ("--extra", extra)]
    subprocess.run(
        ["uv", "sync", "--quiet", *extra_flags],
        cwd=project_dir,
        env=clean_env({}),
        check=True,
        capture_output=True,
        text=True,
    )


def venv_bin(project_dir: Path, executable: str) -> Path:
    path = project_dir / ".venv" / "bin" / executable
    if not path.exists():
        raise RuntimeError(f"{executable} not found in {project_dir}/.venv — did sync fail?")
    return path


class ManagedProcess:
    """One supervised child: spawn, wait for its health URL, terminate, keep the log."""

    def __init__(
        self,
        *,
        name: str,
        command: list[str],
        env: dict[str, str],
        cwd: Path,
        log_path: Path,
    ) -> None:
        self._name = name
        self._command = command
        self._env = env
        self._cwd = cwd
        self.log_path = log_path
        self._process: subprocess.Popen[bytes] | None = None

    def start(self, health_url: str) -> None:
        """Spawn the child and block until ``health_url`` answers 200, or fail loudly."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("wb") as log:
            self._process = subprocess.Popen(
                self._command,
                env=self._env,
                cwd=self._cwd,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError(
                    f"{self._name} exited with {self._process.returncode} during startup; "
                    f"log: {self.log_path}\n{self._log_tail()}"
                )
            try:
                if httpx.get(health_url, timeout=1.0).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        self.stop()
        raise RuntimeError(
            f"{self._name} did not answer {health_url} within {STARTUP_TIMEOUT_SECONDS}s; "
            f"log: {self.log_path}\n{self._log_tail()}"
        )

    def stop(self) -> None:
        """Terminate the child; idempotent, escalates to kill after a grace period."""
        process = self._process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

    def _log_tail(self, lines: int = 25) -> str:
        try:
            content = self.log_path.read_text(errors="replace").splitlines()
        except OSError:
            return "<log unreadable>"
        return "\n".join(content[-lines:])
