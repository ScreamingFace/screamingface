"""`screamingface up` can start the Engine from an Engine environment of its own (OME-1620).

Think of the local stack as three servers that used to share one kitchen. The Engine's imported
boards need an ingredient (`inspect-ai`) that cannot sit on the same shelf as the Gateway's
(`litellm`, OME-1626), so the Engine gets its own kitchen: an interpreter the supervisor is
pointed at, started as a child process. These tests pin the three decisions that make that safe:
WHICH interpreter is chosen, that a half-stocked one (medxpert only) is refused loudly rather
than served quietly, and that the child is started and the datasets prepared with exactly the
commands and environment the Engine documents.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from screamingface._runtime import cli, engine_env, server
from screamingface._runtime import source as source_module
from screamingface._runtime.config import RuntimeConfig
from screamingface._runtime.source import MODE_BUNDLED, MODE_CHECKOUT, RuntimeSource

# --- which interpreter --------------------------------------------------------------------------


def _python_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_the_flag_wins_over_the_environment_and_the_checkout(tmp_path: Path) -> None:
    flagged = _python_file(tmp_path / "flagged" / "python")
    exported = _python_file(tmp_path / "exported" / "python")
    checkout = tmp_path / "repo"
    _python_file(checkout / "apps" / "screamingface-engine" / ".venv" / "bin" / "python")

    chosen = engine_env.resolve_engine_python(
        flagged,
        {engine_env.ENGINE_PYTHON_ENV: str(exported)},
        RuntimeSource(mode=MODE_CHECKOUT, root=checkout),
    )

    assert chosen == flagged.resolve()


def test_the_environment_variable_wins_over_the_checkout_default(tmp_path: Path) -> None:
    exported = _python_file(tmp_path / "exported" / "python")
    checkout = tmp_path / "repo"
    _python_file(checkout / "apps" / "screamingface-engine" / ".venv" / "bin" / "python")

    chosen = engine_env.resolve_engine_python(
        None,
        {engine_env.ENGINE_PYTHON_ENV: str(exported)},
        RuntimeSource(mode=MODE_CHECKOUT, root=checkout),
    )

    assert chosen == exported.resolve()


def test_a_checkout_defaults_to_the_engine_apps_own_venv(tmp_path: Path) -> None:
    # STORY: as a dev in the monorepo, `uv sync --extra benchmarks` in the Engine app is all I
    # do; `screamingface up` then finds that venv on its own, so `just` is no longer the only
    # way to a full local Engine.
    checkout = tmp_path / "repo"
    venv_python = _python_file(
        checkout / "apps" / "screamingface-engine" / ".venv" / "bin" / "python"
    )

    chosen = engine_env.resolve_engine_python(
        None, {}, RuntimeSource(mode=MODE_CHECKOUT, root=checkout)
    )

    assert chosen == venv_python.resolve()


def test_a_venv_symlink_is_kept_as_the_venv_interpreter(tmp_path: Path) -> None:
    """INVARIANT: the interpreter path is never resolved through its symlink.

    `.venv/bin/python` points at the base interpreter; the first real boot (2026-11-04) followed
    it and started an Engine with no pydantic, because the venv's packages live beside the
    SYMLINK, not beside its target.
    """
    base = _python_file(tmp_path / "base" / "python3.12")
    checkout = tmp_path / "repo"
    venv_python = checkout / "apps" / "screamingface-engine" / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    os.symlink(base, venv_python)

    by_default = engine_env.resolve_engine_python(
        None, {}, RuntimeSource(mode=MODE_CHECKOUT, root=checkout)
    )
    by_name = engine_env.resolve_engine_python(
        venv_python, {}, RuntimeSource(mode=MODE_BUNDLED, root=None)
    )
    in_config = RuntimeConfig(data_dir=tmp_path, engine_python=venv_python).engine_python

    assert by_default == by_name == in_config == venv_python
    assert in_config is not None and in_config.is_symlink()


def test_a_checkout_without_the_engine_venv_falls_back_to_in_process(tmp_path: Path) -> None:
    chosen = engine_env.resolve_engine_python(
        None, {}, RuntimeSource(mode=MODE_CHECKOUT, root=tmp_path / "repo")
    )

    assert chosen is None


def test_a_pip_install_without_the_variable_falls_back_to_in_process() -> None:
    # INVARIANT: a plain `pip install screamingface[runtime]` boots exactly as before this
    # unit — the in-process Engine — until PR 3 teaches `up` to build the environment.
    assert engine_env.resolve_engine_python(None, {}, RuntimeSource(MODE_BUNDLED, None)) is None


@pytest.mark.parametrize("via", ["flag", "environment"])
def test_a_named_interpreter_that_is_not_a_file_is_refused_by_name(
    tmp_path: Path, via: str
) -> None:
    missing = tmp_path / "nowhere" / "python"
    flag = missing if via == "flag" else None
    environment = {engine_env.ENGINE_PYTHON_ENV: str(missing)} if via == "environment" else {}

    with pytest.raises(RuntimeError, match=str(missing)):
        engine_env.resolve_engine_python(flag, environment, RuntimeSource(MODE_BUNDLED, None))


def test_a_blank_environment_variable_counts_as_unset() -> None:
    chosen = engine_env.resolve_engine_python(
        None, {engine_env.ENGINE_PYTHON_ENV: "  "}, RuntimeSource(MODE_BUNDLED, None)
    )

    assert chosen is None


# --- what the interpreter can serve -------------------------------------------------------------


def _fake_interpreter(tmp_path: Path, *, stdout: str = "", stderr: str = "", code: int = 0) -> Path:
    """A stand-in Engine interpreter: a script that prints what the real preparer would.

    WHY a script and not a monkeypatched `subprocess.run`: the contract under test is the ARGV
    the supervisor sends and the stdout it reads back, and only a real child proves both.
    """
    script = tmp_path / "fake-python"
    # WHY a Python script run by this interpreter: the stand-in must print exact bytes on any
    # shell, and `sys.executable` is the one interpreter every test host has.
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"sys.stdout.write({stdout!r})\n"
        f"sys.stderr.write({stderr!r})\n"
        f"raise SystemExit({code})\n"
    )
    script.chmod(0o700)
    return script


def test_bundle_ids_come_from_the_engines_own_preparer(tmp_path: Path) -> None:
    recorded: list[list[str]] = []
    python = tmp_path / "python"

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        recorded.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ifeval\nmedxpert\nmmlu\n", stderr="")

    ids = engine_env.engine_bundle_ids(python, {}, run=run)

    assert ids == ("ifeval", "medxpert", "mmlu")
    # INVARIANT: the Engine's preparer is the one list of what it can serve; the supervisor
    # never keeps a board list of its own (the medxpert-only tuple was exactly that).
    assert recorded == [
        [str(python), "-m", "screamingface_engine.benchmarks.prepare", "--list-bundles"]
    ]


def test_a_failing_preparer_surfaces_its_stderr_and_the_fix(tmp_path: Path) -> None:
    python = tmp_path / "python"

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, 1, stdout="", stderr="ModuleNotFoundError: No module named 'url4'"
        )

    with pytest.raises(RuntimeError) as exc:
        engine_env.engine_bundle_ids(python, {}, run=run)

    message = str(exc.value)
    assert str(python) in message
    assert "No module named 'url4'" in message


def test_a_real_child_is_run_with_the_engines_argv(tmp_path: Path) -> None:
    python = _fake_interpreter(tmp_path, stdout="medxpert\nifeval\n")

    assert engine_env.engine_bundle_ids(python, dict(os.environ)) == ("medxpert", "ifeval")


def test_a_medxpert_only_environment_is_refused_with_the_sync_command(tmp_path: Path) -> None:
    """INVARIANT: an Engine env without the inspect extra must fail `up`, not serve one board.

    Silence is the failure mode this stack exists to end — a dev who forgot the extra would
    otherwise get a healthy-looking stack that refuses every imported board at run time.
    """
    python = tmp_path / "repo" / "apps" / "screamingface-engine" / ".venv" / "bin" / "python"

    with pytest.raises(RuntimeError) as exc:
        engine_env.require_full_engine(
            python, ("medxpert",), RuntimeSource(MODE_CHECKOUT, tmp_path / "repo")
        )

    message = str(exc.value)
    assert "uv sync --extra benchmarks" in message
    assert "apps/screamingface-engine" in message


def test_a_pointed_at_environment_is_told_which_extra_it_lacks(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"screamingface-engine\[benchmarks\]"):
        engine_env.require_full_engine(
            tmp_path / "python", ("medxpert",), RuntimeSource(MODE_BUNDLED, None)
        )


def test_an_environment_with_imported_boards_passes(tmp_path: Path) -> None:
    engine_env.require_full_engine(
        tmp_path / "python", ("ifeval", "medxpert"), RuntimeSource(MODE_BUNDLED, None)
    )


# --- the commands and the environment the child gets -------------------------------------------


def test_the_serve_command_is_the_engines_local_mode_on_the_stacks_port(tmp_path: Path) -> None:
    command = engine_env.serve_command(tmp_path / "python", 9111)

    # WHY `-c`: `screamingface_engine.cli` has no `__main__` guard, so `-m` would import it
    # and exit 0 without serving (the first real boot, 2026-11-04).
    assert command == [
        str(tmp_path / "python"),
        "-c",
        "from screamingface_engine.cli import main; main()",
        "serve",
        "--local",
        "--port",
        "9111",
    ]


def test_the_prepare_command_names_the_assets_root_and_the_bundle(tmp_path: Path) -> None:
    command = engine_env.prepare_command(tmp_path / "python", tmp_path / "assets", "ifeval")

    assert command == [
        str(tmp_path / "python"),
        "-m",
        "screamingface_engine.benchmarks.prepare",
        "--root",
        str(tmp_path / "assets"),
        "--bundle",
        "ifeval",
    ]


def test_the_engine_child_environment_carries_what_the_in_process_engine_was_handed(
    tmp_path: Path,
) -> None:
    """The child must see the same world the in-process Engine was built with — the datasets
    root, the gateway address (as the Engine's Settings reads it), the artifacts folder and the
    runner config — or a run would spill, read or call somewhere the supervisor does not know."""
    config = RuntimeConfig(data_dir=tmp_path, engine_port=9111, gateway_port=9105)

    environment = server._engine_child_environment(config, {"HOME": "/home/u", "PATH": "/bin"})

    assert environment["URL4_BENCHMARK_ASSETS"] == str(tmp_path.resolve() / "benchmark-assets")
    assert environment["URL4_CLOUD_AIGATEWAY_BASE_URL"] == "http://127.0.0.1:9105"
    assert environment["AIGATEWAY_BASE_URL"] == "http://127.0.0.1:9105"
    assert environment["URL4_CLOUD_ARTIFACTS_DIR"] == str(tmp_path.resolve() / "artifacts")
    assert environment["URL4_RUNNER_CONFIG"] == str(config.runner_config)
    assert environment["HOME"] == "/home/u"


# --- is a bundle prepared? ---------------------------------------------------------------------


def test_bundle_status_follows_the_cases_json_completion_marker(tmp_path: Path) -> None:
    # WHY cases.json (OME-1790): every Engine preparer writes it LAST, so a folder holding a
    # parseable, non-empty one is finished; anything else is debris from a run that died.
    assets = tmp_path / "assets"
    assert engine_env.bundle_status(assets, "ifeval") == "missing"

    (assets / "ifeval").mkdir(parents=True)
    assert engine_env.bundle_status(assets, "ifeval") == "incomplete"

    (assets / "ifeval" / "cases.json").write_text("[{")
    assert engine_env.bundle_status(assets, "ifeval") == "incomplete"

    (assets / "ifeval" / "cases.json").write_text("[]")
    assert engine_env.bundle_status(assets, "ifeval") == "incomplete"

    (assets / "ifeval" / "cases.json").write_text('[{"id": 1}]')
    assert engine_env.bundle_status(assets, "ifeval") == "prepared"


# --- `screamingface prepare` through the Engine's preparer --------------------------------------


@pytest.fixture
def engine_prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """A config pointed at a fake Engine env whose preparer lists two bundles and, when asked
    to prepare one, writes its cases.json — the way the real preparer finishes."""
    python = tmp_path / "engine" / "python"
    python.parent.mkdir()
    python.write_text("")
    config = RuntimeConfig(data_dir=tmp_path / "data", engine_python=python)
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if "--list-bundles" in command:
            return subprocess.CompletedProcess(command, 0, stdout="ifeval\nmedxpert\n", stderr="")
        root = Path(command[command.index("--root") + 1])
        bundle = command[command.index("--bundle") + 1]
        (root / bundle).mkdir(parents=True, exist_ok=True)
        (root / bundle / "cases.json").write_text('[{"id": 1}]')
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(engine_env.subprocess, "run", run)
    monkeypatch.setattr(cli, "require_runtime_extra", lambda: None, raising=False)
    monkeypatch.setattr(
        "screamingface._runtime.server.require_runtime_extra",
        lambda: RuntimeSource(MODE_BUNDLED, None),
    )
    return {"config": config, "calls": calls, "python": python}


def test_prepare_list_shows_every_engine_bundle_with_its_status(
    engine_prepare: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    config = engine_prepare["config"]
    assert isinstance(config, RuntimeConfig)
    (config.assets_dir / "medxpert").mkdir(parents=True)
    (config.assets_dir / "medxpert" / "cases.json").write_text('[{"id": 1}]')

    cli._prepare(config, None, all_benchmarks=False, list_benchmarks=True)

    out = capsys.readouterr().out
    assert "ifeval       missing" in out
    assert "medxpert     prepared" in out


def test_prepare_runs_the_engines_preparer_for_the_named_bundle(
    engine_prepare: dict[str, object],
) -> None:
    config = engine_prepare["config"]
    calls = engine_prepare["calls"]
    assert isinstance(config, RuntimeConfig) and isinstance(calls, list)

    cli._prepare(config, "ifeval", all_benchmarks=False)

    prepare_calls = [call for call in calls if "--bundle" in call]
    assert prepare_calls == [
        [
            str(engine_prepare["python"]),
            "-m",
            "screamingface_engine.benchmarks.prepare",
            "--root",
            str(config.assets_dir),
            "--bundle",
            "ifeval",
        ]
    ]
    assert engine_env.bundle_status(config.assets_dir, "ifeval") == "prepared"


def test_prepare_refuses_a_bundle_the_engine_does_not_serve(
    engine_prepare: dict[str, object],
) -> None:
    config = engine_prepare["config"]
    assert isinstance(config, RuntimeConfig)

    with pytest.raises(RuntimeError, match="no such benchmark 'nope'.*--list"):
        cli._prepare(config, "nope", all_benchmarks=False)


def test_prepare_skips_a_finished_bundle_unless_forced(
    engine_prepare: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    config = engine_prepare["config"]
    calls = engine_prepare["calls"]
    assert isinstance(config, RuntimeConfig) and isinstance(calls, list)
    (config.assets_dir / "ifeval").mkdir(parents=True)
    (config.assets_dir / "ifeval" / "cases.json").write_text('[{"id": 1}]')
    (config.assets_dir / "ifeval" / "stale.txt").write_text("old")

    cli._prepare(config, "ifeval", all_benchmarks=False)
    assert not [call for call in calls if "--bundle" in call]
    assert "already prepared" in capsys.readouterr().out

    # WHY the folder is cleared first: the Engine's preparer refuses a non-empty folder, so
    # `--force` must hand it an empty one — and a leftover file from an older prepare must go.
    cli._prepare(config, "ifeval", all_benchmarks=False, force=True)
    assert [call for call in calls if "--bundle" in call]
    assert not (config.assets_dir / "ifeval" / "stale.txt").exists()
    assert engine_env.bundle_status(config.assets_dir, "ifeval") == "prepared"


def test_prepare_all_walks_every_engine_bundle(engine_prepare: dict[str, object]) -> None:
    config = engine_prepare["config"]
    calls = engine_prepare["calls"]
    assert isinstance(config, RuntimeConfig) and isinstance(calls, list)

    cli._prepare(config, None, all_benchmarks=True)

    assert [call[-1] for call in calls if "--bundle" in call] == ["ifeval", "medxpert"]


def test_prepare_without_an_engine_environment_keeps_the_medxpert_path(tmp_path: Path) -> None:
    # INVARIANT: no Engine env → exactly the pre-existing behaviour, down to the argument check.
    config = RuntimeConfig(data_dir=tmp_path)

    with pytest.raises(RuntimeError, match="choose one benchmark or pass --all"):
        cli._prepare(config, None, all_benchmarks=False)


# --- the supervisor ------------------------------------------------------------------------------


def test_build_apps_builds_no_in_process_engine_when_an_engine_env_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import types

    built: list[str] = []

    def module(name: str, **attributes: object) -> None:
        stub = types.ModuleType(name)
        for key, value in attributes.items():
            setattr(stub, key, value)
        monkeypatch.setitem(sys.modules, name, stub)

    module("aigateway.config", Settings=lambda **kwargs: types.SimpleNamespace(**kwargs))
    module("aigateway.main", create_app=lambda settings: built.append("gateway") or object())
    module("pydantic", SecretStr=lambda value: value)
    module("screamingface_engine.config", Settings=lambda **kwargs: kwargs)
    module(
        "screamingface_engine.local",
        create_local_app=lambda **kwargs: built.append("engine") or object(),
    )
    monkeypatch.setattr(server, "_gateway_config_summary", lambda settings: {})
    python = tmp_path / "python"
    python.write_text("")

    _gateway, engine, _summary = server._build_apps(
        RuntimeConfig(data_dir=tmp_path / "data", engine_python=python)
    )

    assert engine is None
    assert built == ["gateway"]


def test_the_scoreboard_seeds_from_the_running_engine_in_engine_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: with the Engine in its own process, the local board can no longer import the
    registry — it reads the Engine's catalogue over HTTP, as the hosted board does, so a local
    leaderboard lists exactly what the local Engine serves."""
    import types

    seeded: dict[str, object] = {}

    async def fake_run(
        *, configured: list[object], engine_url: str | None, engine_rows: object = None
    ) -> int:
        seeded.update(configured=configured, engine_url=engine_url, engine_rows=engine_rows)
        return 0

    def module(name: str, **attributes: object) -> None:
        stub = types.ModuleType(name)
        for key, value in attributes.items():
            setattr(stub, key, value)
        monkeypatch.setitem(sys.modules, name, stub)

    module("uvicorn", run=lambda *args, **kwargs: None)
    module("scoreboard.config", Settings=lambda **kwargs: types.SimpleNamespace(**kwargs))
    module("scoreboard.main", create_app=lambda settings: object())
    module("scoreboard.seed", _run=fake_run, load_benchmarks_json=lambda raw: [])
    module("screamingface_engine.benchmarks.builtins", BUILTIN_BENCHMARKS=())
    monkeypatch.setattr(server, "scoreboard_assets", lambda: (tmp_path, tmp_path))
    config = RuntimeConfig(data_dir=tmp_path / "data", engine_port=9111)

    server.run_scoreboard(config, seed_from_engine=True)

    assert seeded == {"configured": [], "engine_url": "http://127.0.0.1:9111", "engine_rows": None}


# --- review round 1 (2026-11-05) -----------------------------------------------------------------


def _stub_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the runtime extra's guard that `restart` imports at call time."""
    import types

    module = types.ModuleType("screamingface._runtime.server")
    module.require_runtime_extra = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "screamingface._runtime.server", module)


