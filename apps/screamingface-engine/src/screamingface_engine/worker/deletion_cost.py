"""The worker's pod-deletion-cost publisher (OME-1931): the port and the coalescing writer.

The worker writes its busy slot count as its OWN pod's
`controller.kubernetes.io/pod-deletion-cost` annotation, so a ReplicaSet scale-down deletes an
idle pod first. This module has no HTTP: `worker/kube_pod.py` is the adapter behind
`PodCostWriter`.

INVARIANT (spec D3): a write never stops or delays a run. `notify` is synchronous, does no I/O
and cannot raise; `run` lives in its own task outside the supervisors' TaskGroup, and only
`CancelledError` leaves it.

WHY a retry and not a timer (spec D3): after a failed write the pod keeps a wrong cost until the
next busy change, which can be hours. The retry stops at the first good write; when the last write
succeeded the worker sends nothing.

LAYERING: worker mode. No import of `screamingface_engine.runner` or the runs registry.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Protocol

from prometheus_client import Counter

logger = logging.getLogger(__name__)

# Spec D2: a write does not start less than 1 s after the previous attempt (at most 1 request per
# second per pod). Spec D3: the retry backoff starts at 1 s and doubles to 30 s.
MIN_WRITE_INTERVAL_S = 1.0
RETRY_INITIAL_S = 1.0
RETRY_MAX_S = 30.0


class PodCostWriter(Protocol):
    """Writes this pod's deletion cost. `write` raises on ANY failure."""

    async def write(self, cost: int) -> None: ...

    async def aclose(self) -> None: ...


class DeletionCostPublisher:
    """Writes the latest busy count to the pod's deletion cost.

    At most one write is in flight. The latest count wins, so a burst of changes coalesces into
    one write. Writes are at least `min_interval_s` apart. A failed write is retried with a
    backoff that a newer count cancels.
    """

    def __init__(
        self,
        writer: PodCostWriter,
        *,
        writes: Counter,
        min_interval_s: float = MIN_WRITE_INTERVAL_S,
        retry_initial_s: float = RETRY_INITIAL_S,
        retry_max_s: float = RETRY_MAX_S,
    ) -> None:
        self._writer = writer
        self._writes = writes
        self._min_interval_s = min_interval_s
        self._retry_initial_s = retry_initial_s
        self._retry_max_s = retry_max_s
        # None until the first `notify`.
        self._desired: int | None = None
        # None until the first good write. WHY None and not 0: the first notify (usually 0) must
        # give one write (spec D2, the start write). A restarted container keeps its old
        # annotation, so a 0 that equals the default must still be written.
        self._written: int | None = None
        self._wake = asyncio.Event()
        # Loop time of the last write ATTEMPT (good or failed); None before the first one.
        self._last_attempt: float | None = None
        # True while the last attempt failed. WHY: only the FIRST failure of a streak logs at
        # WARNING. With no Role or no API-server egress every retry fails, and one WARNING per
        # retry would be 2 lines per minute per pod with no end. The error counter has the rate.
        self._failing = False

    def notify(self, busy: int) -> None:
        """Store the latest busy count and wake `run`. Sync, no I/O, cannot raise."""
        if busy == self._desired:
            return
        self._desired = busy
        self._wake.set()

    async def run(self) -> None:
        """Write the latest count until cancelled. Only `CancelledError` leaves it."""
        while True:
            await self._wake.wait()
            self._wake.clear()
            await self._write_until_current()

    async def aclose(self) -> None:
        """Close the writer. Never raises: the worker is exiting."""
        with contextlib.suppress(Exception):
            await self._writer.aclose()

    async def _write_until_current(self) -> None:
        backoff = self._retry_initial_s
        while self._desired is not None and self._desired != self._written:
            await self._pace()
            # Read AFTER the pause: a burst during it gives ONE write of the latest count.
            cost = self._desired
            if cost is None or cost == self._written:
                return
            # WHY clear here (spec D3): a notify during THIS attempt must wake the retry wait, but a
            # notify from before it (already read into `cost`) must not skip the next backoff.
            self._wake.clear()
            if await self._attempt(cost, backoff):
                backoff = self._retry_initial_s
                continue
            await self._wait_for_wake(backoff)
            backoff = min(backoff * 2, self._retry_max_s)

    async def _pace(self) -> None:
        """Sleep until `min_interval_s` after the last attempt (spec D2)."""
        if self._last_attempt is None:
            return
        delay = self._last_attempt + self._min_interval_s - asyncio.get_running_loop().time()
        if delay > 0:
            await asyncio.sleep(delay)

    async def _attempt(self, cost: int, backoff: float) -> bool:
        self._last_attempt = asyncio.get_running_loop().time()
        try:
            await self._writer.write(cost)
        except Exception as exc:  # CancelledError is a BaseException: a shutdown passes through
            self._writes.labels(outcome="error").inc()
            logger.log(
                logging.DEBUG if self._failing else logging.WARNING,
                "pod-deletion-cost write failed with %r; retry in %.0fs "
                "(more failures of this streak log at DEBUG)",
                exc,
                backoff,
            )
            self._failing = True
            return False
        self._written = cost
        self._writes.labels(outcome="ok").inc()
        if self._failing:
            self._failing = False
            logger.info("pod-deletion-cost writes work again")
        return True

    async def _wait_for_wake(self, timeout_s: float) -> None:
        """Wait for a new count OR the backoff, whichever is first (spec D3: a new count wakes
        the retry at once; the minimum interval still applies in `_pace`)."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout_s)
        self._wake.clear()


__all__ = [
    "MIN_WRITE_INTERVAL_S",
    "RETRY_INITIAL_S",
    "RETRY_MAX_S",
    "DeletionCostPublisher",
    "PodCostWriter",
]
