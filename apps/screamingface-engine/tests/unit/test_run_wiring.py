"""Turning Runs on in the App (OME-1785, E5 P1 spec D2, R4, R9, R11)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from screamingface_engine.adapters.memory import InMemoryCandidateOutcomeStream
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.config import Settings
from screamingface_engine.runs import db
from screamingface_engine.runs.records import RunSpec, owner_key
from screamingface_engine.runs.wiring import (
    RunsConfigError,
    SchemaBehindError,
    ensure_sqlite_dir,
    install_runs,
    local_database_url,
    open_run_store,
)


class _CountingStream(InMemoryCandidateOutcomeStream):
    def __init__(self) -> None:
        super().__init__(ack_wait_s=0.05)
        self.updates: list[bool] = []

    async def ensure_stream(self, *, update: bool = False) -> None:
        self.updates.append(update)


def test_a_hosted_app_with_no_database_url_runs_with_runs_off(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = FastAPI()
    stream = _CountingStream()

    with caplog.at_level(logging.WARNING):
        install_runs(app, Settings(), stream, local=False)
        with TestClient(app):
            assert app.state.run_registry is None

    assert "Runs are off" in caplog.text
    # INVARIANT (spec R11): the App's own producers still publish, so the stream is declared.
    assert stream.updates == [True]


@pytest.mark.parametrize("url", ["sqlite://engine.sqlite3", "sqlite:///data/engine.sqlite3"])
def test_a_hosted_app_refuses_a_sqlite_database(url: str) -> None:
    """WHY (spec D2): a pod's SQLite file is wiped on every restart."""
    with pytest.raises(RunsConfigError, match="SQLite"):
        install_runs(FastAPI(), Settings(database_url=url), _CountingStream(), local=False)


def test_without_a_url_the_local_database_lives_in_the_home_folder(tmp_path: Path) -> None:
    # WHY not beside the artifacts: their default is a temp path the OS may clear, and another
    # user's Engine may own it.
    settings = Settings(artifacts_dir=str(tmp_path / "artifacts"))

    assert local_database_url(settings, home=tmp_path) == (
        f"sqlite://{tmp_path}/.screamingface-engine/engine.sqlite3"
    )


def test_a_local_database_url_is_kept(tmp_path: Path) -> None:
    url = f"sqlite://{tmp_path}/elsewhere.sqlite3"

    assert local_database_url(Settings(database_url=url)) == url


def test_a_fresh_local_database_is_migrated_and_written(tmp_path: Path) -> None:
    app = FastAPI()
    stream = _CountingStream()
    settings = Settings(database_url=f"sqlite://{tmp_path}/fresh/engine.sqlite3")
    install_runs(app, settings, stream, local=True, writer_retry_s=0.01)

    with TestClient(app) as client:
        store = app.state.run_registry
        assert store is not None
        owner = owner_key("local")

        async def bind_and_publish() -> None:
            run = await store.create(owner, RunSpec("k", "bench", 1, ("alpha",), "1.0"))
            await store.bind(owner, run.id, 0, "topic-1")
            await stream.publish("topic-1", CandidateOutcome("succeeded"))
            for _ in range(200):
                record = await store.get(owner, run.id)
                if record is not None and record.state == "complete":
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("the outcome was never written")

        assert client.portal is not None
        client.portal.call(bind_and_publish)

    assert (tmp_path / "fresh" / "engine.sqlite3").exists()


@pytest.mark.asyncio
async def test_an_unmigrated_database_is_refused_naming_the_migrate_step(tmp_path: Path) -> None:
    """INVARIANT (spec R9): the App never runs on a schema older than its code."""
    url = f"sqlite://{tmp_path}/engine.sqlite3"
    with pytest.raises(SchemaBehindError, match="migrate"):
        await open_run_store(url, Settings(), survives_restart=False, migrate_first=False)


@pytest.mark.asyncio
async def test_a_migrated_database_opens(tmp_path: Path) -> None:
    url = f"sqlite://{tmp_path}/engine.sqlite3"
    await db.migrate(url)
    store = await open_run_store(url, Settings(), survives_restart=True, migrate_first=False)
    try:
        assert await store.get(owner_key("local"), "run_" + "0" * 32) is None
    finally:
        await store.aclose()


def test_the_local_app_turns_runs_on() -> None:
    from screamingface_engine.local import create_local_app

    app = create_local_app(Settings(jwt_secret="s" * 32), env={})

    with TestClient(app):
        assert app.state.run_registry is not None
    assert app.state.run_registry is None


def test_a_non_sqlite_url_creates_no_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WHY: the URL carries a password, and it must never become a path on disk."""
    monkeypatch.chdir(tmp_path)

    ensure_sqlite_dir("postgres://engine:secret@localhost:5432/engine")

    assert list(tmp_path.iterdir()) == []


def test_a_sqlite_url_gets_its_folder(tmp_path: Path) -> None:
    ensure_sqlite_dir(f"sqlite://{tmp_path}/a/b/engine.sqlite3")

    assert (tmp_path / "a" / "b").is_dir()


def test_runs_leave_another_tortoise_app_in_the_process_alone(tmp_path: Path) -> None:
    """WHY: the Client's local runtime serves aigateway and the Engine in one process, and
    aigateway owns Tortoise's global state. The Engine's database must never touch it."""
    from tortoise import Tortoise
    from tortoise.connection import connections

    async def start_the_neighbour() -> None:
        await Tortoise.init(
            config={
                "connections": {"default": f"sqlite://{tmp_path}/neighbour.sqlite3"},
                "apps": {
                    "neighbour": {"models": ["neighbour_models"], "default_connection": "default"}
                },
            },
            _enable_global_fallback=True,
        )

    async def the_neighbour_answers() -> None:
        await connections.get("default").execute_query("select 1")

    app = FastAPI()
    install_runs(app, Settings(), _CountingStream(), local=True)
    with TestClient(app) as client:
        assert client.portal is not None
        client.portal.call(start_the_neighbour)
        store = app.state.run_registry
        assert store is not None
        client.portal.call(store.get, owner_key("local"), "run_" + "0" * 32)
        client.portal.call(the_neighbour_answers)
    with TestClient(FastAPI()) as client:
        assert client.portal is not None
        client.portal.call(the_neighbour_answers)
        client.portal.call(Tortoise.close_connections)


def test_a_local_restart_sweeps_the_last_processs_candidates_lost(tmp_path: Path) -> None:
    """Spec R6 at App start: the in-memory outcome stream died with the last process."""
    settings = Settings(database_url=f"sqlite://{tmp_path}/engine.sqlite3")
    owner = owner_key("local")

    first = FastAPI()
    install_runs(first, settings, _CountingStream(), local=True)
    with TestClient(first) as client:
        assert client.portal is not None
        store = first.state.run_registry
        run = client.portal.call(store.create, owner, RunSpec("k", "b", 1, ("alpha",), "1.0"))
        client.portal.call(store.bind, owner, run.id, 0, "topic-1")
        client.portal.call(store.mark_scheduled, "topic-1")

    second = FastAPI()
    install_runs(second, settings, _CountingStream(), local=True)
    with TestClient(second) as client:
        assert client.portal is not None
        store = second.state.run_registry

        async def swept_lost() -> None:
            for _ in range(200):
                record = await store.get(owner, run.id)
                if record is not None and record.candidates[0].state == "lost":
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("the start sweep never settled the Candidate")

        client.portal.call(swept_lost)
    assert second.state.run_sweep_task is None