def test_a_restart_in_this_checkout_never_runs_the_real_engine_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: the suite never reads the developer's real Engine venv (conftest).

    Without that isolation `_config` finds `apps/screamingface-engine/.venv/bin/python` in the
    checkout the tests run from, and `restart` then runs the real Engine's bundle listing: a
    prior restart test failed with "serves only medxpert" on a dev box whose Engine venv lacks
    the benchmarks extra, and spawned a 4 s child on one that has it. CI was green only because
    CI has no Engine venv. Here the real checkout is MADE to look like it has one — the venv
    path is pointed at a file every checkout carries — so the guard is exercised on every machine.
    """
    real_root = source_module.checkout_root()
    assert real_root is not None, "the suite runs from a ScreamingFace checkout"
    monkeypatch.setattr(engine_env, "_VENV_PYTHON", Path("pyproject.toml"))
    monkeypatch.setattr(
        engine_env.subprocess, "run", lambda *a, **k: pytest.fail("ran a real Engine child")
    )
    _stub_server(monkeypatch)
    monkeypatch.setattr(cli, "_require_runner_config", lambda _config: None)
    monkeypatch.setattr(cli, "_down", lambda _config: None)
    started: list[RuntimeConfig] = []
    monkeypatch.setattr(cli, "_up", lambda config, *, foreground: started.append(config))

    args = cli._parser().parse_args(["--data-dir", str(tmp_path / "data"), "restart"])
    cli._restart(cli._config(args), args, foreground=False)

    assert started[0].engine_python is None
    assert engine_env.checkout_engine_venv(RuntimeSource(MODE_CHECKOUT, real_root)) is None


def test_the_scoreboard_refuses_to_serve_an_unseeded_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seeder returns 1 when the Engine's catalogue was unreadable and the board was never
    seeded. Serving anyway put an empty leaderboard behind a READY banner; the child must exit,
    so the supervisor reports it (with the seeder's own lines drained into runtime.log)."""
    import types

    async def unseeded(**_: object) -> int:
        return 1

    def module(name: str, **attributes: object) -> None:
        stub = types.ModuleType(name)
        for key, value in attributes.items():
            setattr(stub, key, value)
        monkeypatch.setitem(sys.modules, name, stub)

    module("uvicorn", run=lambda *a, **k: pytest.fail("served an unseeded board"))
    module("scoreboard.config", Settings=lambda **kwargs: types.SimpleNamespace(**kwargs))
    module("scoreboard.main", create_app=lambda settings: object())
    module("scoreboard.seed", _run=unseeded, load_benchmarks_json=lambda raw: [])
    module("screamingface_engine.benchmarks.builtins", BUILTIN_BENCHMARKS=())
    monkeypatch.setattr(server, "scoreboard_assets", lambda: (tmp_path, tmp_path))

    with pytest.raises(RuntimeError, match="could not read the Engine's benchmarks"):
        server.run_scoreboard(RuntimeConfig(data_dir=tmp_path / "data"), seed_from_engine=True)


