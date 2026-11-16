"""GET /v1/limits serves the per-caller in-flight cap the runner enforces (OME-1314)."""

from __future__ import annotations

from collections.abc import Mapping

import httpx
import pytest
from _fakes import RecordingJobRunner
from fastapi import FastAPI
from test_inprocess_outcomes import _Executor
from test_queue_admission import _FakeQueue, _runner

from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.rest.limits import CallerLimits
from screamingface_engine.testing import InMemoryEventStream


async def _get(
    app: FastAPI, path: str, *, headers: Mapping[str, str] | None = None
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as client:
        return await client.get(path, headers=headers)


@pytest.mark.asyncio
async def test_limits_reports_the_runners_cap() -> None:
    runner = InProcessJobRunner(
        InMemoryEventStream(), lambda env: _Executor(), max_concurrent_runs=5
    )
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream(), job_runner=runner)

    response = await _get(app, "/v1/limits")

    assert response.status_code == 200
    assert response.json() == {"caller_inflight_cap": 5}


@pytest.mark.asyncio
async def test_limits_falls_back_to_the_setting_without_the_port() -> None:
    runner = RecordingJobRunner()
    assert not isinstance(runner, CallerLimits)
    app = create_app(
        Settings(jwt_secret="s", run_queue_caller_inflight_cap=11),
        stream=InMemoryEventStream(),
        job_runner=runner,
    )

    response = await _get(app, "/v1/limits")

    assert response.json() == {"caller_inflight_cap": 11}


@pytest.mark.asyncio
async def test_limits_without_a_runner_uses_the_setting() -> None:
    app = create_app(
        Settings(jwt_secret="s", run_queue_caller_inflight_cap=13),
        stream=InMemoryEventStream(),
    )

    response = await _get(app, "/v1/limits")

    assert response.json() == {"caller_inflight_cap": 13}


@pytest.mark.asyncio
async def test_the_default_cap_is_served(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("URL4_CLOUD_RUN_QUEUE_CALLER_INFLIGHT_CAP", raising=False)
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream())

    response = await _get(app, "/v1/limits")

    assert response.json() == {
        "caller_inflight_cap": Settings(jwt_secret="s").run_queue_caller_inflight_cap
    }


def test_the_queue_runner_exposes_its_enforced_cap() -> None:
    runner = _runner(_FakeQueue(), caller_inflight_cap=17)

    assert isinstance(runner, CallerLimits)
    assert runner.caller_inflight_cap == 17


def test_the_in_process_runner_exposes_its_cap() -> None:
    runner = InProcessJobRunner(
        InMemoryEventStream(), lambda env: _Executor(), max_concurrent_runs=3
    )

    assert isinstance(runner, CallerLimits)
    assert runner.caller_inflight_cap == 3


def test_limits_is_documented_in_openapi() -> None:
    schema = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream()).openapi()

    assert "/v1/limits" in schema["paths"]
    assert schema["paths"]["/v1/limits"]["get"]["tags"] == ["Catalog"]
    assert "CallerLimitsBody" in schema["components"]["schemas"]
