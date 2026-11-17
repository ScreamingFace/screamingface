"""One run's result, written in chunks: kept inline, spilled into the artifact store, or refused.

FEATURE: memory fix 3 (OME-1835), unit 1. The aggregate used to build the whole Candidate
Result as one string, and `runner.executor.build_result` then encoded all of it once more to
measure it. Now the aggregate hands the spool a body writer. The spool counts the UTF-8 bytes
as they arrive, keeps up to the inline cap in memory, moves into an artifact sink past the
inline cap, and only counts past the allowed size. So the result never has to exist whole.

Think of a cloakroom with tickets. A small coat goes back over the counter as it is (INLINE).
A big coat goes on the rack (the artifact store), and the aggregate gets a short ticket (a
~90-char JSON reference with a random key) to return as the run body. `build_result` gives the
ticket back to the spool that issued it and gets the claim ticket of the artifact
(`ResultArtifact`). A coat too big for the rack is refused at the counter (TOO_LARGE).

INVARIANT: run-scoped. One spool per run, made, bound and closed by
`runner.operation_capture`. The binding never outlives its block.

INVARIANT: a reference resolves only through the spool that issued it. The key is random and
the spool keeps its own book, so a body that only looks like a reference gives nothing.

INVARIANT: fail closed. When the spool issued a reference, the run body must be exactly an
issued reference; any other body raises `UnredeemedResultReference`. A spool that issued
nothing returns None, and the body takes today's path.

INVARIANT: one delivery rule. The verdict comes from `decide_result_delivery`, so the
three-way rule and "hard cap first" have one owner. This module only streams the bytes.

WHY its own exceptions: `artifacts` is a shared leaf of the layering gate and must not import
the url4 engine (only `url4.streaming`). The caller maps these errors to its own codes.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import secrets
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from screamingface_engine.artifacts.delivery import (
    ResultDelivery,
    allowed_result_bytes,
    decide_result_delivery,
    result_too_large_message,
)
from screamingface_engine.artifacts.ports import ArtifactSink, StreamingArtifactWriter
from url4.streaming.protocol.signals import ResultArtifact

REFERENCE_SCHEMA = "screamingface.result-spool-ref.v1"
"""The schema of an issued reference: `{"schema": REFERENCE_SCHEMA, "key": "<32 hex>"}`."""

_REFERENCE_MAX_CHARS = 128
"""A body longer than this is never looked up: an issued reference is about 90 chars."""

WriteBody = Callable[[Callable[[str], None]], None]
"""A body writer: it calls the given `write` with each chunk of the result text, in order."""


class ResultSpoolError(Exception):
    """The base of every error the spool raises itself."""


class ResultTooLarge(ResultSpoolError):
    """The result is over the allowed size. The message is `result_too_large_message`."""

    def __init__(self, size: int, allowed: int) -> None:
        super().__init__(result_too_large_message(size, allowed))
        self.size = size
        self.allowed = allowed


class ResultSpoolClosed(ResultSpoolError):
    """The run ended (or was cancelled) while, or before, the result was written."""

    def __init__(self) -> None:
        super().__init__("the run's result spool is closed")


class UnredeemedResultReference(ResultSpoolError):
    """The spool issued a reference, but the run body is not exactly an issued reference."""

    def __init__(self) -> None:
        super().__init__("the run's result is not the result reference its aggregate issued")


class ResultSpool:
    """The run's result spool. See the module docstring for the invariants."""

    def __init__(
        self, store: StreamingArtifactWriter | None, *, inline_cap: int, hard_cap: int
    ) -> None:
        # Public, read-only by convention.
        self.store = store
        self.inline_cap = inline_cap
        self.hard_cap = hard_cap
        self._lock = threading.Lock()
        self._closed = False
        # Open sinks. The one who removes a sink from this list owns its abort, so a sink is
        # aborted once, by close or by its delivery, never by both.
        self._sinks: list[ArtifactSink] = []
        self._issued: dict[str, ResultArtifact] = {}

    def deliver(self, write_body: WriteBody) -> str:
        """Stream one result. INLINE returns the text; SPILL returns a reference.

        Raises `ResultTooLarge` over the allowed size, `ResultSpoolClosed` after close, and
        any error of the body writer or the sink as itself.
        """

        delivery = _Delivery(self)
        try:
            write_body(delivery.write)
            return delivery.finish()
        except BaseException:
            delivery.abort()
            raise

    def redeem(self, body: str) -> ResultArtifact | None:
        """The artifact of an issued reference.

        None means this spool issued nothing (today's path). An exact issued reference gives
        its artifact; with any issued reference, any other body fails closed.
        """

        with self._lock:
            if not self._issued:
                return None
            artifact = self._issued.get(body) if len(body) <= _REFERENCE_MAX_CHARS else None
        if artifact is None:
            raise UnredeemedResultReference()
        return artifact

    def close(self) -> None:
        """Set the stop flag that the writer checks at every chunk, and abort an open sink.

        Called when the run's execute ends, whether it succeeded, failed or was cancelled.
        Idempotent; never raises.
        """

        with self._lock:
            self._closed = True
            sinks, self._sinks = self._sinks, []
        for sink in sinks:
            with contextlib.suppress(OSError, ValueError):
                sink.abort()

    # The helpers below with a `_locked` suffix need the caller to hold `_lock`.

    def _check_open_locked(self) -> None:
        if self._closed:
            raise ResultSpoolClosed()

    def _track_locked(self, sink: ArtifactSink) -> None:
        self._sinks.append(sink)

    def _untrack_locked(self, sink: ArtifactSink) -> bool:
        """Remove `sink`. True only if it was present: the remover owns the abort."""

        for index, tracked in enumerate(self._sinks):
            if tracked is sink:
                del self._sinks[index]
                return True
        return False

    def _issue(self, artifact: ResultArtifact) -> str:
        reference = json.dumps(
            {"schema": REFERENCE_SCHEMA, "key": secrets.token_hex(16)}, separators=(",", ":")
        )
        with self._lock:
            self._check_open_locked()
            self._issued[reference] = artifact
        return reference


