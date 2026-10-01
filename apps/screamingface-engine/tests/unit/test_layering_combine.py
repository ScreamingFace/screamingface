"""Layering fixtures for the COMBINE core (FW-13, FW-D6; OME-1289 E4a, unit 1).

# WHY this file exists. `screamingface_engine/combine/` is a SHARED LEAF with a hexagonal rule
# inside it: its core (every module but the wiring module and the plugin subtree) defines the
# ports and runs specs, and never imports a plugin or the module that lists them. A plugin imports
# only the ports. The tests drive the real script against synthetic source trees, so they pin the
# RULE rather than today's tree.
"""

from __future__ import annotations

import importlib.util
import pathlib
import types

import pytest

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


def _offenders(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    layering = _layering()
    monkeypatch.setattr(layering, "SRC", _source_tree(tmp_path))
    monkeypatch.setattr(layering, "ROOT", tmp_path)
    return layering.check_layers()


def _flags(offenders: list[str], relative: str) -> bool:
    return any(relative in offender for offender in offenders)


def test_combine_is_a_shared_leaf(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    layering = _layering()
    src = _source_tree(tmp_path)
    endpoint = _write(src, "combine/endpoint.py", "")
    monkeypatch.setattr(layering, "SRC", src)
    assert layering._half_of(endpoint) is None


def test_layering_gate_fails_when_core_imports_a_plugin(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        _source_tree(tmp_path),
        "combine/endpoint.py",
        "from screamingface_engine.combine.operators.extract import OPERATORS\n",
    )
    assert _flags(_offenders(tmp_path, monkeypatch), "combine/endpoint.py")


def test_a_relative_plugin_import_from_the_core_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(_source_tree(tmp_path), "combine/spec.py", "from .operators import extract\n")
    assert _flags(_offenders(tmp_path, monkeypatch), "combine/spec.py")


def test_a_core_module_importing_builtins_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        _source_tree(tmp_path),
        "combine/registry.py",
        "from screamingface_engine.combine.builtins import BUILTIN_OPERATORS\n",
    )
    assert _flags(_offenders(tmp_path, monkeypatch), "combine/registry.py")


def test_builtins_may_import_plugins(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _source_tree(tmp_path)
    _write(src, "combine/operators/extract.py", "")
    _write(
        src,
        "combine/builtins.py",
        "from screamingface_engine.combine.operators import extract\n"
        "from screamingface_engine.combine.operators.extract import OPERATORS\n",
    )
    assert not _flags(_offenders(tmp_path, monkeypatch), "combine/builtins.py")


def test_a_plugin_importing_the_endpoint_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        _source_tree(tmp_path),
        "combine/operators/extract.py",
        "from screamingface_engine.combine.endpoint import COMBINE_ROUTE\n",
    )
    assert _flags(_offenders(tmp_path, monkeypatch), "combine/operators/extract.py")


def test_a_plugin_importing_benchmarks_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        _source_tree(tmp_path),
        "combine/operators/reduce.py",
        "from screamingface_engine.benchmarks.contract import DECLARED_FAILURE_CODES\n",
    )
    assert _flags(_offenders(tmp_path, monkeypatch), "combine/operators/reduce.py")


def test_a_plugin_importing_ports_passes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        _source_tree(tmp_path),
        "combine/operators/select.py",
        "from screamingface_engine.combine.ports import OperatorDescriptor\n"
        "from screamingface_engine.combine import ports\n"
        "from .. import ports as relative_ports\n",
    )
    assert not _flags(_offenders(tmp_path, monkeypatch), "combine/operators/select.py")


def test_a_combine_module_importing_world_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The existing shared-leaf rule already covers `combine/`: it may not reach the world."""
    _write(
        _source_tree(tmp_path),
        "combine/endpoint.py",
        "from screamingface_engine.world.config import WorldConfig\n",
    )
    assert _flags(_offenders(tmp_path, monkeypatch), "combine/endpoint.py")


def test_a_world_module_may_import_the_combine_core(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route adapter (`world/combine.py`) is the engine-importing half: world -> combine."""
    _write(
        _source_tree(tmp_path),
        "world/combine.py",
        "from screamingface_engine.combine.endpoint import COMBINE_ROUTE, run_combine\n"
        "from screamingface_engine.combine.registry import OperatorRegistry\n",
    )
    assert not _flags(_offenders(tmp_path, monkeypatch), "world/combine.py")


def test_the_gate_tolerates_a_tree_without_combine(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(_source_tree(tmp_path), "job_env_stub.py", "")
    assert _offenders(tmp_path, monkeypatch) == []
