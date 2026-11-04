"""A checkout's `screamingface up` builds its own Engine environment too (OME-1620, PR 4).

Think of PR 3's builder with one swapped step: instead of installing the wheel's copies of the
Engine and url4, a checkout installs the LIVE source trees editable, so edits are served without
a rebuild and the dev's own venv is never touched. These tests pin the three things that make
that safe: the environment is keyed by its root (two checkouts never share one), the install
names both live projects editable and nothing else, and `up` reaches for it only where it
should — a checkout whose Engine venv is missing or half-stocked, never a named interpreter.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from screamingface._runtime import cli, engine_env
from screamingface._runtime.config import RuntimeConfig
from screamingface._runtime.source import MODE_BUNDLED, MODE_CHECKOUT, RuntimeSource


def _record(ran: list[list[str]]):  # noqa: ANN202 - a test helper returning a stand-in runner
    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        ran.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    return run


# --- the editable environment --------------------------------------------------------------


def test_the_editable_key_carries_the_checkout_root(tmp_path: Path) -> None:
    # INVARIANT: two checkouts (or a checkout and a pip install) never share an environment.
    wheel_key = engine_env.environment_key()
    one = engine_env.environment_key(editable_root=tmp_path / "a")
    other = engine_env.environment_key(editable_root=tmp_path / "b")

    assert len({wheel_key, one, other}) == 3


def test_a_checkout_installs_the_live_projects_editable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented sequence, with uv: venv on this interpreter, the pins, then the two live
    source trees installed editable with no dependency resolution of their own. Nothing is
    assembled or copied — the live code IS the install."""
    monkeypatch.setattr(
        engine_env, "_assemble_projects", lambda _: pytest.fail("assembled a copy in a checkout")
    )
    ran: list[list[str]] = []
    root = tmp_path / "repo"

    python = engine_env.ensure_engine_environment(
        tmp_path / "data",
        environ={},
        run=_record(ran),
        which=lambda name: "/usr/bin/uv" if name == "uv" else None,
        progress=lambda _: None,
        editable_root=root,
    )

    target = python.parents[1]
    assert target.parent == tmp_path / "data" / engine_env.ENGINE_ENV_DIRNAME
    assert target.name == engine_env.environment_key(editable_root=root)
    assert ran[0] == ["/usr/bin/uv", "venv", "--python", sys.executable, str(target)]
    assert ran[1][:6] == ["/usr/bin/uv", "pip", "install", "--python", str(python), "-r"]
    assert ran[2] == [
        "/usr/bin/uv",
        "pip",
        "install",
        "--python",
        str(python),
        "--no-deps",
        "-e",
        str(root / "packages" / "url4"),
        "-e",
        str(root / "apps" / "screamingface-engine"),
    ]
    assert (target / engine_env.READY_MARKER).read_text() == target.name


def test_pip_installs_the_live_projects_editable_too(tmp_path: Path) -> None:
    ran: list[list[str]] = []
    root = tmp_path / "repo"

    python = engine_env.ensure_engine_environment(
        tmp_path / "data",
        environ={},
        run=_record(ran),
        which=lambda _: None,
        progress=lambda _: None,
        editable_root=root,
    )

    assert ran[2] == [
        str(python),
        "-m",
        "pip",
        "install",
        "--no-deps",
        "-e",
        str(root / "packages" / "url4"),
        "-e",
        str(root / "apps" / "screamingface-engine"),
    ]


# --- where `up` reaches for it ---------------------------------------------------------------


def test_a_checkout_builds_the_editable_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def ensure(data_dir: Path, **kwargs: object) -> Path:
        seen.update(data_dir=data_dir, **kwargs)
        return tmp_path / "python"

    monkeypatch.setattr(engine_env, "ensure_engine_environment", ensure)
    root = tmp_path / "repo"

    chosen = engine_env.environment_for(tmp_path / "data", RuntimeSource(MODE_CHECKOUT, root), {})

    assert chosen == tmp_path / "python"
    assert seen["data_dir"] == tmp_path / "data"
    assert seen["editable_root"] == root


