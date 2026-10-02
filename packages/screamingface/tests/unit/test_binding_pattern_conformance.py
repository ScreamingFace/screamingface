"""The attributed-operation binding vocabulary, bound to the Engine by one shared fixture.

FEATURE: judge_N and writer_N join model_N and synthesis_N as attributed operation bindings
(OME-1289). STORY: as a researcher, an operation the SDK names is an operation the Engine
attributes — the two copies of the pattern cannot drift apart.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from screamingface import url4 as sdk_url4
from screamingface._evaluation import topology
from screamingface._operation_bindings import (
    OPERATION_BINDING,
    OPERATION_BINDING_PATTERN,
    TOPOLOGY_BINDING,
)

# parents[4] = the monorepo root (tests/unit → tests → screamingface → packages → root)
_ENGINE_APP = Path(__file__).resolve().parents[4] / "apps" / "screamingface-engine"
_FIXTURE = _ENGINE_APP / "tests" / "unit" / "data" / "combine_contract" / "binding_names.json"
_ENGINE_OUTPUTS = (
    _ENGINE_APP / "src" / "screamingface_engine" / "benchmarks" / "operation_outputs.py"
)

pytestmark = pytest.mark.skipif(
    not _ENGINE_APP.exists(), reason="engine app not present (installed run)"
)


def _fixture() -> dict[str, object]:
    # WHY the guard splits in two: skip only when the whole engine APP is absent; a present
    # app with a missing fixture must FAIL, not skip.
    assert _FIXTURE.exists(), "combine_contract/binding_names.json moved — update the bind"
    loaded = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_binding_pattern_fixture_matches_sdk_and_engine() -> None:
    fixture = _fixture()

    assert OPERATION_BINDING_PATTERN == fixture["pattern"]
    for name in fixture["accept"]:  # type: ignore[attr-defined]
        assert OPERATION_BINDING.fullmatch(name), name
        assert TOPOLOGY_BINDING.fullmatch(name), name
    for name in fixture["reject"]:  # type: ignore[attr-defined]
        assert not OPERATION_BINDING.fullmatch(name), name
    # the topology vocabulary is the operation vocabulary plus the corrective loop's binding
    assert TOPOLOGY_BINDING.fullmatch("loop_candidate")
    # one pattern for every SDK consumer
    assert sdk_url4._BINDING is OPERATION_BINDING
    assert topology._BINDING is TOPOLOGY_BINDING
    assert sdk_url4._REFERENCE.findall("$judge_1 $writer_2 $answer_3") == ["judge_1", "writer_2"]


def test_engine_binding_pattern_matches_the_shared_fixture() -> None:
    # The engine widened `_BINDING` in unit 3 of OME-1289; both sides bind to the shared fixture.
    fixture = _fixture()
    tree = ast.parse(_ENGINE_OUTPUTS.read_text(encoding="utf-8"))
    engine_pattern: str | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", "") == "_BINDING" for target in node.targets
        ):
            constants = [
                item.value
                for item in ast.walk(node)
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            engine_pattern = constants[0] if constants else None
    assert engine_pattern is not None, "engine operation_outputs._BINDING not found"
    assert engine_pattern == fixture["pattern"]
