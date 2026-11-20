"""E5 P2 spec R1, R2 and R4: the App starts its Run drivers with Runs, and stops them first.

FEATURE: a detached Run (OME-1837). STORY: as a researcher whose Engine restarts mid-Run, my Run
resumes with the same Candidates, and none starts twice.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from run_driver_support import DriverRunner
from run_registry_support import start_spec

from screamingface_engine.adapters.memory import InMemoryCandidateOutcomeStream, InMemoryEventStream
from screamingface_engine.config import Settings
from screamingface_engine.runner_queue import RunQueueUnavailable
from screamingface_engine.runs.records import owner_key
from screamingface_engine.runs.wiring import install_runs

OWNER = owner_key("local")


def _app(settings: Settings, runner: DriverRunner | None) -> FastAPI:
    app = FastAPI()
    install_runs(
        app,
        settings,
        InMemoryCandidateOutcomeStream(),
        local=True,
        job_runner=runner,
        events=InMemoryEventStream(),
    )
    return app


async def _until(check: object, what: str) -> None:
    for _ in range(300):
        if check():  # type: ignore[operator]
            return
        await asyncio.sleep(0.01)
    raise AssertionError(what)


def test_the_app_drives_a_registered_run(tmp_path: Path) -> None:
    settings = Settings(database_url=f"sqlite://{tmp_path}/engine.sqlite3")
    runner = DriverRunner()
    app = _app(settings, runner)

    with TestClient(app) as client:
        assert client.portal is not None
        store = app.state.run_registry
        client.portal.call(store.register, OWNER, start_spec("a", "b", owner_email=None))
        client.portal.call(app.state.run_drivers.wake)
        client.portal.call(_until, lambda: len(runner.starts) == 2, "the Run was never started")

    assert app.state.run_driver_task is None


def test_an_app_restart_resumes_the_run_with_the_same_topics(tmp_path: Path) -> None:
    """R2: a Candidate whose start never landed is started again under its own topic."""
    settings = Settings(database_url=f"sqlite://{tmp_path}/engine.sqlite3")
    down = DriverRunner()
    down.refusals = [RunQueueUnavailable("the queue is down")] * 100
    first = _app(settings, down)
    with TestClient(first) as client:
        assert client.portal is not None
        store = first.state.run_registry
        run, _ = client.portal.call(store.register, OWNER, start_spec("a", owner_email=None))

        async def bound() -> str:
            for _ in range(300):
                plan = await store.pending_starts(run.id)
                if plan is not None and plan.pending and plan.pending[0].topic is not None:
                    return plan.pending[0].topic
                await asyncio.sleep(0.01)
            raise AssertionError("the Candidate was never bound")

        client.portal.call(first.state.run_drivers.wake)
        topic = client.portal.call(bound)

    up = DriverRunner()
    second = _app(settings, up)
    with TestClient(second) as client:
        assert client.portal is not None
        client.portal.call(_until, lambda: bool(up.starts), "the Run did not resume")

    assert [start["topic"] for start in up.starts] == [topic]


def test_without_a_job_runner_no_run_is_driven(tmp_path: Path) -> None:
    settings = Settings(database_url=f"sqlite://{tmp_path}/engine.sqlite3")
    app = _app(settings, None)

    with TestClient(app):
        assert app.state.run_drivers is None