def test_a_pip_install_builds_from_the_wheels_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def ensure(data_dir: Path, **kwargs: object) -> Path:
        seen.update(data_dir=data_dir, **kwargs)
        return tmp_path / "python"

    monkeypatch.setattr(engine_env, "ensure_engine_environment", ensure)

    engine_env.environment_for(tmp_path / "data", RuntimeSource(MODE_BUNDLED, None), {})

    assert seen.get("editable_root") is None


def test_a_frozen_app_still_never_builds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        engine_env, "ensure_engine_environment", lambda *a, **k: pytest.fail("built anyway")
    )

    assert engine_env.environment_for(tmp_path, RuntimeSource(MODE_CHECKOUT, tmp_path), {}) is None


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A checkout whose Engine app venv exists but lists medxpert only, plus a buildable env."""
    root = tmp_path / "repo"
    venv_python = root / "apps" / "screamingface-engine" / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("")
    built = tmp_path / "built" / "python"
    built.parent.mkdir()
    built.write_text("")
    listings = {str(venv_python): ("medxpert",), str(built): ("ifeval", "medxpert")}
    monkeypatch.setattr(
        engine_env, "engine_bundle_ids", lambda python, _env, **_: listings[str(python)]
    )
    monkeypatch.setattr(engine_env, "ensure_engine_environment", lambda *a, **k: built)
    monkeypatch.setattr(
        cli.runtime_source, "resolve_source", lambda _env: RuntimeSource(MODE_CHECKOUT, root)
    )
    return {"root": root, "venv_python": venv_python, "built": built}


def test_a_half_stocked_engine_venv_falls_through_to_the_built_environment(
    tmp_path: Path, checkout: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """STORY: as a dev whose Engine venv was synced without the benchmarks extra, `up` just
    works — it builds the editable environment and says why, instead of sending me to run a
    sync that would break my pre-push gate."""
    config = RuntimeConfig(data_dir=tmp_path / "data", engine_python=checkout["venv_python"])

    ready, ids = cli._require_full_engine_environment(config)

    assert ready.engine_python == checkout["built"]
    assert ids == ("ifeval", "medxpert")
    assert "lacks the inspect extra" in capsys.readouterr().out


def test_a_named_half_stocked_interpreter_is_still_refused(
    tmp_path: Path, checkout: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT: a setting that NAMED an interpreter is honoured or refused, never replaced —
    # replacing it would serve from an environment the user never pointed at.
    named = tmp_path / "named" / "python"
    named.parent.mkdir()
    named.write_text("")
    monkeypatch.setattr(engine_env, "engine_bundle_ids", lambda *a, **k: ("medxpert",))
    config = RuntimeConfig(data_dir=tmp_path / "data", engine_python=named)

    with pytest.raises(RuntimeError, match="lacks the inspect extra"):
        cli._require_full_engine_environment(config)


# --- the two hints ----------------------------------------------------------------------------


def test_up_says_when_no_dataset_is_prepared_yet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = RuntimeConfig(data_dir=tmp_path / "data")

    cli._hint_unprepared_datasets(config, ("ifeval", "medxpert"))
    assert "screamingface prepare" in capsys.readouterr().out

    (config.assets_dir / "ifeval").mkdir(parents=True)
    (config.assets_dir / "ifeval" / "cases.json").write_text('[{"id": 1}]')
    cli._hint_unprepared_datasets(config, ("ifeval", "medxpert"))
    assert capsys.readouterr().out == ""


def test_prepare_warns_instead_of_failing_when_the_preparer_skipped_the_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A gated dataset without a Hugging Face token exits 0 and writes nothing (the preparer's
    documented skip). `prepare --all` must carry on past it and say so, not stop the other
    ninety downloads."""
    python = tmp_path / "python"
    python.write_text("")
    config = RuntimeConfig(data_dir=tmp_path / "data", engine_python=python)

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if "--list-bundles" in command:
            return subprocess.CompletedProcess(command, 0, stdout="xstest\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(engine_env.subprocess, "run", run)

    cli._prepare(config, "xstest", all_benchmarks=False)

    out = capsys.readouterr().out
    assert "xstest" in out and "skipped" in out
    assert engine_env.bundle_status(config.assets_dir, "xstest") == "missing"
