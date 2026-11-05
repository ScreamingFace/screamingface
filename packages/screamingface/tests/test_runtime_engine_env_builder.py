"""`screamingface up` builds a pip user's Engine environment on first run (OME-1620 / OME-1626).

Think of it as `up` stocking the Engine's own kitchen the first time: it assembles the Engine
project from the sources the wheel carries, installs the Engine's PINNED dependency world (the
same `inspect-ai` and `inspect-evals` the deployed Engine runs, so every board keeps the same
revision), marks the environment ready, and from then on only reuses it. These tests pin what
makes that safe: the environment is keyed by its inputs, a half-built one is never reused, the
installer sequence is exactly the documented one, and the committed pins never drift from the
Engine's lock.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from screamingface._runtime import cli, engine_env
from screamingface._runtime.config import RuntimeConfig
from screamingface._runtime.source import MODE_BUNDLED, MODE_CHECKOUT, RuntimeSource

# --- the environment's identity ---------------------------------------------------------------


def test_the_key_follows_the_pins(monkeypatch: pytest.MonkeyPatch) -> None:
    # INVARIANT: a pin bump makes a NEW environment — an old one built on other versions would
    # serve boards whose revision no longer matches the deployed Engine's.
    before = engine_env.environment_key()
    monkeypatch.setattr(engine_env, "_requirements_text", lambda: "inspect-ai==9.9.9\n")

    assert engine_env.environment_key() != before
    assert len(before) == 16


def test_a_ready_environment_is_reused_without_running_anything(tmp_path: Path) -> None:
    python = _ready_environment(tmp_path)
    ran: list[list[str]] = []

    chosen = engine_env.ensure_engine_environment(
        tmp_path, environ={}, run=_recorder(ran), which=lambda _: None, progress=lambda _: None
    )

    assert chosen == python
    assert ran == []
    assert engine_env.existing_engine_environment(tmp_path) == python


def test_a_folder_without_the_ready_marker_is_not_an_environment(tmp_path: Path) -> None:
    # WHY: a build killed halfway leaves a venv folder with some packages; the marker is
    # written LAST, so only a finished environment is ever started.
    python = _ready_environment(tmp_path)
    (python.parents[1] / engine_env.READY_MARKER).unlink()

    assert engine_env.existing_engine_environment(tmp_path) is None


# --- building it -------------------------------------------------------------------------------


def _recorder(ran: list[list[str]]) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        ran.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    return run


def _ready_environment(data_dir: Path) -> Path:
    target = data_dir / engine_env.ENGINE_ENV_DIRNAME / engine_env.environment_key()
    python = target / engine_env._INTERPRETER_IN_VENV
    python.parent.mkdir(parents=True)
    python.write_text("")
    (target / engine_env.READY_MARKER).write_text(engine_env.environment_key())
    return python


@pytest.fixture
def vendored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Stand-ins for the packages and project files the wheel carries."""
    packages: dict[str, Path] = {}
    for name in ("screamingface_engine", "screamingface_engine_inspect", "url4"):
        package = tmp_path / "site" / name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(f"# {name}\n")
        (package / "__pycache__").mkdir()
        (package / "__pycache__" / "x.pyc").write_bytes(b"")
        packages[name] = package
    dist = tmp_path / "engine_dist"
    (dist / "screamingface-engine").mkdir(parents=True)
    (dist / "screamingface-engine" / "pyproject.toml").write_text(
        '[project]\nname = "screamingface-engine"\nversion = "1.5.0"\n'
    )
    (dist / "url4").mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        (dist / "url4" / name).write_text(f"{name}\n")
    monkeypatch.setattr(engine_env, "_vendored_package", lambda name: packages[name])
    monkeypatch.setattr(engine_env, "_project_file", lambda project, name: dist / project / name)
    return packages


