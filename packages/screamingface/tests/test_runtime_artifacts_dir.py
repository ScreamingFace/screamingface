"""FEATURE (OME-1448): the local stack keeps spilled results in the data dir, not in TMPDIR.

INVARIANT (OME-929): the writer (the in-process runner's env) and the reader (the App's
`EngineSettings`) must be handed the SAME artifacts folder. These tests build the apps through
`_build_apps` with the two app factories replaced by recorders, so no server starts.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from screamingface_engine import job_env

from screamingface._runtime import cli, server
from screamingface._runtime.config import ARTIFACTS_DIR_ENV, RuntimeConfig, default_data_dir


@dataclass
class _Captured:
    settings: Any
    env: dict[str, str]


def _stub_module(monkeypatch: pytest.MonkeyPatch, name: str, **attributes: Any) -> None:
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)


def _engine_settings(**kwargs: Any) -> SimpleNamespace:
    """Record what `_build_apps` hands the App. WHY capture-only: every call now passes
    `artifacts_dir` explicitly, so the reader never falls back to its own env lookup."""
    return SimpleNamespace(**kwargs)


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, _Captured]:
    """Replace the four runtime-extra modules `_build_apps` imports at call time.

    WHY stubs and not the real apps: the SDK test job installs no runtime extra (see
    `[tool.coverage.run]` in pyproject.toml), so `fastapi` and `pydantic_settings` are absent
    and the real `aigateway.main` / `screamingface_engine.local` cannot be imported. `job_env`
    has no third-party import and stays real: it owns the env var name under test.
    """
    record: dict[str, _Captured] = {}

    def fake_engine(*, settings: Any, env: Any) -> object:
        record["engine"] = _Captured(settings=settings, env=dict(env))
        return object()

    _stub_module(
        monkeypatch,
        "aigateway.config",
        Settings=lambda **kw: SimpleNamespace(request_cache_enabled=False, **kw),
    )
    _stub_module(monkeypatch, "aigateway.main", create_app=lambda _settings: object())
    _stub_module(monkeypatch, "screamingface_engine.config", Settings=_engine_settings)
    _stub_module(monkeypatch, "screamingface_engine.local", create_local_app=fake_engine)
    return record


def test_la0_user_override_reaches_both_sides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured: dict[str, _Captured]
) -> None:
    chosen = tmp_path / "chosen"
    monkeypatch.setenv(job_env.ARTIFACTS_DIR, str(chosen))

    server._build_apps(RuntimeConfig(data_dir=tmp_path / "data"))

    engine = captured["engine"]
    assert engine.env[job_env.ARTIFACTS_DIR] == str(chosen)
    assert engine.settings.artifacts_dir == str(chosen)


def test_artifacts_env_name_is_the_engines_own() -> None:
    # INVARIANT: `_runtime/config.py` spells the Engine's env name to stay importable without
    # the runtime extra; a rename on either side must fail here, not 404 a paid result.
    assert ARTIFACTS_DIR_ENV == job_env.ARTIFACTS_DIR


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("", None), ("   ", None), (" /chosen ", Path("/chosen"))],
)
def test_artifacts_override_treats_blank_as_unset(
    tmp_path: Path, value: str | None, expected: Path | None
) -> None:
    config = RuntimeConfig(data_dir=tmp_path)
    environ = {} if value is None else {ARTIFACTS_DIR_ENV: value}

    assert config.artifacts_override(environ) == expected
    assert config.effective_artifacts_dir(environ) == (expected or config.artifacts_dir)


def test_la1_default_is_the_same_data_dir_folder_on_both_sides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured: dict[str, _Captured]
) -> None:
    monkeypatch.delenv(job_env.ARTIFACTS_DIR, raising=False)
    config = RuntimeConfig(data_dir=tmp_path / "data")

    server._build_apps(config)

    engine = captured["engine"]
    assert engine.settings.artifacts_dir == str(config.artifacts_dir)
    assert engine.env[job_env.ARTIFACTS_DIR] == str(config.artifacts_dir)


@pytest.mark.parametrize("blank", ["", "   "])
def test_la1_blank_override_counts_as_unset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    captured: dict[str, _Captured],
    blank: str,
) -> None:
    monkeypatch.setenv(job_env.ARTIFACTS_DIR, blank)
    config = RuntimeConfig(data_dir=tmp_path / "data")

    server._build_apps(config)

    engine = captured["engine"]
    assert engine.settings.artifacts_dir == str(config.artifacts_dir)
    assert engine.env[job_env.ARTIFACTS_DIR] == str(config.artifacts_dir)


def test_la2_default_folder_is_created_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured: dict[str, _Captured]
) -> None:
    monkeypatch.delenv(job_env.ARTIFACTS_DIR, raising=False)
    config = RuntimeConfig(data_dir=tmp_path / "data")

    server._build_apps(config)

    assert config.artifacts_dir == config.data_dir / "artifacts"
    assert config.artifacts_dir.is_dir()
    assert config.artifacts_dir.stat().st_mode & 0o777 == 0o700


def test_la2_user_override_folder_is_left_to_the_engine_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured: dict[str, _Captured]
) -> None:
    monkeypatch.setenv(job_env.ARTIFACTS_DIR, str(tmp_path / "chosen"))
    config = RuntimeConfig(data_dir=tmp_path / "data")

    server._build_apps(config)

    assert not config.artifacts_dir.exists()
    assert not (tmp_path / "chosen").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_la5_unwritable_data_dir_raises_an_error_naming_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured: dict[str, _Captured]
) -> None:
    monkeypatch.delenv(job_env.ARTIFACTS_DIR, raising=False)
    data_dir = tmp_path / "locked"
    data_dir.mkdir()
    config = RuntimeConfig(data_dir=data_dir)
    data_dir.chmod(0o500)
    try:
        with pytest.raises(OSError, match="artifacts") as raised:
            server._build_apps(config)
    finally:
        data_dir.chmod(0o700)

    assert str(config.artifacts_dir) in str(raised.value)
    assert "engine" not in captured


def test_la6_data_dir_override_moves_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured: dict[str, _Captured]
) -> None:
    monkeypatch.delenv(job_env.ARTIFACTS_DIR, raising=False)
    moved = tmp_path / "elsewhere"
    monkeypatch.setenv("SCREAMINGFACE_DATA_DIR", str(moved))
    config = RuntimeConfig(data_dir=default_data_dir())

    server._build_apps(config)

    expected = str(moved.resolve() / "artifacts")
    assert captured["engine"].settings.artifacts_dir == expected
    assert captured["engine"].env[job_env.ARTIFACTS_DIR] == expected


def test_la2_existing_default_folder_is_made_private_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured: dict[str, _Captured]
) -> None:
    monkeypatch.delenv(job_env.ARTIFACTS_DIR, raising=False)
    config = RuntimeConfig(data_dir=tmp_path / "data")
    config.artifacts_dir.mkdir(parents=True)
    config.artifacts_dir.chmod(0o755)

    server._build_apps(config)

    assert config.artifacts_dir.stat().st_mode & 0o777 == 0o700


def test_la7_status_shows_the_artifacts_folder_and_its_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = RuntimeConfig(data_dir=tmp_path)
    config.artifacts_dir.mkdir()
    (config.artifacts_dir / ("a" * 64)).write_bytes(b"12345")
    (config.artifacts_dir / ("b" * 64)).write_bytes(b"678")
    monkeypatch.setattr(cli, "_health", lambda services: dict.fromkeys(services, True))

    cli._print_status(config)

    human = capsys.readouterr().out
    assert f"{config.artifacts_dir}  (8 bytes)" in human

    cli._print_status(config, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifacts_dir"] == str(config.artifacts_dir)
    assert payload["artifacts_bytes"] == 8


def test_la7_status_reports_zero_bytes_for_a_missing_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = RuntimeConfig(data_dir=tmp_path)
    monkeypatch.setattr(cli, "_health", lambda services: dict.fromkeys(services, True))

    cli._print_status(config, json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["artifacts_dir"] == str(config.artifacts_dir)
    assert payload["artifacts_bytes"] == 0


def test_la7_status_survives_a_file_swept_between_listing_and_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # INVARIANT: the Engine's hourly TTL sweep can delete a parcel while `status` sums the
    # folder; `status` must count what is left, never crash on the vanished file.
    config = RuntimeConfig(data_dir=tmp_path)
    config.artifacts_dir.mkdir()
    kept = config.artifacts_dir / ("a" * 64)
    swept = config.artifacts_dir / ("b" * 64)
    kept.write_bytes(b"12345")
    swept.write_bytes(b"678")
    real_stat = Path.stat

    def stat_after_sweep(self: Path, *args: Any, **kwargs: Any) -> os.stat_result:
        if self == swept:
            raise FileNotFoundError(str(self))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_after_sweep)
    monkeypatch.setattr(cli, "_health", lambda services: dict.fromkeys(services, True))

    cli._print_status(config, json_output=True)

    assert json.loads(capsys.readouterr().out)["artifacts_bytes"] == 5


def test_la7_status_reports_the_folder_the_server_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # WHY: the serving child records the folder its Engine was built with; `status` from
    # another shell, with a different env, must report that folder, not the default.
    config = RuntimeConfig(data_dir=tmp_path / "data")
    chosen = tmp_path / "fast-disk"
    chosen.mkdir()
    (chosen / ("c" * 64)).write_bytes(b"1234567")
    monkeypatch.setattr(cli, "_read_state", lambda _config: {"artifacts_dir": str(chosen)})
    monkeypatch.setattr(cli, "_health", lambda services: dict.fromkeys(services, True))

    cli._print_status(config, json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["artifacts_dir"] == str(chosen)
    assert payload["artifacts_bytes"] == 7


def test_la7_status_marks_an_unreadable_folder_size_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = RuntimeConfig(data_dir=tmp_path)
    config.artifacts_dir.mkdir()
    real_iterdir = Path.iterdir

    def refused(self: Path) -> Any:
        if self == config.artifacts_dir:
            raise PermissionError(str(self))
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", refused)
    monkeypatch.setattr(cli, "_health", lambda services: dict.fromkeys(services, True))

    cli._print_status(config, json_output=True)
    assert json.loads(capsys.readouterr().out)["artifacts_bytes"] is None
    cli._print_status(config)
    assert f"{config.artifacts_dir}  (size unknown)" in capsys.readouterr().out
