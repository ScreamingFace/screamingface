"""The vendored Inspect numeric rule is pure, complete and pinned (OME-1289, E4a, unit 2).

FEATURE: the engine grades a numeric answer exactly as Inspect does, without importing Inspect.
STORY: as an author of a numeric Candidate, my combine counts two answers as equal when Inspect's
own grader would. This is the base lane (no Inspect install); the lane that compares the copy with
the installed packages is ``inspect/test_combine_inspect_vendor_drift.py``. GP#2 and GP#7.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys
import types
import unicodedata

import pytest

from screamingface_engine.combine.operators import _inspect_vendor as vendor

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
_SCRIPT = _REPO_ROOT / ".claude/scripts/check_layering.py"
_PINS = {
    "INSPECT_AI_VERSION",
    "INSPECT_EVALS_VERSION",
    "PINNED_PYTHON",
    "UNIDATA_VERSION",
    "VENDORED_NAMES",
}


def _layering() -> types.ModuleType:
    """Load the gate as a module (`check_layering.py` is a repo script, not an installed one)."""
    spec = importlib.util.spec_from_file_location("check_layering", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _vendor_path() -> pathlib.Path:
    assert vendor.__file__ is not None
    return pathlib.Path(vendor.__file__)


def test_vendored_rule_pins_the_engine_image_unicode_data() -> None:
    if sys.version_info[:2] != vendor.PINNED_PYTHON:
        pytest.skip("the vendored rule is pinned to the engine image's Python 3.13")
    assert unicodedata.unidata_version == vendor.UNIDATA_VERSION


def test_vendored_module_imports_only_stdlib() -> None:
    layering = _layering()
    imported = layering.imported_top_level_modules(_vendor_path())
    assert imported <= sys.stdlib_module_names | {"__future__"}
    assert imported & layering.COMBINE_PLUGIN_DENY == set()
    assert layering.check_combine() == []


def test_vendored_module_holds_only_listed_definitions() -> None:
    listed = {name for _, names in vendor.VENDORED_NAMES for name in names}
    assert listed
    found: set[str] = set()
    for node in ast.parse(_vendor_path().read_text("utf-8")).body:
        if isinstance(node, ast.FunctionDef):
            found.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            found.update(target.id for target in targets if isinstance(target, ast.Name))
    assert found == listed | _PINS
