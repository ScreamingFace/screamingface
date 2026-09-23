"""`active_count` is the gauge its docstring always claimed to be (OME-942).

`InProcessJobRunner.active_count()` is the admission gate's own input — the number of runs in
flight, and the number `max_concurrent_runs` is compared against. Its docstring said it was
"what `/metrics` would report"; no collector ever read it, so the one number that says whether
the App is at its admission ceiling was visible only to the code that enforced it. An operator
watching runs get refused had no series to look at.

OWNER DECISION (2026-09-17): register it.

NOT done, deliberately: nothing here adds a scrape endpoint to the run mode. The gauge is
served by the App's existing `/metrics`, so the one-shot Job doctrine (`check_layering.py`)
is untouched.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from screamingface_engine.app import create_app

_GAUGE = "screamingface_engine_active_runs"


class _RunnerWithActiveCount:
    """Shaped like `InProcessJobRunner` for the one method the collector reads."""

    def __init__(self, active: int = 0) -> None:
        self.active = active

    def active_count(self) -> int:
        return self.active


class _QueueShapedRunner:
    """The queue runner: schedules onto a worker pool, so it has no in-process count."""


def _samples(body: str, name: str) -> list[float]:
    """Every sample value published under `name`, read from the parsed exposition."""
    values: list[float] = []
    for family in text_string_to_metric_families(body):
        for sample in family.samples:
            if sample.name == name:
                values.append(sample.value)
    return values


def _scrape(client: TestClient) -> str:
    response = client.get("/metrics")
    assert response.status_code == 200
    return response.text


def test_the_in_flight_run_count_is_exposed() -> None:
    # STORY: as the operator watching runs get refused, I can see the App is at its ceiling.
    runner = _RunnerWithActiveCount(active=2)
    with TestClient(create_app(job_runner=cast(Any, runner))) as client:
        assert _samples(_scrape(client), _GAUGE) == [2.0]


def test_the_gauge_is_documented() -> None:
    """A bare number in an exposition is unusable — the HELP text is what tells the next
    operator what they are looking at."""
    runner = _RunnerWithActiveCount(active=1)
    with TestClient(create_app(job_runner=cast(Any, runner))) as client:
        families = [
            family
            for family in text_string_to_metric_families(_scrape(client))
            if family.name == _GAUGE
        ]

    assert len(families) == 1
    assert families[0].type == "gauge"
    assert families[0].documentation.strip() != ""


def test_the_gauge_follows_the_runner_rather_than_a_captured_value() -> None:
    """INVARIANT: registered through a getter and read at SCRAPE time. A value captured at
    `create_app` would report the boot-time zero forever — a permanently-green series, which
    is worse than none."""
    runner = _RunnerWithActiveCount(active=0)
    with TestClient(create_app(job_runner=cast(Any, runner))) as client:
        assert _samples(_scrape(client), _GAUGE) == [0.0]

        runner.active = 3

        assert _samples(_scrape(client), _GAUGE) == [3.0]


def test_zero_in_flight_runs_is_reported_as_zero_not_omitted() -> None:
    """An idle App is a real reading, unlike the queue depth's cold start: `active_count` is
    authoritative from the first moment the runner exists."""
    runner = _RunnerWithActiveCount(active=0)
    with TestClient(create_app(job_runner=cast(Any, runner))) as client:
        assert _samples(_scrape(client), _GAUGE) == [0.0]


def test_a_runner_with_no_in_process_count_exposes_no_series() -> None:
    """INVARIANT: absence, never a confident 0. The queue runner's runs execute in the worker
    pool, so a 0 here would read as "nothing is running" for a fleet that is saturated."""
    with TestClient(create_app(job_runner=cast(Any, _QueueShapedRunner()))) as client:
        assert _samples(_scrape(client), _GAUGE) == []


def test_an_app_with_no_runner_exposes_no_series() -> None:
    """A stream-only App schedules nothing; /metrics must not depend on wiring order."""
    with TestClient(create_app()) as client:
        assert _samples(_scrape(client), _GAUGE) == []
