"""Engine-side twin of the SDK catalogue-vocabulary conformance bind (OME-1257).

FEATURE: the catalogue listing grouped by difficulty × interaction.
WHY a twin on the engine side: CI is path-filtered — the SDK's conformance test
never runs on an engine-only PR, so an engine edit to a declared axis vocabulary
would merge green and only fail later on an unrelated SDK PR. This twin runs in
the ENGINE lane and parses the SDK's source, so whichever side drifts, the lane
that carried the drift goes red. No cross-app import in either direction
(failure-codes precedent, OME-1233).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.definition import (
    _DIFFICULTY_TIERS,
    _INTERACTION_TYPES,
)

# parents[3] = apps/, so its parent is the monorepo root
_SDK_PACKAGE = Path(__file__).resolve().parents[3].parent / "packages" / "screamingface"
_SDK_CONTRACT = _SDK_PACKAGE / "src" / "screamingface" / "_catalogue_vocabulary.py"


def _sdk_tuple(tree: ast.Module, name: str) -> tuple[str, ...] | None:
    """Read one SDK vocabulary tuple by its assignment name, order preserved."""

    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == name:
            value = node.value
            if isinstance(value, ast.Tuple):
                return tuple(
                    item.value
                    for item in value.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                )
    return None


@pytest.mark.skipif(not _SDK_PACKAGE.exists(), reason="SDK package not present")
def test_the_engine_vocabularies_match_the_sdk_vocabularies() -> None:
    # INVARIANT: whichever side adds, removes, or REORDERS an axis value, the lane
    # running THAT side's tests fails loudly — order matters because the difficulty
    # tuple is the listing's easy→hard reading direction. A present SDK package with
    # a missing/renamed contract file must FAIL, not skip.
    assert _SDK_CONTRACT.exists(), "SDK _catalogue_vocabulary.py moved — update the bind"
    tree = ast.parse(_SDK_CONTRACT.read_text(encoding="utf-8"))
    sdk_tiers = _sdk_tuple(tree, "DECLARED_DIFFICULTY_TIERS")
    sdk_interactions = _sdk_tuple(tree, "DECLARED_INTERACTION_TYPES")
    assert sdk_tiers is not None, "SDK DECLARED_DIFFICULTY_TIERS not found"
    assert sdk_tiers == _DIFFICULTY_TIERS
    assert sdk_interactions is not None, "SDK DECLARED_INTERACTION_TYPES not found"
    assert sdk_interactions == _INTERACTION_TYPES
