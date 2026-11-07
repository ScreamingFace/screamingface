"""E5 P1 spec D12, R2, R9: a retried cancel finishes its stops, a binding names one Candidate,
and the Runs lifecycle releases what it took however it ends (OME-1785).

FEATURE: first-class Runs. STORY: as a researcher, I retry a cancel that failed and my Run's
Candidates are stopped; a local Engine that failed to start can be started again.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from _fakes import RecordingJobRunner
from fastapi import FastAPI
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
)
from test_runs_routes import ALICE, LIFETIME_S, SECRET, TOKEN_T0, WINDOW_S, _Engine, _record

from screamingface_engine.adapters.jetstream import QueueReadError
from screamingface_engine.adapters.memory import InMemoryCandidateOutcomeStream
from screamingface_engine.auth import JwtCodec
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.config import Settings
from screamingface_engine.runs import wiring
from screamingface_engine.runs.records import owner_key
from screamingface_engine.runs.wiring import LocalDatabaseInUseError, hold_local_database

pytestmark = pytest.mark.asyncio

_ALICE_KEY = owner_key("alice@example.org")
_PRIVATE = ("private, no-store", "X-User-Email")


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


class _StopFailsOnce(RecordingJobRunner):
    def __init__(self) -> None:
        super().__init__()
        self.attempts: list[str] = []

    async def stop(self, topic: str) -> None:
        self.attempts.append(topic)
        if len(self.attempts) == 1:
            raise QueueReadError(topic)
        await super().stop(topic)


# --- a retried cancel (spec D12) -----------------------------------------------------------


async def test_a_retried_cancel_stops_what_the_failed_one_could_not(registry: Registry) -> None:
    runner = _StopFailsOnce()
    engine = _Engine(registry, runner=runner)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    await registry.store.bind(_ALICE_KEY, run_id, 0, "topic-a")

    failed = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)
    retried = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    assert failed.status_code == 503
    assert (failed.headers["Cache-Control"], failed.headers["Vary"]) == _PRIVATE
    assert retried.status_code == 204
    assert runner.attempts == ["topic-a", "topic-a"]
    assert runner.stopped == ["topic-a"]


class _StoppedOutcomeFirst:
    """A registry whose running Candidate ends `stopped` on its own just before the cancel."""

    def __init__(self, store: Any, topic: str) -> None:
        self._store = store
        self._topic = topic

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    async def cancel(self, owner: Any, run_id: str) -> Any:
        await self._store.settle(self._topic, CandidateOutcome("stopped"))
        return await self._store.cancel(owner, run_id)


async def test_a_stopped_outcome_that_beat_the_cancel_is_not_the_cancels(
    registry: Registry,
) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    await registry.store.bind(_ALICE_KEY, run_id, 0, "topic-a")
    await registry.store.mark_scheduled("topic-a")
    engine.app.state.run_registry = _StoppedOutcomeFirst(registry.store, "topic-a")

    resp = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    assert resp.status_code == 204
    assert engine.runner.stopped == []
    assert (await _record(registry, run_id)).candidates[0].state == "stopped"


# --- a binding names one Candidate (spec R2) -----------------------------------------------


async def test_a_repeated_binding_header_is_refused(registry: Registry) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create()).json()["id"]
    token = JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(
        "topic-a", TOKEN_T0
    )
    headers = [
        ("URL4-Capability", token),
        ("Prefer", "respond-async"),
        ("X-User-Email", "alice@example.org"),
        ("X-SF-Run", run_id),
        ("X-SF-Run-Candidate", "0"),
        ("X-SF-Run-Candidate", "9999"),
    ]

    resp = await engine.client.get("/", params={"q": "gpt(hi)"}, headers=headers)

    assert (resp.status_code, resp.json()["code"]) == (400, "malformed_header")
    assert engine.runner.scheduled == []


# --- the local database's lock -------------------------------------------------------------


def test_a_symlink_to_the_database_finds_the_same_lock(tmp_path: Path) -> None:
    real = tmp_path / "engine.sqlite3"
    real.touch()
    alias = tmp_path / "alias.sqlite3"
    alias.symlink_to(real)
    held = hold_local_database(f"sqlite://{real}")
    try:
        with pytest.raises(LocalDatabaseInUseError):
            hold_local_database(f"sqlite://{alias}")
    finally:
        os.close(held)


def _lifecycle(tmp_path: Path) -> tuple[wiring._RunsLifecycle, str]:
    app = FastAPI()
    app.state.run_registry = None
    app.state.outcome_writer_task = None
    app.state.run_sweep_task = None
    url = f"sqlite://{tmp_path}/engine.sqlite3"
    lifecycle = wiring._RunsLifecycle(
        app,
        Settings(),
        InMemoryCandidateOutcomeStream(),
        url=url,
        local=True,
        writer_retry_s=1.0,
    )
    return lifecycle, url


def _local_app(tmp_path: Path) -> tuple[FastAPI, str]:
    """A bare App with local Runs installed on its own database file."""
    app = FastAPI()
    url = f"sqlite://{tmp_path}/engine.sqlite3"
    wiring.install_runs(
        app, Settings(database_url=url), InMemoryCandidateOutcomeStream(), local=True
    )
    return app, url


async def test_a_failed_start_releases_the_local_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WHY: no shutdown hook runs after a failed start, and a local Engine inside the Client's
    process lives on to start again."""

    async def _refuse(*args: object, **kwargs: object) -> object:
        raise RuntimeError("the database refused")

    monkeypatch.setattr(wiring, "open_run_store", _refuse)
    app, url = _local_app(tmp_path)

    with pytest.raises(RuntimeError, match="refused"):
        async with app.router.lifespan_context(app):
            pass

    os.close(hold_local_database(url))


class _FailingStore:
    async def aclose(self) -> None:
        raise RuntimeError("close failed")


async def test_a_failed_close_still_releases_the_local_lock(tmp_path: Path) -> None:
    lifecycle, url = _lifecycle(tmp_path)
    lifecycle._local_lock = hold_local_database(url)
    lifecycle._app.state.run_registry = _FailingStore()

    await lifecycle.stop()  # logged, so the App's later shutdown hooks still run

    os.close(hold_local_database(url))


# --- the documented contract ---------------------------------------------------------------


async def test_the_openapi_documents_bodies_problems_and_headers() -> None:
    spec = (await _Engine(None).client.get("/openapi.json")).json()

    post = spec["paths"]["/runs"]["post"]["responses"]
    delete = spec["paths"]["/runs/{run_id}"]["delete"]["responses"]
    assert "RunBody" in post["200"]["content"]["application/json"]["schema"]["$ref"]
    assert post["200"]["headers"].keys() == {"Cache-Control", "Vary"}
    assert "application/problem+json" in post["409"]["content"]
    assert "content" not in delete["202"] or not delete["202"]["content"]
    assert "Retry-After" in delete["503"]["headers"]