class _Delivery:
    """One `deliver` call: the byte count, the in-memory buffer and the open sink."""

    def __init__(self, spool: ResultSpool) -> None:
        self._spool = spool
        self.size = 0
        self.buffer: list[bytes] = []
        self.sink: ArtifactSink | None = None
        self.allowed = allowed_result_bytes(
            spool.inline_cap, spool.hard_cap, spill_available=spool.store is not None
        )

    def write(self, chunk: str) -> None:
        # A lone surrogate raises UnicodeEncodeError here, which ends the delivery, as the
        # one-shot encode of build_result did.
        data = chunk.encode("utf-8")
        spool = self._spool
        with spool._lock:
            spool._check_open_locked()
            self.size += len(data)
            if self.size > self.allowed:
                # Past the allowed size the verdict is TOO_LARGE: only count from here on.
                self._drop_locked()
                return
            if self.sink is None and self.size > spool.inline_cap:
                self._open_sink_locked()
            if self.sink is not None:
                self.sink.write(data)
            else:
                self.buffer.append(data)

    def finish(self) -> str:
        spool = self._spool
        decision = decide_result_delivery(
            self.size,
            inline_cap=spool.inline_cap,
            hard_cap=spool.hard_cap,
            spill_available=spool.store is not None,
        )
        if decision is ResultDelivery.TOO_LARGE:
            raise ResultTooLarge(self.size, self.allowed)
        if decision is ResultDelivery.INLINE:
            return b"".join(self.buffer).decode("utf-8")
        with spool._lock:
            spool._check_open_locked()
            sink, self.sink = self.sink, None
            assert sink is not None  # SPILL means the size passed the inline cap in write
            spool._untrack_locked(sink)
        # WHY outside the lock: a commit can be a 1 GiB PUT, and close must not wait for it.
        # KNOWN WINDOW: if close runs during the commit, the commit still finishes and _issue
        # raises ResultSpoolClosed. Nobody waits for that result (the run has ended), and the
        # committed object has no ticket; the store's TTL sweep (filesystem sweeper, bucket
        # lifecycle) removes it.
        return spool._issue(sink.commit())

    def abort(self) -> None:
        with self._spool._lock:
            sink, self.sink = self.sink, None
            owned = sink is not None and self._spool._untrack_locked(sink)
        self.buffer.clear()
        if owned and sink is not None:
            sink.abort()

    def _open_sink_locked(self) -> None:
        store = self._spool.store
        assert store is not None  # over the inline cap but within allowed means a store exists
        self.sink = store.open_sink()
        self._spool._track_locked(self.sink)
        for piece in self.buffer:
            self.sink.write(piece)
        self.buffer.clear()

    def _drop_locked(self) -> None:
        self.buffer.clear()
        sink, self.sink = self.sink, None
        if sink is not None and self._spool._untrack_locked(sink):
            sink.abort()


_bound: contextvars.ContextVar[ResultSpool | None] = contextvars.ContextVar(
    "screamingface_result_spool", default=None
)


@contextmanager
def binding_result_spool(spool: ResultSpool | None) -> Iterator[None]:
    """Bind the run's spool for the enclosed steps; ``None`` keeps today's whole-string path.

    INVARIANT: the binding never outlives its block, so one run never delivers into, or
    redeems from, another run's spool.
    """

    token: contextvars.Token[ResultSpool | None] = _bound.set(spool)
    try:
        yield
    finally:
        _bound.reset(token)


def bound_result_spool() -> ResultSpool | None:
    """The spool bound to the current run, if there is one."""

    return _bound.get()


__all__ = [
    "REFERENCE_SCHEMA",
    "ResultSpool",
    "ResultSpoolClosed",
    "ResultSpoolError",
    "ResultTooLarge",
    "UnredeemedResultReference",
    "WriteBody",
    "binding_result_spool",
    "bound_result_spool",
]
