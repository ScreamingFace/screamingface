"""Drift guard for the engine-side SDK-compiled quorum fixtures (OME-1289 unit 13 x OME-1557).

The Engine's ``test_sdk_quorum_contracts.py`` runs these url4 files verbatim; this file keeps each
byte-identical to what the SDK compiles today, like ``test_engine_url4_contract_fixtures.py``.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_quorum_url4_contract_fixtures as m; [m.write_fixture(n) for n in m.BUILDERS]"
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, engine_operators, requires_engine_app
from _combine_flow_fixtures import flow_operators

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate


def quorum_vote_url4() -> str:
    """Three members, the third optional, voting with a quorum of two."""

    recipe = sf.Fanout(
        ["prov/alpha", "prov/beta", sf.Model("prov/gamma", optional=True)], quorum=2
    ) >> sf.Vote(over="last_line", normalize="text")
    return compile_candidate(recipe, operators=engine_operators()).url4


def quorum_judge_vote_url4() -> str:
    """The judge-weighted vote over a quorum panel: the judge scores the members that answered."""

    recipe = (
        sf.Fanout(["prov/alpha", "prov/beta", sf.Model("prov/gamma", optional=True)], quorum=2)
        >> sf.Judge("prov/judge", rubric="Score each answer.")
        >> sf.Vote(over="last_number", normalize="numeric", weights=sf.signal("score:judge"))
    )
    return compile_candidate(recipe, operators=flow_operators()).url4


BUILDERS: dict[str, Callable[[], str]] = {
    "quorum_judge_vote_candidate.url4": quorum_judge_vote_url4,
    "quorum_vote_candidate.url4": quorum_vote_url4,
}


def write_fixture(name: str) -> None:
    # WHY no trailing newline here: the repo's end-of-file-fixer hook appends one.
    (COMBINE_CONTRACT / name).write_text(BUILDERS[name](), encoding="utf-8")


@requires_engine_app
@pytest.mark.parametrize("name", BUILDERS)
def test_engine_quorum_fixture_matches_the_sdk_compiler(name: str) -> None:
    fixture = COMBINE_CONTRACT / name
    assert ENGINE_APP.exists()
    assert fixture.exists(), f"combine_contract/{name} is missing - run write_fixture({name!r})"
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == BUILDERS[name]()
