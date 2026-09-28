"""Admission without a payload queue."""

import time
from collections import Counter
from collections.abc import Callable

from analytics_service.contract import Batch
from analytics_service.ports import EventDelivery


class AdmissionRejected(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code


class Ingestion:
    def __init__(
        self,
        delivery: EventDelivery,
        *,
        enabled: bool,
        max_inflight: int,
        requests_per_minute: int,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.delivery, self.enabled = delivery, enabled
        self.max_inflight, self.rate, self.clock = max_inflight, requests_per_minute, clock
        self.draining, self.inflight = False, 0
        self.window, self.requests = clock(), 0
        # INVARIANT: bounded status-code keys only, never IDs or payload values.
        self.counters: Counter[str] = Counter()

    def enter(self) -> None:
        if not self.enabled or self.draining:
            raise AdmissionRejected(503, "unavailable")
        now = self.clock()
        if now - self.window >= 60:
            self.window, self.requests = now, 0
        if self.requests >= self.rate:
            raise AdmissionRejected(429, "rate_limited")
        self.requests += 1
        if self.inflight >= self.max_inflight:
            raise AdmissionRejected(503, "busy")
        # WHY: no await between checking and reserving on the ASGI event loop.
        self.inflight += 1

    def leave(self) -> None:
        self.inflight -= 1

    async def forward(self, batch: Batch) -> int:
        await self.delivery.deliver(batch)
        return len(batch.events)
