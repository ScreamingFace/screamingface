"""Wiring evidence for the cache-snapshot scheduler (OME-1021).

The scheduler is armed by the app's lifespan only when enabled and is owned by it —
started at startup, cancelled and awaited at shutdown. And the containment promise: an
export in flight (or failing) never perturbs the request path — a global-cache HIT
completes while the export is streaming, and a store failure surfaces as a record and a
log line, never as an app error.

These tests run the ORM on sqlite while Settings carry a postgresql:// DSN — the one
`database_url` field feeds both the ORM and the exporter, and the product rule (review C5)
requires a Postgres scheme whenever snapshots are armed. The export DSN is never dialed
here: every test replaces the scheduler's `_run` before any fire, so the exporter's lazy
`postgres_connect` never runs. Only the lifespan's `init_db` is pointed at the sqlite file.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tortoise import Tortoise

from aigateway.config import Settings
from aigateway.core.request_cache.store import RequestCacheWrite
from aigateway.db import build_tortoise_config, init_db
from aigateway.main import create_app

_CHAT_PATH = "/v1/chat/completions"
_CHAT_BODY = {
    "model": "anthropic/claude-haiku-4-5",
    "messages": [{"role": "user", "content": "how many primes below one hundred?"}],
}

_CANNED = {
    "id": "cmpl-cached",
    "object": "chat.completion",
    "created": 1750000000,
    "model": "anthropic/claude-haiku-4-5",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "CACHED-ANSWER"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
}


def _prepare_sqlite(database_url: str) -> None:
    async def _prepare() -> None:
        await Tortoise.close_connections()
        await Tortoise.init(
            config=build_tortoise_config(database_url), _enable_global_fallback=True
        )
        await Tortoise.generate_schemas()
        await Tortoise.close_connections()

    asyncio.run(_prepare())


def _settings(tmp_path: Path, *, snapshot_enabled: bool) -> Settings:
    sqlite_url = f"sqlite://{tmp_path / 'aigateway.sqlite3'}"
    return Settings(
        **{
            "_env_file": None,
            # Postgres scheme while armed (the C5 rule); sqlite when disabled — both the
            # real shapes a deployment would carry.
            "AIGATEWAY_DATABASE_URL": _EXPORT_DSN if snapshot_enabled else sqlite_url,
            "AIGW_AUTH_MODE": "disabled",
            "AIGW_REQUEST_CACHE_ENABLED": "true",
            "AIGW_CACHE_SNAPSHOT_ENABLED": "true" if snapshot_enabled else "false",
            "AIGW_CACHE_SNAPSHOT_S3_ENDPOINT_URL": "http://127.0.0.1:3900",
            "AIGW_CACHE_SNAPSHOT_S3_ACCESS_KEY": "GKtestaccess",
            "AIGW_CACHE_SNAPSHOT_S3_SECRET_KEY": "secret",
        }
    )


def _app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    snapshot_enabled: bool = True,
) -> FastAPI:
    """create_app over sqlite storage, carrying the export DSN the product rule requires."""
    sqlite_url = f"sqlite://{tmp_path / 'aigateway.sqlite3'}"
    _prepare_sqlite(sqlite_url)
    real_init_db = init_db

    async def _init_sqlite(_dsn: str) -> None:
        # The seam the one-field-two-consumers design creates: whatever DSN Settings say,
        # the ORM in these tests runs on the prepared sqlite file.
        await real_init_db(sqlite_url)

    monkeypatch.setattr("aigateway.main.init_db", _init_sqlite)
    return create_app(settings=_settings(tmp_path, snapshot_enabled=snapshot_enabled))


class _HitStore:
    """A store that answers every lookup with the canned response — the target contract."""

    def cache_available(self) -> bool:
        return True

    async def get(self, key_hash: str) -> dict[str, Any] | None:
        return dict(_CANNED)

    async def set_if_absent(self, entry: RequestCacheWrite) -> str:
        return "not_stored"


# Never dialed: postgres-form so Settings accept an armed snapshot (review C5), but every
# test replaces the scheduler's `_run` before any fire.
_EXPORT_DSN = "postgresql://snapshot:snapshot@127.0.0.1:5/aigateway"


def test_the_lifespan_starts_and_stops_the_scheduler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)

    test_client = TestClient(app, base_url="http://127.0.0.1:50000", client=("127.0.0.1", 50000))
    with test_client:
        scheduler = app.state.cache_snapshot_scheduler
        assert scheduler is not None
        assert scheduler._task is not None and not scheduler._task.done()

    # Shutdown cancelled and awaited the owned task: nothing outlives the app.
    assert app.state.cache_snapshot_scheduler._task is None


def test_disabled_snapshot_never_arms_a_scheduler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch, snapshot_enabled=False)

    test_client = TestClient(app, base_url="http://127.0.0.1:50000", client=("127.0.0.1", 50000))
    with test_client:
        assert not hasattr(app.state, "cache_snapshot_scheduler")


def test_a_slow_export_never_blocks_a_cache_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The containment proof: a hit completes while the export is streaming."""
    app = _app(tmp_path, monkeypatch)
    app.state.request_cache_store = _HitStore()

    test_client = TestClient(app, base_url="http://127.0.0.1:50000", client=("127.0.0.1", 50000))
    with test_client:
        portal = test_client.portal
        assert portal is not None  # entered: the lifespan portal is live
        scheduler = app.state.cache_snapshot_scheduler

        async def _make_event() -> asyncio.Event:
            return asyncio.Event()

        gate = portal.call(_make_event)

        async def slow_run() -> None:
            await gate.wait()

        scheduler._run = slow_run

        async def _start_fire() -> asyncio.Task[None]:
            return asyncio.create_task(scheduler._fire())

        fired = portal.call(_start_fire)
        time.sleep(0.05)  # the export is now in flight, blocked on the gate

        response = test_client.post(_CHAT_PATH, json=_CHAT_BODY)
        assert response.status_code == 200, response.text
        assert response.json()["choices"][0]["message"]["content"] == "CACHED-ANSWER"
        assert response.headers["X-AIGW-Cache"] == "hit"

        async def _release_and_finish() -> None:
            gate.set()
            await asyncio.wait_for(fired, timeout=10)

        portal.call(_release_and_finish)
        assert scheduler.records()[0].state == "complete"


def test_a_failed_export_is_recorded_and_never_an_app_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)

    test_client = TestClient(app, base_url="http://127.0.0.1:50000", client=("127.0.0.1", 50000))
    with test_client:
        portal = test_client.portal
        assert portal is not None  # entered: the lifespan portal is live
        scheduler = app.state.cache_snapshot_scheduler

        async def failing_run() -> None:
            raise RuntimeError("garage is down")

        scheduler._run = failing_run
        scheduler._retry_attempts = 1  # one attempt: no long backoff sleeps in the test

        async def _fire_and_wait() -> None:
            await asyncio.wait_for(scheduler._fire(), timeout=10)

        portal.call(_fire_and_wait)

        (record,) = scheduler.records()
        assert record.state == "failed"
        assert record.error == "RuntimeError: garage is down"
        assert scheduler.busy is False

        # The app is still serving requests.
        assert test_client.get("/healthz").status_code == 200
