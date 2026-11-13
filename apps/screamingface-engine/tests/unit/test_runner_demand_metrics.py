"""The runner-demand gauges (runner-pool autoscaling, spec D3): read from the sampler's last good
sample, absent before the first sample, and the age keeps growing after a failed sample."""

from datetime import UTC, datetime, timedelta

import pytest

from screamingface_engine.metrics import Metrics, build_metrics, register_runner_demand_metrics
from screamingface_engine.runner_demand import RunnerDemandSampler
from screamingface_engine.runner_queue import BucketReading

T0 = datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC)
READINGS = [
    BucketReading(4, 4, 4),
    BucketReading(4, 0, 4),
    BucketReading(0, 1, 4),
    None,
]
NAMES = [
    "screamingface_engine_runner_demand",
    "screamingface_engine_runner_demand_running",
    "screamingface_engine_runner_demand_claimable",
    "screamingface_engine_runner_demand_queued",
    "screamingface_engine_runner_demand_unbound_buckets",
    "screamingface_engine_runner_demand_sample_age_s",
]


def _collector_values(metrics: Metrics, name: str) -> list[float]:
    return [
        sample.value
        for metric in metrics.registry.collect()
        for sample in metric.samples
        if sample.name == name
    ]


class _Source:
    def __init__(self, readings: list[BucketReading | None]) -> None:
        self.readings = readings
        self.error: Exception | None = None

    async def bucket_readings(self) -> list[BucketReading | None]:
        if self.error is not None:
            raise self.error
        return list(self.readings)


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def test_no_sampler_exports_no_series() -> None:
    metrics = build_metrics()
    register_runner_demand_metrics(metrics, lambda: None)

    for name in NAMES:
        assert _collector_values(metrics, name) == []


def test_no_series_before_the_first_sample() -> None:
    metrics = build_metrics()
    sampler = RunnerDemandSampler(_Source(READINGS), stale_s=30.0, clock=_Clock())
    register_runner_demand_metrics(metrics, lambda: sampler)

    for name in NAMES:
        assert _collector_values(metrics, name) == []


@pytest.mark.asyncio
async def test_all_six_gauges_after_a_sample() -> None:
    metrics = build_metrics()
    clock = _Clock()
    sampler = RunnerDemandSampler(_Source(READINGS), stale_s=30.0, clock=clock)
    register_runner_demand_metrics(metrics, lambda: sampler)

    await sampler.sample()
    clock.now = T0 + timedelta(seconds=2)

    assert _collector_values(metrics, "screamingface_engine_runner_demand") == [9.0]
    assert _collector_values(metrics, "screamingface_engine_runner_demand_running") == [8.0]
    assert _collector_values(metrics, "screamingface_engine_runner_demand_claimable") == [1.0]
    assert _collector_values(metrics, "screamingface_engine_runner_demand_queued") == [5.0]
    assert _collector_values(metrics, "screamingface_engine_runner_demand_unbound_buckets") == [1.0]
    assert _collector_values(metrics, "screamingface_engine_runner_demand_sample_age_s") == [2.0]


@pytest.mark.asyncio
async def test_a_failed_sample_keeps_the_series_and_the_age_grows() -> None:
    metrics = build_metrics()
    clock = _Clock()
    source = _Source(READINGS)
    sampler = RunnerDemandSampler(source, stale_s=30.0, clock=clock)
    register_runner_demand_metrics(metrics, lambda: sampler)

    await sampler.sample()
    source.error = RuntimeError()
    with pytest.raises(RuntimeError):
        await sampler.sample()
    clock.now = T0 + timedelta(seconds=40)

    assert _collector_values(metrics, "screamingface_engine_runner_demand") == [9.0]
    assert _collector_values(metrics, "screamingface_engine_runner_demand_sample_age_s") == [40.0]
