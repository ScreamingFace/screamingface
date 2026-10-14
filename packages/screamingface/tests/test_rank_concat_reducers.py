"""sf.Rank and sf.Concat: validation, spec, repr and compile shape (OME-1289, RK-6, CC-2/5)."""

from __future__ import annotations

from typing import Any

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators, members3

import screamingface as sf
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface.reducer import Reducer


def _scores_judge(**kw: Any) -> sf.Judge:
    return sf.Judge("provider/j", returns="scores", rubric=RUBRIC, **kw)


def _spec(extract: str, normalize: str, reduce: str, select: str, reducer: str) -> str:
    return (
        f'{{"extract":{extract},"members":["member_1","member_2","member_3"],'
        f'"normalize":{normalize},"reduce":{reduce},"reducer":"{reducer}",'
        f'"schema":"screamingface.combine-spec.v1","select":{select},"weights":null}}'
    )


def test_k_bounds_are_enforced() -> None:
    with pytest.raises(ValueError, match="Rank k must be between 1 and 256"):
        sf.Rank(k=0, by_field="score")
    with pytest.raises(ValueError, match="Rank k must be between 1 and 256"):
        sf.Rank(k=257, by_field="score")
    with pytest.raises(TypeError, match="Rank k must be an integer"):
        sf.Rank(k=True, by_field="score")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Rank k must be an integer"):
        sf.Rank(k=2.0, by_field="score")  # type: ignore[arg-type]
    assert sf.Rank(k=1, by_field="score").k == 1
    assert sf.Rank(k=256, by_field="score").k == 256

    with pytest.raises(ValueError, match="k=4"):
        sf.Fusion(members3(), synthesizer=sf.Rank(k=4, by_field="s"))
    assert sf.Fusion(members3(), synthesizer=sf.Rank(k=3, by_field="s")).members


def test_rank_needs_exactly_one_ranking_source() -> None:
    with pytest.raises(ValueError, match="exactly one of by=, by_field= or by_signal="):
        sf.Rank(k=2)
    with pytest.raises(ValueError, match="exactly one of by=, by_field= or by_signal="):
        sf.Rank(k=2, by=_scores_judge(), by_field="score")
    with pytest.raises(ValueError, match=r"Rank\(by=\.\.\.\) needs sf.Judge"):
        sf.Rank(k=2, by=sf.Judge("provider/j", returns="label", rubric=RUBRIC))
    with pytest.raises(TypeError, match="Rank by must be an sf.Judge"):
        sf.Rank(k=2, by="provider/j")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="Rank by_field must be a string"):
        sf.Rank(k=2, by_field=3)  # type: ignore[arg-type]
    for bad in ("", "a.", ".a", "a[01]", "a b", "$a", "a" * 257):
        with pytest.raises(ValueError, match="Rank by_field .* must be a JSON path"):
            sf.Rank(k=2, by_field=bad)
    for good in ("score", "a.b", "a[0].b", "[0].a", "a" * 256):
        assert sf.Rank(k=2, by_field=good).by_field == good


def test_rank_fields_and_repr_round_trip() -> None:
    judge = _scores_judge(params={"temperature": 0})
    by_judge = sf.Rank(k=2, by=judge)
    by_field = sf.Rank(k=2, by_field="score")

    assert (by_judge.name, by_judge.k, by_judge.by, by_judge.by_field) == ("rank", 2, judge, None)
    assert (by_field.name, by_field.by, by_field.by_field) == ("rank", None, "score")
    assert repr(by_field) == "Rank(k=2, by_field='score')"
    assert repr(by_judge) == f"Rank(k=2, by={judge!r})"
    for rank in (by_judge, by_field):
        rebuilt = eval(repr(rank), {"Rank": sf.Rank, "Judge": sf.Judge})  # noqa: S307
        assert rebuilt == rank
    assert by_judge != by_field
    assert sf.Rank(k=2, by_field="score") == by_field
    assert sf.Rank(k=3, by_field="score") != by_field
    with pytest.raises(TypeError):
        hash(by_field)
    fusion = sf.Fusion(members3(), synthesizer=by_field)
    assert repr(fusion).endswith(f"synthesizer={by_field!r})")


def test_empty_separator_raises() -> None:
    with pytest.raises(ValueError, match="Concat separator must not be empty"):
        sf.Concat(separator="")
    with pytest.raises(ValueError, match="Concat separator must be at most 1024 characters"):
        sf.Concat(separator="x" * 1025)
    with pytest.raises(TypeError, match="Concat separator must be a string"):
        sf.Concat(separator=3)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Concat label must be a bool"):
        sf.Concat(label="yes")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Concat label must be a bool"):
        sf.Concat(label=1)  # type: ignore[arg-type]
    assert sf.Concat(separator="x" * 1024).separator == "x" * 1024


def test_concat_defaults_fields_and_repr_round_trip() -> None:
    concat = sf.Concat()

    assert (concat.name, concat.separator, concat.label) == ("concat", "\n\n---\n\n", True)
    assert repr(concat) == "Concat(separator='\\n\\n---\\n\\n', label=True)"
    odd = sf.Concat("  \"$\" 'é'", label=False)
    for item in (concat, odd):
        assert eval(repr(item), {"Concat": sf.Concat}) == item  # noqa: S307
    assert concat != odd
    with pytest.raises(TypeError):
        hash(concat)
    assert repr(sf.Fusion(members3(), synthesizer=concat)).endswith(f"synthesizer={concat!r})")


def test_rank_and_concat_specs() -> None:
    operators = flow_operators()

    def text(reducer: Reducer) -> str:
        return combine_spec_text(reducer, member_count=3, operators=operators)

    assert text(sf.Concat("$|\x7f", label=False)) == _spec(
        "null",
        "null",
        '{"args":{"label":false,"separator":"\\u0024|\\u007f"},"op":"join@1"}',
        '{"args":{},"op":"all@1"}',
        "concat",
    )
