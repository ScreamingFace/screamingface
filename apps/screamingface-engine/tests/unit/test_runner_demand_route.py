"""`GET /runner-demand`: the claimable-demand body the KEDA `metrics-api` trigger reads (spec D3).

WHY these tests pin the status codes: a 200 with a made-up number, or a 0 for "no sample", would
scale a loaded pool down to its minimum. Every answer here must come from a sample that was read.
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
READINGS = [BucketReading(4, 4, 4), BucketReading(4, 0, 4), BucketReading(0, 1, 4), None]


class _Source:
    async def bucket_readings(self) -> list[BucketReading | None]:
        return list(READINGS)


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


def _sampled(clock: _Clock) -> RunnerDemandSampler:
    s = RunnerDemandSampler(_Source(), stale_s=30.0, clock=clock)
    asyncio.run(s.sample())
    return s


def test_no_sampler_answers_404_disabled() -> None:
    r = _client(None).get("/runner-demand")

    assert r.status_code == 404
    assert r.json() == {"status": "disabled"}


def test_no_sample_yet_answers_503_never_zero() -> None:
    r = _client(RunnerDemandSampler(_Source(), stale_s=30.0, clock=_Clock())).get("/runner-demand")

    assert r.status_code == 503
    assert r.json() == {"status": "stale", "age_s": None}


def test_a_stale_sample_answers_503() -> None:
    clock = _Clock()
    s = _sampled(clock)
    clock.now = T0 + timedelta(seconds=31)

    r = _client(s).get("/runner-demand")

    assert r.status_code == 503
    assert r.json() == {"status": "stale", "age_s": 31.0}


def test_a_fresh_sample_answers_the_exact_body() -> None:
    clock = _Clock()
    s = _sampled(clock)
    clock.now = T0 + timedelta(seconds=2.5)

    r = _client(s).get("/runner-demand")

    assert r.status_code == 200
    assert r.json() == {
        "demand": 9,
        "running": 8,
        "claimable": 1,
        "queued": 5,
        "unbound_buckets": 1,
        "sampled_at": "2026-11-10T12:00:00Z",
        "age_s": 2.5,
    }


def test_the_body_holds_aggregate_counts_only() -> None:
    clock = _Clock()
    s = _sampled(clock)
    clock.now = T0 + timedelta(seconds=2.5)

    r = _client(s).get("/runner-demand")

    assert set(r.json()) == {
        "demand",
        "running",
        "claimable",
        "queued",
        "unbound_buckets",
        "sampled_at",
        "age_s",
    }
    assert "url4-runners" not in r.text
    assert "url4-runq" not in r.text


def test_the_route_needs_no_credential_and_is_not_in_the_schema() -> None:
    client = _client(_sampled(_Clock()))

    assert client.get("/runner-demand").status_code == 200
    assert "/runner-demand" not in client.get("/openapi.json").json()["paths"]
