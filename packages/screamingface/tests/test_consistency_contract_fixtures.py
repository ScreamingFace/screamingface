"""Drift guard for the SDK-compiled consistency url4 fixtures (E4b part 7 unit 4, CA#6).

FEATURE: the Engine runs ``combine_contract/consistency_pick_candidate.url4`` verbatim (CA#7), and
unit 5 rebuilds both fixtures through ``BUILDERS``. This file keeps each data file byte-identical
to what the SDK compiles today. ``consistency_pick_recipe`` (F1) and ``consistency_median_recipe``
(F2) are the recipes of the consistency-api PRD §3; other test modules import them.
STORY: as a maintainer, a change to the compile of the consistency sample calls fails here, not in
a silent Engine run.
INVARIANT defended: each fixture is the SDK compile of one three-member Fusion that declares
sf.Consistency (CA-2, CA-3).

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0, 'tests'); \
import test_consistency_contract_fixtures as m; [m.write_fixture(n) for n in m.BUILDERS]"
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, engine_operators, requires_engine_app

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate

_MEMBERS = ["prov/alpha", "prov/beta", "prov/gamma"]


def consistency_pick_recipe() -> sf.Recipe:
    """F1: a Pick of the member whose answer comes back most often (n=3, temperature 1.0)."""
    return sf.Fanout(_MEMBERS, signals={"cons": sf.Consistency(n=3)}, name="pick") >> sf.ArgMax(
        "cons"
    )


def consistency_median_recipe() -> sf.Recipe:
    """F2: a median whose steps are the match of the samples (n=2, temperature 0.7)."""
    return (
        sf.Fanout(_MEMBERS, signals={"cons": sf.Consistency(n=2, temperature=0.7)}, name="median")
        >> sf.Median()
    )


def consistency_pick_url4() -> str:
    return compile_candidate(consistency_pick_recipe(), operators=engine_operators()).url4


def consistency_median_url4() -> str:
    return compile_candidate(consistency_median_recipe(), operators=engine_operators()).url4


BUILDERS: dict[str, Callable[[], str]] = {
    "consistency_median_candidate.url4": consistency_median_url4,
    "consistency_pick_candidate.url4": consistency_pick_url4,
}
# A fixed tuple: a later unit adds to BUILDERS, never to this tuple (test-plan §6).
_FIXTURES: tuple[str, ...] = (
    "consistency_median_candidate.url4",
    "consistency_pick_candidate.url4",
)


def write_fixture(name: str) -> None:
    # WHY "\n": the end-of-file-fixer wants one final newline; every reader strips exactly one.
    (COMBINE_CONTRACT / name).write_text(BUILDERS[name]() + "\n", encoding="utf-8")


@requires_engine_app
@pytest.mark.parametrize("name", _FIXTURES)
def test_consistency_url4_fixtures_match_the_sdk_compile(name: str) -> None:
    fixture = COMBINE_CONTRACT / name
    assert ENGINE_APP.exists()
    assert fixture.exists(), f"combine_contract/{name} is missing - run write_fixture({name!r})"
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == BUILDERS[name]()
