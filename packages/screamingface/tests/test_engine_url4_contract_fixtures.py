"""Drift guard for the engine-side SDK-compiled url4 fixtures (OME-1289).

The Engine's tests run the SDK-compiled Candidates in
``apps/screamingface-engine/tests/unit/data/combine_contract/*.url4`` verbatim (its own tests need
no SDK). This file keeps each data file byte-identical to what the SDK compiles today, so a
compiler change that is not mirrored in a fixture fails HERE. ``BUILDERS`` maps each fixture file
name to the function that compiles it.

Regenerate from ``packages/screamingface`` (one name, or all of them)::

    uv run python -c "import sys; sys.path.insert(0,'tests'); \
import test_engine_url4_contract_fixtures as m; [m.write_fixture(n) for n in m.BUILDERS]"
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, engine_operators, requires_engine_app
from _combine_flow_fixtures import flow_operators
from _nodes import fusion_node
from _reducer_fixtures import FixtureVote, _entry

import screamingface as sf
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.operators import _OperatorCatalog, decode_operator_catalog
from screamingface.reducer import Reducer

_ROUTE_SOURCE = ENGINE_APP / "tests" / "unit" / "data" / "corrective_loop_candidate.url4"
_ROUTE = re.compile(r"/benchmarks/ifeval/[A-Za-z0-9]+/check-surface")

# The real unit-2 ids only: no `last_number@2`, so the fixtures pin what the Engine serves.
_TWO_REDUCERS_OPERATORS = {
    "extract": ("last_number", "last_line"),
    "normalize": ("numeric", "text"),
    "reduce": ("mode",),
    "select": ("first_holder",),
}
# The Engine's real v1 ids, the four a FixtureVote pins.
_SAMPLES_OPERATORS = {
    "extract": ("last_number",),
    "normalize": ("numeric",),
    "reduce": ("mode",),
    "select": ("first_holder",),
}


def _catalog(names: Mapping[str, Sequence[str]]) -> _OperatorCatalog:
    return decode_operator_catalog(
        {
            "object": "list",
            "data": [
                _entry(name, 1, stage)
                for stage, stage_names in names.items()
                for name in stage_names
            ],
        }
    )


def argmax_cost_url4() -> str:
    """Three members, the first with a param; the cheapest member's answer is the answer."""

    recipe = sf.Fusion(
        [sf.Model("prov/alpha", params={"temperature": 0.5}), "prov/beta", "prov/gamma"],
        synthesizer=sf.Pick(by_signal=sf.signal("cost_usd"), order="min"),
    )
    return compile_candidate(recipe, operators=flow_operators()).url4


def two_reducers_url4() -> str:
    recipe = sf.Pipeline(
        [
            fusion_node(["provider/alpha", "provider/beta", "provider/gamma"], FixtureVote()),
            fusion_node(
                ["provider/delta", "provider/epsilon"],
                FixtureVote(extract="last_line", normalize="text"),
            ),
        ]
    )
    return compile_candidate(recipe, operators=_catalog(_TWO_REDUCERS_OPERATORS)).url4


def corrective_vote_url4() -> str:
    # The check route comes from the committed `corrective_loop_candidate.url4` (the IFEval offer
    # the Engine already pins), so this fixture links to the same IFEval check surface.
    match = _ROUTE.search(_ROUTE_SOURCE.read_text(encoding="utf-8"))
    assert match is not None, "corrective_loop_candidate.url4 lost the IFEval check route"
    recipe = sf.CorrectiveLoop(
        [
            sf.Fusion(["prov/member-a", "prov/member-b", "prov/member-c"], synthesizer=sf.Vote()),
            "prov/member-d",
        ],
        judge="prov/judge",
        max_rounds=2,
    )
    surface = _CheckSurface(
        check_route=match.group(0), feedback_intent="feedback", expected_check_cost="free"
    )
    return compile_candidate(recipe, operators=engine_operators(), check_surface=surface).url4


