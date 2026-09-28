"""The shared events stream's own metrics (uniform executor, PRD 01 §4 Observability):
store use, subject purges, and publish conflicts — on both the App's registry and the
worker's own.

Modelled on `test_queue_metrics.py`: the App-side collectors read a getter's return value at
scrape time, so a fake with (or missing) the right attribute is the whole fixture; nothing
here needs a real broker.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import Any

import pytest

from screamingface_engine.app import _EventsStoreMonitor
from screamingface_engine.metrics import Metrics, build_metrics, register_events_metrics
from screamingface_engine.worker.metrics import (
    build_worker_metrics,
    register_events_publish_conflicts_metrics,
)


class _FakeStream:
    """A stand-in for `_JetStreamConnection`'s metrics-relevant surface."""

    def __init__(
        self, *, snapshot: tuple[int, float] | None = None, purges: int | None = 0
    ) -> None:
        self.store_snapshot = snapshot
        if purges is not None:
            self.subject_purges = purges


class _FakePublisher:
    def __init__(self, conflicts: Counter[str] | None = None) -> None:
        if conflicts is not None:
            self.publish_conflicts = conflicts


class _RefreshableStream:
    """A fake `_JetStreamConnection` whose `refresh_store_usage` plays back a queue of
    results, each either a `(bytes, ratio)` snapshot or an exception to raise — the same
    shape a broker blip and a recovered read take turns producing."""

    def __init__(self) -> None:
        self.store_snapshot: tuple[int, float] | None = None
        self._queue: list[Any] = []

    def queue(self, outcome: Any) -> None:
        self._queue.append(outcome)

    async def refresh_store_usage(self) -> tuple[int, float]:
        outcome = self._queue.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        self.store_snapshot = outcome
        return outcome


def _samples(metrics: Metrics, name: str) -> list[tuple[dict[str, str], float]]:
    return [
        (dict(sample.labels), sample.value)
        for metric in metrics.registry.collect()
        for sample in metric.samples
        if sample.name == name
    ]


def _values(metrics: Metrics, name: str) -> list[float]:
    return [value for _, value in _samples(metrics, name)]


# --- App-side collector (_EventsStoreCollector / register_events_metrics) ------------------


def test_the_collector_renders_store_bytes_and_utilization_from_a_fake_stream() -> None:
    metrics = build_metrics()
    stream = _FakeStream(snapshot=(100, 0.25))
    register_events_metrics(metrics, lambda: stream, lambda: None)

    assert _values(metrics, "screamingface_engine_events_store_bytes") == [100.0]
    assert _values(metrics, "screamingface_engine_events_store_utilization_ratio") == [0.25]


def test_the_collector_omits_store_series_before_the_first_reading() -> None:
    """Cold start: `store_snapshot` is None until `refresh_store_usage` runs once, and a
    confident 0 would be indistinguishable from a genuinely empty store (same rule as the
    queue depth gauge)."""
    metrics = build_metrics()
    stream = _FakeStream(snapshot=None)
    register_events_metrics(metrics, lambda: stream, lambda: None)

    assert _values(metrics, "screamingface_engine_events_store_bytes") == []
    assert _values(metrics, "screamingface_engine_events_store_utilization_ratio") == []


def test_the_collector_renders_subject_purges() -> None:
    metrics = build_metrics()
    stream = _FakeStream(purges=7)
    register_events_metrics(metrics, lambda: stream, lambda: None)

    assert _values(metrics, "screamingface_engine_events_subject_purges_total") == [7.0]


def test_the_collector_omits_subject_purges_when_the_attribute_is_absent() -> None:
    metrics = build_metrics()
    stream = _FakeStream(purges=None)
    register_events_metrics(metrics, lambda: stream, lambda: None)

    assert _values(metrics, "screamingface_engine_events_subject_purges_total") == []


def test_the_collector_renders_publish_conflicts_by_writer() -> None:
    metrics = build_metrics()
    publisher = _FakePublisher(conflicts=Counter({"app": 2, "supervisor": 5}))
    register_events_metrics(metrics, lambda: None, lambda: publisher)

    samples = _samples(metrics, "screamingface_engine_events_publish_conflicts_total")
    assert dict((labels["writer"], value) for labels, value in samples) == {
        "app": 2.0,
        "supervisor": 5.0,
    }


def test_the_collector_omits_publish_conflicts_without_a_publisher() -> None:
    metrics = build_metrics()
    register_events_metrics(metrics, lambda: None, lambda: None)

    assert _values(metrics, "screamingface_engine_events_publish_conflicts_total") == []


def test_the_collector_is_a_no_op_without_a_stream_or_publisher() -> None:
    metrics = build_metrics()
    register_events_metrics(metrics, lambda: None, lambda: None)

    assert _values(metrics, "screamingface_engine_events_store_bytes") == []
    assert _values(metrics, "screamingface_engine_events_store_utilization_ratio") == []
    assert _values(metrics, "screamingface_engine_events_subject_purges_total") == []


# --- Worker-side collector (register_events_publish_conflicts_metrics) --------------------


def test_the_worker_collector_renders_publish_conflicts() -> None:
    metrics = build_worker_metrics()
    publisher = _FakePublisher(conflicts=Counter({"supervisor": 3}))
    register_events_publish_conflicts_metrics(metrics, publisher)

    samples = [
        (dict(sample.labels), sample.value)
        for metric in metrics.registry.collect()
        for sample in metric.samples
        if sample.name == "screamingface_engine_events_publish_conflicts_total"
    ]
    assert samples == [({"writer": "supervisor"}, 3.0)]


def test_the_worker_collector_omits_publish_conflicts_without_a_publisher() -> None:
    metrics = build_worker_metrics()
    register_events_publish_conflicts_metrics(metrics, None)

    samples = [
        sample
        for metric in metrics.registry.collect()
        for sample in metric.samples
        if sample.name == "screamingface_engine_events_publish_conflicts_total"
    ]
    assert samples == []


# --- The store-usage monitor tick (_EventsStoreMonitor) -----------------------------------


def test_a_tick_refreshes_the_stream_snapshot() -> None:
    stream = _RefreshableStream()
    stream.queue((512, 0.5))
    monitor = _EventsStoreMonitor(stream)

    asyncio.run(monitor.tick())

    assert stream.store_snapshot == (512, 0.5)


def test_a_raising_refresh_does_not_raise_and_leaves_the_previous_snapshot() -> None:
    stream = _RefreshableStream()
    stream.store_snapshot = (100, 0.1)
    stream.queue(RuntimeError("broker unreachable"))
    monitor = _EventsStoreMonitor(stream)

    asyncio.run(monitor.tick())  # must not raise

    assert stream.store_snapshot == (100, 0.1)


def test_the_monitor_recovers_on_the_next_tick_after_a_failure() -> None:
    stream = _RefreshableStream()
    stream.queue(RuntimeError("broker unreachable"))
    stream.queue((2048, 0.9))
    monitor = _EventsStoreMonitor(stream)

    asyncio.run(monitor.tick())
    asyncio.run(monitor.tick())

    assert stream.store_snapshot == (2048, 0.9)


def test_the_monitor_logs_a_warning_once_per_failure_streak(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stream = _RefreshableStream()
    stream.queue(RuntimeError("boom"))
    stream.queue(RuntimeError("boom again"))
    monitor = _EventsStoreMonitor(stream)

    with caplog.at_level(logging.WARNING, logger="screamingface_engine.app"):
        asyncio.run(monitor.tick())
        asyncio.run(monitor.tick())

    warnings = [r for r in caplog.records if "refresh failed" in r.message]
    assert len(warnings) == 1
