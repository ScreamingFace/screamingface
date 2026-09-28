"""The SDK's catalogue-axis vocabularies: conformance with the engine (OME-1257).

FEATURE: the catalogue listing grouped by difficulty × interaction.
STORY: as a researcher, the tier sections I see are exactly the tiers boards can
declare — the engine and SDK copies cannot drift apart, and neither can their ORDER,
because the order is the easy→hard reading direction of the listing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from screamingface._catalogue_vocabulary import (
    DECLARED_DIFFICULTY_TIERS,
    DECLARED_INTERACTION_TYPES,
)

# parents[4] = the monorepo root (tests/unit → tests → screamingface → packages → root)
_ENGINE_APP = Path(__file__).resolve().parents[4] / "apps" / "screamingface-engine"
_ENGINE_DEFINITION = _ENGINE_APP / "src" / "screamingface_engine" / "benchmarks" / "definition.py"


def _engine_tuple(tree: ast.Module, name: str) -> tuple[str, ...] | None:
    """Read one engine vocabulary tuple by its assignment name, order preserved."""

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


@pytest.mark.skipif(not _ENGINE_APP.exists(), reason="engine app not present (installed run)")
def test_the_sdk_vocabularies_match_the_engine_vocabularies() -> None:
    # INVARIANT (the conformance bind, failure-codes precedent OME-1233): the engine
    # and SDK keep two deliberate copies of each closed axis vocabulary — a value
    # added on one side and forgotten on the other fails HERE, loudly. Parsed from
    # the engine's source because an app's internals may never be imported.
    # WHY tuples, not sets: the difficulty ORDER is the listing's easy→hard reading
    # direction — a reordered copy is as wrong as a missing value.
    assert _ENGINE_DEFINITION.exists(), "engine definition.py moved — update the bind"
    tree = ast.parse(_ENGINE_DEFINITION.read_text(encoding="utf-8"))
    engine_tiers = _engine_tuple(tree, "_DIFFICULTY_TIERS")
    engine_interactions = _engine_tuple(tree, "_INTERACTION_TYPES")
    assert engine_tiers is not None, "engine _DIFFICULTY_TIERS not found"
    assert engine_tiers == DECLARED_DIFFICULTY_TIERS
    assert engine_interactions is not None, "engine _INTERACTION_TYPES not found"
    assert engine_interactions == DECLARED_INTERACTION_TYPES
