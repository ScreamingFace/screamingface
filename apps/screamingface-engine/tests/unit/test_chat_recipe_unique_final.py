"""With tools, a final binding with two sources at its scope is refused before the run (TC-S16).

FEATURE: tool-calls §3.1, §3.2 and TC-S16. With tools, the re-point moves each source of a final
binding, so two sources of one final model binding at one scope (the root or a Gate branch body)
would both run and fail the turn with `final_step_ambiguous` after the model calls were paid. The
recipe check refuses such a recipe with tools as `recipe_not_supported`; with no tools it runs as
built. The run-time `final_step_ambiguous` stays the last guard.
"""

from __future__ import annotations

import pytest
from _chat_app import ToolCatalog, answered, body, chat_app, error, post
from _chat_corpus import corpus
from _chat_final_world import TOOL

from screamingface_engine.chat.recipe import RecipeRefusal, check_recipe

_ROOT_TWICE = "(model_1:0.0:/prov/a($input)!'x', model_1:0.0:/prov/b($input)!'y')!'$model_1'"
_BRANCH_END = "')!'$model_1';iteration.on_error=fail"


def _branch_twice() -> str:
    """The keyword router with a second `model_1` source in the body of its `then` branch."""
    router = corpus()["keyword_router.url4"]
    assert router.count(_BRANCH_END) == 1
    return router.replace(
        _BRANCH_END, "', model_1:0.0:/prov/b($input)!'twice')!'$model_1';iteration.on_error=fail"
    )


def _cases() -> list[object]:
    return [
        pytest.param(_ROOT_TWICE, id="root"),
        pytest.param(_branch_twice(), id="gate-branch-body"),
    ]


@pytest.mark.parametrize("recipe", _cases())
def test_a_final_binding_with_two_sources_is_refused_with_tools(recipe: str) -> None:
    with pytest.raises(RecipeRefusal) as refused:
        check_recipe(recipe, with_tools=True)

    assert refused.value.code == "recipe_not_supported"
    assert "not unique" in refused.value.message
    assert "prov/" not in refused.value.message


@pytest.mark.parametrize("recipe", _cases())
def test_the_same_recipe_with_no_tools_runs_as_built(recipe: str) -> None:
    checked = check_recipe(recipe, with_tools=False)

    assert any(position.kind == "model" for position in checked.positions)


def test_two_sources_of_a_binding_that_is_not_final_are_not_refused() -> None:
    recipe = (
        "(model_1:0.0:/prov/a($input)!'x', model_1:0.0:/prov/b($input)!'y',"
        " model_2:0.0:/prov/a($model_1)!'z')!'$model_2'"
    )

    checked = check_recipe(recipe, with_tools=True)

    assert [position.binding for position in checked.positions] == ["model_2"]


@pytest.mark.asyncio
@pytest.mark.parametrize("recipe", _cases())
async def test_the_route_answers_400_and_schedules_no_run(recipe: str) -> None:
    catalog = ToolCatalog(
        {
            model: ["tools"]
            for model in ("prov/a", "prov/b", "prov/math", "prov/coder", "prov/general")
        }
    )
    ca = chat_app(answered(), catalog=catalog)

    resp = await post(ca.app, body(recipe, tools=[TOOL]))

    assert resp.status_code == 400
    assert resp.headers["x-should-retry"] == "false"
    envelope = error(resp)
    assert envelope["code"] == "recipe_not_supported"
    assert "not unique" in envelope["message"]
    assert envelope["param"] == "model"
    assert ca.runner.attempted == []
    assert ca.runner.scheduled == []
    assert ca.objects.objects == {}
    assert catalog.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("recipe", _cases())
async def test_the_route_runs_the_same_recipe_with_no_tools(recipe: str) -> None:
    ca = chat_app(answered())

    resp = await post(ca.app, body(recipe))

    assert resp.status_code == 200
    assert [run["url4"] for run in ca.runner.scheduled] == [recipe]