def test_status_reads_bundles_from_disk_and_never_starts_the_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: `status --json` is polled (Studio, scripts); a 4 s Engine child per call is not a status.
    monkeypatch.setattr(
        engine_env, "engine_bundle_ids", lambda *a, **k: pytest.fail("status ran the Engine")
    )
    python = tmp_path / "python"
    python.write_text("")
    config = RuntimeConfig(data_dir=tmp_path / "data", engine_python=python)
    (config.assets_dir / "ifeval").mkdir(parents=True)
    (config.assets_dir / "ifeval" / "cases.json").write_text('[{"id": 1}]')
    (config.assets_dir / "mmlu").mkdir()

    statuses = cli._benchmark_statuses(config, ask_engine=False)

    assert statuses == {"ifeval": "prepared", "mmlu": "incomplete"}


def test_doctor_reports_a_broken_engine_environment_instead_of_dying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(*_: object, **__: object) -> tuple[str, ...]:
        raise RuntimeError("the Engine at /x/python could not list its benchmarks (exit 1)")

    monkeypatch.setattr(engine_env, "engine_bundle_ids", broken)
    _stub_server(monkeypatch)
    python = tmp_path / "python"
    python.write_text("")

    code = cli._doctor(RuntimeConfig(data_dir=tmp_path / "data", engine_python=python))

    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL  engine environment" in out
    assert "could not list its benchmarks" in out


