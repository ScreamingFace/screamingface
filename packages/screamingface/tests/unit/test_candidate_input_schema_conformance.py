"""The SDK reads exactly the candidate-input schemas the engine writes (OME-1680).

FEATURE: a Case Result shows a picture Case's question (OME-1680). STORY: as a researcher, a
new envelope version cannot land in the engine without the SDK learning to read it, so my
results never silently fall back to raw wire text.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from screamingface.case_result import _CANDIDATE_INPUT_SCHEMAS

# parents[4] = the monorepo root (tests/unit → tests → screamingface → packages → root)
_ENGINE_APP = Path(__file__).resolve().parents[4] / "apps" / "screamingface-engine"
_ENGINE_CONTRACT = _ENGINE_APP / "src" / "screamingface_engine" / "benchmarks" / "contract.py"
_SCHEMA_FAMILY = "screamingface.candidate-input."


def _engine_schemas() -> set[str]:
    """Every module-level ``NAME = "screamingface.candidate-input.*"`` in the engine contract."""

    tree: ast.Module = ast.parse(_ENGINE_CONTRACT.read_text(encoding="utf-8"))
    return {
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and node.value.value.startswith(_SCHEMA_FAMILY)
    }


@pytest.mark.skipif(not _ENGINE_APP.exists(), reason="engine app not present (installed run)")
def test_the_sdk_reads_exactly_the_engines_candidate_input_schemas() -> None:
    # INVARIANT (acceptance 5): the engine and SDK keep two deliberate copies of the schema
    # names; a version added on one side only fails HERE instead of leaving the SDK showing raw
    # envelopes. Parsed from source because an app's internals may never be imported.
    # WHY the guard splits in two: skip only when the whole engine app is absent (an installed
    # package run); a present app with a moved contract file must FAIL, not skip.
    assert _ENGINE_CONTRACT.exists(), "engine contract.py moved — update the bind"
    engine: set[str] = _engine_schemas()

    # WHY a floor: a parse that finds nothing would make the equality vacuous.
    assert "screamingface.candidate-input.v1" in engine
    assert set(_CANDIDATE_INPUT_SCHEMAS) == engine
