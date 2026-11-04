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

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        ran.append(list(command))
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
    requirements = str(engine_env._requirements_path())
    assert ran[0] == ["/usr/bin/uv", "venv", "--python", sys.executable, str(target)]
    assert ran[1] == ["/usr/bin/uv", "pip", "install", "--python", str(python), "-r", requirements]
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


def test_the_committed_pins_equal_a_fresh_export_of_the_engine_lock() -> None:
    """The deployed Engine's world and the local one are the same file, by construction.

    Regenerate with `uv run python scripts/export_engine_requirements.py` when the Engine's
    lock moves. Needs uv on PATH, which the SDK's CI lane has; it fails loudly without it rather
    than skipping, so a lane without uv cannot pass this by accident.
    """
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "export_engine_requirements.py"
    spec = importlib.util.spec_from_file_location("export_engine_requirements", script)
    assert spec is not None and spec.loader is not None
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    committed: Path = exporter.REQUIREMENTS

    assert committed.read_text(encoding="utf-8") == exporter.exported_requirements()
    assert committed == engine_env._requirements_path()
    assert "inspect-ai==" in committed.read_text(encoding="utf-8")
