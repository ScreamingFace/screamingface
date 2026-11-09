"""The SDK reads exactly the candidate-input schemas the engine writes (OME-1680).

FEATURE: a Case Result shows a picture Case's question (OME-1680). STORY: as a researcher, a
new envelope version cannot land in the engine without the SDK learning to read it, so my
results never silently fall back to raw wire text.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from screamingface.case_result import _CANDIDATE_INPUT_SCHEMAS, _DATA_URI_RE

# parents[4] = the monorepo root (tests/unit → tests → screamingface → packages → root)
_ENGINE_APP = Path(__file__).resolve().parents[4] / "apps" / "screamingface-engine"
_ENGINE_CONTRACT = _ENGINE_APP / "src" / "screamingface_engine" / "benchmarks" / "contract.py"
_ENGINE_ENVELOPE = (
    _ENGINE_APP / "src" / "screamingface_engine" / "benchmarks" / "candidate_input.py"
)
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


def _compiled_pattern(source: Path, name: str) -> tuple[str, set[str]]:
    """The pattern text and ``re`` flag names of ``name = re.compile(...)`` in a source file."""

    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.args[0], ast.Constant)
            and isinstance(node.value.args[0].value, str)
        ):
            flags: set[str] = {
                arg.attr for arg in node.value.args[1:] if isinstance(arg, ast.Attribute)
            }
            return node.value.args[0].value, flags
    raise AssertionError(f"{name} = re.compile(...) not found in {source}")


@pytest.mark.skipif(not _ENGINE_APP.exists(), reason="engine app not present (installed run)")
def test_the_sdk_data_uri_pattern_is_the_engines() -> None:
    # INVARIANT: a picture the engine accepts is one the SDK can measure; if the two patterns
    # drift, an accepted picture falls back to its raw base64 in the view. The twin of the
    # engine ↔ gateway pins (apps/aigateway/tests/unit/test_data_uri_matches_engine.py).
    assert _ENGINE_ENVELOPE.exists(), "engine candidate_input.py moved — update the bind"
    pattern, flags = _compiled_pattern(_ENGINE_ENVELOPE, "_DATA_URI_RE")

    assert _DATA_URI_RE.pattern == pattern
    assert _DATA_URI_RE.flags == re.compile(pattern, sum(getattr(re, f) for f in flags)).flags
