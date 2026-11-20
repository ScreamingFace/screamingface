"""The gateway lifespan always arms the frozen copy sweep trigger and stops it at shutdown.

(OME-1947, prd/copy-sweep.md S-24 and S-32, contracts.md K7)

WHY these tests build their own app and TestClient in the test body: the start log record is
written while the lifespan starts, and the `client` fixture starts it before the test body runs.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tortoise import Tortoise

from aigateway.config import Settings
from aigateway.core.frozen_copy.sweep_trigger import FrozenCopySweepTrigger
from aigateway.db import build_tortoise_config
from aigateway.main import create_app

_MAIN_LOGGER = "aigateway.main"


def _prepare_sqlite(database_url: str) -> None:
    async def _prepare() -> None:
        await Tortoise.close_connections()
        await Tortoise.init(
            config=build_tortoise_config(database_url), _enable_global_fallback=True
        )
        await Tortoise.generate_schemas()
        await Tortoise.close_connections()

    asyncio.run(_prepare())


def _app(tmp_path: Path, **env: str) -> FastAPI:
    sqlite_url = f"sqlite://{tmp_path / 'aigateway.sqlite3'}"
    _prepare_sqlite(sqlite_url)
    settings = Settings(
        **{
            "_env_file": None,
            "AIGATEWAY_DATABASE_URL": sqlite_url,
            "AIGW_AUTH_MODE": "disabled",
            **env,
        }
    )
    return create_app(settings=settings)


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, base_url="http://127.0.0.1:50000", client=("127.0.0.1", 50000))


class _FakeTrigger:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def start(self) -> None:
        self.calls.append("start")

    async def stop(self) -> None:
        self.calls.append("stop")


def test_the_lifespan_always_arms_the_sweep_trigger_and_stops_it_at_shutdown(
    tmp_path: Path,
) -> None:
    # Cache snapshots and auth are off in these settings: this proves the arm has no condition.
    app = _app(tmp_path)

    with _client(app):
        trigger = app.state.frozen_copy_sweep_trigger
        assert isinstance(trigger, FrozenCopySweepTrigger)
        task = trigger.task
        assert task is not None
        assert not task.done()
        assert task.get_name() == "frozen-copy-sweep"
        assert trigger.runs == 0

    assert task.done()
    assert trigger.task is None


def test_the_trigger_uses_the_interval_of_the_settings(tmp_path: Path) -> None:
    app = _app(tmp_path, AIGW_FROZEN_COPY_SWEEP_INTERVAL_SECONDS="120")

    with _client(app):
        assert app.state.frozen_copy_sweep_trigger.interval_s == 120.0


def test_no_setting_can_turn_the_sweep_off() -> None:
    names = list(Settings.model_fields)

    assert [n for n in names if "sweep_enabled" in n] == []
    assert [
        n for n in names if n.startswith("frozen_copy_") and ("enabled" in n or n.endswith("_from"))
    ] == []


def test_the_lifespan_starts_and_stops_a_trigger_put_on_app_state(tmp_path: Path) -> None:
    app = _app(tmp_path)
    fake = _FakeTrigger()
    app.state.frozen_copy_sweep_trigger = fake

    with _client(app):
        assert fake.calls == ["start"]
        assert app.state.frozen_copy_sweep_trigger is fake

    assert fake.calls == ["start", "stop"]


def test_the_start_log_has_the_three_sweep_settings(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app = _app(
        tmp_path,
        AIGW_FROZEN_COPY_SWEEP_INTERVAL_SECONDS="120",
        AIGW_FROZEN_COPY_OPEN_IDLE_SECONDS="7200",
        AIGW_FROZEN_COPY_SWEEP_MAX_ENTRIES="55",
    )

    # WHY the logger name: logs.configure() sets propagate=False on the aigateway logger.
    with caplog.at_level(logging.INFO, logger=_MAIN_LOGGER):
        with _client(app):
            pass

    messages = [
        r.getMessage()
        for r in caplog.records
        if r.name == _MAIN_LOGGER and r.getMessage().startswith("frozen copy sweep armed")
    ]
    assert messages == [
        "frozen copy sweep armed (interval_s=120, open_idle_s=7200, max_entries=55)"
    ]


def test_shutdown_removes_the_trigger_that_the_lifespan_built(tmp_path: Path) -> None:
    app = _app(tmp_path)

    with _client(app):
        built = app.state.frozen_copy_sweep_trigger
        assert isinstance(built, FrozenCopySweepTrigger)

    assert getattr(app.state, "frozen_copy_sweep_trigger", None) is None
    assert built.task is None


def test_shutdown_keeps_a_trigger_put_on_app_state(tmp_path: Path) -> None:
    app = _app(tmp_path)
    fake = _FakeTrigger()
    app.state.frozen_copy_sweep_trigger = fake

    with _client(app):
        pass

    assert app.state.frozen_copy_sweep_trigger is fake
    assert fake.calls == ["start", "stop"]
