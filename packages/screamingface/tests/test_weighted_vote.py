"""sf.Vote(weights=...): validation, compiled spec, repr and url4 recovery (OME-1289, WV-1/3/8)."""

from __future__ import annotations

import json
import math
from typing import Any

import pytest
from _combine_contract import engine_operators
from url4 import Expression, build

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec
from screamingface.url4 import _calls

_NUMBER: dict[str, Any] = {"extract": "last_number", "normalize": "numeric"}


def _fusion(synthesizer: sf.Vote, members: int = 3) -> sf.Fusion:
    routes = [f"provider/m{index}" for index in range(1, members + 1)]
    return sf.Fusion(routes, synthesizer=synthesizer)


def _url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=engine_operators()).url4


def _raw_intent(url4: str) -> str:
    root = build(url4)
    assert isinstance(root, Expression)
    return _calls(root)["synthesis_1"].raw_intent


def test_missing_weight_raises_before_any_call() -> None:
    with pytest.raises(ValueError, match=r"^vote has 2 weights for 3 members$"):
        sf.Fusion(["p/a", "p/b", "p/c"], synthesizer=sf.Vote(weights=[1, 2]))
    with pytest.raises(ValueError, match=r"^vote has 3 weights for 2 members$"):
        sf.Fusion(["p/a", "p/b"], synthesizer=sf.Vote(weights=[1, 2, 3]))
    assert sf.Fusion(["p/a", "p/b"], synthesizer=sf.Vote(weights=[1, 2])) is not None


@pytest.mark.parametrize("bad", [0, -1, math.nan, math.inf, -math.inf, 10**400, 0.0, -0.5])
def test_non_positive_or_non_finite_weight_raises(bad: Any) -> None:
    with pytest.raises(ValueError, match="finite and greater than zero"):
        sf.Vote(weights=[1, bad])


@pytest.mark.parametrize("bad", [[], ()])
def test_empty_weights_raise_value_error(bad: Any) -> None:
    with pytest.raises(ValueError):
        sf.Vote(weights=bad)


@pytest.mark.parametrize("bad", [[True], [1, False], ["1"], "12", b"12", 5, [None], [1, "2"]])
def test_non_numeric_weights_raise_type_error(bad: Any) -> None:
    with pytest.raises(TypeError):
        sf.Vote(weights=bad)


def test_weights_are_stored_as_a_float_tuple() -> None:
    vote = sf.Vote(weights=[2, 1.5])
    assert vote.weights == (2.0, 1.5)
    assert vote.weights is not None
    assert all(type(weight) is float for weight in vote.weights)
    assert sf.Vote().weights is None
    assert sf.Vote(weights=[2, 1]) == sf.Vote(weights=(2.0, 1.0))
    assert sf.Vote(weights=[2, 1]) != sf.Vote(weights=[1, 2])
    assert sf.Vote(weights=[1]) != sf.Vote()


def test_weights_on_median_raise_type_error() -> None:
    with pytest.raises(TypeError, match="weights apply to Vote only"):
        sf.Median(weights=[1])  # type: ignore[arg-type]
    assert sf.Median(weights=None).select == "nearest"


def test_weighted_vote_compiles_to_weighted_spec() -> None:
    raw = _raw_intent(_url4(_fusion(sf.Vote(**_NUMBER, weights=[2, 1, 1]))))
    assert '"reduce":{"args":{},"op":"weighted_mode@1"}' in raw
    assert '"select":{"args":{},"op":"max_weight_holder@1"}' in raw
    assert '"weights":{"member_1":2.0,"member_2":1.0,"member_3":1.0}' in raw
    assert json.loads(raw)["reducer"] == "vote"
    # Unweighted stays on mode / first_holder (unit 5).
    plain = json.loads(_raw_intent(_url4(_fusion(sf.Vote(**_NUMBER)))))
    assert plain["reduce"]["op"] == "mode@1"
    assert plain["select"]["op"] == "first_holder@1"
    assert plain["weights"] is None


def test_repr_shows_weights_only_when_set() -> None:
    assert repr(sf.Vote(weights=[2, 1])) == (
        "Vote(extract='last_line', normalize='text', weights=(2.0, 1.0))"
    )
    assert repr(sf.Vote()) == "Vote(extract='last_line', normalize='text')"
    value = sf.Vote(weights=[2, 1.5])
    assert eval(repr(value), {"Vote": sf.Vote}) == value  # noqa: S307 - our own repr, no input


def test_weighted_vote_round_trips_through_url4_with_ten_or_more_members() -> None:
    weights = tuple(float(index) for index in range(1, 12))
    vote = sf.Vote(**_NUMBER, weights=weights)
    url4 = _url4(_fusion(vote, members=11))
    raw = _raw_intent(url4)
    # WHY this pin: canonical JSON sorts keys, so member_10 comes before member_2 in the text.
    assert raw.index('"member_10":') < raw.index('"member_2":')
    expected = sf.Vote(extract="last_number@1", normalize="numeric@1", weights=weights)
    assert sf.Vote._from_spec(decode_combine_spec(raw)) == expected
    code = sf.Url4(url4).to_python()
    assert f"weights={weights!r}" in code
    assert "weights=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0)" in code
    namespace: dict[str, Any] = {}
    exec(code, namespace)  # noqa: S102 - our own generated code
    assert _url4(namespace["candidate"]) == url4


def _spec(**overrides: Any) -> dict[str, Any]:
    spec = json.loads(
        combine_spec_text(
            sf.Vote(**_NUMBER, weights=[2, 1, 1]), member_count=3, operators=engine_operators()
        )
    )
    spec.update(overrides)
    return spec


def _op(name: str) -> dict[str, Any]:
    return {"op": f"{name}@1", "args": {}}


@pytest.mark.parametrize(
    "spec",
    [
        # weighted spec with the unweighted operators, and the reverse
        _spec(reduce=_op("mode")),
        _spec(select=_op("first_holder")),
        _spec(weights=None),
        {**_spec(weights=None), "reduce": _op("weighted_mode"), "select": _op("max_weight_holder")},
        _spec(extract=None),
    ],
)
def test_from_spec_refuses_inconsistent_weighted_specs(spec: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="cannot rebuild"):
        sf.Vote._from_spec(spec)


def test_from_spec_refuses_a_weight_map_that_misses_a_member() -> None:
    spec = _spec()
    del spec["weights"]["member_3"]
    with pytest.raises(ValueError, match="cannot rebuild"):
        sf.Vote._from_spec(spec)
