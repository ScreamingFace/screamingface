"""The reducer signal hooks: bindings, context, operation shape, field paths (OME-1289)."""

from __future__ import annotations

import pytest
from _combine_flow_fixtures import flow_operators
from _reducer_fixtures import compiled_vote_url4, fixture_operators, reducer_fusion
from url4 import Expression, Source, Text, build, render, struct

import screamingface as sf
from screamingface._evaluation.candidate import (
    _CandidateCompiler,
    _fusion_context,
    _ResolvedRecipe,
    compile_candidate,
)
from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec
from screamingface._evaluation.topology import _operation_shape, _RecipeTopology
from screamingface._signals import FIELD_PATH
from screamingface.reducer import _spec_ops, _spec_steps


def test_a_reducer_without_signals_compiles_as_before() -> None:
    compiled = compile_candidate(reducer_fusion(), operators=fixture_operators())

    assert compiled.url4 == compiled_vote_url4()
    root = build(compiled.url4)
    assert isinstance(root, Expression)
    topology = root.sources[-1]
    assert isinstance(topology, Source)
    assert isinstance(topology.value, Text)
    assert '"signals"' not in topology.value.value
    assert "signals" not in compiled.url4
    assert [operation.kind for operation in compiled.operations] == ["model"] * 3 + ["combine"]


def test_next_binding_counts_each_prefix_on_its_own() -> None:
    compiler = _CandidateCompiler()

    assert compiler._next_binding("synthesis") == "synthesis_1"
    assert compiler._next_binding("judge") == "judge_1"
    assert compiler._next_binding("judge") == "judge_2"
    assert compiler._next_binding("writer") == "writer_1"
    assert compiler._next_binding("synthesis") == "synthesis_2"


def _members() -> tuple[_ResolvedRecipe, ...]:
    return tuple(
        _ResolvedRecipe(
            reference=f"$model_{index}",
            operation_id=f"op_model_{index}",
            name=f"m{index}",
            kind="model",
            models=(f"provider/m{index}",),
            topology=_RecipeTopology(
                kind="model", name=f"m{index}", binding=f"model_{index}", role="model"
            ),
        )
        for index in (1, 2)
    )


def test_fusion_context_adds_signals_only_when_present() -> None:
    members = _members()
    today = render(
        struct({"input": "$input", "outputs": {"member_1": "$model_1", "member_2": "$model_2"}})
    )

    assert _fusion_context("$input", members) == today
    assert _fusion_context("$input", members, None) == today
    assert _fusion_context("$input", members, {}) == today

    with_signals = _fusion_context("$input", members, {"judge": "$judge_1"})
    assert with_signals == render(
        struct(
            {
                "input": "$input",
                "outputs": {"member_1": "$model_1", "member_2": "$model_2"},
                "signals": {"judge": "$judge_1"},
            }
        )
    )
    assert "signals: {judge: '$judge_1'}" in with_signals
    assert with_signals.index("outputs") < with_signals.index("signals")


def test_operation_shape_is_one_rule() -> None:
    def node(kind: str, role: str | None = None) -> _RecipeTopology:
        return _RecipeTopology(kind=kind, name="x", binding="model_1", role=role)  # type: ignore[arg-type]

    assert _operation_shape(node("reducer")) == ("combine", "combine")
    assert _operation_shape(node("model", "judge")) == ("judge", "judge")
    assert _operation_shape(node("model", "synthesis")) == ("synthesis", "synthesis")
    assert _operation_shape(node("model", "model")) == ("model", "answer")
    assert _operation_shape(node("model")) == ("model", "answer")


@pytest.mark.parametrize("path", ["a", "a.b", "a[0].b", "[0].a", "a[10]", "_a1.b_2[3][4]"])
def test_field_path_matches_the_engine_grammar_for_valid_paths(path: str) -> None:
    assert FIELD_PATH.fullmatch(path) is not None


@pytest.mark.parametrize(
    "path", ["", "a.", ".a", "a[01]", "a b", "$a", "a..b", "1a", "a[]", "a[-1]"]
)
def test_field_path_matches_the_engine_grammar_for_invalid_paths(path: str) -> None:
    assert FIELD_PATH.fullmatch(path) is None


def test_spec_steps_read_every_stage_with_its_args() -> None:
    spec = decode_combine_spec(
        combine_spec_text(
            sf.Judge("provider/j", returns="scores", rubric="Score."),
            member_count=2,
            operators=flow_operators(),
        )
    )

    assert _spec_steps(spec) == {
        "extract": None,
        "normalize": None,
        "reduce": ("scores@1", {"source": "judge"}),
        "select": ("max_score@1", {}),
    }
    with pytest.raises(ValueError, match="cannot rebuild"):
        _spec_ops(spec, "scores")
