"""What the driver tests share: a job runner that records every start, and the drivers' settings.

FEATURE: a detached Run (OME-1837), E5 P2 spec R1 to R11.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.ports import IdentityAwareJobRunner
from screamingface_engine.runs.driver import DriverSettings, RunDrivers
from screamingface_engine.runs.store import TortoiseRunStore
from url4.streaming.interfaces import JobStatus
from url4.streaming.protocol import OutboundFrame

SETTINGS = DriverSettings(
    inflight=8,
    lease_s=60,
    tick_s=15,
    outcome_grace_s=120,
    orphan_grace_s=120,
    job_deadline_s=57_600,
    retry_s=5,
)


class DriverRunner(IdentityAwareJobRunner):
    """Records each start with all its arguments; refuses, stops and answers as scripted."""

    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []
        # Raised, in order, by the next schedule calls; None lets a call through.
        self.refusals: list[BaseException | None] = []
        self.stopped: list[str] = []
        self.failing_stops = 0
        self.frames: dict[str, OutboundFrame] = {}
        # Run inside `schedule`, before it records: lets a test land a stop mid-start.
        self.during_schedule: Callable[[str], Awaitable[None]] | None = None

    async def schedule(self, topic: str, url4: str, deadline_s: int, **kwargs: Any) -> str:
        if self.during_schedule is not None:
            await self.during_schedule(topic)
        if self.refusals:
            refusal = self.refusals.pop(0)
            if refusal is not None:
                raise refusal
        self.starts.append({"topic": topic, "url4": url4, "deadline_s": deadline_s, **kwargs})
        return topic

    async def stop(self, topic: str) -> None:
        await self.stop_bound(topic)

    async def stop_bound(self, topic: str) -> None:
        if self.failing_stops:
            self.failing_stops -= 1
            raise QueueReadError("the queue's tail could not be read")
        self.stopped.append(topic)

    async def exists(self, topic: str) -> bool:
        return False

    async def status(self, topic: str) -> JobStatus:
        return "not_found"

    async def last_frame(self, topic: str) -> OutboundFrame | None:
        return self.frames.get(topic)


def drivers(
    store: TortoiseRunStore,
    runner: DriverRunner,
    clock: Callable[[], Any],
    settings: DriverSettings = SETTINGS,
) -> RunDrivers:
    return RunDrivers(store, runner, stream=InMemoryEventStream(), settings=settings, clock=clock)
