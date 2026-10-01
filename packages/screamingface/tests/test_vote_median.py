"""sf.Vote and sf.Median: compiled spec, validation, repr and url4 recovery (OME-1289, VT-9/10)."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest
from _combine_contract import engine_operators
from url4 import Expression, build, expr, render, src, text

import screamingface as sf
import screamingface.reducer as reducer_module
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec
from screamingface._evaluation.url4 import _candidate_from_url4
from screamingface.reducer import Reducer
from screamingface.url4 import _calls

_SURFACE = _CheckSurface(
    check_route="/benchmarks/ifeval/revision-1/check-surface",
    feedback_intent="feedback",
    expected_check_cost="free",
)


def _fusion(synthesizer: Reducer) -> sf.Fusion:
    return sf.Fusion(["provider/a", "provider/b", "provider/c"], synthesizer=synthesizer)


def _url4(recipe: sf.Recipe, **kwargs: Any) -> str:
    return compile_candidate(recipe, operators=engine_operators(), **kwargs).url4


def _raw_intent(synthesizer: Reducer) -> str:
    root = build(_url4(_fusion(synthesizer)))
    assert isinstance(root, Expression)
    return _calls(root)["synthesis_1"].raw_intent


def _spec(reducer: Reducer, members: int = 3) -> dict[str, Any]:
    return json.loads(
        combine_spec_text(reducer, member_count=members, operators=engine_operators())
    )


def test_vote_compiles_to_pinned_spec() -> None:
    assert _raw_intent(sf.Vote(extract="last_number", normalize="numeric")) == (
        '{"extract":{"args":{},"op":"last_number@1"},"members":["member_1","member_2","member_3"],'
        '"normalize":{"args":{},"op":"numeric@1"},"reduce":{"args":{},"op":"mode@1"},'
        '"reducer":"vote","schema":"screamingface.combine-spec.v1",'
        '"select":{"args":{},"op":"first_holder@1"},"weights":null}'
    )
    defaults = json.loads(_raw_intent(sf.Vote()))
    assert defaults["extract"]["op"] == "last_line@1"
    assert defaults["normalize"]["op"] == "text@1"
    median = _raw_intent(sf.Median(select="value"))
    assert '"normalize":{"args":{},"op":"numeric@1"}' in median
    assert '"reduce":{"args":{},"op":"median@1"}' in median
    assert '"reducer":"median"' in median
    assert '"select":{"args":{},"op":"value@1"}' in median


def test_median_rejects_a_normalize_argument() -> None:
    with pytest.raises(TypeError):
        sf.Median(normalize="text")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="'nearest' or 'value'"):
        sf.Median(select="mode")
    assert sf.Median(select="nearest@1").select == "nearest@1"


def test_vote_and_median_are_exported_and_registered() -> None:
    assert sf.Vote is reducer_module.Vote
    assert sf.Median is reducer_module.Median
    assert reducer_module._REDUCER_CLASSES["vote"] is sf.Vote
    assert reducer_module._REDUCER_CLASSES["median"] is sf.Median
    assert isinstance(sf.Vote(), reducer_module.Reducer)
    assert isinstance(sf.Median(), reducer_module.Reducer)
    assert "Reducer" not in sf.__all__


def test_reprs_are_constructor_calls_that_rebuild_equal_values() -> None:
    assert repr(sf.Vote()) == "Vote(extract='last_line', normalize='text')"
    assert repr(sf.Vote(normalize=None)).endswith("normalize=None)")
    assert repr(sf.Median()) == "Median(extract='last_number', select='nearest')"
    namespace = {"Vote": sf.Vote, "Median": sf.Median}
    for value in (sf.Vote(), sf.Vote(normalize=None), sf.Median(select="value")):
        assert eval(repr(value), namespace) == value  # noqa: S307 - our own repr, no input
    assert sf.Vote() != sf.Vote(extract="boxed")
    for value in (sf.Vote(), sf.Median()):
        with pytest.raises(TypeError):
            hash(value)


def test_url4_round_trip_rebuilds_vote_and_median() -> None:
    vote = sf.Vote(extract="last_number", normalize="numeric")
    vote_python = sf.Url4(_url4(_fusion(vote))).to_python()
    assert "synthesizer=sf.Vote(extract='last_number@1', normalize='numeric@1')" in vote_python
    median_python = sf.Url4(_url4(_fusion(sf.Median(select="value")))).to_python()
    assert "synthesizer=sf.Median(extract='last_number@1', select='value@1')" in median_python

    assert sf.Vote._from_spec(decode_combine_spec(_raw_intent(vote))) == sf.Vote(
        extract="last_number@1", normalize="numeric@1"
    )

    loop = sf.CorrectiveLoop([_fusion(vote), "provider/d"], judge="provider/j", max_rounds=2)
    linked = render(
        expr(
            src(text(_url4(loop, check_surface=_SURFACE)), name="candidate", weight=0.0),
            src("/benchmarks/ifeval/revision-1/cases", name="rows", weight=0.0),
            intent=text("$rows"),
        )
    )
    assert _candidate_from_url4(linked).kind == "corrective_loop"


def _mutate(reducer: Reducer, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    spec = copy.deepcopy(_spec(reducer))
    change(spec)
    return spec


def _step(spec: dict[str, Any], stage: str, op: str) -> None:
    spec[stage] = {"op": op, "args": {}}


@pytest.mark.parametrize(
    ("cls", "reducer", "change"),
    [
        pytest.param(
            sf.Vote, sf.Vote(), lambda s: _step(s, "reduce", "median@1"), id="vote-median"
        ),
        pytest.param(sf.Vote, sf.Vote(), lambda s: s.update(extract=None), id="vote-no-extract"),
        pytest.param(
            sf.Median, sf.Median(), lambda s: _step(s, "normalize", "text@1"), id="median-text"
        ),
        pytest.param(
            sf.Median, sf.Median(), lambda s: _step(s, "select", "first_holder@1"), id="median-pick"
        ),
        pytest.param(
            sf.Median,
            sf.Median(),
            lambda s: s.update(normalize={"op": "numeric@1", "args": {"x": 1}}),
            id="median-args",
        ),
        pytest.param(
            sf.Median,
            sf.Median(),
            lambda s: s.update(weights={"member_1": 1.0, "member_2": 1.0, "member_3": 1.0}),
            id="median-weights",
        ),
    ],
)
def test_from_spec_refuses_specs_it_cannot_rebuild(
    cls: Any, reducer: Reducer, change: Callable[[dict[str, Any]], None]
) -> None:
    with pytest.raises(ValueError, match="cannot rebuild"):
        cls._from_spec(_mutate(reducer, change))


def test_vote_rejects_a_blank_or_non_string_operator() -> None:
    with pytest.raises(TypeError):
        sf.Vote(extract="")
    with pytest.raises(TypeError):
        sf.Vote(normalize=3)  # type: ignore[arg-type]
