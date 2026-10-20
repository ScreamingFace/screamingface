"""The combine recipes of the README section "Combine recipes", one builder each (E4b RC).

FEATURE (E4b recipes PRD, RC-D1 and RC-D3): each recipe is compiled by the SDK into
``apps/screamingface-engine/tests/unit/data/combine_contract/<fixture>``, and the Engine runs
those bytes offline (``ET/test_combine_recipes.py``). ``test_combine_recipe_fixtures.py`` keeps
each fixture byte-equal to the SDK compile, and ``test_combine_recipes_readme.py`` proves that the
README code compiles to the same bytes.

A later unit adds a recipe by appending one ``@recipe(...)`` builder at the end of this file, the
README row and code line, and the fixture. Never edit an existing builder: its bytes are a fixture.

Regenerate every fixture from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0, 'tests'); \
import _combine_recipes as r; [r.write_recipe_fixture(n) for n in r.RECIPES]"
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from _combine_contract import COMBINE_CONTRACT
from _combine_flow_fixtures import flow_operators

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate

RecipeBuilder = Callable[[], sf.Recipe]

# The same values as the README "Combine recipes" code block. Change both or neither.
ROUTES = ["provider/alpha", "provider/beta", "provider/gamma"]
REPLY_JSON = (
    "Answer the request. Reply with only one JSON object: "
    '{"answer": "<your answer>", "confidence": <a number from 0 to 1>}.'
)
WRITER_PROMPT = "Write the final answer to the input from the selected answers."
RUBRIC = "Give a higher number to a more correct answer."


@dataclass(frozen=True, slots=True)
class RecipeFixture:
    scenario: str  # the scenario id of the recipes PRD, for example "S1"
    fixture: str  # the file name under combine_contract/, for example "recipe_s1.url4"
    # the variable that the README code block assigns, for example "s1_median_number"
    readme_name: str
    build: RecipeBuilder


# fixture file name -> recipe; filled by @recipe in file order
RECIPES: dict[str, RecipeFixture] = {}


def recipe(
    scenario: str, fixture: str, readme_name: str
) -> Callable[[RecipeBuilder], RecipeBuilder]:
    """Register a builder under its fixture name (a duplicate name is a bug in this file)."""

    def register(build: RecipeBuilder) -> RecipeBuilder:
        if fixture in RECIPES:
            raise ValueError(f"two recipes write {fixture}")
        RECIPES[fixture] = RecipeFixture(scenario, fixture, readme_name, build)
        return build

    return register


def compile_recipe(fixture: str) -> str:
    """The url4 that the SDK compiles today for the recipe of ``fixture``."""

    return compile_candidate(RECIPES[fixture].build(), operators=flow_operators()).url4


def write_recipe_fixture(fixture: str) -> None:
    # WHY the "\n": the repo's end-of-file-fixer hook wants one final newline, and every reader
    # strips exactly one.
    (COMBINE_CONTRACT / fixture).write_text(compile_recipe(fixture) + "\n", encoding="utf-8")


def _json_members() -> list[sf.Recipe]:
    return [sf.Model(route, prompt=REPLY_JSON) for route in ROUTES]


def _writer() -> sf.Model:
    return sf.Model("provider/writer", prompt=WRITER_PROMPT)


def _judge() -> sx.Judge:
    return sx.Judge("provider/judge", rubric=RUBRIC)


@recipe("S1", "recipe_s1.url4", "s1_median_number")
def recipe_s1() -> sf.Recipe:
    return sx.Fanout(ROUTES) >> sx.Median(over="last_number", select="value")


@recipe("S2", "recipe_s2.url4", "s2_median_member")
def recipe_s2() -> sf.Recipe:
    return sx.Fanout(ROUTES) >> sx.Median(over="last_number")


@recipe("S5", "recipe_s5.url4", "s5_max_confidence")
def recipe_s5() -> sf.Recipe:
    return sx.Fanout(_json_members()) >> sx.ArgMax("field:confidence")


@recipe("S7", "recipe_s7.url4", "s7_top_confidence")
def recipe_s7() -> sf.Recipe:
    return (
        sx.Fanout(_json_members()) >> sx.Rank(2, by="field:confidence") >> sx.Synthesize(_writer())
    )


@recipe("S8", "recipe_s8.url4", "s8_argmax_confidence")
def recipe_s8() -> sf.Recipe:
    return sx.Fanout(_json_members()) >> sx.ArgMax("field:confidence")


@recipe("S9", "recipe_s9.url4", "s9_confident_only")
def recipe_s9() -> sf.Recipe:
    return (
        sx.Fanout(_json_members())
        >> sx.Filter(where=sf.signal("field:confidence") > 0.7)
        >> sx.Synthesize(_writer())
    )


@recipe("S10", "recipe_s10.url4", "s10_judge_top")
def recipe_s10() -> sf.Recipe:
    return sx.Fanout(ROUTES) >> _judge() >> sx.Rank(2, by="score:judge") >> sx.Synthesize(_writer())


@recipe("S11", "recipe_s11_max.url4", "s11_judge_best")
def recipe_s11_max() -> sf.Recipe:
    return sx.Fanout(ROUTES) >> _judge() >> sx.ArgMax("score:judge")


@recipe("S3", "recipe_s3.url4", "s3_mean_static")
def recipe_s3() -> sf.Recipe:
    return sx.Fanout(ROUTES) >> sx.Mean(weights=(1, 1, 2))


@recipe("S4", "recipe_s4.url4", "s4_mean_by_confidence")
def recipe_s4() -> sf.Recipe:
    return sx.Fanout(_json_members()) >> sx.Mean(
        over="field:answer", weights=sf.signal("field:confidence")
    )


@recipe("S4, median form", "recipe_s4_median.url4", "s4_median_by_confidence")
def recipe_s4_median() -> sf.Recipe:
    return sx.Fanout(_json_members()) >> sx.Median(
        over="field:answer", weights=sf.signal("field:confidence"), select="value"
    )
