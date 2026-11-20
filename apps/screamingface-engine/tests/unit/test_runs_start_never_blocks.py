"""E5 P2 spec §4.1 (`GET /`) and D16: a raw start never touches the Run registry, so a Run's
history never blocks it, and the `X-SF-Run` headers a Client from before P2 sends bind nothing.

FEATURE: a detached Run (OME-1837). STORY: as a researcher on a released Client, my evaluation
starts on a P2 Engine whatever its Run history says, even when its database stops answering.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
)
from test_runs_routes import ALICE, BOB, UNKNOWN, _Engine

from screamingface_engine.runs.records import owner_key

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


async def test_runs_off_ignores_a_malformed_binding() -> None:
    engine = _Engine(None)

    resp = await engine.start("topic-a", **{"X-SF-Run-Candidate": "0"})

    assert resp.status_code == 202
    assert len(engine.runner.scheduled) == 1


@pytest.mark.parametrize(
    ("who", "candidate"),
    [
        ("own", "0"),
        ("foreign", "0"),
        ("unknown", "0"),
        ("canceled", "0"),
        ("own", "x"),
        ("own", None),
    ],
    ids=["own", "foreign", "unknown", "canceled", "bad-index", "no-index"],
)
async def test_a_start_that_names_a_run_runs_as_a_plain_start(
    registry: Registry, who: str, candidate: str | None
) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create()).json()["id"]
    if who == "canceled":
        await engine.client.delete(f"/runs/{run_id}", headers=ALICE)
    named = UNKNOWN if who == "unknown" else run_id
    headers = BOB if who == "foreign" else {}

    resp = await engine.start("topic-a", named, candidate=candidate, **headers)

    assert resp.status_code == 202
    assert [s.topic for s in engine.runner.scheduled] == ["topic-a"]
    run = await registry.store.get(owner_key(ALICE["X-User-Email"]), run_id)
    assert run is not None
    assert {c.attempt_id for c in run.candidates} == {None}


class _Hangs:
    """A registry none of whose calls ever answers."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def __getattr__(self, name: str) -> Any:
        return self._never

    async def _never(self, *args: Any) -> Any:
        await asyncio.Event().wait()


async def test_a_hung_database_does_not_hold_a_start(registry: Registry) -> None:
    engine = _Engine(registry)
    run_id = (await engine.create()).json()["id"]
    engine.app.state.run_registry = _Hangs(registry.store)

    resp = await asyncio.wait_for(engine.start("topic-a", run_id), timeout=5)

    assert resp.status_code == 202
    assert len(engine.runner.scheduled) == 1
