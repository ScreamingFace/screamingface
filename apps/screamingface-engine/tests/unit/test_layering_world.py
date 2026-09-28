"""Layering fixtures for the WORLD category (prd/01 T7, AC7-AC8).

# WHY this file exists. Unit 1 introduces `screamingface_engine/world/` — a package BOTH halves
# may import, importing NEITHER half. That is a new category in `.claude/scripts/check_layering.py`,
# not a shared leaf: a shared leaf is importable by both halves too, but the world is the
# FOUNDATION both halves are built over, so a shared leaf may not reach back into it without
# re-creating a cycle (the world already imports shared leaves such as `job_env`).
#
# The tests drive the real script against synthetic source trees, so they pin the RULE rather
# than the current tree. A rule that only holds because today's tree happens to be clean is not
# a rule; the fixtures are what make these assertions able to fail for the right reason.
"""

from __future__ import annotations

import importlib.util
import pathlib
import types

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
_SCRIPT = _REPO_ROOT / ".claude/scripts/check_layering.py"


def _layering() -> types.ModuleType:
    """Load the gate as a module (`check_layering.py` is a repo script, not an installed one)."""
    spec = importlib.util.spec_from_file_location("check_layering", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: pathlib.Path, relative: str, source: str) -> pathlib.Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source)
    return target


def _source_tree(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "apps/screamingface-engine/src/screamingface_engine"


def _offenders(tmp_path: pathlib.Path, monkeypatch) -> list[str]:
    layering = _layering()
    src = _source_tree(tmp_path)
    monkeypatch.setattr(layering, "SRC", src)
    monkeypatch.setattr(layering, "ROOT", tmp_path)
    return layering.check_layers()


def test_the_world_category_exists_and_classifies_world_modules(tmp_path, monkeypatch) -> None:
    """AC7: `world` is its OWN category, not an unlisted shared leaf."""

    layering = _layering()
    assert layering.WORLD == {"world"}

    src = _source_tree(tmp_path)
    world = _write(src, "world/connector.py", "")
    monkeypatch.setattr(layering, "SRC", src)
    assert layering._half_of(world) == "world"


def test_a_world_module_importing_runner_fails(tmp_path, monkeypatch) -> None:
    """AC7: the world imports neither half, so importing `runner` is a violation."""

    src = _source_tree(tmp_path)
    _write(
        src,
        "world/bad_world.py",
        "from screamingface_engine.runner.executor import Url4Executor\n",
    )
    offenders = _offenders(tmp_path, monkeypatch)
    assert any("world/bad_world.py" in offender for offender in offenders), offenders


def test_a_world_module_importing_a_control_plane_module_fails(tmp_path, monkeypatch) -> None:
    """AC7, the other clause: `world` imports neither HALF — and `rest` is control plane even
    though it is not `runner`. Without this fixture the clause was implemented but unpinned."""

    src = _source_tree(tmp_path)
    _write(
        src,
        "world/bad_control.py",
        "from screamingface_engine.rest.routes import router\n",
    )
    offenders = _offenders(tmp_path, monkeypatch)
    assert any("world/bad_control.py" in offender for offender in offenders), offenders


def test_a_runner_module_importing_world_serving_fails(tmp_path, monkeypatch) -> None:
    """The F4 composition helper (`world.serving`) is serving-side: it imports Starlette and
    compiles the App's route table. A Job's cold start stays engine + httpx + nats-py, so the
    run half may import `world` — everything except this one module."""

    src = _source_tree(tmp_path)
    _write(
        src,
        "runner/imports_guard.py",
        "from screamingface_engine.world.serving import compose_serving_world\n",
    )
    offenders = _offenders(tmp_path, monkeypatch)
    assert any("runner/imports_guard.py" in offender for offender in offenders), offenders


def test_a_control_plane_module_importing_world_serving_passes(tmp_path, monkeypatch) -> None:
    """The mirror of the exception: the serving half composes serving worlds — that is its job."""

    src = _source_tree(tmp_path)
    _write(
        src,
        "rest/uses_guard.py",
        "from screamingface_engine.world.serving import compose_serving_world\n",
    )
    offenders = _offenders(tmp_path, monkeypatch)
    assert not any("rest/uses_guard.py" in offender for offender in offenders), offenders


def test_a_control_plane_module_may_import_world(tmp_path, monkeypatch) -> None:
    """AC8: the control plane is ENTITLED to the world — that is the whole point of the category."""

    src = _source_tree(tmp_path)
    _write(
        src,
        "rest/uses_world.py",
        "from screamingface_engine.world.config import WorldConfig\n",
    )
    offenders = _offenders(tmp_path, monkeypatch)
    assert not any("rest/uses_world.py" in offender for offender in offenders), offenders


def test_a_control_plane_module_importing_runner_still_fails(tmp_path, monkeypatch) -> None:
    """AC8: adding WORLD does not widen the control plane's reach into the run mode."""

    src = _source_tree(tmp_path)
    _write(
        src,
        "rest/bad_control.py",
        "from screamingface_engine.runner.executor import Url4Executor\n",
    )
    offenders = _offenders(tmp_path, monkeypatch)
    assert any("rest/bad_control.py" in offender for offender in offenders), offenders


def test_a_shared_leaf_may_not_import_the_world(tmp_path, monkeypatch) -> None:
    """The world is the FOUNDATION, so the dependency arrow points one way only.

    A shared leaf importing the world would cycle: `world.config` imports `job_env`, so
    `job_env` importing `world` would make the pair mutually dependent.
    """

    src = _source_tree(tmp_path)
    _write(
        src,
        "job_env_stub.py",
        "from screamingface_engine.world.cache import policy_to_body_field\n",
    )
    offenders = _offenders(tmp_path, monkeypatch)
    assert any("job_env_stub.py" in offender for offender in offenders), offenders


def test_the_doctrine_records_the_narrowed_rule() -> None:
    """The doctrine sentence changes from the whole expression to an ENSEMBLE, and says why."""

    source = _SCRIPT.read_text()
    assert "the control plane never runs an ENSEMBLE in-process" in source
    assert "docs/plans/prd/01-foundation-world-module.md" in source


# --- FX-70 (U1-L9): an exemption names a PATH, not a file name --------------------------------

_RUN_MODE_IMPORT = "from screamingface_engine.runner.executor import Url4Executor\n"


def test_an_exemption_covers_only_the_top_level_module_it_names(tmp_path, monkeypatch) -> None:
    """`local.py` and `cli.py` are exempt because they are the two composition roots. A module
    that merely shares the name one level down (`world/local.py`, `rest/cli.py`) is not one, so
    it must be checked like any other file — a basename match exempted it silently."""

    src = _source_tree(tmp_path)
    _write(src, "world/local.py", _RUN_MODE_IMPORT)
    _write(src, "rest/cli.py", _RUN_MODE_IMPORT)
    _write(src, "local.py", _RUN_MODE_IMPORT)
    _write(src, "cli.py", _RUN_MODE_IMPORT)

    offenders = _offenders(tmp_path, monkeypatch)

    assert any("screamingface_engine/world/local.py:" in o for o in offenders), offenders
    assert any("screamingface_engine/rest/cli.py:" in o for o in offenders), offenders
    assert not any("screamingface_engine/local.py:" in o for o in offenders), offenders
    assert not any("screamingface_engine/cli.py:" in o for o in offenders), offenders