def test_uv_builds_the_environment_from_the_pins_then_the_vendored_projects(
    tmp_path: Path, vendored: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented sequence, with uv on PATH: a venv on THIS interpreter, the pinned world,
    then the two vendored projects with no dependency resolution of their own — every version
    comes from the pins, never from what pip or uv would pick today."""
    ran: list[list[str]] = []
    assembled: dict[str, list[str]] = {}
    pins: list[str] = []

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        ran.append(list(command))
        if "-r" in command:
            # The pins file, like the projects, exists only while the install runs.
            pins.append(Path(command[command.index("-r") + 1]).read_text(encoding="utf-8"))
        if "--no-deps" in command:
            # The assembled projects exist only while the install runs: record their layout now.
            for project in command[command.index("--no-deps") + 1 :]:
                assembled[Path(project).name] = sorted(
                    str(path.relative_to(project))
                    for path in Path(project).rglob("*")
                    if path.is_file()
                )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    python = engine_env.ensure_engine_environment(
        tmp_path,
        environ={},
        run=run,
        which=lambda name: "/usr/bin/uv" if name == "uv" else None,
        progress=lambda _: None,
    )

    target = tmp_path / engine_env.ENGINE_ENV_DIRNAME / engine_env.environment_key()
    assert python == target / engine_env._INTERPRETER_IN_VENV
    assert ran[0] == ["/usr/bin/uv", "venv", "--python", sys.executable, str(target)]
    assert ran[1][:6] == ["/usr/bin/uv", "pip", "install", "--python", str(python), "-r"]
    assert pins == [engine_env._requirements_text()]
    assert ran[2][:6] == ["/usr/bin/uv", "pip", "install", "--python", str(python), "--no-deps"]
    assert [Path(project).name for project in ran[2][6:]] == ["url4", "screamingface-engine"]
    assert assembled["url4"] == ["LICENSE", "README.md", "pyproject.toml", "src/url4/__init__.py"]
    assert assembled["screamingface-engine"] == [
        "pyproject.toml",
        "src/screamingface_engine/__init__.py",
        "src/screamingface_engine_inspect/__init__.py",
    ]
    # INVARIANT: the marker is the last thing written, and names the key it certifies.
    assert (target / engine_env.READY_MARKER).read_text() == engine_env.environment_key()


def test_pip_is_the_installer_when_uv_is_absent(tmp_path: Path, vendored: dict[str, Path]) -> None:
    ran: list[list[str]] = []

    python = engine_env.ensure_engine_environment(
        tmp_path, environ={}, run=_recorder(ran), which=lambda _: None, progress=lambda _: None
    )

    target = tmp_path / engine_env.ENGINE_ENV_DIRNAME / engine_env.environment_key()
    assert ran[0] == [sys.executable, "-m", "venv", str(target)]
    assert ran[1][:5] == [str(python), "-m", "pip", "install", "-r"]
    assert ran[2][:5] == [str(python), "-m", "pip", "install", "--no-deps"]


def test_a_failed_step_names_itself_and_leaves_no_half_built_environment(
    tmp_path: Path, vendored: dict[str, Path]
) -> None:
    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if "-r" in command:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="ERROR: No matching distribution found for inspect-ai==0.3.263",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    with pytest.raises(RuntimeError, match="No matching distribution") as exc:
        engine_env.ensure_engine_environment(
            tmp_path, environ={}, run=run, which=lambda _: None, progress=lambda _: None
        )

    assert "pip install" in str(exc.value)
    assert not (tmp_path / engine_env.ENGINE_ENV_DIRNAME / engine_env.environment_key()).exists()
    assert engine_env.existing_engine_environment(tmp_path) is None


def test_an_environment_built_on_other_pins_is_removed(
    tmp_path: Path, vendored: dict[str, Path]
) -> None:
    # Clean removal: a pin bump must not leave 700 MB of the previous world behind.
    stale = tmp_path / engine_env.ENGINE_ENV_DIRNAME / "0000000000000000"
    stale.mkdir(parents=True)
    (stale / engine_env.READY_MARKER).write_text("0000000000000000")
    ran: list[list[str]] = []

    engine_env.ensure_engine_environment(
        tmp_path, environ={}, run=_recorder(ran), which=lambda _: None, progress=lambda _: None
    )

    assert not stale.exists()


def test_progress_says_where_and_roughly_how_much(
    tmp_path: Path, vendored: dict[str, Path]
) -> None:
    said: list[str] = []

    engine_env.ensure_engine_environment(
        tmp_path, environ={}, run=_recorder([]), which=lambda _: None, progress=said.append
    )

    assert any(str(tmp_path / engine_env.ENGINE_ENV_DIRNAME) in line for line in said)
    assert any("MB" in line for line in said)


# --- where `up` reaches for it -----------------------------------------------------------------


def test_a_built_environment_is_found_under_the_data_dir(tmp_path: Path) -> None:
    python = _ready_environment(tmp_path)

    chosen = engine_env.resolve_engine_python(
        None, {}, RuntimeSource(MODE_BUNDLED, None), data_dir=tmp_path
    )

    assert chosen == python


def test_a_named_interpreter_still_wins_over_a_built_environment(tmp_path: Path) -> None:
    _ready_environment(tmp_path)
    named = tmp_path / "named" / "python"
    named.parent.mkdir()
    named.write_text("")

    chosen = engine_env.resolve_engine_python(
        named, {}, RuntimeSource(MODE_BUNDLED, None), data_dir=tmp_path
    )

    assert chosen == named


@pytest.mark.usefixtures("real_engine_build")
def test_up_builds_the_environment_for_a_pip_install_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: a pip user gets the environment built; a checkout dev without the Engine venv
    keeps the in-process Engine (and the `uv sync` hint), never a 700 MB download by surprise."""
    built = tmp_path / "built" / "python"
    built.parent.mkdir()
    built.write_text("")
    calls: list[Path] = []

    def ensure(data_dir: Path, **_: object) -> Path:
        calls.append(data_dir)
        return built

    monkeypatch.setattr(engine_env, "ensure_engine_environment", ensure)
    config = RuntimeConfig(data_dir=tmp_path / "data")

    bundled = cli._with_built_engine_environment(config, RuntimeSource(MODE_BUNDLED, None))
    checkout = cli._with_built_engine_environment(config, RuntimeSource(MODE_CHECKOUT, tmp_path))

    assert bundled.engine_python == built
    assert calls == [config.data_dir]
    assert checkout.engine_python is None


@pytest.mark.usefixtures("real_engine_build")
def test_an_explicit_interpreter_is_never_replaced_by_a_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        engine_env, "ensure_engine_environment", lambda *a, **k: pytest.fail("built anyway")
    )
    named = tmp_path / "python"
    named.write_text("")
    config = RuntimeConfig(data_dir=tmp_path / "data", engine_python=named)

    assert cli._with_built_engine_environment(config, RuntimeSource(MODE_BUNDLED, None)) == config


