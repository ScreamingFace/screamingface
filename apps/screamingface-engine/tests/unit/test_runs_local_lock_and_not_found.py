"""E5 P1 spec D5, R9: a local Engine keeps Runs only in a SQLite file, and a 404 names only a
well-formed Run id (OME-1785).

FEATURE: first-class Runs. STORY: as a researcher, a local Engine pointed at a shared server
database refuses to start instead of settling another Engine's live Candidates, and an answer
never repeats a malformed id back at any length.
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
from tortoise.exceptions import DBConnectionError, OperationalError, TransactionManagementError

from screamingface_engine.adapters.memory import InMemoryCandidateOutcomeStream
from screamingface_engine.config import Settings
from screamingface_engine.runs import wiring

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(params=DATABASES)
async def registry(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Registry]:
    async for opened in open_registry(request, tmp_path):
        yield opened


async def test_a_local_engine_refuses_a_server_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WHY: a second local Engine on the same server database settles the first one's live
    Candidates `lost` at its start; only a SQLite file can be held by one Engine."""
    monkeypatch.chdir(tmp_path)
    opened: list[str] = []

    async def _open(url: str, *args: object, **kwargs: object) -> object:
        opened.append(url)
        raise AssertionError("a refused database is never opened")

    monkeypatch.setattr(wiring, "open_run_store", _open)
    lifecycle = wiring._RunsLifecycle(
        FastAPI(),
        Settings(),
        InMemoryCandidateOutcomeStream(),
        url="postgres://engine@db.example/engine",
        local=True,
        writer_retry_s=1.0,
    )

    with pytest.raises(wiring.RunsConfigError, match="sqlite://"):
        await lifecycle.start()

    assert opened == []


async def test_a_malformed_run_id_is_not_echoed(registry: Registry) -> None:
    engine = _Engine(registry)
    long_id = "x" * 8_000

    read = await engine.client.get(f"/runs/{long_id}", headers=ALICE)

    assert read.status_code == 404
    assert long_id not in read.text


class _DatabaseGone:
    """A registry whose every call fails the way a lost database connection does."""

    def __getattr__(self, name: str) -> object:
        async def _fails(*args: object, **kwargs: object) -> object:
            raise ConnectionResetError("the database went away")

        return _fails


async def test_an_unexpected_registry_failure_is_a_private_retryable_problem(
    registry: Registry,
) -> None:
    """WHY: the answer depends on who asks, so even an unexpected failure must not be a shared
    plain-text 500 (spec §4.1)."""
    engine = _Engine(registry)
    engine.app.state.run_registry = _DatabaseGone()

    answers = [
        await engine.create(),
        await engine.client.get("/runs", headers=ALICE),
        await engine.client.get("/runs/run_" + "0" * 32, headers=ALICE),
    ]

    for resp in answers:
        assert resp.status_code == 503
        assert resp.headers["Content-Type"] == "application/problem+json"
        assert resp.headers["Cache-Control"] == "private, no-store"
        assert resp.headers["Vary"] == "X-User-Email"
        assert "Retry-After" in resp.headers


class _RegistryBug:
    def __getattr__(self, name: str) -> object:
        async def _fails(*args: object, **kwargs: object) -> object:
            raise KeyError("a bug, not an outage")

        return _fails


async def test_a_registry_bug_is_a_private_500_not_a_retryable_503(registry: Registry) -> None:
    """WHY: retrying a bug fails the same way, so the Client must not be told to retry it; the
    answer still depends on who asks, so it stays private."""
    engine = _Engine(registry)
    engine.app.state.run_registry = _RegistryBug()

    resp = await engine.client.get("/runs", headers=ALICE)

    assert resp.status_code == 500
    assert resp.headers["Content-Type"] == "application/problem+json"
    assert (resp.headers["Cache-Control"], resp.headers["Vary"]) == (
        "private, no-store",
        "X-User-Email",
    )
    assert "Retry-After" not in resp.headers
    assert "a bug" not in resp.text


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("database is locked"),
        TransactionManagementError("the transaction was lost"),
        DBConnectionError("could not connect"),
        TimeoutError(),
    ],
)
async def test_a_database_that_could_not_answer_is_a_retryable_503(
    registry: Registry, error: Exception
) -> None:
    class _Unavailable:
        def __getattr__(self, name: str) -> object:
            async def _fails(*args: object, **kwargs: object) -> object:
                raise error

            return _fails

    engine = _Engine(registry)
    engine.app.state.run_registry = _Unavailable()

    resp = await engine.client.get("/runs", headers=ALICE)

    assert resp.status_code == 503
    assert "Retry-After" in resp.headers
