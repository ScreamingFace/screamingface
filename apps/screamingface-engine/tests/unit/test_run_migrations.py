"""The Run registry's schema ships as a migration (OME-1785, sdlc-python S1).

The registry contract builds every test database with these migrations, so the schema it tests is
the one that ships. These tests pin the rest: the migration matches the models, it re-runs as a
no-op, and the config names the right packages.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from screamingface_engine.runs import db

APP_DIR = Path(__file__).resolve().parents[2]


def test_the_config_registers_the_models_and_their_migrations() -> None:
    config = db.build_tortoise_config("sqlite://:memory:")
    app = config["apps"][db.APP_LABEL]

    assert app["models"] == ["screamingface_engine.runs.models"]
    assert app["migrations"] == "screamingface_engine.runs.migrations"
    assert config["use_tz"] is True and config["timezone"] == "UTC"


@pytest.mark.asyncio
async def test_the_migration_creates_the_tables_and_reruns_as_a_no_op(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite3"
    await db.migrate(f"sqlite://{path}")
    await db.migrate(f"sqlite://{path}")

    with sqlite3.connect(path) as conn:
        tables = {
            row[0] for row in conn.execute("select name from sqlite_master where type='table'")
        }
        applied = conn.execute("select count(*) from tortoise_migrations").fetchone()[0]
    assert {"runs", "run_candidates"} <= tables
    shipped = [m for m in (APP_DIR / "src/screamingface_engine/runs/migrations").glob("0*.py")]
    assert applied == len(shipped)


def test_the_autodetector_proposes_no_change() -> None:
    """The projected state after the migrations equals the models, so `makemigrations` stays
    silent. Out of process: the autodetector needs its own `Tortoise.init`."""
    script = """
import asyncio, json
from tortoise import Tortoise
from tortoise.migrations.autodetector import MigrationAutodetector
from screamingface_engine.runs.db import build_tortoise_config

async def main():
    config = build_tortoise_config("sqlite://:memory:")
    await Tortoise.init(config=config, init_connections=False)
    try:
        writers = await MigrationAutodetector(Tortoise.apps, config["apps"]).changes()
        print(json.dumps([op.describe() for w in writers for op in w.operations]))
    finally:
        await Tortoise.close_connections()

asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=APP_DIR, check=True, capture_output=True, text=True
    )

    assert json.loads(result.stdout.strip().splitlines()[-1]) == []