def _state_with_engine(config: RuntimeConfig, python: Path) -> None:
    cli._write_state(
        config,
        {
            "schema_version": 1,
            "pid": 42,
            "owner_token": "secret",
            "control_url": "http://127.0.0.1:1",
            "services": config.services,
            "engine_python": str(python),
        },
    )


@pytest.fixture
def restart_stubs(monkeypatch: pytest.MonkeyPatch) -> list[RuntimeConfig]:
    _stub_server(monkeypatch)
    monkeypatch.setattr(cli, "_verify_owner", lambda _state: False)
    monkeypatch.setattr(cli, "_require_runner_config", lambda _config: None)
    monkeypatch.setattr(cli, "_require_full_engine_environment", lambda _config: None)
    monkeypatch.setattr(cli, "_down", lambda _config: None)
    started: list[RuntimeConfig] = []
    monkeypatch.setattr(cli, "_up", lambda config, *, foreground: started.append(config))
    return started


def test_restart_keeps_the_recorded_interpreter_over_a_found_default(
    tmp_path: Path, restart_stubs: list[RuntimeConfig]
) -> None:
    # INVARIANT: like the datasets folder, the interpreter is part of what the stack IS; a
    # checkout default (merely found) must not swap it out from under a restart.
    recorded = _python_file(tmp_path / "recorded" / "python")
    found = _python_file(tmp_path / "found" / "python")
    config = RuntimeConfig(data_dir=tmp_path / "data", engine_python=found)
    _state_with_engine(config, recorded)
    args = cli._parser().parse_args(["--data-dir", str(tmp_path / "data"), "restart"])

    cli._restart(config, args, foreground=False)

    assert restart_stubs[0].engine_python == recorded


