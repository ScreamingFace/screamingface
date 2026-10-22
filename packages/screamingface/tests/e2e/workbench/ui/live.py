"""Live telemetry for the run page (unit 6 plan, Task 6): tail a running run's JSONL files.

While a run executes, two kinds of file grow under its out dir ``<root>/runs/<id>``:

- ``spans.jsonl``: the session OTLP receiver's, every span the targets export (spec §3.6);
- ``<target>/<notebook>/events.jsonl``: each notebook's SDK event recorder.

``stream`` turns them into server-sent events: one ``call`` per span that names a model (the
engine's provider call), and ``counts`` with running totals. It ends with ``end`` once the run
has ended and the files are drained.

Guarantees (Review Focus 2 and 4):
- **complete lines only**: bytes after the last newline are held back until their newline
  arrives, even at the end, so a half-written JSON line is never shown;
- **handles are released**: every file handle is closed when the stream ends, is closed by the
  server (``aclose``) or is cancelled (Starlette cancels it on ``http.disconnect``);
- **redacted again** on read, like the bundle loader: the writers redact, this does not trust it;
- **bounded**: a read takes at most ``CHUNK_BYTES`` per file per poll, a line longer than
  ``LINE_BYTES_CAP`` is skipped, and at most ``LINES_CAP`` rows per file are kept. Whatever is
  skipped is counted and shown (``unreadable``, ``over_cap``), never silently lost.

WHY poll on the event loop, not in a thread: a cancelled ``to_thread`` read keeps running, and
closing its handle from the loop would race it. A chunk-capped local read is short.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import IO, Any, Final

from workbench.bundle import EVENTS_FILE, SPANS_FILE
from workbench.redaction import redact_named_tree
from workbench.ui.bundles import regular_file
from workbench.ui.telemetry import LINES_CAP, int_or_none, money, money_sum

CHUNK_BYTES: Final = 256 << 10
LINE_BYTES_CAP: Final = 4 << 20
NAME_CHARS: Final = 120
_NOTEBOOK_DIR: Final = re.compile(r"^[A-Za-z0-9_.-]+$")

type Json = dict[str, Any]


def _object(line: bytes) -> Json | None:
    """A redacted JSON object; None for anything else, including a too-deep document."""
    try:
        value: object = json.loads(line)
        return redact_named_tree(value) if isinstance(value, dict) else None
    except (ValueError, RecursionError):
        return None


class JsonlTail:
    """The complete, redacted JSON-object lines appended to one file since the last ``read``.

    The handle stays open between reads (a long run appends for minutes) and is reopened from
    the start when the file is replaced or truncated: a rerun's bundle starts a new file.
    """

    def __init__(
        self,
        path: Path,
        *,
        chunk: int = CHUNK_BYTES,
        line_cap: int = LINE_BYTES_CAP,
        rows_cap: int = LINES_CAP,
    ) -> None:
        self.path = path
        self._chunk, self._line_cap, self._rows_cap = chunk, line_cap, rows_cap
        self._handle: IO[bytes] | None = None
        self._inode: tuple[int, int] | None = None
        self._offset = 0
        self._pending = b""
        self._skipping = False  # inside an over-long line: drop bytes until its newline
        self.rows = 0
        self.unreadable = 0
        self.over_cap = 0
        self.more = False  # the last read stopped at the chunk cap: more bytes are waiting

    @property
    def opened(self) -> bool:
        return self._handle is not None

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
        self._handle = None

    def _reset(self) -> None:
        self.close()
        self._offset, self._pending, self._skipping = 0, b"", False

    def _stat(self) -> os.stat_result | None:
        try:
            return self.path.stat() if regular_file(self.path) else None
        except OSError:
            return None

    def _ensure_open(self) -> IO[bytes] | None:
        """The handle, (re)opened when the path now names another file; None when absent."""
        stat = self._stat()
        if stat is None:
            self._reset()
            return None
        inode = (stat.st_dev, stat.st_ino)
        if self._handle is not None and (inode != self._inode or stat.st_size < self._offset):
            self._reset()
        if self._handle is None:
            try:
                fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                self._handle, self._inode = os.fdopen(fd, "rb"), inode
            except OSError:
                pass  # gone or swapped for a symlink between the stat and the open
        return self._handle

    def read(self) -> list[Json]:
        handle = self._ensure_open()
        if handle is None:
            self.more = False
            return []
        handle.seek(self._offset)
        data = handle.read(self._chunk)
        self._offset += len(data)
        self.more = len(data) == self._chunk
        *lines, self._pending = (self._pending + data).split(b"\n")
        rows = [row for row in map(self._row, self._lines(lines)) if row is not None]
        if len(self._pending) > self._line_cap:  # no newline in sight: skip this line
            self._pending, self._skipping = b"", True
            self.unreadable += 1
        return rows

    def _lines(self, lines: list[bytes]) -> list[bytes]:
        if self._skipping and lines:  # the first newline ends the skipped line
            self._skipping = False
            lines = lines[1:]
        elif self._skipping:
            self._pending = b""
        return [line for line in lines if line.strip()]

    def _row(self, line: bytes) -> Json | None:
        if self.rows >= self._rows_cap:
            self.over_cap += 1
            return None
        row = _object(line) if len(line) <= self._line_cap else None
        self.unreadable += row is None
        self.rows += row is not None
        return row


# --- model calls -------------------------------------------------------------------------------


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _dict(value: object) -> Json:
    return value if isinstance(value, dict) else {}  # pyright: ignore[reportUnknownVariableType]


@dataclass(frozen=True)
class ModelCall:
    service: str
    name: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    cache: str | None
    duration_ms: float | None
    error: str | None

    def as_json(self) -> Json:
        return {
            "service": self.service,
            "name": self.name,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache": self.cache,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


def _duration_ms(span: Json) -> float | None:
    start, end = int_or_none(span.get("start_ns")), int_or_none(span.get("end_ns"))
    if start is None or end is None:
        return None
    return round(max(0, end - start) / 1e6, 1)


def model_call(span: Json) -> ModelCall | None:
    """The span as a model-call row when it names a model (``gen_ai.*``); else None."""
    attributes = _dict(span.get("attributes"))
    model = _str(attributes.get("gen_ai.response.model") or attributes.get("gen_ai.request.model"))
    if model is None:
        return None
    status = _dict(span.get("status"))
    error = _str(attributes.get("error.type"))
    if status.get("code") == "error":
        error = _str(status.get("message")) or error or "error"
    name = _str(span.get("name")) or "?"
    return ModelCall(
        service=_str(span.get("service")) or "unknown service",
        name=name if len(name) <= NAME_CHARS else name[:NAME_CHARS] + "…",
        model=model,
        input_tokens=int_or_none(attributes.get("gen_ai.usage.input_tokens")),
        output_tokens=int_or_none(attributes.get("gen_ai.usage.output_tokens")),
        cache=_str(attributes.get("url4.cache_status")),
        duration_ms=_duration_ms(span),
        error=error,
    )


# --- one run's out dir -------------------------------------------------------------------------


def _add(total: int | None, part: int | None) -> int | None:
    """INVARIANT (as the bundle page): one unknown part makes the total unknown, never 0."""
    return None if total is None or part is None else total + part


@dataclass
class _Totals:
    events: int = 0
    spans: int = 0
    calls: int = 0
    input_tokens: int | None = 0
    output_tokens: int | None = 0
    cache_hits: int = 0
    errors: int = 0
    costs: list[Decimal | None] = field(default_factory=list[Decimal | None])

    def call(self, call: ModelCall) -> None:
        self.calls += 1
        self.input_tokens = _add(self.input_tokens, call.input_tokens)
        self.output_tokens = _add(self.output_tokens, call.output_tokens)
        self.cache_hits += call.cache == "hit"
        self.errors += call.error is not None

    def event(self, event: Json) -> None:
        self.events += 1
        if event.get("kind") == "usage" and event.get("scope") == "self":  # subtree: a roll-up
            self.costs.append(money(_dict(event.get("usage")).get("cost_usd")))


@dataclass(frozen=True)
class Poll:
    calls: tuple[ModelCall, ...]
    counts: Json
    more: bool  # some file still has unread bytes


class LiveTelemetry:
    """Follows ``out_dir/spans.jsonl`` and ``out_dir/<target>/*/events.jsonl`` of one run."""

    def __init__(self, out_dir: Path, target: str) -> None:
        self._out = out_dir
        self._target = target
        self._spans = JsonlTail(out_dir / SPANS_FILE)
        self._events: dict[str, JsonlTail] = {}
        self._totals = _Totals()

    @property
    def open_files(self) -> int:
        return sum(t.opened for t in self._tails())

    def _tails(self) -> list[JsonlTail]:
        return [self._spans, *self._events.values()]

    def _discover(self) -> None:
        """Notebook dirs appear as the run reaches them; symlinked ones are never followed."""
        base = self._out / self._target
        try:
            dirs = [d for d in base.iterdir() if not d.is_symlink() and d.is_dir()]
        except OSError:
            return
        for d in dirs:
            if _NOTEBOOK_DIR.fullmatch(d.name) and d.name not in self._events:
                self._events[d.name] = JsonlTail(d / EVENTS_FILE)

    def poll(self) -> Poll:
        self._discover()
        calls: list[ModelCall] = []
        for span in self._spans.read():
            self._totals.spans += 1
            call = model_call(span)
            if call is not None:
                self._totals.call(call)
                calls.append(call)
        for name in sorted(self._events):
            for event in self._events[name].read():
                self._totals.event(event)
        more = any(t.more for t in self._tails())
        return Poll(tuple(calls), self.counts(), more)

    def counts(self) -> Json:
        totals, tails = self._totals, self._tails()
        cost = money_sum(totals.costs)
        return {
            "events": totals.events,
            "spans": totals.spans,
            "calls": totals.calls,
            "input_tokens": totals.input_tokens,
            "output_tokens": totals.output_tokens,
            "cache_hits": totals.cache_hits,
            "errors": totals.errors,
            "cost_usd": None if cost is None else str(cost),
            "notebooks": len(self._events),
            "unreadable": sum(t.unreadable for t in tails),
            "over_cap": sum(t.over_cap for t in tails),
        }

    def close(self) -> None:
        for tail in self._tails():
            tail.close()


# --- server-sent events ------------------------------------------------------------------------


def _frame(event: str, data: object) -> str:
    # json.dumps escapes every control and non-ASCII character: a value cannot end the frame.
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def stream(
    live: LiveTelemetry,
    ended: Callable[[], bool],
    *,
    interval: float = 0.5,
    keepalive: float = 15.0,
) -> AsyncGenerator[str]:
    """SSE frames of ``live`` until ``ended()`` and the files are drained; then ``end``.

    ``reset`` opens every stream: a reconnecting browser clears what it showed, since the
    stream starts over from the top of each file. A comment goes out after ``keepalive``
    seconds of quiet, so a server notices a browser that went away on its next write.
    """
    try:
        yield "retry: 2000\n\n"
        yield _frame("reset", {})
        shown: Json | None = None
        quiet_since = time.monotonic()
        while True:
            done = ended()  # read BEFORE the poll: what was written before the end is shown
            batch = live.poll()
            frames = [_frame("call", call.as_json()) for call in batch.calls]
            if batch.counts != shown:
                shown = batch.counts
                frames.append(_frame("counts", batch.counts))
            if not frames and time.monotonic() - quiet_since >= keepalive:
                frames.append(": keepalive\n\n")
            for chunk in frames:
                yield chunk
            quiet_since = time.monotonic() if frames else quiet_since
            if done and not batch.more:
                break
            # WHY sleep(0) when more is waiting: drain fast, but still yield to the loop (and to
            # a cancellation) between chunks.
            await asyncio.sleep(0 if batch.more else interval)
        yield _frame("end", {})
    finally:
        live.close()
