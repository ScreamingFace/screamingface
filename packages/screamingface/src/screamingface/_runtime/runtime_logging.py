from __future__ import annotations

import contextlib
import contextvars
import io
import os
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

MAX_LOG_BYTES = 10 * 1024 * 1024
LOG_BACKUPS = 5

_service = contextvars.ContextVar("screamingface_runtime_log_service", default="supervisor")


def _open_private(path: Path) -> TextIO:
    """Open the runtime log for append, readable only by its owner.

    INVARIANT (OME-990): this file carries the same class of secret as the ``runtime.json``
    beside it — prompt-bearing output and the Engine's WS capability ticket — and that file
    has been ``0600`` since it started holding the owner token.
    """
    # WHY both the mode argument AND the chmod: the mode is applied only when the file is
    # CREATED, so opening privately protects a new log but leaves a `runtime.log` written
    # 0644 by an earlier version at its old mode forever. The chmod is what remediates the
    # logs already on disk, on the reopen every `screamingface up` performs.
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    stream = os.fdopen(descriptor, "a", encoding="utf-8")
    path.chmod(0o600)
    return stream


@contextlib.contextmanager
def log_service(name: str) -> Iterator[None]:
    token = _service.set(name)
    try:
        yield
    finally:
        _service.reset(token)


class RuntimeLog(io.TextIOBase):
    def __init__(self, path: Path, *, console: TextIO | None = None) -> None:
        self._path = path
        self._console = console
        self._lock = threading.Lock()
        self._buffer = ""
        path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = _open_private(path)

    def write(self, value: str) -> int:
        with self._lock:
            self._buffer += value
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                self._write_line(line)
        return len(value)

    def writable(self) -> bool:
        return True

    def flush(self) -> None:
        with self._lock:
            self._stream.flush()
            if self._console is not None:
                self._console.flush()

    def close(self) -> None:
        if self.closed:
            return
        with self._lock:
            if self._buffer:
                self._write_line(self._buffer)
                self._buffer = ""
        super().close()
        self._stream.close()

    def _write_line(self, line: str) -> None:
        rendered = f"{datetime.now(UTC).isoformat()} [{_service.get()}] {line}\n"
        if self._stream.tell() + len(rendered.encode()) > MAX_LOG_BYTES:
            self._rotate()
        self._stream.write(rendered)
        self._stream.flush()
        if self._console is not None:
            self._console.write(rendered)
            self._console.flush()

    def _rotate(self) -> None:
        self._stream.close()
        oldest = self._path.with_name(f"{self._path.name}.{LOG_BACKUPS}")
        oldest.unlink(missing_ok=True)
        for index in range(LOG_BACKUPS - 1, 0, -1):
            source = self._path.with_name(f"{self._path.name}.{index}")
            if source.exists():
                source.replace(self._path.with_name(f"{self._path.name}.{index + 1}"))
        if self._path.exists():
            self._path.replace(self._path.with_name(f"{self._path.name}.1"))
        self._stream = _open_private(self._path)


@contextlib.contextmanager
def capture_runtime_log(path: Path, *, foreground: bool) -> Iterator[RuntimeLog]:
    previous_stdout, previous_stderr = sys.stdout, sys.stderr
    runtime_log = RuntimeLog(path, console=previous_stdout if foreground else None)
    sys.stdout = runtime_log
    sys.stderr = runtime_log
    try:
        yield runtime_log
    finally:
        sys.stdout, sys.stderr = previous_stdout, previous_stderr
        runtime_log.close()
