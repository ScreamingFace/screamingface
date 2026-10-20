"""Drift guard for the Pick output url4 fixtures the Engine runs (E4b pick-output).

The Engine's tests run ``recipe_s5_pick_output.url4`` and ``recipe_s8_pick_output.url4`` under
``apps/screamingface-engine/tests/unit/data/combine_contract/`` verbatim. These are the two
combine recipes of the README (S5 "choose response with maximum confidence", S8 "response from
model chosen") with ``output="answer"``. This file keeps each data file byte-identical to what the
SDK compiles today, so a compiler change that is not mirrored in a fixture fails HERE.
FEATURE: S5 and S8 recipes that answer one JSON field of the winner's reply.
STORY: as a maintainer, the Engine's copy of the S5 and S8 recipes is the SDK's copy.
INVARIANT defended: the fixture files are the SDK compiler output, byte for byte.

Regenerate from ``packages/screamingface`` (one name, or all of them)::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_pick_output_url4_fixtures as m; [m.write_fixture(n) for n in m.BUILDERS]"
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, requires_engine_app
from _combine_flow_fixtures import flow_operators

from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate

_MEMBERS = ["prov/alpha", "prov/beta", "prov/gamma"]


def s5_pick_output_url4() -> str:
    """S5: the answer is the ``answer`` field of the member with the highest confidence."""

    recipe = sx.Fanout(_MEMBERS) >> sx.ArgMax("field:confidence", output="answer")
    return compile_candidate(recipe, operators=flow_operators()).url4


def s8_pick_output_url4() -> str:
    """S8: the answer is the ``answer`` field of the member a signal chooses."""

    recipe = sx.Fanout(_MEMBERS) >> sx.ArgMax("field:confidence", output="answer")
    return compile_candidate(recipe, operators=flow_operators()).url4


BUILDERS: dict[str, Callable[[], str]] = {
    "recipe_s5_pick_output.url4": s5_pick_output_url4,
    "recipe_s8_pick_output.url4": s8_pick_output_url4,
}


def write_fixture(name: str) -> None:
    # WHY no trailing newline here: the repo's end-of-file-fixer hook appends one, and the
    # engine test and this guard both strip exactly one.
    (COMBINE_CONTRACT / name).write_text(BUILDERS[name](), encoding="utf-8")


@requires_engine_app
@pytest.mark.parametrize("name", BUILDERS)
def test_pick_output_url4_fixture_matches_the_sdk_compiler(name: str) -> None:
    # WHY the guard splits in two: skip only when the whole engine APP is absent; a present
    # app with a missing fixture must FAIL, not skip.
    fixture = COMBINE_CONTRACT / name
    assert ENGINE_APP.exists()
    assert fixture.exists(), f"combine_contract/{name} is missing - run write_fixture({name!r})"
    # WHY removesuffix: the repo's end-of-file-fixer hook appends one newline to data files.
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == BUILDERS[name]()
