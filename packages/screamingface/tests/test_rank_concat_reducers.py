"""sf.Rank and sf.Concat: validation, spec, repr and compile shape (OME-1289, RK-6, CC-2/5)."""

from __future__ import annotations

from typing import Any

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators, members3
from url4 import Expression, RelExpr, Source, Text, build, render, struct

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface.operation import OperationInfo
from screamingface.reducer import Reducer

_COMBINE_PATH = "/ensemble/combine/v1"
_SEPARATOR_TEXT = "\\n\\n---\\n\\n"  # how the default separator is spelled inside the spec JSON


def _scores_judge(**kw: Any) -> sf.Judge:
    return sf.Judge("provider/j", returns="scores", rubric=RUBRIC, **kw)


def _next_stage() -> sf.Model:
    return sf.Model("provider/w", prompt="Write the final answer from these drafts.")


def _compile(recipe: sf.Recipe) -> Any:
    return compile_candidate(recipe, operators=flow_operators())


def _sources(url4: str) -> list[Any]:
    root = build(url4)
    assert isinstance(root, Expression)
    return list(root.sources)


def _call(source: Any) -> RelExpr:
    assert isinstance(source, Source)
    assert isinstance(source.value, RelExpr)
    return source.value


def _context(signals: dict[str, str] | None) -> str:
    payload: dict[str, Any] = {
        "input": "$input",
        "outputs": {f"member_{index}": f"$model_{index}" for index in (1, 2, 3)},
    }
    if signals is not None:
        payload["signals"] = signals
    return render(struct(payload))


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
    with pytest.raises(ValueError, match="exactly one of by= or by_field="):
        sf.Rank(k=2)
    with pytest.raises(ValueError, match="exactly one of by= or by_field="):
        sf.Rank(k=2, by=_scores_judge(), by_field="score")
    with pytest.raises(ValueError, match=r"Rank\(by=\.\.\.\) needs sf.Judge"):
        sf.Rank(k=2, by=sf.Judge("provider/j", returns="label", rubric=RUBRIC))
    with pytest.raises(ValueError, match=r"Rank\(by=\.\.\.\) needs sf.Judge"):
        sf.Rank(k=2, by="provider/j")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="Rank by_field must be a string"):
        sf.Rank(k=2, by_field=3)  # type: ignore[arg-type]
    for bad in ("", "a.", ".a", "a[01]", "a b", "$a", "a" * 257):
        with pytest.raises(ValueError, match="Rank by_field must be a JSON field path"):
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

    assert text(sf.Rank(k=2, by=_scores_judge())) == _spec(
        "null",
        "null",
        '{"args":{"source":"judge"},"op":"scores@1"}',
        '{"args":{"k":2},"op":"top_k@1"}',
        "rank",
    )
    # WHY numeric@1 exactly: scores@1 assumes the v1 output form, so a later numeric@2 must not
    # change what this Rank means.
    assert text(sf.Rank(k=2, by_field="score")) == _spec(
        '{"args":{"path":"score"},"op":"json_field@1"}',
        '{"args":{},"op":"numeric@1"}',
        '{"args":{"source":"values"},"op":"scores@1"}',
        '{"args":{"k":2},"op":"top_k@1"}',
        "rank",
    )
    assert text(sf.Concat()) == _spec(
        "null",
        "null",
        f'{{"args":{{"label":true,"separator":"{_SEPARATOR_TEXT}"}},"op":"join@1"}}',
        '{"args":{},"op":"all@1"}',
        "concat",
    )
    assert text(sf.Concat("$|\x7f", label=False)) == _spec(
        "null",
        "null",
        '{"args":{"label":false,"separator":"\\u0024|\\u007f"},"op":"join@1"}',
        '{"args":{},"op":"all@1"}',
        "concat",
    )


