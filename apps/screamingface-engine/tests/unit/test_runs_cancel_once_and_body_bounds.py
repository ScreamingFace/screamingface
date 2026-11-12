"""E5 P1 spec D2, D12: a cancel owes its stops once, the Runs lifecycle is released however the
App ends, and a refused `/runs` request answers a bounded, private Problem (OME-1785).

FEATURE: first-class Runs. STORY: as a researcher, retrying a cancel never stops twice what
already stopped, and a malformed request never gets an answer that grows with it.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

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
from test_runs_routes import ALICE, BODY, _Engine

from screamingface_engine.adapters.memory import InMemoryCandidateOutcomeStream
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


# --- a cancel owes its stops once (spec D12) -----------------------------------------------


async def test_a_retried_cancel_does_not_stop_again_what_already_stopped(
    registry: Registry,
) -> None:
    engine = _Engine(registry, runner=RecordingJobRunner())
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    await registry.store.bind(_ALICE_KEY, run_id, 0, "topic-a")
    await registry.store.mark_scheduled("topic-a")

    first = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)
    retried = await engine.client.delete(f"/runs/{run_id}", headers=ALICE)

    # The outcome has not landed yet, so the Candidate still reads live.
    assert (first.status_code, retried.status_code) == (202, 202)
    assert engine.runner.stopped == ["topic-a"]


# --- the Runs lifecycle --------------------------------------------------------------------


async def test_an_earlier_shutdown_hook_that_fails_still_releases_runs(tmp_path: Path) -> None:
    app = FastAPI()
    url = f"sqlite://{tmp_path}/engine.sqlite3"
    wiring.install_runs(
        app, Settings(database_url=url), InMemoryCandidateOutcomeStream(), local=True
    )

    async def _fails() -> None:
        raise RuntimeError("an earlier shutdown hook failed")

    app.router.on_shutdown.insert(0, _fails)

    with pytest.raises(RuntimeError, match="earlier shutdown hook"):
        async with app.router.lifespan_context(app):
            assert app.state.run_registry is not None

    assert app.state.run_registry is None
    assert (app.state.outcome_writer_task, app.state.run_sweep_task) == (None, None)
    os.close(hold_local_database(url))


def test_a_url_fragment_finds_the_same_lock(tmp_path: Path) -> None:
    url = f"sqlite://{tmp_path}/engine.sqlite3"
    held = hold_local_database(url)
    try:
        with pytest.raises(LocalDatabaseInUseError):
            hold_local_database(f"{url}#ignored")
    finally:
        os.close(held)


# --- a refused request answers a bounded, private Problem ----------------------------------


@pytest.mark.parametrize(
    "extra",
    [{f"field_{i}": 1 for i in range(5_000)}, {"x" * 100_000: 1}],
    ids=["thousands-of-fields", "a-huge-field-name"],
)
async def test_a_422_names_a_bounded_part_of_the_request(
    registry: Registry, extra: dict[str, int]
) -> None:
    engine = _Engine(registry)

    resp = await engine.client.post("/runs", json={**BODY, **extra}, headers=ALICE)

    assert resp.status_code == 422
    assert len(resp.content) < 4_096


async def test_a_body_that_is_not_utf8_is_a_private_400_problem(registry: Registry) -> None:
    engine = _Engine(registry)

    resp = await engine.client.post(
        "/runs",
        content=b'{"client_key": "k\x80"}',
        headers={"Content-Type": "application/json", **ALICE},
    )

    assert (resp.status_code, resp.json()["code"]) == (400, "malformed_body")
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert (resp.headers["Cache-Control"], resp.headers["Vary"]) == _PRIVATE


async def test_the_openapi_declares_the_private_400s() -> None:
    spec = (await _Engine(None).client.get("/openapi.json")).json()

    runs_400 = spec["paths"]["/runs"]["post"]["responses"]["400"]
    assert "application/problem+json" in runs_400["content"]
    assert runs_400["headers"].keys() == {"Cache-Control", "Vary"}
