"""`--benchmark-assets-dir`: the runtime reads datasets from a separate, read-only folder.

FEATURE (spec D10, slice D1): Studio bundles every benchmark dataset inside the signed app and
starts the runtime with `screamingface --data-dir D up --benchmark-assets-dir P`.
INVARIANT: without the option every path, env value, state record and report is unchanged.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from screamingface._runtime import cli, server
from screamingface._runtime.config import RuntimeConfig

_BENCHMARKS = ("draco", "ifeval", "healthbench", "gdpval", "medxpert", "contracteval")
_REQUIRED = {
    "draco": ("criteria", "rubrics"),
    "ifeval": ("instructions", "nltk_data"),
    "healthbench": ("rubrics",),
    "gdpval": ("rubrics",),
    "medxpert": ("answers",),
    "contracteval": ("answers",),
}


def _prepared_folder(root: Path) -> Path:
    """A fixture folder holding all six bundles, as `prepare --all` leaves them."""
    for name in _BENCHMARKS:
        destination = root / name
        destination.mkdir(parents=True)
        for relative in _REQUIRED[name]:
            (destination / relative).mkdir()
        (destination / "cases.json").write_text('[{"id":1}]')
        cli._write_json_atomic(
            cli._benchmark_manifest_path(destination), {"fingerprint": f"{name}:revision"}
        )
    return root


def _owned_state(config: RuntimeConfig, assets: Path | None) -> None:
    state: dict[str, object] = {
        "schema_version": 1,
        "pid": 42,
        "owner_token": "secret",
        "control_url": "http://127.0.0.1:1",
        "services": config.services,
    }
    if assets is not None:
        state["benchmark_assets_dir"] = str(assets)
    cli._write_state(config, state)


def _stub_runtime_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("screamingface._runtime.server")
    module.require_runtime_extra = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "screamingface._runtime.server", module)


def _owned_and_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_runtime_extra(monkeypatch)
    monkeypatch.setattr(cli, "_verify_owner", lambda _state: True)
    monkeypatch.setattr(cli, "_health", lambda services: dict.fromkeys(services, True))
    monkeypatch.setattr(cli, "_benchmark_fingerprint", lambda name: f"{name}:revision")


# --- T-D1.1 RuntimeConfig -------------------------------------------------------------


def test_the_default_assets_folder_is_unchanged(tmp_path: Path) -> None:
    config = RuntimeConfig(data_dir=tmp_path)

    assert config.benchmark_assets_dir is None
    assert config.assets_dir == tmp_path.resolve() / "benchmark-assets"


def test_the_override_is_the_assets_folder(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"

    config = RuntimeConfig(data_dir=tmp_path / "data", benchmark_assets_dir=bundled)

    assert config.assets_dir == bundled.resolve()
    # INVARIANT: the data directory's own files never move with the datasets.
    assert config.state_path == (tmp_path / "data").resolve() / "runtime.json"


def test_the_override_resolves_home_and_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    from_home = RuntimeConfig(data_dir=tmp_path, benchmark_assets_dir=Path("~/bundled"))
    relative = RuntimeConfig(data_dir=tmp_path, benchmark_assets_dir=Path("bundled"))

    assert from_home.assets_dir == tmp_path.resolve() / "bundled"
    assert relative.assets_dir == tmp_path.resolve() / "bundled"
    assert relative.assets_dir.is_absolute()


# --- T-D1.2 CLI shape -----------------------------------------------------------------


def test_up_accepts_the_option_after_the_command(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    args = cli._parser().parse_args(
        ["--data-dir", str(tmp_path), "up", "--foreground", "--benchmark-assets-dir", str(bundled)]
    )

    config = cli._config(args)

    assert config.assets_dir == bundled.resolve()
    assert config.data_dir == tmp_path.resolve()


def test_commands_without_the_option_use_the_default_folder(tmp_path: Path) -> None:
    for command in ("up", "status", "doctor", "down"):
        args = cli._parser().parse_args(["--data-dir", str(tmp_path), command])

        assert cli._config(args).assets_dir == tmp_path.resolve() / "benchmark-assets"


# --- T-D1.2 Engine environment --------------------------------------------------------


def _capture_engine_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    def module(name: str, **attributes: object) -> None:
        stub = types.ModuleType(name)
        for key, value in attributes.items():
            setattr(stub, key, value)
        monkeypatch.setitem(sys.modules, name, stub)

    def create_local_app(*, settings: object, env: dict[str, str]) -> object:
        captured["env"] = dict(env)
        return object()

    module("aigateway.config", Settings=lambda **kwargs: types.SimpleNamespace(**kwargs))
    module("aigateway.main", create_app=lambda settings: object())
    module("screamingface_engine.config", Settings=lambda **kwargs: kwargs)
    module("screamingface_engine.local", create_local_app=create_local_app)
    monkeypatch.setattr(server, "_gateway_config_summary", lambda settings: {})
    return captured


def test_the_override_reaches_the_engine_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _capture_engine_env(monkeypatch)
    bundled = tmp_path / "bundled"

    server._build_apps(RuntimeConfig(data_dir=tmp_path, benchmark_assets_dir=bundled))

    env = captured["env"]
    assert isinstance(env, dict)
    assert env["URL4_BENCHMARK_ASSETS"] == str(bundled.resolve())


def test_the_engine_environment_keeps_the_default_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _capture_engine_env(monkeypatch)

    server._build_apps(RuntimeConfig(data_dir=tmp_path))

    env = captured["env"]
    assert isinstance(env, dict)
    assert env["URL4_BENCHMARK_ASSETS"] == str(tmp_path.resolve() / "benchmark-assets")


# --- T-D1.2 up ------------------------------------------------------------------------


def test_up_fails_before_any_service_starts_when_the_folder_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_runtime_extra(monkeypatch)
    missing = tmp_path / "no-such-folder"
    config = RuntimeConfig(data_dir=tmp_path / "data", benchmark_assets_dir=missing)

    def never(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a service was started")

    monkeypatch.setattr(cli, "_serve", never)
    monkeypatch.setattr(cli.subprocess, "Popen", never)

    with pytest.raises(RuntimeError, match=str(missing.resolve())):
        cli._up(config, foreground=True)
    assert not config.data_dir.exists()


def test_up_refuses_a_file_where_the_folder_should_be(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_runtime_extra(monkeypatch)
    not_a_folder = tmp_path / "file"
    not_a_folder.write_text("")
    config = RuntimeConfig(data_dir=tmp_path / "data", benchmark_assets_dir=not_a_folder)

    with pytest.raises(RuntimeError, match="benchmark assets folder"):
        cli._up(config, foreground=True)


def test_main_reports_the_missing_folder_and_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_runtime_extra(monkeypatch)
    missing = tmp_path / "no-such-folder"

    with pytest.raises(SystemExit) as raised:
        cli.main(["--data-dir", str(tmp_path), "up", "--benchmark-assets-dir", str(missing)])

    assert str(missing.resolve()) in str(raised.value.code)


def test_the_background_child_is_given_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_runtime_extra(monkeypatch)
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    commands: list[list[str]] = []

    def popen(command: list[str], **_kwargs: object) -> object:
        commands.append(command)
        return object()

    monkeypatch.setattr(cli.subprocess, "Popen", popen)
    monkeypatch.setattr(cli, "_wait_ready", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "_port_open", lambda _port: False)

    cli._up(
        RuntimeConfig(data_dir=tmp_path / "data", benchmark_assets_dir=bundled), foreground=False
    )
    cli._up(RuntimeConfig(data_dir=tmp_path / "plain"), foreground=False)

    with_option, without_option = commands
    flag = with_option.index("--benchmark-assets-dir")
    assert with_option[flag + 1] == str(bundled.resolve())
    assert "--benchmark-assets-dir" not in without_option
    parsed = cli._parser().parse_args(with_option[3:])
    assert cli._config(parsed).assets_dir == bundled.resolve()


def _served_state(config: RuntimeConfig, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    recorded: dict[str, object] = {}

    def run_server(config: RuntimeConfig, *_args: object) -> None:
        recorded.update(json.loads(config.state_path.read_text()))

    monkeypatch.setattr(cli, "_run_server", run_server)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    cli._serve_logged(config, "token")
    return recorded


def test_the_serving_child_records_the_folder_in_runtime_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundled = tmp_path / "bundled"

    state = _served_state(
        RuntimeConfig(data_dir=tmp_path / "data", benchmark_assets_dir=bundled), monkeypatch
    )

    assert state["benchmark_assets_dir"] == str(bundled.resolve())


def test_the_default_runtime_state_gains_no_new_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _served_state(RuntimeConfig(data_dir=tmp_path / "data"), monkeypatch)

    assert "benchmark_assets_dir" not in state


# --- T-D1.2 status and doctor ---------------------------------------------------------


def test_doctor_reports_the_bundled_folder_as_prepared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _owned_and_healthy(monkeypatch)
    monkeypatch.setattr(cli, "_get_json", lambda _url: [{"status": "connected"}])
    bundled = _prepared_folder(tmp_path / "bundled")
    config = RuntimeConfig(data_dir=tmp_path / "data")
    _owned_state(config, bundled)

    cli._doctor(config)

    output = capsys.readouterr().out
    assert str(bundled.resolve()) in output
    for name in _BENCHMARKS:
        assert f"PASS  {name + ' assets':22} prepared" in output


def test_doctor_without_a_recorded_folder_reads_the_data_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _owned_and_healthy(monkeypatch)
    monkeypatch.setattr(cli, "_get_json", lambda _url: [{"status": "connected"}])
    _prepared_folder(tmp_path / "bundled")
    config = RuntimeConfig(data_dir=tmp_path / "data")
    _owned_state(config, None)

    cli._doctor(config)

    output = capsys.readouterr().out
    assert "benchmark assets dir" not in output
    assert f"WARN  {'draco assets':22} missing" in output


def test_doctor_ignores_the_folder_of_a_stack_it_does_not_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _owned_and_healthy(monkeypatch)
    monkeypatch.setattr(cli, "_verify_owner", lambda _state: False)
    monkeypatch.setattr(cli, "_port_open", lambda _port: False)
    bundled = _prepared_folder(tmp_path / "bundled")
    config = RuntimeConfig(data_dir=tmp_path / "data")
    _owned_state(config, bundled)

    cli._doctor(config)

    assert f"WARN  {'draco assets':22} missing" in capsys.readouterr().out


def test_status_json_reports_the_recorded_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _owned_and_healthy(monkeypatch)
    bundled = _prepared_folder(tmp_path / "bundled")
    config = RuntimeConfig(data_dir=tmp_path / "data")
    _owned_state(config, bundled)

    assert cli._print_status(config, json_output=True) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["benchmark_assets_dir"] == str(bundled.resolve())
    assert payload["benchmarks"] == dict.fromkeys(_BENCHMARKS, "prepared")


def test_status_json_without_the_option_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _owned_and_healthy(monkeypatch)
    config = RuntimeConfig(data_dir=tmp_path / "data")
    _owned_state(config, None)

    cli._print_status(config, json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert "benchmark_assets_dir" not in payload
    assert payload["benchmarks"] == dict.fromkeys(_BENCHMARKS, "missing")


# --- T-D1.2 prepare -------------------------------------------------------------------


def test_prepare_refuses_the_option(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    bundled.mkdir()

    with pytest.raises(SystemExit) as raised:
        cli.main(
            [
                "--data-dir",
                str(tmp_path),
                "prepare",
                "--all",
                "--benchmark-assets-dir",
                str(bundled),
            ]
        )

    message = str(raised.value.code)
    assert "prepare" in message
    assert "--benchmark-assets-dir" in message
    assert not (bundled / "draco").exists()


def test_prepare_refuses_the_option_from_a_real_process(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "screamingface._runtime.cli",
            "--data-dir",
            str(tmp_path),
            "prepare",
            "--list",
            "--benchmark-assets-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "--benchmark-assets-dir" in completed.stderr


# --- restart keeps the folder ---------------------------------------------------------


def test_restart_keeps_the_recorded_folder_unless_given_a_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundled = tmp_path / "bundled"
    other = tmp_path / "other"
    started: list[RuntimeConfig] = []
    monkeypatch.setattr(cli, "_verify_owner", lambda _state: False)
    monkeypatch.setattr(cli, "_down", lambda _config: None)
    monkeypatch.setattr(cli, "_up", lambda config, *, foreground: started.append(config))

    for argv in (["restart"], ["restart", "--benchmark-assets-dir", str(other)]):
        config = RuntimeConfig(data_dir=tmp_path / "data")
        _owned_state(config, bundled)
        args = cli._parser().parse_args(["--data-dir", str(tmp_path / "data"), *argv])
        cli._restart(cli._config(args), args, foreground=False)

    kept, replaced = started
    assert kept.assets_dir == bundled.resolve()
    assert replaced.assets_dir == other.resolve()
