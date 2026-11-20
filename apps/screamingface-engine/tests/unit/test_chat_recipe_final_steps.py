"""The final model steps of a checked recipe as plain data (prd/tool-calls.md §3.1).

The route side of tools reads the binding, the model route and the parameters of each final model
step (TC-S10, TC-S11). Each step is found by its scope and binding name, never by its path, Gate
bodies included.
"""

from __future__ import annotations

import pytest
from _chat_corpus import corpus

from screamingface_engine.chat.recipe import (
    CheckedRecipe,
    FinalModelStep,
    FinalPosition,
    RepointError,
    check_recipe,
    final_model_steps,
    one_model_recipe,
)
from url4 import RelExpr, expr, render, src, text
from url4.core.nodes import Expression
from url4.core.parser import build


def _fusion(synthesis: RelExpr | None = None) -> str:
    """Two members on one route and a synthesis on another; the members are not final."""
    return render(
        expr(
            src(
                RelExpr(path="/prov/a", context="$input", intent=text("Answer A")),
                name="model_1",
                weight=0.0,
            ),
            src(
                RelExpr(path="/prov/a", context="$input", intent=text("Answer B")),
                name="model_2",
                weight=0.0,
            ),
            src(
                synthesis
                or RelExpr(path="/prov/b", context="$model_1 $model_2", intent=text("Merge")),
                name="synthesis_1",
                weight=0.0,
            ),
            intent=text("$synthesis_1"),
        )
    )


def test_one_model_recipe_has_one_final_step() -> None:
    steps = final_model_steps(check_recipe(one_model_recipe("prov/a"), with_tools=True))
    assert steps == (FinalModelStep("model_1", "/prov/a", {}),)


def test_fusion_gives_only_the_synthesis_step() -> None:
    steps = final_model_steps(check_recipe(_fusion(), with_tools=True))
    assert steps == (FinalModelStep("synthesis_1", "/prov/b", {}),)


def test_gate_branches_each_give_their_own_model_call() -> None:
    checked = check_recipe(corpus()["keyword_router.url4"], with_tools=True)
    steps = final_model_steps(checked)
    assert [(step.binding, step.route) for step in steps] == [
        ("model_1", "/prov/math"),
        ("model_2", "/prov/coder"),
        ("model_3", "/prov/general"),
    ]
    assert [(step.binding, step.route) for step in steps] == [
        (position.binding, position.route) for position in checked.positions
    ]
    assert all(position.scope for position in checked.positions)


def test_a_step_keeps_its_web_search_parameter() -> None:
    synthesis = RelExpr(
        path="/prov/b",
        context="$model_1 $model_2",
        intent=text("Merge"),
        params=(("web_search", "true"),),
    )
    steps = final_model_steps(check_recipe(_fusion(synthesis), with_tools=True))
    assert len(steps) == 1
    assert steps[0].params.get("web_search") == "true"


def test_outcome_positions_give_no_step() -> None:
    checked = check_recipe(corpus()["word_abstain.url4"], with_tools=True)
    steps = final_model_steps(checked)
    assert [(step.binding, step.route) for step in steps] == [("model_1", "/prov/general")]


@pytest.mark.parametrize(
    "position",
    [
        pytest.param(FinalPosition("model", "model_1", (), "/prov/a"), id="not-a-model-call"),
        pytest.param(FinalPosition("model", "model_9", (), "/prov/a"), id="no-such-binding"),
    ],
)
def test_a_position_without_a_model_call_is_a_repoint_error(position: FinalPosition) -> None:
    root = build("(model_1:0.0:'plain words')!'$model_1'")
    assert isinstance(root, Expression)
    with pytest.raises(RepointError):
        final_model_steps(CheckedRecipe(root, (position,)))
