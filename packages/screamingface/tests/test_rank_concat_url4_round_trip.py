"""A compiled Rank or Concat survives url4: editable Python, replay and tampering (OME-1289)."""

from __future__ import annotations

from typing import Any

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators, members3
from _nodes import FusionNode
from url4 import expr, render, src, text

import screamingface as sf
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.url4 import _candidate_from_url4
from screamingface._surface.chain import Step
from screamingface._surface.lowering import lower

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


def _after(*steps: Step, members: int = 3) -> sf.Recipe:
    """A block of ``steps`` after a Fanout, closed by the writer that reads the selection."""

    routes = [f"provider/{name}" for name in "abcdef"[:members]]
    writer = sf.Synthesize(sf.Model("provider/w", prompt="Write."))
    return sf.Pipeline([sf.Fanout(routes), *steps, writer])


def _scores_judge() -> sf.Judge:
    return sf.Judge("provider/j", rubric=RUBRIC)


def _by_judge(k: int) -> sf.Rank:
    return sf.Rank(k, by="score:judge")


def _shapes() -> dict[str, sf.Recipe]:
    return {
        "rank by judge": _after(_scores_judge(), _by_judge(2)),
        "rank by judge with params": _after(
            sf.Judge("provider/j", rubric="Score.\nCosts $5.", params={"seed": 7}), _by_judge(1)
        ),
        "rank by signal": _after(sf.Rank(2, by="field:score")),
        "rank by signal min": _after(sf.Rank(2, by="field:score", order="min")),
        "rank by accounting signal": _after(sf.Rank(2, by="cost_usd", order="min")),
        "concat": _after(sf.Concat()),
        "concat without labels": _after(sf.Concat("<<$|>>", label=False)),
        "concat with an odd separator": _after(sf.Concat(" \x7f\t\"'\\é💥")),
        # WHY a recipe writer: the second selection reads the first one's envelope, and its own
        # writer closes it
        "two selections in a row": sf.Fanout(members3())
        >> _scores_judge()
        >> _by_judge(2)
        >> sf.Synthesize(
            sf.Fanout(["provider/d", "provider/e"]) >> sf.Concat() >> sf.Synthesize("provider/w")
        ),
        "selection as a recipe synthesizer": sf.Fanout(members3())
        >> sf.Synthesize(sf.Fanout(members3()) >> sf.Concat() >> sf.Synthesize("provider/s")),
    }


@pytest.mark.parametrize(
    "shape",
    [
        "rank by judge with params",
        "rank by signal min",
        "rank by accounting signal",
        "concat with an odd separator",
        "two selections in a row",
        "selection as a recipe synthesizer",
    ],
)
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
    assert judged.splitlines()[-4:] == [
        "    >> sf.Judge('provider/j', rubric='Pick the most correct answer.')",
        "    >> sf.Rank(2, by='score:judge')",
        "    >> sf.Synthesize('provider/w', prompt='Write.')",
        ")",
    ]
    signal = sf.Url4(_compiled(_shapes()["rank by signal min"]).url4).to_python()
    assert "    >> sf.Rank(2, by='field:score', order='min')" in signal.splitlines()
    plain = sf.Url4(_compiled(_shapes()["rank by signal"]).url4).to_python()
    assert "    >> sf.Rank(2, by='field:score')" in plain.splitlines()
    concat = sf.Url4(_compiled(_shapes()["concat"]).url4).to_python()
    assert "    >> sf.Concat()" in concat.splitlines()


def test_the_recovered_reducers_equal_the_originals() -> None:
    for shape in (
        "rank by judge with params",
        "rank by signal min",
        "rank by accounting signal",
        "concat without labels",
    ):
        chain = _shapes()[shape]
        rebuilt = _recovered(_compiled(chain).url4)
        assert isinstance(chain, sf.Pipeline)
        assert isinstance(rebuilt, sf.Pipeline)
        # the Fanout, the judge and the narrow step come back as written; the writer holds its
        # prompt on the step (Synthesize('provider/w', prompt=...)), which lowers to the same Model
        assert rebuilt.steps[:-1] == chain.steps[:-1]
        original, lowered = lower(chain), lower(rebuilt)
        assert isinstance(original, sf.Pipeline)
        assert isinstance(lowered, sf.Pipeline)
        before, after = original._stage_values()[0], lowered._stage_values()[0]
        assert isinstance(before, FusionNode)
        assert isinstance(after, FusionNode)
        assert after.synthesizer == before.synthesizer


def _tamperings() -> dict[str, tuple[str, str, str, str]]:
    """name -> (shape, text to replace, replacement, expected error)."""

    return {
        "k is a string": (
            "rank by signal",
            '"args":{"k":2,"order":"max"}',
            '"args":{"k":"2","order":"max"}',
            _CANNOT_REBUILD,
        ),
        "k above the member count": (
            "rank by signal",
            '"args":{"k":2,"order":"max"}',
            '"args":{"k":5,"order":"max"}',
            _CANNOT_REBUILD,
        ),
        "by_signal: orders that differ": (
            "rank by signal",
            '"args":{"key":"field:score","order":"max"},"op":"by_signal@1"',
            '"args":{"key":"field:score","order":"min"},"op":"by_signal@1"',
            _CANNOT_REBUILD,
        ),
        "by_signal: key is not a string": (
            "rank by signal",
            '"key":"field:score"',
            '"key":3',
            _CANNOT_REBUILD,
        ),
        "label not a bool": ("concat", '"label":true', '"label":"yes"', _CANNOT_REBUILD),
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
        [_after(sf.Concat()), _after(_scores_judge(), _by_judge(1))],
        judge="provider/x",
        max_rounds=2,
    )
    solo = sf.SelfCorrective(_after(sf.Rank(1, by="field:s")), max_rounds=2)
    shown = {
        "corrective_loop": (
            ">> sf.Concat() >> sf.Synthesize(",
            ">> sf.Rank(1, by='score:judge') >> sf.Synthesize(",
        ),
        "self_corrective": (">> sf.Rank(1, by='field:s') >> sf.Synthesize(",),
    }

    for recipe, kind in ((loop, "corrective_loop"), (solo, "self_corrective")):
        compiled = _compiled(recipe)
        source = sf.Url4(compiled.url4).to_python()
        for step in shown[kind]:
            assert step in source
        assert _compiled(_recovered(compiled.url4)).url4 == compiled.url4
        replayed = _candidate_from_url4(_linked(compiled.url4))
        assert replayed.kind == kind
        assert "ensemble/combine/v1" not in replayed.models
