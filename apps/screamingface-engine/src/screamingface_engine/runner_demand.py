"""Claimable runner demand: the signal the runner pool autoscales on (runner-pool autoscaling,
spec D1-D3).

The App reads every bucket's durable consumer on its own cadence (`RunnerDemandSampler`), turns
the readings into one number (`claimable_demand`), and serves it on `GET /runner-demand` for a
KEDA `metrics-api` trigger. The chart's ScaledObject keeps `replicas = ceil(demand / workerSlots)`.

LAYERING: CONTROL PLANE (`check_layering.py` lists it). It imports the shared leaf `runner_queue`
for `BucketReading`, and `runner_queue` must never import this module. It imports nothing from
`adapters` or `app`: the queue runner reaches it only through the `DemandSource` protocol.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from screamingface_engine.runner_queue import BucketReading


@dataclass(frozen=True, slots=True)
class RunnerDemand:
    """One demand reading across all buckets.

    demand = running + claimable: the scale signal.
    running = sum of num_ack_pending over the buckets: runs executing now.
    claimable = queued runs a new pod could claim now: per bucket, min(queued, headroom), where
        headroom = max(0, max_ack_pending - running). A bucket with no cap has headroom = queued.
    queued = sum of num_pending over the bound buckets, held-back runs included (operators only).
    unbound_buckets = consumers that no worker has bound yet (they add 0).
    """

    demand: int
    running: int
    claimable: int
    queued: int
    unbound_buckets: int


def claimable_demand(readings: Sequence[BucketReading | None]) -> RunnerDemand:
    """Turn per-bucket readings into one `RunnerDemand` (spec D1).

    WHY not the stream message count: runs that a bucket's `max_ack_pending` holds back cannot be
    claimed by ANY pod, so counting them adds pods that stay idle. Spec scenario: A and B are at
    their cap of 4 with 4 runs queued each, and C has n runs queued. The stream count is 16 + n
    (5 pods), but only one new pod can do work. Here demand = 8 + min(n, 4), so 3 pods.
    """
    running = 0
    queued = 0
    claimable = 0
    unbound = 0
    for r in readings:
        if r is None:
            unbound += 1
            continue
        # A running count above a lowered cap gives 0 headroom, never a negative one.
        headroom = r.queued if r.max_ack_pending <= 0 else max(0, r.max_ack_pending - r.running)
        running += r.running
        queued += r.queued
        claimable += min(r.queued, headroom)
    return RunnerDemand(
        demand=running + claimable,
        running=running,
        claimable=claimable,
        queued=queued,
        unbound_buckets=unbound,
    )


@runtime_checkable
class DemandSource(Protocol):
    """Anything that reads every bucket's consumer. `QueueJobRunner` satisfies it structurally,
    even over a queue that cannot read buckets, so the composition root also checks the runner's
    `reads_buckets` before it installs the sampler. The in-process runner does not satisfy it (it
    has no queue)."""

    async def bucket_readings(self) -> list[BucketReading | None]: ...


class RunnerDemandSampler:
    """One per App process. It keeps the LAST GOOD sample with its time.

    A failed `sample()` raises and leaves the old sample in place, which ages out to stale.
    INVARIANT: `fresh()` never returns a reading older than `stale_s`, so `/runner-demand` never
    answers a 0 it did not read. `stale_s` > 0 is enforced by `Settings`.
    """

    def __init__(
        self,
        source: DemandSource,
        *,
        stale_s: float,
        clock: Callable[[], datetime],
    ) -> None:
        self._source = source
        self.stale_s = stale_s
        self._clock = clock
        self._last: tuple[RunnerDemand, datetime] | None = None

    async def sample(self) -> None:
        readings = await self._source.bucket_readings()
        self._last = (claimable_demand(readings), self._clock())

    def snapshot(self) -> tuple[RunnerDemand, datetime] | None:
        return self._last

    def age_s(self) -> float | None:
        return None if self._last is None else self._age(self._last[1])

    def fresh(self) -> tuple[RunnerDemand, datetime, float] | None:
        """(demand, sampled_at, age_s) of the last good sample, from ONE read; None when there is
        no sample or it is older than `stale_s`."""
        if self._last is None:
            return None
        demand, sampled_at = self._last
        age = self._age(sampled_at)
        return None if age > self.stale_s else (demand, sampled_at, age)

    def _age(self, sampled_at: datetime) -> float:
        # A clock that stepped back reads as age 0, never a negative age.
        return max(0.0, (self._clock() - sampled_at).total_seconds())


__all__ = ["DemandSource", "RunnerDemand", "RunnerDemandSampler", "claimable_demand"]
