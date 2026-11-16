"""`RunnerDemandSampler`: the last good sample, its age, and the stale window (spec D2, D3)."""

from datetime import UTC, datetime, timedelta

import pytest

from screamingface_engine.runner_demand import DemandSource, RunnerDemand, RunnerDemandSampler
from screamingface_engine.runner_queue import BucketReading

T0 = datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC)
READINGS = [
    BucketReading(4, 4, 4),
    BucketReading(4, 0, 4),
    BucketReading(0, 1, 4),
    None,
]
EXPECTED = RunnerDemand(demand=9, running=8, claimable=1, queued=5, unbound_buckets=1)


class _Source:
    def __init__(self, readings: list[BucketReading | None]) -> None:
        self.readings = readings
        self.error: Exception | None = None
        self.calls = 0

    async def bucket_readings(self) -> list[BucketReading | None]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.readings)


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _sampler(source: _Source, clock: _Clock, stale_s: float = 30.0) -> RunnerDemandSampler:
    return RunnerDemandSampler(source, stale_s=stale_s, clock=clock)


def test_before_any_sample_nothing_is_fresh() -> None:
    clock = _Clock()
    s = _sampler(_Source(READINGS), clock)

    assert s.snapshot() is None
    assert s.fresh() is None
    assert s.age_s() is None


@pytest.mark.asyncio
async def test_a_sample_is_fresh_with_its_age() -> None:
    clock = _Clock()
    s = _sampler(_Source(READINGS), clock)

    await s.sample()

    clock.now = T0 + timedelta(seconds=2)
    assert s.fresh() == (EXPECTED, T0, 2.0)
    assert s.snapshot() == (EXPECTED, T0)
    assert s.age_s() == 2.0


@pytest.mark.asyncio
async def test_a_failed_sample_raises_and_keeps_the_last_good_sample() -> None:
    clock = _Clock()
    source = _Source(READINGS)
    s = _sampler(source, clock)
    await s.sample()

    source.error = RuntimeError("broker down")
    clock.now = T0 + timedelta(seconds=10)
    with pytest.raises(RuntimeError):
        await s.sample()

    assert s.snapshot() == (EXPECTED, T0)
    assert s.fresh() == (EXPECTED, T0, 10.0)


@pytest.mark.asyncio
async def test_the_kept_sample_turns_stale_after_stale_s() -> None:
    clock = _Clock()
    source = _Source(READINGS)
    s = _sampler(source, clock)
    await s.sample()

    source.error = RuntimeError("broker down")
    with pytest.raises(RuntimeError):
        await s.sample()

    clock.now = T0 + timedelta(seconds=30)
    assert s.fresh() == (EXPECTED, T0, 30.0)

    clock.now = T0 + timedelta(seconds=30.5)
    assert s.fresh() is None
    assert s.snapshot() == (EXPECTED, T0)
    assert s.age_s() == 30.5


@pytest.mark.asyncio
async def test_a_source_error_before_any_sample_leaves_nothing() -> None:
    clock = _Clock()
    source = _Source(READINGS)
    source.error = RuntimeError("broker down")
    s = _sampler(source, clock)

    with pytest.raises(RuntimeError):
        await s.sample()

    assert s.snapshot() is None


@pytest.mark.asyncio
async def test_a_clock_behind_the_sample_reads_as_age_zero() -> None:
    clock = _Clock()
    s = _sampler(_Source(READINGS), clock)
    await s.sample()

    clock.now = T0 - timedelta(seconds=5)
    assert s.age_s() == 0.0
    assert s.fresh() == (EXPECTED, T0, 0.0)


def test_anything_with_bucket_readings_is_a_demand_source() -> None:
    assert isinstance(_Source([]), DemandSource) is True
    assert isinstance(object(), DemandSource) is False


def test_stale_s_is_exposed() -> None:
    assert _sampler(_Source(READINGS), _Clock(), stale_s=12.0).stale_s == 12.0
