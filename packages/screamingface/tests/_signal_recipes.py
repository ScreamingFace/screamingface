"""The signal recipes of the README section "Signal sources", one builder each (E4b part 3 RC-1).

FEATURE (E4b part 3 recipes PRD, RC-1): each signal recipe (S12 to S16) is compiled by the SDK into
``apps/screamingface-engine/tests/unit/data/combine_contract/<fixture>``, and the Engine runs
those bytes offline (``ET/test_signal_recipes.py``). ``test_signal_recipe_fixtures.py`` keeps
each fixture byte-equal to the SDK compile, and ``test_signal_recipes_readme.py`` proves that the
README code compiles to the same bytes.

Regenerate the five new fixtures from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0, 'tests'); \
import _signal_recipes as r; [r.write_signal_recipe_fixture(n) for n in r.SIGNAL_RECIPES]"

Never edit an existing builder: its bytes are a fixture.
"""

from __future__ import annotations

from collections.abc import Callable

from _combine_contract import COMBINE_CONTRACT
from _combine_flow_fixtures import flow_operators
from _combine_recipes import WRITER_PROMPT, RecipeBuilder, RecipeFixture

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

# The same values as the README "Signal sources" code block. Change both or neither.
SIGNAL_ROUTES = [
    "openrouter/openai/gpt-4o-mini",
    "openrouter/openai/gpt-4.1-mini",
    "openrouter/openai/gpt-4.1-nano",
]
STATED_PROMPT = (
    "Answer the request. On the first line write Confidence: and a whole number from 0 to 100. "
    "On the last line write only your final answer."
)
CONFIDENCE_PATTERN = r"Confidence: ([0-9]+)"
SMALL_ROUTE = "openrouter/openai/gpt-4o-mini"
LARGE_WRITER_ROUTE = "openrouter/openai/gpt-4.1"
LOGPROB_THRESHOLD = -0.3

# fixture file name -> recipe; filled by @signal_recipe in file order
SIGNAL_RECIPES: dict[str, RecipeFixture] = {}


def signal_recipe(
    scenario: str, fixture: str, readme_name: str
) -> Callable[[RecipeBuilder], RecipeBuilder]:
    """Register a builder under its fixture name (a duplicate name is a bug in this file)."""

    def register(build: RecipeBuilder) -> RecipeBuilder:
        if fixture in SIGNAL_RECIPES:
            raise ValueError(f"two recipes write {fixture}")
        SIGNAL_RECIPES[fixture] = RecipeFixture(scenario, fixture, readme_name, build)
        return build

    return register


def compile_signal_recipe(fixture: str) -> str:
    """The url4 that the SDK compiles today for the signal recipe of ``fixture``."""

    return compile_candidate(SIGNAL_RECIPES[fixture].build(), operators=flow_operators()).url4


def write_signal_recipe_fixture(fixture: str) -> None:
    # WHY the "\n": the end-of-file-fixer hook wants one final newline; every reader strips one.
    (COMBINE_CONTRACT / fixture).write_text(compile_signal_recipe(fixture) + "\n", encoding="utf-8")


@signal_recipe("S12", "recipe_s12.url4", "s12_verbalized_vote")
def recipe_s12() -> sf.Recipe:
    return sf.Fanout(
        [sf.Model(route, prompt=STATED_PROMPT) for route in SIGNAL_ROUTES],
        signals={"conf": sf.Verbalized(CONFIDENCE_PATTERN)},
    ) >> sf.Vote(weights=sf.signal("conf"))


@signal_recipe("S13", "recipe_s13.url4", "s13_logprob_vote")
def recipe_s13() -> sf.Recipe:
    return sf.Fanout(SIGNAL_ROUTES, signals={"p": sf.Logprob("prob")}) >> sf.Vote(
        weights=sf.signal("p")
    )


@signal_recipe("S14", "recipe_s14.url4", "s14_logprob_best")
def recipe_s14() -> sf.Recipe:
    return sf.Fanout(SIGNAL_ROUTES, signals={"lp": sf.Logprob("mean")}) >> sf.ArgMax("lp")


@signal_recipe("S15", "recipe_s15.url4", "s15_entropy_best")
def recipe_s15() -> sf.Recipe:
    return sf.Fanout(SIGNAL_ROUTES, signals={"ent": sf.Entropy()}) >> sf.ArgMin("ent")


@signal_recipe("S16", "recipe_s16.url4", "s16_logprob_threshold")
def recipe_s16() -> sf.Recipe:
    return (
        sf.Fanout([SMALL_ROUTE], signals={"lp": sf.Logprob("mean")})
        >> sf.Filter(where=sf.signal("lp") >= LOGPROB_THRESHOLD)
        >> sf.Synthesize(sf.Model(LARGE_WRITER_ROUTE, prompt=WRITER_PROMPT))
    )
