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

BURST = 200.0
REFILL_PER_S = 100.0
RESERVED_FOR_OUTCOMES = 40

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
        self._tokens = BURST
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

    def _admit(self, state: str, *, reserve_terminal: bool = False) -> bool:
        now = self.monotonic()
        self._tokens = min(BURST, self._tokens + max(0.0, now - self._last) * REFILL_PER_S)
        self._last = max(now, self._last)
        cost = 2 if reserve_terminal else 1
        threshold = RESERVED_FOR_OUTCOMES + cost if state in {"started", "running"} else cost
        if self._tokens < threshold:
            self.suppress("rate")
            return False
        self._tokens -= cost
        return True

    def emit(
        self,
        sink: Emitter,
        body: str,
        attributes: Mapping[str, Scalar],
        *,
        reserve_terminal: bool = False,
        prepaid_terminal: bool = False,
    ) -> bool:
        # INVARIANT: faults in optional bookkeeping never replace the operation outcome.
        # Catch ordinary exceptions only; process control/cancellation must propagate.
        try:
            return self._emit(sink, body, attributes, reserve_terminal, prepaid_terminal)
        except Exception:
            self.suppress("invalid")
            return False

    def _emit(
        self,
        sink: Emitter,
        body: str,
        attributes: Mapping[str, Scalar],
        reserve_terminal: bool,
        prepaid_terminal: bool,
    ) -> bool:
        with self._lock:
            record = dict(attributes)
            snapshot = self._suppressed.copy()
            if snapshot != self._reported:
                record.update({PREFIX + "suppressed." + k: v for k, v in snapshot.items()})
            wire = json.dumps({"body": body, "attributes": record}, allow_nan=False).encode()
            if not self.active or len(body) > 256 or len(wire) > 4096:
                if self.active:
                    self.suppress("oversize")
                return False
            state = str(record[PREFIX + "state"])
            if not prepaid_terminal and not self._admit(state, reserve_terminal=reserve_terminal):
                return False
            severity = "WARN" if state in {"retrying", "refused", "cancelled"} else "INFO"
            if state == "failed":
                severity = "ERROR"
            try:
                sink(body, MappingProxyType(record), severity=severity)
            except Exception:
                # INVARIANT: uncertain sink delivery is not producer suppression. Keep the
                # snapshot pending; consumers merge cumulative counters by maxima.
                pass
            else:
                self._reported = snapshot
            return True


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
