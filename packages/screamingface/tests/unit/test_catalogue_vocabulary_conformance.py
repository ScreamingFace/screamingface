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


_ENGINE_CONTRACT = _ENGINE_APP / "src" / "screamingface_engine" / "benchmarks" / "contract.py"


def _engine_text(tree: ast.Module, name: str) -> str | None:
    """Read one engine string constant by its assignment name."""

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and getattr(node.target, "id", "") == name
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return None


def _engine_class_fields(tree: ast.Module, class_name: str) -> set[str]:
    """The annotated field names one engine class declares."""

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                item.target.id
                for item in node.body
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            }
    return set()


@pytest.mark.skipif(not _ENGINE_APP.exists(), reason="engine app not present (installed run)")
def test_the_inverted_grade_key_is_spelled_the_same_on_both_sides() -> None:
    """OME-1400: the SDK reads the refusal-rate mark from the Benchmark resource and the
    run result. A rename on either side must fail this lane, not a researcher's paid run."""

    from screamingface._catalogue_vocabulary import INVERTED_GRADE_KEY

    assert _ENGINE_DEFINITION.exists(), "engine definition.py moved — update the bind"
    assert _ENGINE_CONTRACT.exists(), "engine contract.py moved — update the bind"
    definition = ast.parse(_ENGINE_DEFINITION.read_text(encoding="utf-8"))
    contract = ast.parse(_ENGINE_CONTRACT.read_text(encoding="utf-8"))
    assert _engine_text(definition, "INVERTED_GRADE_KEY") == INVERTED_GRADE_KEY
    assert INVERTED_GRADE_KEY in _engine_class_fields(contract, "CandidateResult")


_ENGINE_PROVENANCE = _ENGINE_APP / "src" / "screamingface_engine" / "benchmarks" / "provenance.py"


@pytest.mark.skipif(not _ENGINE_APP.exists(), reason="engine app not present (installed run)")
def test_the_saturation_verdicts_match_the_engine_verdicts() -> None:
    # OME-1455: the listing will group on these words; whichever side adds or reorders one,
    # the lane running that side's tests fails loudly (the difficulty-tier bind's reason).
    from screamingface._catalogue_vocabulary import SATURATION_VERDICTS

    assert _ENGINE_PROVENANCE.exists(), "engine provenance.py moved — update the bind"
    tree = ast.parse(_ENGINE_PROVENANCE.read_text(encoding="utf-8"))
    engine_verdicts = _engine_tuple(tree, "SATURATION_VERDICTS")
    assert engine_verdicts is not None, "engine SATURATION_VERDICTS not found"
    assert engine_verdicts == SATURATION_VERDICTS