def filter_pipeline_url4() -> str:
    """Four members, a confidence filter, then a writer that sees only the members that pass."""

    recipe = sf.Pipeline(
        [
            sf.Fusion(
                ["prov/alpha", "prov/beta", "prov/gamma", "prov/delta"],
                synthesizer=sf.Filter(where=sf.signal("field:confidence") >= 0.6),
            ),
            "prov/writer",
        ]
    )
    return compile_candidate(recipe, operators=flow_operators()).url4


def judge_vote_url4() -> str:
    """Three members voting on a number, each answer weighed by the judge's score for its member."""

    recipe = sf.Fusion(
        ["prov/alpha", "prov/beta", "prov/gamma"],
        synthesizer=sf.Vote(
            extract="last_number",
            normalize="numeric",
            weights=sf.signal("score:judge"),
            judge=sf.Judge("prov/judge", returns="scores", rubric="Score each answer."),
        ),
    )
    return compile_candidate(recipe, operators=flow_operators()).url4


def _samples_url4(synthesizer: Reducer) -> str:
    recipe = fusion_node(sf.samples("prov/member-a", 5, temperature=0.7), synthesizer)
    return compile_candidate(recipe, operators=_catalog(_SAMPLES_OPERATORS)).url4


def samples_vote_url4() -> str:
    return _samples_url4(FixtureVote())


def signal_vote_url4() -> str:
    """Three members, the first with a param, voting with weights = each member's own cost."""

    recipe = sf.Fusion(
        [sf.Model("prov/alpha", params={"temperature": 0.5}), "prov/beta", "prov/gamma"],
        synthesizer=sf.Vote(extract="last_line", normalize="text", weights=sf.signal("cost_usd")),
    )
    return compile_candidate(recipe, operators=engine_operators()).url4


BUILDERS: dict[str, Callable[[], str]] = {
    "argmax_cost_candidate.url4": argmax_cost_url4,
    "two_reducers_candidate.url4": two_reducers_url4,
    "corrective_vote_candidate.url4": corrective_vote_url4,
    "filter_pipeline_candidate.url4": filter_pipeline_url4,
    "judge_vote_candidate.url4": judge_vote_url4,
    "samples_vote_candidate.url4": samples_vote_url4,
    "signal_vote_candidate.url4": signal_vote_url4,
}


def write_fixture(name: str) -> None:
    # WHY no trailing newline here: the repo's end-of-file-fixer hook appends one, and the
    # engine test and this guard both strip exactly one.
    (COMBINE_CONTRACT / name).write_text(BUILDERS[name](), encoding="utf-8")


@requires_engine_app
@pytest.mark.parametrize("name", BUILDERS)
def test_engine_url4_fixture_matches_the_sdk_compiler(name: str) -> None:
    # WHY the guard splits in two: skip only when the whole engine APP is absent; a present
    # app with a missing fixture must FAIL, not skip.
    fixture = COMBINE_CONTRACT / name
    assert ENGINE_APP.exists()
    assert fixture.exists(), f"combine_contract/{name} is missing - run write_fixture({name!r})"
    # WHY removesuffix: the repo's end-of-file-fixer hook appends one newline to data files.
    assert fixture.read_text(encoding="utf-8").removesuffix("\n") == BUILDERS[name]()


@pytest.mark.parametrize(
    "synthesizer",
    [
        sf.Reduce("plurality", extract=sf.Extract("last_number", normalize="numeric")),
        sf.Vote(extract="last_number", normalize="numeric"),
    ],
    ids=["reduce-plurality", "vote"],
)
def test_block_form_samples_vote_compiles_to_the_engine_fixture(synthesizer: Reducer) -> None:
    """A block and a named vote compile to the engine fixture byte for byte,
    so the Engine's samples world tests run the block form too (BK#12 engine half).
    """

    url4 = _samples_url4(synthesizer)

    assert url4 == samples_vote_url4()
    if ENGINE_APP.exists():
        fixture = COMBINE_CONTRACT / "samples_vote_candidate.url4"
        assert fixture.read_text(encoding="utf-8").removesuffix("\n") == url4
