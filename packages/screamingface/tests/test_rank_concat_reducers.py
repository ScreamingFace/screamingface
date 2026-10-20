"""sf.Rank and sf.Concat: validation, spec, repr and compile shape (OME-1289, RK-6, CC-2/5)."""

from __future__ import annotations

from typing import Any

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators, members3
from _nodes import ConcatNode, JudgeNode, RankNode

import screamingface as sf
from screamingface import _surface as sx
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface.reducer import Reducer


def _scores_judge(**kw: Any) -> JudgeNode:
    # group F (7f): only the Rank source rows read a judge node
    return JudgeNode("provider/j", returns="scores", rubric=RUBRIC, **kw)


def _spec(extract: str, normalize: str, reduce: str, select: str, reducer: str) -> str:
    return (
        f'{{"extract":{extract},"members":["member_1","member_2","member_3"],'
        f'"normalize":{normalize},"reduce":{reduce},"reducer":"{reducer}",'
        f'"schema":"screamingface.combine-spec.v1","select":{select},"weights":null}}'
    )


def test_k_bounds_are_enforced() -> None:
    with pytest.raises(ValueError, match="Rank k must be between 1 and 256"):
        sx.Rank(0, by="field:score")
    with pytest.raises(ValueError, match="Rank k must be between 1 and 256"):
        sx.Rank(257, by="field:score")
    with pytest.raises(TypeError, match="Rank k must be an integer"):
        sx.Rank(True, by="field:score")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Rank k must be an integer"):
        sx.Rank(2.0, by="field:score")  # type: ignore[arg-type]
    assert sx.Rank(1, by="field:score").k == 1
    assert sx.Rank(256, by="field:score").k == 256

    with pytest.raises(ValueError, match="k=4"):
        _ = sx.Fanout(members3()) >> sx.Rank(4, by="field:s") >> sx.Synthesize("provider/w")
    assert (sx.Fanout(members3()) >> sx.Rank(3, by="field:s") >> sx.Synthesize("provider/w")).steps


def test_rank_needs_exactly_one_ranking_source() -> None:
    # group F (7f): the by=/by_field=/by_signal= sources of the Rank node are deleted (D7-8)
    with pytest.raises(ValueError, match="exactly one of by=, by_field= or by_signal="):
        RankNode(k=2)
    with pytest.raises(ValueError, match="exactly one of by=, by_field= or by_signal="):
        RankNode(k=2, by=_scores_judge(), by_field="score")
    with pytest.raises(ValueError, match=r"Rank\(by=\.\.\.\) needs sf.Judge"):
        RankNode(k=2, by=JudgeNode("provider/j", returns="label", rubric=RUBRIC))
    with pytest.raises(TypeError, match="Rank by must be an sf.Judge"):
        RankNode(k=2, by="provider/j")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="Rank by_field must be a string"):
        RankNode(k=2, by_field=3)  # type: ignore[arg-type]
    for bad in ("", "a.", ".a", "a[01]", "a b", "$a", "a" * 257):
        with pytest.raises(ValueError, match="Rank by_field .* must be a JSON path"):
            RankNode(k=2, by_field=bad)
    for good in ("score", "a.b", "a[0].b", "[0].a", "a" * 256):
        assert RankNode(k=2, by_field=good).by_field == good


def test_rank_fields_and_repr_round_trip() -> None:
    judge = sx.Judge("provider/j", rubric=RUBRIC, params={"temperature": 0})
    by_judge = sx.Rank(2, by="score:judge")
    by_field = sx.Rank(2, by="field:score")
    judged = sx.Fanout(members3()) >> judge >> by_judge >> sx.Synthesize("provider/w")

    assert (by_judge.k, by_judge.by, by_judge.order) == (2, sf.signal("score:judge"), "max")
    assert (by_field.k, by_field.by, by_field.order) == (2, sf.signal("field:score"), "max")
    assert repr(by_field) == "Rank(2, by='field:score')"
    assert repr(judged).endswith(
        f">> {judge!r} >> Rank(2, by='score:judge') >> Synthesize('provider/w')"
    )
    for rank in (by_judge, by_field):
        rebuilt = eval(repr(rank), {"Rank": sx.Rank})  # noqa: S307
        assert rebuilt == rank
    assert by_judge != by_field
    assert sx.Rank(2, by="field:score") == by_field
    assert sx.Rank(3, by="field:score") != by_field
    with pytest.raises(TypeError):
        hash(by_field)
    fusion = sx.Fanout(members3()) >> by_field >> sx.Synthesize("provider/w")
    assert repr(fusion).endswith(f">> {by_field!r} >> Synthesize('provider/w')")


def test_empty_separator_raises() -> None:
    with pytest.raises(ValueError, match="Concat separator must not be empty"):
        sx.Concat("")
    with pytest.raises(ValueError, match="Concat separator must be at most 1024 characters"):
        sx.Concat("x" * 1025)
    with pytest.raises(TypeError, match="Concat separator must be a string"):
        sx.Concat(3)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Concat label must be a bool"):
        sx.Concat(label="yes")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Concat label must be a bool"):
        sx.Concat(label=1)  # type: ignore[arg-type]
    assert sx.Concat("x" * 1024).separator == "x" * 1024


def test_concat_defaults_fields_and_repr_round_trip() -> None:
    concat = sx.Concat()

    assert (concat.separator, concat.label) == ("\n\n---\n\n", True)
    assert repr(concat) == "Concat()"
    odd = sx.Concat("  \"$\" 'é'", label=False)
    for item in (concat, odd):
        assert eval(repr(item), {"Concat": sx.Concat}) == item  # noqa: S307
    assert concat != odd
    with pytest.raises(TypeError):
        hash(concat)
    chain = sx.Fanout(members3()) >> concat >> sx.Synthesize("provider/w")
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
