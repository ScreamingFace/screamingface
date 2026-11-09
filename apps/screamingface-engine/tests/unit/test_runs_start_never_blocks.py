"""E5 P1 spec §8, R2: a Run's history never blocks a start, whether Runs are off or the
database hangs (OME-1785).

FEATURE: first-class Runs. STORY: as a researcher, my evaluation starts even when the Engine's
Run history is off or its database stops answering.
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
from test_runs_routes import _Engine

from screamingface_engine.rest import runs_start

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


class _Hangs:
    """A registry whose named write never answers."""

    def __init__(self, store: Any, hung: str) -> None:
        self._store = store
        self._hung = hung

    def __getattr__(self, name: str) -> Any:
        if name == self._hung:
            return self._never
        return getattr(self._store, name)

    async def _never(self, *args: Any) -> Any:
        await asyncio.Event().wait()


@pytest.mark.parametrize("hung", ["bind", "mark_scheduled"])
async def test_a_hung_database_does_not_hold_a_bound_start(
    registry: Registry, hung: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runs_start, "_START_WRITE_TIMEOUT_S", 0.05)
    engine = _Engine(registry)
    run_id = (await engine.create(candidates=["a"])).json()["id"]
    engine.app.state.run_registry = _Hangs(registry.store, hung)

    resp = await asyncio.wait_for(engine.start("topic-a", run_id), timeout=5)

    assert resp.status_code == 202
    assert len(engine.runner.scheduled) == 1
