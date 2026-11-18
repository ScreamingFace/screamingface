"""The chat recipe check refuses a benchmark-linked expression (prd/chat-completion.md CC-S15)."""

from __future__ import annotations

import pytest
from _chat_corpus import corpus

from screamingface_engine.chat.recipe import LINKED_EXPRESSION_MESSAGE, RecipeRefusal, check_recipe
from url4 import RelExpr, Text, expr, render, src, text


def _linked_recipe(candidate: Text | RelExpr) -> str:
    """A root that names $model_1, with a top-level candidate source of the given value."""

    return render(
        expr(
            src(candidate, name="candidate", weight=0.0),
            src(
                RelExpr(path="/prov/b", context="$candidate", intent=text("judge")),
                name="model_1",
                weight=0.0,
            ),
            intent=text("$model_1"),
        )
    )


@pytest.mark.parametrize("with_tools", [False, True])
def test_benchmark_linked_expression_is_refused_with_the_candidate_hint(with_tools: bool) -> None:
    text_recipe = corpus()["lowering:pair-synthesize-evaluation"]
    with pytest.raises(RecipeRefusal) as caught:
        check_recipe(text_recipe, with_tools=with_tools)
    assert caught.value.code == "recipe_invalid"


@pytest.mark.parametrize("with_tools", [False, True])
def test_a_recipe_with_a_top_level_candidate_text_source_is_refused(with_tools: bool) -> None:
    linked = _linked_recipe(text("(model_1:0.0:/prov/a($input)!'x')!'$model_1'"))
    with pytest.raises(RecipeRefusal) as caught:
        check_recipe(linked, with_tools=with_tools)
    assert caught.value.code == "recipe_invalid"
    assert caught.value.message == LINKED_EXPRESSION_MESSAGE
    assert "Candidate URL4" in LINKED_EXPRESSION_MESSAGE
    assert "/prov/a" not in caught.value.message


def test_a_candidate_source_that_is_not_text_is_not_this_refusal() -> None:
    recipe = _linked_recipe(RelExpr(path="/prov/a", context="$input", intent=text("x")))
    checked = check_recipe(recipe, with_tools=False)
    assert checked.positions
