"""A compiled Rank or Concat survives url4: editable Python, replay and tampering (OME-1289)."""

from __future__ import annotations

from typing import Any

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators, members3
from url4 import expr, render, src, text

import screamingface as sf
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.url4 import _candidate_from_url4
from screamingface.reducer import Reducer

_SURFACE = _CheckSurface(
    check_route="/benchmarks/ifeval/revision-1/check-surface",
    feedback_intent="feedback",
    expected_check_cost="free",
)
_CANNOT_REBUILD = "cannot rebuild"


def _compiled(recipe: sf.Recipe) -> Any:
    return compile_candidate(recipe, check_surface=_SURFACE, operators=flow_operators())


def _linked(candidate: str) -> str:
    return render(
        expr(
            src(text(candidate), name="candidate", weight=0.0),
            src("/benchmarks/ifeval/revision-1/cases", name="rows", weight=0.0),
            intent=text("$rows"),
        )
    )


def _recovered(url4: str) -> sf.Recipe:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    candidate = namespace["candidate"]
    assert isinstance(candidate, sf.Recipe)
    return candidate


def _after(synthesizer: Reducer, *, members: int = 3) -> sf.Pipeline:
    routes = [f"provider/{name}" for name in "abcdef"[:members]]
    return sf.Pipeline(
        [sf.Fusion(routes, synthesizer=synthesizer), sf.Model("provider/w", prompt="Write.")]
    )


def _scores_judge() -> sf.Judge:
    return sf.Judge("provider/j", returns="scores", rubric=RUBRIC)


def _shapes() -> dict[str, sf.Recipe]:
    return {
        "rank by judge": _after(sf.Rank(k=2, by=_scores_judge())),
        "rank by judge with params": _after(
            sf.Rank(
                k=1,
                by=sf.Judge(
                    "provider/j", returns="scores", rubric="Score.\nCosts $5.", params={"seed": 7}
                ),
            )
        ),
        "rank by field": _after(sf.Rank(k=2, by_field="result.score[0]")),
        "concat": _after(sf.Concat()),
        "concat plain": _after(sf.Concat("||")),
        "concat without labels": _after(sf.Concat("<<$|>>", label=False)),
        "concat with an odd separator": _after(sf.Concat(" \x7f\t\"'\\é💥")),
        "two selections in a row": sf.Pipeline(
            [
                sf.Fusion(members3(), synthesizer=sf.Rank(k=2, by=_scores_judge())),
                sf.Fusion(["provider/d", "provider/e"], synthesizer=sf.Concat()),
                "provider/w",
            ]
        ),
        "selection as a recipe synthesizer": sf.Fusion(
            members3(),
            synthesizer=sf.Pipeline([sf.Fusion(members3(), synthesizer=sf.Concat()), "provider/s"]),
        ),
    }


@pytest.mark.parametrize("shape", sorted(_shapes()))
def test_rank_and_concat_round_trip(shape: str) -> None:
    compiled = _compiled(_shapes()[shape])

    assert _compiled(_recovered(compiled.url4)).url4 == compiled.url4
    replayed = _candidate_from_url4(_linked(compiled.url4))
    assert replayed.operations == compiled.operations
    assert replayed.models == compiled.models
    assert [member.operation_id for member in replayed.members] == [
        member.operation_id for member in compiled.members
    ]
    assert [member.models for member in replayed.members] == [
        member.models for member in compiled.members
    ]


def test_to_python_writes_the_reducers() -> None:
    judged = sf.Url4(_compiled(_shapes()["rank by judge"]).url4).to_python()
    assert (
        "synthesizer=sf.Rank(k=2, by=sf.Judge('provider/j', returns='scores', "
        "rubric='Pick the most correct answer.')),"
    ) in judged
    field = sf.Url4(_compiled(_shapes()["rank by field"]).url4).to_python()
    assert "synthesizer=sf.Rank(k=2, by_field='result.score[0]')," in field
    concat = sf.Url4(_compiled(_shapes()["concat"]).url4).to_python()
    assert "synthesizer=sf.Concat(separator='\\n\\n---\\n\\n', label=True)," in concat


def test_the_recovered_reducers_equal_the_originals() -> None:
    for shape in ("rank by judge with params", "rank by field", "concat without labels"):
        original = _shapes()[shape]
        rebuilt = _recovered(_compiled(original).url4)
        assert isinstance(original, sf.Pipeline)
        assert isinstance(rebuilt, sf.Pipeline)
        before, after = original.stages[0], rebuilt.stages[0]
        assert isinstance(before, sf.Fusion)
        assert isinstance(after, sf.Fusion)
        assert after.synthesizer == before.synthesizer