def test_a_frozen_app_never_builds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # WHY: Studio ships the runtime frozen; it cannot create a venv and keeps the in-process
    # Engine until it brings an Engine environment of its own (SCREAMINGFACE_ENGINE_PYTHON).
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        engine_env, "ensure_engine_environment", lambda *a, **k: pytest.fail("built anyway")
    )

    assert (
        engine_env.environment_for_pip_install(tmp_path, RuntimeSource(MODE_BUNDLED, None), {})
        is None
    )


# --- the pins never drift from the Engine's lock ---------------------------------------------


# --- review round 1 (2026-11-05) -----------------------------------------------------------------


def _no_project_files(project: str, name: str) -> Path:
    raise FileNotFoundError(f"project file not found for {project}: {name}")


@pytest.mark.parametrize("frozen", [True, False])
def test_looking_for_a_built_environment_never_raises_without_project_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, frozen: bool
) -> None:
    """A frozen Studio sidecar (or any install without `engine_dist/` and no checkout) has
    nothing to compute an environment key from. LOOKING for an environment runs on every
    `up`, `status` and `doctor`, so it must answer "none", not crash the sidecar at config
    time; only an actual BUILD may raise."""
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(engine_env, "_project_file", _no_project_files)

    chosen = engine_env.resolve_engine_python(
        None, {}, RuntimeSource(MODE_BUNDLED, None), data_dir=tmp_path
    )

    assert chosen is None
    if not frozen:
        with pytest.raises(FileNotFoundError):
            engine_env.ensure_engine_environment(
                tmp_path, environ={}, run=_recorder([]), which=lambda _: None, progress=print
            )


