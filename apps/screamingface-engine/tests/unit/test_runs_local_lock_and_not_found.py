"""E5 P1 spec D5, R9: a local Engine locks only a SQLite file, and a 404 names only a
well-formed Run id (OME-1785).

FEATURE: first-class Runs. STORY: as a researcher, a local Engine on my own Postgres starts, and
an answer never repeats a malformed id back at any length.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from run_registry_support import (
    DATABASES,
    Registry,
    open_registry,
    postgres_server,  # noqa: F401  (a fixture the Postgres parameter requests)
)
from test_runs_routes import ALICE, _Engine

from screamingface_engine.adapters.memory import InMemoryCandidateOutcomeStream
from screamingface_engine.config import Settings
from screamingface_engine.runs import wiring

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


async def test_a_local_engine_on_a_server_database_takes_no_file_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    opened: list[str] = []

    async def _open(url: str, *args: object, **kwargs: object) -> object:
        opened.append(url)
        raise RuntimeError("stop after the lock")

    monkeypatch.setattr(wiring, "open_run_store", _open)
    url = "postgres://engine@db.example/engine"
    lifecycle = wiring._RunsLifecycle(
        FastAPI(),
        Settings(),
        InMemoryCandidateOutcomeStream(),
        url=url,
        local=True,
        writer_retry_s=1.0,
    )

    with pytest.raises(RuntimeError, match="stop after the lock"):
        await lifecycle.start()

    assert opened == [url]
    assert list(tmp_path.iterdir()) == []


async def test_a_malformed_run_id_is_not_echoed(registry: Registry) -> None:
    engine = _Engine(registry)
    long_id = "x" * 8_000

    start = await engine.start("topic-a", long_id)
    read = await engine.client.get(f"/runs/{long_id}", headers=ALICE)

    for resp in (start, read):
        assert resp.status_code == 404
        assert long_id not in resp.text
