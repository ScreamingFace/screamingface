"""The Case-id cap: the SDK's copy matches the Engine's (OME-1739, review on #1653).

STORY: as a researcher, a list the Engine would take is never refused by the SDK first, and a
list the SDK sends is never one the Engine refuses for its length.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from screamingface._evaluation.case_selection import MAX_SELECTED_CASES

# parents[4] = the monorepo root (tests/unit → tests → screamingface → packages → root)
_ENGINE_APP = Path(__file__).resolve().parents[4] / "apps" / "screamingface-engine"
_ENGINE_SELECTION = _ENGINE_APP / "src" / "screamingface_engine" / "benchmarks" / "selection.py"


def _engine_int(tree: ast.Module, name: str) -> int | None:
    """Read one module-level integer constant from the Engine's source by its name."""

    for node in tree.body:
        if isinstance(node, ast.Assign):
            names: list[str] = [getattr(target, "id", "") for target in node.targets]
        elif isinstance(node, ast.AnnAssign):
            names = [getattr(node.target, "id", "")]
        else:
            continue
        value: ast.expr | None = node.value
        if name in names and isinstance(value, ast.Constant) and type(value.value) is int:
            return value.value
    return None


@pytest.mark.skipif(not _ENGINE_APP.exists(), reason="engine app not present (installed run)")
def test_the_sdk_case_id_cap_matches_the_engine_cap() -> None:
    # INVARIANT: two deliberate copies, bound here. A raised Engine cap would otherwise leave the
    # SDK refusing lists the Engine accepts; parsed from source because an app's internals may
    # never be imported.
    assert _ENGINE_SELECTION.exists(), "engine benchmarks/selection.py moved — update the bind"
    tree: ast.Module = ast.parse(_ENGINE_SELECTION.read_text(encoding="utf-8"))
    engine_cap: int | None = _engine_int(tree, "MAX_SELECTED_CASE_IDS")
    assert engine_cap is not None, "engine MAX_SELECTED_CASE_IDS not found"
    assert engine_cap == MAX_SELECTED_CASES