def test_restart_takes_a_newly_named_interpreter(
    tmp_path: Path, restart_stubs: list[RuntimeConfig]
) -> None:
    recorded = _python_file(tmp_path / "recorded" / "python")
    named = _python_file(tmp_path / "named" / "python")
    config = RuntimeConfig(data_dir=tmp_path / "data", engine_python=named)
    _state_with_engine(config, recorded)
    args = cli._parser().parse_args(
        ["--data-dir", str(tmp_path / "data"), "restart", "--engine-python", str(named)]
    )

    cli._restart(config, args, foreground=False)

    assert restart_stubs[0].engine_python == named


def test_prepare_uses_the_running_stacks_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: `prepare --list` beside a running stack must list what THAT Engine serves.
    recorded = _python_file(tmp_path / "recorded" / "python")
    found = _python_file(tmp_path / "found" / "python")
    config = RuntimeConfig(data_dir=tmp_path / "data", engine_python=found)
    _state_with_engine(config, recorded)
    monkeypatch.setattr(cli, "_verify_owner", lambda _state: True)
    args = cli._parser().parse_args(["--data-dir", str(tmp_path / "data"), "prepare", "--list"])

    assert cli._with_recorded_engine(config, args).engine_python == recorded

    monkeypatch.setattr(cli, "_verify_owner", lambda _state: False)
    assert cli._with_recorded_engine(config, args).engine_python == found