def test_the_key_follows_the_project_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = engine_env.environment_key()
    other = tmp_path / "pyproject.toml"
    other.write_text('[project]\nname = "screamingface-engine"\nversion = "9.9.9"\n')
    monkeypatch.setattr(engine_env, "_project_file", lambda project, name: other)

    assert engine_env.environment_key() != before


def test_two_ups_never_build_over_each_other(tmp_path: Path, vendored: dict[str, Path]) -> None:
    """Two `up`s in two shells: the second waits on the build lock, then REUSES what the first
    built instead of deleting its half-built folder and starting again."""
    import fcntl
    import threading

    root = tmp_path / engine_env.ENGINE_ENV_DIRNAME
    root.mkdir()
    holder = (root / engine_env._BUILD_LOCK).open("w")
    fcntl.flock(holder, fcntl.LOCK_EX)
    ran: list[list[str]] = []
    result: dict[str, Path] = {}
    second = threading.Thread(
        target=lambda: result.update(
            python=engine_env.ensure_engine_environment(
                tmp_path,
                environ={},
                run=_recorder(ran),
                which=lambda _: None,
                progress=lambda _: None,
            )
        )
    )
    second.start()
    second.join(timeout=0.3)
    assert second.is_alive(), "the second up must wait for the first build"
    built = _ready_environment(tmp_path)  # the first up finishes
    fcntl.flock(holder, fcntl.LOCK_UN)
    holder.close()
    second.join(timeout=5)

    assert result["python"] == built
    assert ran == []


def test_the_build_says_which_step_it_is_on(tmp_path: Path, vendored: dict[str, Path]) -> None:
    # WHY: a pip install of 136 pins prints nothing for minutes; without steps it reads as a hang.
    said: list[str] = []

    engine_env.ensure_engine_environment(
        tmp_path, environ={}, run=_recorder([]), which=lambda _: None, progress=said.append
    )

    steps = [line for line in said if line.lstrip().startswith(("1/3", "2/3", "3/3"))]
    assert len(steps) == 3


@pytest.mark.usefixtures("real_engine_build")
def test_up_hands_the_built_environment_to_the_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The call in `up` that builds the environment, pinned: delete it and this goes red."""
    import types

    built = tmp_path / "built" / "python"
    built.parent.mkdir()
    built.write_text("")
    monkeypatch.setattr(engine_env, "ensure_engine_environment", lambda *a, **k: built)
    server = types.ModuleType("screamingface._runtime.server")
    server.require_runtime_extra = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "screamingface._runtime.server", server)
    monkeypatch.setattr(
        cli.runtime_source, "resolve_source", lambda _env: RuntimeSource(MODE_BUNDLED, None)
    )
    monkeypatch.setattr(cli, "_require_runner_config", lambda _config: None)
    monkeypatch.setattr(cli, "_port_open", lambda _port: False)
    reached: list[RuntimeConfig] = []

    class _Stop(Exception):
        pass

    def full(config: RuntimeConfig) -> None:
        reached.append(config)
        raise _Stop

    monkeypatch.setattr(cli, "_require_full_engine_environment", full)

    with pytest.raises(_Stop):
        cli._up(RuntimeConfig(data_dir=tmp_path / "data"), foreground=False)

    assert reached[0].engine_python == built
