"""The warm child pool's observability (uniform executor PRD 03 §4 Non-functional
requirements): `build_worker_metrics()` exposes the four warm-pool metric names, and
`WarmChildPool` actually drives them — `warm_children` to the idle count, and
`warm_spawn_failures_total` on a spawn failure.

A tiny scripted fake child speaks the READY half of the protocol on an in-memory control
pipe — trimmed from `test_warm_pool.py`'s `_FakeChild`/`_Spawner`, which drive the full
hand-off protocol this test does not need.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from screamingface_engine import child_protocol as cp
from screamingface_engine.worker.metrics import build_worker_metrics
from screamingface_engine.worker.warm_pool import WarmChildPool, WarmHandle


@dataclass
class _FakeChild:
    """Reaches READY on construction and is never assigned a run — this test only drives
    the warming path (spawn -> READY -> idle), not the claim hand-off."""

    pid: int
    returncode: int | None = None
    control: asyncio.StreamReader = field(default_factory=asyncio.StreamReader)
    stdin: Any = None
    stdout: Any = None
    stderr: Any = None

    def __post_init__(self) -> None:
        self.control.feed_data(cp.encode_ready(pid=self.pid, world_ok=True))
        self._exited = asyncio.Event()

    async def wait(self) -> int:
        # Blocks until `terminate`/`kill` (drain) — an idle child that "exits" the moment it
        # is awaited would look, to `_watch_idle`, exactly like a real child dying: the pool
        # would immediately count a warm failure and replenish, never settling at `size` idle.
        await self._exited.wait()
        return self.returncode or 0

    def terminate(self) -> None:
        self.returncode = -15
        self._exited.set()

    def kill(self) -> None:
        self.returncode = -9
        self._exited.set()


class _Spawner:
    """Hands out scripted children in order; the first `fail` calls raise OSError instead
    (a warm spawn that never started — WC-D5)."""

    def __init__(self, *children: _FakeChild, fail: int = 0) -> None:
        self._children = list(children)
        self._fail = fail

    async def __call__(self) -> WarmHandle:
        if self._fail:
            self._fail -= 1
            raise OSError("exec failed")
        child = self._children.pop(0)
        return WarmHandle(proc=child, control=child.control)  # type: ignore[arg-type]


class _NoBackoffSleep:
    """Replaces the real 1s/2s/… backoff with a scheduling yield, so the failure test does
    not actually wait out the delay."""

    async def __call__(self, delay: float) -> None:
        await asyncio.sleep(0)


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


def _sample_values(registry: Any, name: str) -> list[float]:
    return [
        sample.value
        for metric in registry.collect()
        for sample in metric.samples
        if sample.name == name
    ]


def test_build_worker_metrics_exposes_the_warm_pool_metric_names() -> None:
    """The four PRD-03 metrics must be on the worker's scrape surface, like every other
    worker metric (`test_worker_metrics.py`'s
    `test_the_worker_metrics_live_on_their_own_registry`)."""
    from prometheus_client import generate_latest

    metrics = build_worker_metrics()
    body = generate_latest(metrics.registry).decode()

    for name in (
        "screamingface_engine_worker_warm_children",
        "screamingface_engine_worker_warm_spawn_failures_total",
        "screamingface_engine_worker_handoff_latency_s",
        "screamingface_engine_worker_child_boot_s",
    ):
        assert name in body, f"{name} missing from the worker's scrape surface"


@pytest.mark.asyncio
async def test_a_started_pool_reports_the_idle_count_on_warm_children() -> None:
    """WC-H1: warming 2 children sets the gauge to 2, matching `pool.idle_count`."""
    metrics = build_worker_metrics()
    pool = WarmChildPool(
        spawn_warm=_Spawner(_FakeChild(1), _FakeChild(2)),
        size=2,
        metrics=metrics,
    )
    pool.start()
    await _settle()

    assert pool.idle_count == 2
    assert _sample_values(metrics.registry, "screamingface_engine_worker_warm_children") == [2.0]
    await pool.drain()


@pytest.mark.asyncio
async def test_a_spawn_oserror_increments_warm_spawn_failures() -> None:
    """WC-D5: a warm spawn that raises OSError counts a failure and the pool still recovers
    (the next scripted child warms after the backoff)."""
    metrics = build_worker_metrics()
    pool = WarmChildPool(
        spawn_warm=_Spawner(_FakeChild(1), fail=1),
        size=1,
        sleep=_NoBackoffSleep(),
        metrics=metrics,
    )
    pool.start()
    await _settle()

    assert _sample_values(
        metrics.registry, "screamingface_engine_worker_warm_spawn_failures_total"
    ) == [1.0]
    assert pool.idle_count == 1
    await pool.drain()
