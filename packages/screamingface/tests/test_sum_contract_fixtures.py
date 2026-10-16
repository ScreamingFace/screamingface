"""Drift guard for the SDK-compiled sum url4 fixtures (E4b part 6, unit 2; SA#12).

FEATURE: the Engine runs ``combine_contract/sum_pick_candidate.url4`` verbatim (SA#13). This file
keeps each data file byte-identical to what the SDK compiles today. ``BUILDERS`` maps each fixture
file name to the function that compiles it. Unit 5 (band-api) appends its builder with one
``BUILDERS |= {...}`` line and its own test function.
STORY: as a maintainer, a change to the SDK compile of a sum fails here, not in a silent Engine
run.
INVARIANT defended: the fixture is the SDK compile of recipe R (sum-api §3), a three-member Pick
of the member with the lowest declared sum ``risk``.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0, 'tests'); \
import test_sum_contract_fixtures as m; [m.write_fixture(n) for n in m.BUILDERS]"
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, engine_operators, requires_engine_app

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

_MEMBERS = ["prov/alpha", "prov/beta", "prov/gamma"]


def sum_pick_url4() -> str:
    """SA-5: recipe R; each member gets risk = 0.5 x sev_a + 0.3 x sev_b, the Pick keeps the
    lowest."""
    recipe = sf.Fusion(
        _MEMBERS,
        name="pick",
        signals={
            "risk": sf.Sum({"sev_a": 0.5, "sev_b": 0.3}),
            "sev_a": sf.Verbalized("A: ([0-9]+)"),
            "sev_b": sf.Verbalized("B: ([0-9]+)"),
        },
        synthesizer=sf.Pick(by_signal=sf.signal("risk"), order="min"),
    )
    return compile_candidate(recipe, operators=engine_operators()).url4


BUILDERS: dict[str, Callable[[], str]] = {"sum_pick_candidate.url4": sum_pick_url4}
# The fixtures of unit 2. A fixed tuple: unit 5 adds to BUILDERS, never to this tuple.
_SUM_FIXTURES: tuple[str, ...] = ("sum_pick_candidate.url4",)


def write_fixture(name: str) -> None:
    # WHY "\n": the end-of-file-fixer wants one final newline; every reader strips exactly one.
    (COMBINE_CONTRACT / name).write_text(BUILDERS[name]() + "\n", encoding="utf-8")


def assert_fixture_matches(name: str) -> None:
    """The committed fixture ``name`` equals what its builder compiles today (unit 5 reuses it)."""
    fixture = COMBINE_CONTRACT / name
    assert ENGINE_APP.exists()
    assert fixture.exists(), f"combine_contract/{name} is missing - run write_fixture({name!r})"
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == BUILDERS[name]()


@requires_engine_app
@pytest.mark.parametrize("name", _SUM_FIXTURES)
def test_sum_pick_fixture_matches_the_sdk_compile(name: str) -> None:
    assert_fixture_matches(name)


# ---- E4b part 6 unit 5 (band-api): BA#7 ----


def gate_band_vote_url4() -> str:
    """BA-2: recipe G, a vote gated on the mean of a declared sum, with an abstain band."""

    recipe = sf.Fusion(
        ["prov/alpha", "prov/beta", "prov/gamma"],
        name="vote",
        signals={
            "risk": sf.Sum({"sev_a": 0.5, "sev_b": 0.3}),
            "sev_a": sf.Verbalized("A: ([0-9]+)"),
            "sev_b": sf.Verbalized("B: ([0-9]+)"),
        },
        synthesizer=sf.Vote(gate=sf.Gate("mean:risk", "<=", 3.0, abstain_band=(2.5, 3.5))),
    )
    return compile_candidate(recipe, operators=engine_operators()).url4


BUILDERS |= {"gate_band_vote_candidate.url4": gate_band_vote_url4}


@requires_engine_app
def test_gate_band_fixture_matches_the_sdk_compile() -> None:
    name = "gate_band_vote_candidate.url4"
    fixture = COMBINE_CONTRACT / name
    assert ENGINE_APP.exists()
    assert fixture.exists(), f"combine_contract/{name} is missing - run write_fixture({name!r})"
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == BUILDERS[name]()
