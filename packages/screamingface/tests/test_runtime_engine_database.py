"""The local Engine keeps its Run registry in the data dir (E5 P1 plan C2, spec D2).

FEATURE: first-class Runs (OME-1785). STORY: as a researcher on `screamingface up`, my Runs are
in `engine.sqlite3` beside `aigateway.sqlite3`, wherever my spilled results go.

INVARIANT: an Engine without the `database_url` setting (one from before E5 P1) is built as
before, so this Client runs against either.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
import test_runtime_artifacts_dir as artifacts_dir_tests
from screamingface_engine import job_env
from test_runtime_artifacts_dir import _Captured, _stub_module

from screamingface._runtime import server
from screamingface._runtime.config import RuntimeConfig

# The fixture that replaces the runtime-extra modules with recorders.
captured = artifacts_dir_tests.captured


class _RunsEngineSettings:
    """An Engine settings class that has the `database_url` field."""

    model_fields: ClassVar[dict[str, object]] = {"artifacts_dir": None, "database_url": None}

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


def test_the_engine_database_is_in_the_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured: dict[str, _Captured]
) -> None:
    _stub_module(monkeypatch, "screamingface_engine.config", Settings=_RunsEngineSettings)
    # WHY an override: the database stays in the data dir even when the spills go elsewhere.
    monkeypatch.setenv(job_env.ARTIFACTS_DIR, str(tmp_path / "chosen"))
    config = RuntimeConfig(data_dir=tmp_path / "data")

    server._build_apps(config)

    expected = f"sqlite://{config.data_dir / 'engine.sqlite3'}"
    assert captured["engine"].settings.database_url == expected


def test_an_engine_without_the_setting_is_built_as_before(
    tmp_path: Path, captured: dict[str, _Captured]
) -> None:
    server._build_apps(RuntimeConfig(data_dir=tmp_path / "data"))

    assert not hasattr(captured["engine"].settings, "database_url")
