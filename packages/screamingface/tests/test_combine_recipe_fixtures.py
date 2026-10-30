"""Drift guard for the E4b recipe fixtures (recipes PRD RC-D1).

FEATURE: the Engine runs ``combine_contract/recipe_*.url4`` verbatim. When the SDK compile of a
recipe changes, this test fails until the fixture is written again with ``write_recipe_fixture``,
so the Engine test always runs the bytes that the SDK compiles today.
"""

from __future__ import annotations

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, requires_engine_app
from _combine_recipes import RECIPES, compile_recipe

# The scenarios that work on E4a (recipes PRD §3). Later units add more, never fewer.
_E4A_RECIPES = {
    "recipe_s1.url4",
    "recipe_s2.url4",
    "recipe_s5.url4",
    "recipe_s7.url4",
    "recipe_s8.url4",
    "recipe_s9.url4",
    "recipe_s10.url4",
    "recipe_s11_max.url4",
}


@requires_engine_app
@pytest.mark.parametrize("name", sorted(RECIPES))
def test_recipe_fixtures_match_the_sdk_compile(name: str) -> None:
    # WHY the guard is split in two: skip only when the whole engine app is absent; a present
    # app with a missing fixture must FAIL, not skip.
    fixture = COMBINE_CONTRACT / name
    assert ENGINE_APP.exists()
    assert fixture.exists(), (
        f"combine_contract/{name} is missing - run write_recipe_fixture({name!r})"
    )
    # WHY removesuffix: every fixture ends with exactly one newline.
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == compile_recipe(name)


def test_recipe_builders_cover_the_e4a_scenarios() -> None:
    assert _E4A_RECIPES <= set(RECIPES)
