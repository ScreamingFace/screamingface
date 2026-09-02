"""The App-side queue metrics (OME-1092): depth, oldest-unclaimed age, and the
max-deliveries advisories.

The queue is the substrate's admission and liveness surface: depth is how far behind the
fleet is, and the oldest-unclaimed age is the run that has waited longest for a worker —
the alert that would have fired on 2026-09-01, when a stuck pool left runs queued forever.
Both are read from the queue runner's CACHED snapshot (sync, no broker round trip at
scrape time), and the max-deliveries counter is the queue's terminal-failure signal.
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from prometheus_client import CollectorRegistry

from screamingface_engine.adapters.max_deliveries import MaxDeliveriesAdvisor
from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.metrics import (
    Metrics,
    build_metrics,
    register_max_deliveries_metrics,
    register_queue_metrics,
)

T0 = datetime(2026, 9, 2, 9, 0, 0, tzinfo=UTC)


class _FakeQueue:
    def __init__(self, *, depth: int = 0, oldest_age: float | None = None) -> None:
        self._depth = depth
        self._oldest_age = oldest_age

    async def publish(self, message: bytes, *, identity: Mapping[str, str] | None = None) -> None:
        raise NotImplementedError

    async def depth(self) -> int:
        return self._depth

    async def oldest_age(self) -> float | None:
        return self._oldest_age


class _FakePublisher:
    async def last_frame(self, topic: str) -> None:
        return None

    async def stream_exists(self, topic: str) -> bool:
        return False

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: object) -> None:
        pass

    async def flush(self) -> None:
        pass


class _FakeControl:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> object:
        raise TimeoutError


def _runner(depth: int, oldest_age: float | None) -> QueueJobRunner:
    return QueueJobRunner(
        queue=_FakeQueue(depth=depth, oldest_age=oldest_age),
        publisher=_FakePublisher(),
        control=_FakeControl(),
        clock=lambda: T0,
        capability_lifetime_s=100.0,
    )


def _collector_values(metrics: Metrics, name: str) -> list[float]:
    return [
        sample.value
        for metric in metrics.registry.collect()
        for sample in metric.samples
        if sample.name == name
    ]


def test_the_queue_snapshot_exposes_the_cached_depth_and_age() -> None:
    runner = _runner(depth=7, oldest_age=123.0)

    # No reading yet: the snapshot is empty until the first refresh.
    assert runner.queue_snapshot() == (None, None)

    import asyncio

    async def _refresh() -> None:
        await runner._refresh_if_stale()  # noqa: SLF001

    asyncio.run(_refresh())

    assert runner.queue_snapshot() == (7, 123.0)


def test_the_queue_collector_renders_depth_and_oldest_unclaimed_age() -> None:
    metrics = build_metrics()
    runner = _runner(depth=7, oldest_age=123.0)

    import asyncio

    async def _refresh() -> None:
        await runner._refresh_if_stale()  # noqa: SLF001

    asyncio.run(_refresh())
    register_queue_metrics(metrics, lambda: runner)

    assert _collector_values(metrics, "screamingface_engine_queue_depth") == [7.0]
    assert _collector_values(metrics, "screamingface_engine_queue_oldest_unclaimed_age_s") == [
        123.0
    ]


def test_the_queue_collector_renders_zero_depth_when_nothing_is_queued() -> None:
    metrics = build_metrics()
    register_queue_metrics(metrics, lambda: _runner(depth=0, oldest_age=None))

    assert _collector_values(metrics, "screamingface_engine_queue_depth") == [0.0]
    # An empty queue has no oldest message — the age series is absent, not a stale zero.
    assert _collector_values(metrics, "screamingface_engine_queue_oldest_unclaimed_age_s") == []


def test_the_queue_collector_is_a_no_op_without_a_queue_runner() -> None:
    metrics = build_metrics()
    register_queue_metrics(metrics, lambda: None)

    assert _collector_values(metrics, "screamingface_engine_queue_depth") == []


def test_the_max_deliveries_collector_renders_the_advisory_counter() -> None:
    metrics = build_metrics()
    advisor = MaxDeliveriesAdvisor("nats://localhost:4222", clock=lambda: T0)
    advisor.advisories_total = 3
    register_max_deliveries_metrics(metrics, lambda: advisor)

    assert _collector_values(metrics, "screamingface_engine_max_deliveries_advisories_total") == [
        3.0
    ]


def test_the_max_deliveries_collector_is_a_no_op_without_an_advisor() -> None:
    metrics = build_metrics()
    register_max_deliveries_metrics(metrics, lambda: None)

    assert _collector_values(metrics, "screamingface_engine_max_deliveries_advisories_total") == []


def test_the_metrics_are_registered_on_the_apps_own_registry() -> None:
    """The queue collectors register on the App's per-instance registry, never the global
    default — the same rule as the catalog/reaper collectors, so repeated `create_app` calls
    in tests cannot collide."""
    registry = CollectorRegistry()
    metrics = Metrics(registry=registry, requests=build_metrics().requests)
    register_queue_metrics(metrics, lambda: None)
    register_max_deliveries_metrics(metrics, lambda: None)

    assert _collector_values(metrics, "screamingface_engine_queue_depth") == []
