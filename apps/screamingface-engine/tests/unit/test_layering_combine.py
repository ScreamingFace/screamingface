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


_DENIED = [
    "socket", "ssl", "http", "urllib", "httpx", "requests", "subprocess", "os", "sys", "time",
    "datetime", "random", "secrets", "uuid", "asyncio", "threading", "multiprocessing",
    "concurrent", "io", "pathlib", "shutil", "tempfile", "logging",
]  # fmt: skip


def test_the_plugin_deny_list_is_the_agreed_set() -> None:
    assert _layering().COMBINE_PLUGIN_DENY == set(_DENIED)


@pytest.mark.parametrize("module", _DENIED)
def test_a_plugin_importing_an_io_or_nondeterminism_module_fails(
    module: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(_source_tree(tmp_path), "combine/operators/extract.py", f"import {module}\n")
    assert _flags(_offenders(tmp_path, monkeypatch), "combine/operators/extract.py")


@pytest.mark.parametrize(
    "source",
    [
        "from concurrent.futures import ThreadPoolExecutor\n",
        "from datetime import datetime\n",
        "import os.path\n",
        "from urllib.parse import quote\n",
    ],
    ids=["from-concurrent", "from-datetime", "dotted-os", "from-urllib"],
)
def test_a_plugin_deny_list_covers_from_imports_and_dotted_names(
    source: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(_source_tree(tmp_path), "combine/operators/extract.py", source)
    assert _flags(_offenders(tmp_path, monkeypatch), "combine/operators/extract.py")


@pytest.mark.parametrize(
    "source",
    [
        "import re\n",
        "import json\n",
        "from decimal import Decimal, localcontext\n",
        "from collections.abc import Mapping\n",
        "from types import MappingProxyType\n",
        "from __future__ import annotations\n",
    ],
    ids=["re", "json", "decimal", "collections-abc", "types", "future"],
)
def test_a_plugin_may_import_the_pure_standard_library(
    source: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(_source_tree(tmp_path), "combine/operators/extract.py", source)
    assert not _flags(_offenders(tmp_path, monkeypatch), "combine/operators/extract.py")


def test_the_core_may_use_logging_and_the_clock_free_stdlib(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deny-list is for plugins; the core's endpoint logs."""
    _write(_source_tree(tmp_path), "combine/endpoint.py", "import logging\nimport math\n")
    assert not _flags(_offenders(tmp_path, monkeypatch), "combine/endpoint.py")


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        ("combine/endpoint.py", "from url4.peer.server import Request\n"),
        ("combine/spec.py", "import url4\n"),
        ("combine/evidence.py", "from url4.core.errors import ResolutionError\n"),
        ("combine/operators/extract.py", "from url4.core.errors import ResolutionError\n"),
        ("combine/operators/select.py", "import url4\n"),
        ("combine/builtins.py", "from url4 import RelExpr\n"),
    ],
    ids=["core-peer", "core-bare", "core-errors", "plugin-errors", "plugin-bare", "wiring"],
)
def test_nothing_under_combine_may_import_url4(
    relative: str, source: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(_source_tree(tmp_path), relative, source)
    assert _flags(_offenders(tmp_path, monkeypatch), relative)


def test_a_world_module_may_import_url4(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The adapter lives in `world/`; only `combine/` is kept free of url4 here."""
    _write(_source_tree(tmp_path), "world/combine.py", "from url4.peer.server import Request\n")
    assert not _flags(_offenders(tmp_path, monkeypatch), "world/combine.py")


def test_the_gate_tolerates_a_tree_without_combine(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(_source_tree(tmp_path), "job_env_stub.py", "")
    assert _offenders(tmp_path, monkeypatch) == []


# --- the one third-party module a plugin may import: re2 (OME-1289, regex@1) --------------------


def test_the_plugin_third_party_allowance_is_re2_only() -> None:
    assert _layering().COMBINE_PLUGIN_THIRD_PARTY == frozenset({"re2"})


@pytest.mark.parametrize("source", ["import re2\n", "from re2 import compile\n"])
def test_a_plugin_may_import_re2(
    source: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(_source_tree(tmp_path), "combine/operators/extract.py", source)
    assert not _flags(_offenders(tmp_path, monkeypatch), "combine/operators/extract.py")


@pytest.mark.parametrize("module", ["numpy", "regex", "pydantic"])
def test_a_plugin_importing_another_third_party_module_fails(
    module: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(_source_tree(tmp_path), "combine/operators/extract.py", f"import {module}\n")
    assert _flags(_offenders(tmp_path, monkeypatch), "combine/operators/extract.py")


def test_the_core_importing_re2_fails(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(_source_tree(tmp_path), "combine/endpoint.py", "import re2\n")
    assert _flags(_offenders(tmp_path, monkeypatch), "combine/endpoint.py")
