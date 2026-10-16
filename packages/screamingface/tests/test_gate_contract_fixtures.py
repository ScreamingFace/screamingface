"""Drift guard for the SDK-compiled gate url4 fixtures (E4b part 5, units 3 and 4; GA#17).

FEATURE: the Engine runs ``combine_contract/gate_*_vote_candidate.url4`` verbatim (GA#18). This
file keeps each data file byte-identical to what the SDK compiles today. ``BUILDERS`` maps each
fixture file name to the function that compiles it. Unit 4 appends its builders with one
``BUILDERS |= {...}`` line and its own test function.
STORY: as a maintainer, a change to the SDK compile of a gated vote fails here, not in a silent
Engine run.
INVARIANT defended: each fixture is the SDK compile of one three-member gated vote (GA-1, GA-4).

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0, 'tests'); \
import test_gate_contract_fixtures as m; [m.write_fixture(n) for n in m.BUILDERS]"
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, engine_operators, requires_engine_app

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

_MEMBERS = ["prov/alpha", "prov/beta", "prov/gamma"]
CONF_PATTERN = "Confidence: ([0-9]+)"


def gate_abstain_vote_url4() -> str:
    """GA-1: the vote keeps its majority when the agreement is at least 0.7; else it abstains."""
    recipe = sf.Fusion(
        _MEMBERS, name="vote", synthesizer=sf.Vote(gate=sf.Gate("agreement", ">=", 0.7))
    )
    return compile_candidate(recipe, operators=engine_operators()).url4


def gate_verbalized_vote_url4() -> str:
    """GA-4: the vote keeps its majority when the chosen member states a confidence of 80+."""
    recipe = sf.Fusion(
        _MEMBERS,
        name="vote",
        signals={"conf": sf.Verbalized(CONF_PATTERN)},
        synthesizer=sf.Vote(gate=sf.Gate("chosen:conf", ">=", 80)),
    )
    return compile_candidate(recipe, operators=engine_operators()).url4


BUILDERS: dict[str, Callable[[], str]] = {
    "gate_abstain_vote_candidate.url4": gate_abstain_vote_url4,
    "gate_verbalized_vote_candidate.url4": gate_verbalized_vote_url4,
}
# The fixtures of unit 3. A fixed tuple: unit 4 adds to BUILDERS, never to this tuple.
_CORE_FIXTURES: tuple[str, ...] = (
    "gate_abstain_vote_candidate.url4",
    "gate_verbalized_vote_candidate.url4",
)


def write_fixture(name: str) -> None:
    # WHY "\n": the end-of-file-fixer wants one final newline; every reader strips exactly one.
    (COMBINE_CONTRACT / name).write_text(BUILDERS[name]() + "\n", encoding="utf-8")


def assert_fixture_matches(name: str) -> None:
    """The committed fixture ``name`` equals what its builder compiles today (unit 4 reuses it)."""
    fixture = COMBINE_CONTRACT / name
    assert ENGINE_APP.exists()
    assert fixture.exists(), f"combine_contract/{name} is missing - run write_fixture({name!r})"
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == BUILDERS[name]()


@requires_engine_app
@pytest.mark.parametrize("name", _CORE_FIXTURES)
def test_gate_url4_fixtures_match_the_sdk_compile(name: str) -> None:
    assert_fixture_matches(name)
