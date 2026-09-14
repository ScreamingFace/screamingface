"""Revocable run-local admission: constant storage, no payload queue."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType
from typing import Literal

from screamingface_engine.activity.contract import MAX_INTEGER, PREFIX, Emitter, Scalar

_CURRENT: ContextVar[ActivitySession | None] = ContextVar("activity_session", default=None)


class ActivitySession:
    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.monotonic = monotonic
        self.wall = wall
        self.active = True
        self._tokens = 200.0
        self._last = monotonic()
        self._lock = threading.RLock()
        self._suppressed = dict.fromkeys(("invalid", "oversize", "rate"), 0)
        self._reported = self._suppressed.copy()

    def revoke(self) -> None:
        with self._lock:
            self.active = False

    def suppress(self, reason: Literal["invalid", "oversize", "rate"]) -> None:
        with self._lock:
            self._suppressed[reason] = min(MAX_INTEGER, self._suppressed[reason] + 1)

    def _admit(self, state: str) -> bool:
        now = self.monotonic()
        self._tokens = min(200.0, self._tokens + max(0.0, now - self._last) * 100.0)
        self._last = max(now, self._last)
        if self._tokens < (41 if state in {"started", "running"} else 1):
            self.suppress("rate")
            return False
        self._tokens -= 1
        return True

    def emit(self, sink: Emitter, body: str, attributes: Mapping[str, Scalar]) -> None:
        # INVARIANT: faults in optional bookkeeping never replace the operation outcome.
        # Catch ordinary exceptions only; process control/cancellation must propagate.
        try:
            self._emit(sink, body, attributes)
        except Exception:
            self.suppress("invalid")

    def _emit(self, sink: Emitter, body: str, attributes: Mapping[str, Scalar]) -> None:
        with self._lock:
            if not self.active:
                return
            record = dict(attributes)
            snapshot = self._suppressed.copy()
            if snapshot != self._reported:
                record.update({PREFIX + "suppressed." + k: v for k, v in snapshot.items()})
            wire = json.dumps({"body": body, "attributes": record}, allow_nan=False).encode()
            if len(body) > 256 or len(wire) > 4096:
                self.suppress("oversize")
                return
            state = str(record[PREFIX + "state"])
            if not self._admit(state):
                return
            severity = "WARN" if state in {"retrying", "refused", "cancelled"} else "INFO"
            if state == "failed":
                severity = "ERROR"
            sink(body, MappingProxyType(record), severity=severity)
            self._reported = snapshot


def current_session() -> ActivitySession | None:
    session = _CURRENT.get()
    return session if session is not None and session.active else None


@contextmanager
def activate(session: ActivitySession | None) -> Iterator[None]:
    token = _CURRENT.set(session)
    try:
        yield
    finally:
        _CURRENT.reset(token)
