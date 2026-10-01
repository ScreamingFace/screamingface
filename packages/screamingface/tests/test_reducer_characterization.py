"""Characterization of today's Fusion compiler before the reducer slot (OME-1289, SL-1/SL-2).

These tests pass on the unchanged compiler by design: they pin the Model and Recipe
synthesizer bytes and the binding vocabulary the reducer slot must not disturb.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import screamingface as sf
from screamingface._evaluation import topology
from screamingface._evaluation.candidate import compile_candidate
from screamingface.operation import OperationInfo
from screamingface.url4 import _BINDING as URL4_BINDING

_DATA = Path(__file__).parent / "data"

_GOLDEN: dict[str, sf.Recipe] = {
    "fusion_model_synthesizer.url4": sf.Fusion(
        [
            sf.Model("provider/a", prompt="Answer A."),
            sf.Model("provider/b", params={"temperature": 0.2}),
        ],
        name="panel",
        synthesizer=sf.Model(
            "provider/s",
            prompt="Blend $1 answers.\nKeep it short.",
            params={"seed": 7},
        ),
    ),
    "pipeline_fusion_synthesizer.url4": sf.Pipeline(
        [
            sf.Model("provider/draft"),
            sf.Fusion(["provider/x", "provider/y"], synthesizer="provider/s"),
        ]
    ),
    "fusion_recipe_synthesizer.url4": sf.Fusion(
        ["provider/a", "provider/b"], synthesizer=sf.Pipeline(["provider/j", "provider/w"])
    ),
}


@pytest.mark.parametrize("golden", sorted(_GOLDEN))
def test_model_synthesizer_url4_is_unchanged(golden: str) -> None:
    # WHY removesuffix: the repo's end-of-file-fixer hook appends one newline to data files;
    # the compiler output has none.
    expected = (_DATA / golden).read_text(encoding="utf-8").removesuffix("\n")

    assert compile_candidate(_GOLDEN[golden]).url4 == expected


def test_model_synthesizer_operations_are_unchanged() -> None:
    compiled = compile_candidate(_GOLDEN["fusion_model_synthesizer.url4"])

    assert [(op.id, op.kind, op.label) for op in compiled.operations] == [
        ("op_model_1", "model", "a answer"),
        ("op_model_2", "model", "b answer"),
        ("op_synthesis_1", "synthesis", "panel synthesis"),
    ]
    assert all(isinstance(op, OperationInfo) for op in compiled.operations)


def test_binding_pattern_today_accepts_model_and_synthesis_only_among_known_names() -> None:
    # Only the stable subset is pinned: the pattern widens (judge_N, writer_N) in OME-1289,
    # and tests/unit/test_binding_pattern_conformance.py pins that acceptance.
    for pattern in (URL4_BINDING, topology._BINDING):
        assert pattern.fullmatch("model_1")
        assert pattern.fullmatch("synthesis_2")
        assert not pattern.fullmatch("answer_5")
        assert not pattern.fullmatch("model_")
        assert not pattern.fullmatch("Model_1")
    assert topology._BINDING.fullmatch("loop_candidate")
