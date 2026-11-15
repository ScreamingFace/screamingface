"""`GET /runner-demand` when no bucket consumer is bound: 503 `unbound`, never a 0.

WHY these tests pin the all-unbound answer: an all-unbound sample reads no demand at all. Answering
it as demand 0 would scale a loaded pool down to its minimum, so the route must refuse it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.runner_demand import RunnerDemandSampler
from screamingface_engine.runner_queue import BucketReading
from screamingface_engine.testing import InMemoryEventStream

SECRET = "runner-demand-route-secret-0123456789abcdef"
T0 = datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC)
ALL_UNBOUND: list[BucketReading | None] = [None] * 16
ONE_BOUND: list[BucketReading | None] = [BucketReading(0, 0, 4)] + [None] * 15


class _Source:
    def __init__(self, readings: list[BucketReading | None]) -> None:
        self.readings = readings

    async def bucket_readings(self) -> list[BucketReading | None]:
        return list(self.readings)


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _client(sampler: RunnerDemandSampler | None) -> TestClient:
    app = create_app(Settings(jwt_secret=SECRET), stream=InMemoryEventStream(), job_runner=None)
    if sampler is not None:
        app.state.runner_demand = sampler
    return TestClient(app)


def _sampled(readings: list[BucketReading | None], clock: _Clock) -> RunnerDemandSampler:
    s = RunnerDemandSampler(_Source(readings), stale_s=30.0, clock=clock)
    asyncio.run(s.sample())
    return s


def test_all_unbound_buckets_answer_503_unbound_never_zero() -> None:
    clock = _Clock()
    s = _sampled(ALL_UNBOUND, clock)
    clock.now = T0 + timedelta(seconds=2.5)

    r = _client(s).get("/runner-demand")

    assert r.status_code == 503
    assert r.json() == {"status": "unbound", "age_s": 2.5}


def test_no_buckets_at_all_answer_503_unbound() -> None:
    clock = _Clock()
    s = _sampled([], clock)
    clock.now = T0 + timedelta(seconds=2.5)

    r = _client(s).get("/runner-demand")

    assert r.status_code == 503
    assert r.json() == {"status": "unbound", "age_s": 2.5}


def test_one_bound_bucket_answers_200_with_its_real_zero() -> None:
    clock = _Clock()
    s = _sampled(ONE_BOUND, clock)
    clock.now = T0 + timedelta(seconds=2.5)

    r = _client(s).get("/runner-demand")

    assert r.status_code == 200
    assert r.json()["demand"] == 0
    assert r.json()["unbound_buckets"] == 15


def test_bound_is_false_before_any_sample() -> None:
    s = RunnerDemandSampler(_Source(ONE_BOUND), stale_s=30.0, clock=_Clock())

    assert s.bound() is False


def test_bound_is_true_after_a_sample_with_one_bound_bucket() -> None:
    s = _sampled(ONE_BOUND, _Clock())

    assert s.bound() is True


def test_bound_follows_the_last_sample() -> None:
    source = _Source(ONE_BOUND)
    s = RunnerDemandSampler(source, stale_s=30.0, clock=_Clock())
    asyncio.run(s.sample())

    source.readings = ALL_UNBOUND
    asyncio.run(s.sample())

    assert s.bound() is False


def test_a_stale_all_unbound_sample_answers_the_stale_503() -> None:
    clock = _Clock()
    s = _sampled(ALL_UNBOUND, clock)
    clock.now = T0 + timedelta(seconds=31)

    r = _client(s).get("/runner-demand")

    assert r.status_code == 503
    assert r.json() == {"status": "stale", "age_s": 31.0}
