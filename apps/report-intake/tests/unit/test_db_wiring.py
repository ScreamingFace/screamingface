"""The ORM configuration has two readers that must never disagree.

`_lifespan` opens the database this service serves from; `tortoise migrate` applies the schema
to the database an operator points it at. They resolve the same `TORTOISE_CONFIG` — the CLI
through `[tool.tortoise]` in `pyproject.toml`, this app through an import — and the failure mode
of them drifting apart is a migration applied to one database while the pods talk to another.
"""

from __future__ import annotations

import tomllib
from datetime import timedelta
from pathlib import Path

import pytest

from report_intake.config import Settings
from report_intake.db import (
    MIGRATIONS_MODULE,
    MODELS_MODULE,
    TORTOISE_CONFIG,
    build_tortoise_config,
)
from report_intake.main import create_app

_APP_ROOT = Path(__file__).resolve().parents[2]


def test_the_config_registers_the_report_models_and_their_migrations() -> None:
    app_config = TORTOISE_CONFIG["apps"]["models"]

    assert app_config["models"] == ["report_intake.reports.models"]
    assert app_config["migrations"] == "report_intake.reports.migrations"


def test_the_named_modules_are_importable() -> None:
    """A typo in either string is a runtime failure at the first query or the first migration,
    never at import — so the strings are checked against the real packages."""
    __import__(MODELS_MODULE)
    __import__(MIGRATIONS_MODULE)


def test_the_migrate_cli_resolves_the_same_configuration_this_app_uses() -> None:
    """`tortoise migrate` finds its config through `pyproject.toml`. If that pointer moves, the
    CLI silently migrates nothing (or something else) while every in-process test passes."""
    pyproject = tomllib.loads((_APP_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["tool"]["tortoise"]["tortoise_orm"] == "report_intake.db.TORTOISE_CONFIG"


def test_timestamps_are_timezone_aware() -> None:
    """Every timestamp this service compares is a deadline or a window edge. A naive datetime
    read back out of the database meets an aware `now` and raises `TypeError` inside a sweep."""
    assert TORTOISE_CONFIG["use_tz"] is True
    assert TORTOISE_CONFIG["timezone"] == "UTC"


def test_building_a_config_for_one_url_leaves_the_module_level_one_alone() -> None:
    """The per-test databases in `conftest.py` all go through this. A shallow copy here would
    make one test's database the next one's."""
    original = TORTOISE_CONFIG["connections"]["default"]

    build_tortoise_config("sqlite://./somewhere-else.sqlite3")

    assert TORTOISE_CONFIG["connections"]["default"] == original


def test_the_store_takes_its_windows_from_settings(
    hermetic_environment: None, monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    """`Settings` is the sole authority on this service's environment (plan §2.4), including the
    two windows — a store holding module constants would ignore the chart."""
    monkeypatch.setenv("REPORT_INTAKE_IDEMPOTENCY_TTL_H", "1")
    monkeypatch.setenv("REPORT_INTAKE_RETENTION_DAYS", "7")

    store = create_app(Settings(database_url=database_url)).state.report_store

    assert store._idempotency_ttl == timedelta(hours=1)
    assert store._retention == timedelta(days=7)