class _StubbornProcess:
    """A child that ignores SIGTERM: `wait` times out until it is killed."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.killed = False

    def poll(self) -> int | None:
        return -9 if self.killed else None

    def terminate(self) -> None:
        self.calls.append("terminate")

    def kill(self) -> None:
        self.calls.append("kill")
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        self.calls.append(f"wait({timeout})")
        if not self.killed:
            raise subprocess.TimeoutExpired("engine", timeout or 0)
        return -9


def test_a_child_that_ignores_terminate_is_killed() -> None:
    # WHY: without the kill, a stuck Engine child keeps 9108 and the next `up` refuses the port.
    process = _StubbornProcess()

    server._stop_child_process(process, grace=0.1)  # type: ignore[arg-type]

    assert process.calls[:2] == ["terminate", "wait(0.1)"]
    assert "kill" in process.calls


def test_the_engine_child_runs_in_its_own_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: in `up --foreground`, Ctrl-C signals the whole terminal process group; a child in
    # that group got SIGINT directly AND a terminate() from the supervisor. Its own session
    # leaves the supervisor as the one that stops it.
    seen: dict[str, object] = {}

    def popen(command: list[str], **kwargs: object) -> object:
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(server.subprocess, "Popen", popen)
    python = tmp_path / "python"
    python.write_text("")

    server._start_engine_child(RuntimeConfig(data_dir=tmp_path / "data", engine_python=python))

    assert seen["start_new_session"] is True