def test_rank_by_judge_compiles_a_judge_call_then_the_combine_call() -> None:
    compiled = _compile(
        sf.Pipeline(
            [sf.Fusion(members3(), synthesizer=sf.Rank(k=2, by=_scores_judge())), _next_stage()]
        )
    )
    sources = _sources(compiled.url4)

    assert [source.name for source in sources] == [
        "model_1",
        "model_2",
        "model_3",
        "judge_1",
        "synthesis_1",
        "model_4",
        "_sf_recipe",
    ]
    judge = _call(sources[3])
    assert judge.path == "/provider/j"
    assert judge.params == (("binding", "judge_1"),)
    assert judge.context == _context(None)
    combine = _call(sources[4])
    assert combine.path == _COMBINE_PATH
    assert combine.params == (("binding", "synthesis_1"),)
    assert combine.context == _context({"judge": "$judge_1"})
    assert isinstance(combine.intent, Text)
    assert '"reducer":"rank"' in combine.intent.value
    assert compiled.operations[3:5] == (
        OperationInfo(
            id="op_judge_1",
            kind="judge",
            label="a+b+c judge",
            depends_on=("op_model_1", "op_model_2", "op_model_3"),
        ),
        OperationInfo(
            id="op_synthesis_1",
            kind="combine",
            label="a+b+c combine",
            depends_on=("op_model_1", "op_model_2", "op_model_3", "op_judge_1"),
        ),
    )
    assert compiled.models == ("provider/a", "provider/b", "provider/c", "provider/j", "provider/w")


def test_concat_compiles_to_one_pure_combine_call() -> None:
    fusion = sf.Fusion(members3(), synthesizer=sf.Concat())
    compiled = _compile(sf.Pipeline([fusion, _next_stage()]))
    sources = _sources(compiled.url4)

    assert [source.name for source in sources] == [
        "model_1",
        "model_2",
        "model_3",
        "synthesis_1",
        "model_4",
        "_sf_recipe",
    ]
    combine = _call(sources[3])
    assert combine.path == _COMBINE_PATH
    assert combine.context == _context(None)
    assert [call.path for call in map(_call, sources[:5])].count(_COMBINE_PATH) == 1
    # the Fusion adds exactly one non-member operation, and no model is called for it
    assert [(operation.id, operation.kind) for operation in compiled.operations] == [
        ("op_model_1", "model"),
        ("op_model_2", "model"),
        ("op_model_3", "model"),
        ("op_synthesis_1", "combine"),
        ("op_model_4", "model"),
    ]
    assert compiled.operations[3].depends_on == ("op_model_1", "op_model_2", "op_model_3")
    assert compiled.models == ("provider/a", "provider/b", "provider/c", "provider/w")
    assert compiled.parameter_assignments == ()


def test_vote_and_judge_are_not_selections() -> None:
    # CHAR: only Rank and Concat carry the selection flag, so a Vote or Judge Fusion still ends
    # a candidate (SL-1).
    for synthesizer in (sf.Vote(), sf.Judge("provider/j", returns="label", rubric=RUBRIC)):
        compiled = _compile(sf.Fusion(members3(), synthesizer=synthesizer))
        assert compiled.operations[-1].kind == "combine"
    assert sf.Rank(k=1, by_field="s")._kind == "selection"
    assert sf.Concat()._kind == "selection"


def _rank_any() -> Any:
    return sf.Rank(k=1, by_field="s")


def _concat_any() -> Any:
    return sf.Concat()


def test_rank_and_concat_are_only_fusion_synthesizers() -> None:
    misplaced: list[Any] = [
        lambda: sf.Pipeline([_rank_any()]),
        lambda: sf.CorrectiveLoop(["p/a", "p/b"], judge=_concat_any()),
        lambda: sf.Fusion([_concat_any(), "p/a"], synthesizer="p/s"),
    ]
    for build_it in misplaced:
        with pytest.raises(TypeError, match="reducer must be a Fusion synthesizer"):
            build_it()
