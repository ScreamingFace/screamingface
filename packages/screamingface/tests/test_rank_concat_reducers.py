"""sf.Rank and sf.Concat: validation, spec, repr and compile shape (OME-1289, RK-6, CC-2/5)."""

from __future__ import annotations

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators, members3
from _nodes import ConcatNode

import screamingface as sf
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface.reducer import Reducer


def _spec(extract: str, normalize: str, reduce: str, select: str, reducer: str) -> str:
    return (
        f'{{"extract":{extract},"members":["member_1","member_2","member_3"],'
        f'"normalize":{normalize},"reduce":{reduce},"reducer":"{reducer}",'
        f'"schema":"screamingface.combine-spec.v1","select":{select},"weights":null}}'
    )


def test_k_bounds_are_enforced() -> None:
    with pytest.raises(ValueError, match="Rank k must be between 1 and 256"):
        sf.Rank(0, by="field:score")
    with pytest.raises(ValueError, match="Rank k must be between 1 and 256"):
        sf.Rank(257, by="field:score")
    with pytest.raises(TypeError, match="Rank k must be an integer"):
        sf.Rank(True, by="field:score")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Rank k must be an integer"):
        sf.Rank(2.0, by="field:score")  # type: ignore[arg-type]
    assert sf.Rank(1, by="field:score").k == 1
    assert sf.Rank(256, by="field:score").k == 256

    with pytest.raises(ValueError, match="k=4"):
        _ = sf.Fanout(members3()) >> sf.Rank(4, by="field:s") >> sf.Synthesize("provider/w")
    assert (sf.Fanout(members3()) >> sf.Rank(3, by="field:s") >> sf.Synthesize("provider/w")).steps


def test_rank_fields_and_repr_round_trip() -> None:
    judge = sf.Judge("provider/j", rubric=RUBRIC, params={"temperature": 0})
    by_judge = sf.Rank(2, by="score:judge")
    by_field = sf.Rank(2, by="field:score")
    judged = sf.Fanout(members3()) >> judge >> by_judge >> sf.Synthesize("provider/w")

    assert (by_judge.k, by_judge.by, by_judge.order) == (2, sf.signal("score:judge"), "max")
    assert (by_field.k, by_field.by, by_field.order) == (2, sf.signal("field:score"), "max")
    assert repr(by_field) == "Rank(2, by='field:score')"
    assert repr(judged).endswith(
        f">> {judge!r} >> Rank(2, by='score:judge') >> Synthesize('provider/w')"
    )
    for rank in (by_judge, by_field):
        rebuilt = eval(repr(rank), {"Rank": sf.Rank})  # noqa: S307
        assert rebuilt == rank
    assert by_judge != by_field
    assert sf.Rank(2, by="field:score") == by_field
    assert sf.Rank(3, by="field:score") != by_field
    with pytest.raises(TypeError):
        hash(by_field)
    fusion = sf.Fanout(members3()) >> by_field >> sf.Synthesize("provider/w")
    assert repr(fusion).endswith(f">> {by_field!r} >> Synthesize('provider/w')")


def test_empty_separator_raises() -> None:
    with pytest.raises(ValueError, match="Concat separator must not be empty"):
        sf.Concat("")
    with pytest.raises(ValueError, match="Concat separator must be at most 1024 characters"):
        sf.Concat("x" * 1025)
    with pytest.raises(TypeError, match="Concat separator must be a string"):
        sf.Concat(3)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Concat label must be a bool"):
        sf.Concat(label="yes")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Concat label must be a bool"):
        sf.Concat(label=1)  # type: ignore[arg-type]
    assert sf.Concat("x" * 1024).separator == "x" * 1024


def test_concat_defaults_fields_and_repr_round_trip() -> None:
    concat = sf.Concat()

    assert (concat.separator, concat.label) == ("\n\n---\n\n", True)
    assert repr(concat) == "Concat()"
    odd = sf.Concat("  \"$\" 'é'", label=False)
    for item in (concat, odd):
        assert eval(repr(item), {"Concat": sf.Concat}) == item  # noqa: S307
    assert concat != odd
    with pytest.raises(TypeError):
        hash(concat)
    chain = sf.Fanout(members3()) >> concat >> sf.Synthesize("provider/w")
    assert repr(chain).endswith(f">> {concat!r} >> Synthesize('provider/w')")


def test_rank_and_concat_specs() -> None:
    operators = flow_operators()

    def text(reducer: Reducer) -> str:
        return combine_spec_text(reducer, member_count=3, operators=operators)

    assert text(ConcatNode("$|\x7f", label=False)) == _spec(
        "null",
        "null",
        '{"args":{"label":false,"separator":"\\u0024|\\u007f"},"op":"join@1"}',
        '{"args":{},"op":"all@1"}',
        "concat",
    )