def _tamperings() -> dict[str, tuple[str, str, str, str]]:
    """name -> (shape, text to replace, replacement, expected error)."""

    return {
        "k is a bool": ("rank by field", '"args":{"k":2}', '"args":{"k":true}', _CANNOT_REBUILD),
        "k is a string": ("rank by field", '"args":{"k":2}', '"args":{"k":"2"}', _CANNOT_REBUILD),
        "k is a float": ("rank by field", '"args":{"k":2}', '"args":{"k":2.0}', _CANNOT_REBUILD),
        "k is zero": ("rank by field", '"args":{"k":2}', '"args":{"k":0}', "between 1 and 256"),
        "k above the member count": (
            "rank by field",
            '"args":{"k":2}',
            '"args":{"k":5}',
            "k=5 members but the Fusion has 3",
        ),
        "extra select arg": (
            "rank by field",
            '"args":{"k":2}',
            '"args":{"k":2,"x":1}',
            _CANNOT_REBUILD,
        ),
        "path is not a field path": (
            "rank by field",
            '"path":"result.score[0]"',
            '"path":"a b"',
            "must be a JSON path",
        ),
        "path is not a string": (
            "rank by field",
            '"path":"result.score[0]"',
            '"path":3',
            _CANNOT_REBUILD,
        ),
        "normalizer is not numeric@1": (
            "rank by field",
            '"op":"numeric@1"',
            '"op":"text@1"',
            _CANNOT_REBUILD,
        ),
        "normalizer is not pinned to the exact id": (
            "rank by field",
            '"op":"numeric@1"',
            '"op":"numeric@2"',
            _CANNOT_REBUILD,
        ),
        "weights set": (
            "rank by field",
            '"weights":null',
            '"weights":{"member_1":1.0,"member_2":1.0,"member_3":1.0}',
            _CANNOT_REBUILD,
        ),
        "values source with a judge call": (
            "rank by judge",
            '"args":{"source":"judge"}',
            '"args":{"source":"values"}',
            _CANNOT_REBUILD,
        ),
        "judge source with an extract": (
            "rank by judge",
            '"extract":null',
            '"extract":{"args":{"path":"s"},"op":"json_field@1"}',
            _CANNOT_REBUILD,
        ),
        "separator empty": ("concat plain", '"separator":"||"', '"separator":""', "empty"),
        "separator not a string": (
            "concat plain",
            '"separator":"||"',
            '"separator":3',
            _CANNOT_REBUILD,
        ),
        "label not a bool": ("concat", '"label":true', '"label":"yes"', _CANNOT_REBUILD),
        "extra join arg": ("concat", '"label":true', '"label":true,"x":1', _CANNOT_REBUILD),
        "select with args": (
            "concat",
            '"args":{},"op":"all@1"',
            '"args":{"x":1},"op":"all@1"',
            _CANNOT_REBUILD,
        ),
        "extract set": (
            "concat",
            '"extract":null',
            '"extract":{"args":{},"op":"whole@1"}',
            _CANNOT_REBUILD,
        ),
    }


@pytest.mark.parametrize("case", sorted(_tamperings()))
def test_rank_and_concat_tampering_is_refused(case: str) -> None:
    shape, old, new, message = _tamperings()[case]
    url4 = _compiled(_shapes()[shape]).url4
    assert old in url4
    tampered = url4.replace(old, new, 1)

    with pytest.raises(ValueError, match=message):
        sf.Url4(tampered).to_python()


def test_a_followed_selection_inside_a_corrective_loop_round_trips() -> None:
    loop = sf.CorrectiveLoop(
        [_after(sf.Concat()), _after(sf.Rank(k=1, by=_scores_judge()))],
        judge="provider/x",
        max_rounds=2,
    )
    solo = sf.SelfCorrective(_after(sf.Rank(k=1, by_field="s")), max_rounds=2)

    for recipe, kind in ((loop, "corrective_loop"), (solo, "self_corrective")):
        compiled = _compiled(recipe)
        source = sf.Url4(compiled.url4).to_python()
        assert "synthesizer=sf.Concat(" in source or "synthesizer=sf.Rank(" in source
        assert _compiled(_recovered(compiled.url4)).url4 == compiled.url4
        replayed = _candidate_from_url4(_linked(compiled.url4))
        assert replayed.kind == kind
        assert "ensemble/combine/v1" not in replayed.models
