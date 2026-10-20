"""Drift guard for the Engine fixtures of the narrow compile (E4b surface unit 5, NC-4).

FEATURE: the Engine test ``ET/test_combine_narrow_run.py`` runs
``narrow_filter_mean_candidate.url4`` and ``narrow_rank_vote_candidate.url4`` verbatim. This file
keeps both data files byte-equal to what the SDK compiles from the new surface, and proves that
each one rebuilds from its own url4 and recompiles to the same bytes (the url4 recompile check).
STORY: as a researcher, ``Fanout >> Filter >> Mean`` and ``Fanout >> Judge >> Rank >> Vote`` are
values that build (``CH-12`` is gone) and compile to the url4 the Engine runs.

Regenerate from ``packages/screamingface``::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_narrow_contract_fixtures as m; m.write_fixtures()"
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, requires_engine_app
from _combine_flow_fixtures import flow_operators
from url4 import build

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.operators import _OperatorCatalog
from screamingface.url4 import (
    _calls,
    _candidate_expression,
    _combine_operator_pairs,
    _recipe_from_topology,
    _require_recompiles,
    _topology_from_expression,
)

_ROUTES = ["prov/alpha", "prov/beta", "prov/gamma", "prov/delta"]
_JSON = "Reply with JSON: {'answer': <number>, 'confidence': <0..1>}."
_RUBRIC = "Score each draft from 0 to 10."


def filter_mean_chain() -> sx.Pipeline:
    """Four JSON members; keep the confident ones, then the mean of their answers."""

    return (
        sx.Fanout([sf.Model(route, prompt=_JSON) for route in _ROUTES])
        >> sx.Filter(where=sx.signal("field:confidence") > 0.7)
        >> sx.Mean(over="field:answer")
    )


def rank_vote_chain() -> sx.Pipeline:
    """Four members, one judge; the top two by the judge, then a judge-weighted vote."""

    return (
        sx.Fanout(_ROUTES)
        >> sx.Judge("prov/judge", rubric=_RUBRIC)
        >> sx.Rank(2, by="score:judge")
        >> sx.Vote(weights="score:judge")
    )


FIXTURES: dict[str, Callable[[], sx.Pipeline]] = {
    "narrow_filter_mean_candidate.url4": filter_mean_chain,
    "narrow_rank_vote_candidate.url4": rank_vote_chain,
}


def _url4(name: str) -> str:
    return compile_candidate(FIXTURES[name](), operators=flow_operators()).url4


def write_fixtures() -> None:
    # WHY no trailing newline: the end-of-file-fixer hook appends one; both readers strip one.
    for name in FIXTURES:
        (COMBINE_CONTRACT / name).write_text(_url4(name), encoding="utf-8")


@requires_engine_app
@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_nc4_the_fixture_matches_the_sdk_compiler(name: str) -> None:
    fixture = COMBINE_CONTRACT / name
    assert ENGINE_APP.exists()
    assert fixture.exists(), f"combine_contract/{name} is missing - run write_fixtures()"
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == _url4(name)


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_nc4_the_url4_rebuilds_and_recompiles_to_the_same_bytes(name: str) -> None:
    url4 = _url4(name)
    candidate, _ = _candidate_expression(build(url4))
    calls = _calls(candidate)
    recipe = _recipe_from_topology(_topology_from_expression(candidate), calls)

    _require_recompiles(candidate, recipe, calls)  # raises on any byte change
    operators = _OperatorCatalog.from_pinned(_combine_operator_pairs(calls))
    assert compile_candidate(recipe, operators=operators).url4 == url4
