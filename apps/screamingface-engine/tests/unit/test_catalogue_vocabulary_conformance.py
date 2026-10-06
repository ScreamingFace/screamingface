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


_SDK_VOCABULARY = _SDK_PACKAGE / "src" / "screamingface" / "_catalogue_vocabulary.py"


def _sdk_text(tree: ast.Module, name: str) -> str | None:
    """Read one SDK string constant by its assignment name."""

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and getattr(node.target, "id", "") == name
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return None


@pytest.mark.skipif(not _SDK_PACKAGE.exists(), reason="SDK package not present")
def test_the_inverted_grade_key_is_spelled_the_same_on_both_sides() -> None:
    """OME-1400: the refusal-rate mark rides the Benchmark resource AND the run result.
    A rename on one side would otherwise surface only at run time — after a paid run,
    as an SDK refusing an unknown field. This twin fails the lane that carried it."""

    from screamingface_engine.benchmarks.contract import CandidateResult
    from screamingface_engine.benchmarks.definition import INVERTED_GRADE_KEY

    assert _SDK_VOCABULARY.exists(), "SDK _catalogue_vocabulary.py moved — update the bind"
    sdk_key = _sdk_text(
        ast.parse(_SDK_VOCABULARY.read_text(encoding="utf-8")), "INVERTED_GRADE_KEY"
    )
    assert sdk_key == INVERTED_GRADE_KEY
    # The run result spells the key through its field name — the same word.
    assert INVERTED_GRADE_KEY in CandidateResult.model_fields


@pytest.mark.skipif(not _SDK_PACKAGE.exists(), reason="SDK package not present")
def test_the_saturation_verdicts_are_spelled_the_same_on_both_sides() -> None:
    # OME-1455: the SDK's copy of SATURATION_VERDICTS orders its listing; the engine side
    # pins it here so an engine-only PR cannot drift the words (the difficulty-tier reason).
    from screamingface_engine.benchmarks.provenance import SATURATION_VERDICTS

    assert _SDK_VOCABULARY.exists(), "SDK _catalogue_vocabulary.py moved — update the bind"
    tree = ast.parse(_SDK_VOCABULARY.read_text(encoding="utf-8"))
    sdk_verdicts = _sdk_tuple(tree, "SATURATION_VERDICTS")
    assert sdk_verdicts is not None, "SDK SATURATION_VERDICTS not found"
    assert sdk_verdicts == SATURATION_VERDICTS
    # The Scoreboard is the third side: its seed stores only a word on this list, so a
    # verdict added on the Engine alone would be stored as null on every board.
    assert _SCOREBOARD_SCHEMAS.exists(), "Scoreboard scores/schemas.py moved — update the bind"
    board_tree = ast.parse(_SCOREBOARD_SCHEMAS.read_text(encoding="utf-8"))
    board_verdicts = _sdk_tuple(board_tree, "SATURATION_VERDICTS")
    assert board_verdicts is not None, "Scoreboard SATURATION_VERDICTS not found"
    assert board_verdicts == SATURATION_VERDICTS


_SCOREBOARD_SCHEMAS = (
    _SDK_PACKAGE.parent.parent
    / "apps"
    / "scoreboard"
    / "src"
    / "scoreboard"
    / "scores"
    / "schemas.py"
)
