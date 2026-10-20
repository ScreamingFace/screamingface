"""A Pipeline warns when the writer stage uses the judge's model (E4b part 2, JW#1-11).

FEATURE: ``sf.Pipeline([sf.Fusion(..., synthesizer=<reads a judge>), <same model>])`` sends one
``sf.JudgeWriterWarning`` at compile time. It never fails the compile and never changes the url4.
STORY: as a researcher, I hear that the writer is also the scorer before I pay for the run.
"""

from __future__ import annotations

import hashlib
import warnings
from collections.abc import Callable
from typing import Literal

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators
from url4 import expr, render, src, text

import screamingface as sf
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import _CompiledCandidate, compile_candidate
from screamingface._evaluation.url4 import _candidate_from_url4
from screamingface.reducer import Reducer
from screamingface.warnings import JudgeWriterWarning

JUDGE_ROUTE = "openrouter/a/b"
MEMBERS = ["provider/m1", "provider/m2", "provider/m3"]
MESSAGE_1_2 = (
    "Pipeline 'judged': stages 1 and 2 use the same model 'openrouter/a/b': stage 1 scores the "
    "members as the judge, and stage 2 writes the answer, so the writer is also the scorer. "
    "Give one of the two stages another model, or keep both and ignore this warning."
)
_SURFACE = _CheckSurface(
    check_route="/benchmarks/ifeval/revision-1/check-surface",
    feedback_intent="feedback",
    expected_check_cost="free",
)


def _judge(route: str = JUDGE_ROUTE) -> sf.Judge:
    return sf.Judge(route, returns="scores", rubric=RUBRIC)


def _ranked(route: str = JUDGE_ROUTE, *, quorum: int | Literal["all"] = "all") -> sf.Fusion:
    return sf.Fusion(MEMBERS, synthesizer=sf.Rank(2, by=_judge(route)), quorum=quorum)


def _judged(writer: str | sf.Recipe = JUDGE_ROUTE, judge: str = JUDGE_ROUTE) -> sf.Pipeline:
    return sf.Pipeline([_ranked(judge), writer], name="judged")


def _compile(recipe: sf.Recipe) -> _CompiledCandidate:
    return compile_candidate(recipe, operators=flow_operators())


def _quiet(recipe: sf.Recipe) -> _CompiledCandidate:
    """Compile with the warning turned into an error: the compile must not send it."""

    with warnings.catch_warnings():
        warnings.simplefilter("error", JudgeWriterWarning)
        return _compile(recipe)


def _linked(candidate: str) -> str:
    return render(
        expr(
            src(text(candidate), name="candidate", weight=0.0),
            src("/benchmarks/ifeval/revision-1/cases", name="rows", weight=0.0),
            intent=text("$rows"),
        )
    )


@pytest.mark.parametrize(
    ("recipe", "expected"),
    [
        (
            sf.Pipeline([_ranked(), JUDGE_ROUTE], name="judged"),
            MESSAGE_1_2,
        ),
        (
            sf.Pipeline(["provider/x", _ranked(), JUDGE_ROUTE], name="judged"),
            "Pipeline 'judged': stages 2 and 3 use the same model 'openrouter/a/b': stage 2 "
            "scores the members as the judge, and stage 3 writes the answer, so the writer is "
            "also the scorer. Give one of the two stages another model, or keep both and ignore "
            "this warning.",
        ),
        (
            sf.Pipeline(
                [_ranked(), sf.Model(JUDGE_ROUTE, prompt="Write.", params={"temperature": 0})],
                name="judged",
            ),
            MESSAGE_1_2,
        ),
    ],
    ids=["first-stage", "middle-stage", "writer-with-prompt-and-params"],
)
def test_judge_then_same_model_writer_warns_once(recipe: sf.Recipe, expected: str) -> None:
    with pytest.warns(JudgeWriterWarning) as recorded:
        _compile(recipe)

    judge_writer = [w for w in recorded if issubclass(w.category, JudgeWriterWarning)]
    assert len(judge_writer) == 1
    assert str(judge_writer[0].message) == expected
    assert isinstance(judge_writer[0].message, sf.EvaluationWarning)
    assert judge_writer[0].filename == __file__
    assert RUBRIC not in expected
    assert "m1" not in str(judge_writer[0].message)


def test_warning_does_not_change_the_url4() -> None:
    with pytest.warns(JudgeWriterWarning):
        warned = _compile(_judged())

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", JudgeWriterWarning)
        quiet = _compile(_judged())

    assert warned.url4 == quiet.url4
    assert warned.operations == quiet.operations
    assert hashlib.sha256(warned.url4.encode()).hexdigest() == (
        "49111ad6bff27b24d853931defe03f18b0ab05a55779f62eee814829e05dd971"
    )
    assert len(warned.url4) == 2557


def test_different_writer_model_does_not_warn() -> None:
    _quiet(_judged("openrouter/c/d"))
    _quiet(_judged(sf.Model("openrouter/a/c")))


@pytest.mark.parametrize(
    ("writer", "judge"),
    [
        ("openrouter/a/b", "/openrouter/a/b"),
        ("/openrouter/a/b", "openrouter/a/b"),
    ],
    ids=["slash-judge", "slash-writer"],
)
def test_two_spellings_of_one_route_warn(writer: str, judge: str) -> None:
    with pytest.warns(JudgeWriterWarning) as recorded:
        _compile(_judged(writer=writer, judge=judge))

    judge_writer = [w for w in recorded if issubclass(w.category, JudgeWriterWarning)]
    assert len(judge_writer) == 1
    assert str(judge_writer[0].message) == MESSAGE_1_2


def test_warning_as_error_raises_from_compile() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", sf.EvaluationWarning)
        with pytest.raises(JudgeWriterWarning) as caught:
            _compile(_judged())

    assert str(caught.value) == MESSAGE_1_2


def _loop() -> sf.Recipe:
    return sf.CorrectiveLoop([_judged(), "provider/d"], judge="provider/j", max_rounds=2)


def _twice() -> sf.Recipe:
    pipeline = _judged()
    return sf.Fusion([pipeline, pipeline], synthesizer="provider/s")


def _two_passes() -> sf.Recipe:
    # Pick by cost_usd reads an accounting signal, so compile_candidate runs a second pass.
    return sf.Fusion(
        [_judged(), "provider/z"],
        synthesizer=sf.Pick(by_signal=sf.signal("cost_usd"), order="min"),
    )


@pytest.mark.parametrize(
    "build",
    [_loop, _twice, _two_passes],
    ids=["corrective-loop-rounds", "same-object-twice", "accounting-second-pass"],
)
def test_one_pipeline_compiled_twice_warns_once(build: Callable[[], sf.Recipe]) -> None:
    recipe = build()
    with pytest.warns(JudgeWriterWarning) as recorded:
        compile_candidate(recipe, check_surface=_SURFACE, operators=flow_operators())

    judge_writer = [w for w in recorded if issubclass(w.category, JudgeWriterWarning)]
    assert len(judge_writer) == 1
    assert str(judge_writer[0].message) == MESSAGE_1_2


def test_url4_rebuild_silences_the_warning() -> None:
    pipeline = sf.Pipeline([_ranked(quorum=2), JUDGE_ROUTE], name="judged")
    with pytest.warns(JudgeWriterWarning) as recorded:
        compiled = _compile(pipeline).url4

    judge_writer = [w for w in recorded if w.category is JudgeWriterWarning]
    assert len(judge_writer) == 1

    with warnings.catch_warnings():
        warnings.simplefilter("error", JudgeWriterWarning)
        python = sf.Url4(compiled).to_python()
        recovered = _candidate_from_url4(_linked(compiled))

    assert "quorum=2" in python
    assert recovered.kind == "pipeline"


@pytest.mark.parametrize(
    "recipe",
    [
        # the judge Fusion is the LAST stage; the same model writes BEFORE it
        sf.Pipeline([JUDGE_ROUTE, sf.Fusion(MEMBERS, synthesizer=_judge())], name="judged"),
        # the next stage is a Fusion (its synthesizer is even the judge's model)
        sf.Pipeline(
            [_ranked(), sf.Fusion([JUDGE_ROUTE, "provider/x"], synthesizer=JUDGE_ROUTE)],
            name="judged",
        ),
        # not adjacent: another model sits between the judge Fusion and the same model
        sf.Pipeline([_ranked(), "provider/x", JUDGE_ROUTE], name="judged"),
        # a judge Fusion alone (not in a Pipeline)
        sf.Fusion(MEMBERS, synthesizer=_judge()),
    ],
    ids=["judge-last", "fusion-next", "not-adjacent", "no-pipeline"],
)
def test_judge_as_last_stage_or_before_a_fusion_does_not_warn(recipe: sf.Recipe) -> None:
    _quiet(recipe)


@pytest.mark.parametrize(
    "synthesizer",
    [
        sf.Vote(
            extract="last_number",
            normalize="numeric",
            weights=sf.signal("score:judge"),
            judge=_judge(),
        ),
        sf.Filter(where=sf.signal("score:judge") >= 7, judge=_judge()),
        _judge(),
        sf.Reduce("top_k", k=2, by=_judge()),
    ],
    ids=["vote-by-judge-score", "filter-by-judge-score", "judge-reducer", "rank-block"],
)
def test_vote_and_filter_by_judge_score_warn_too(synthesizer: Reducer) -> None:
    pipeline = sf.Pipeline(
        [sf.Fusion(MEMBERS, synthesizer=synthesizer), JUDGE_ROUTE], name="judged"
    )
    with pytest.warns(JudgeWriterWarning) as recorded:
        _compile(pipeline)

    judge_writer = [w for w in recorded if issubclass(w.category, JudgeWriterWarning)]
    assert len(judge_writer) == 1
    assert str(judge_writer[0].message) == MESSAGE_1_2


@pytest.mark.parametrize(
    "synthesizer",
    [
        # a merge writer (key "writer_summary") on the same model is not a judge
        sf.Merge(
            fields={
                "answer": sf.FieldRule.majority(normalize="text"),
                "summary": sf.FieldRule.model(JUDGE_ROUTE, prompt="Write."),
            }
        ),
        # a Model synthesizer is not a reducer, so it is not a judge
        JUDGE_ROUTE,
    ],
    ids=["merge-writer", "model-synthesizer"],
)
def test_merge_writer_does_not_warn(synthesizer: Reducer | str) -> None:
    _quiet(sf.Pipeline([sf.Fusion(MEMBERS, synthesizer=synthesizer), JUDGE_ROUTE], name="judged"))


def test_judge_writer_warning_is_public() -> None:
    assert getattr(sf, "JudgeWriterWarning", None) is JudgeWriterWarning
    assert "JudgeWriterWarning" in sf.__all__
    assert issubclass(JudgeWriterWarning, sf.EvaluationWarning)
    assert issubclass(JudgeWriterWarning, UserWarning)


# --- review fix P5 #2: a gate's fallback judge is a judge too ------------------------------------


def _label_judge(route: str = JUDGE_ROUTE) -> sf.Judge:
    return sf.Judge(route, returns="label", rubric=RUBRIC)


@pytest.mark.parametrize(
    "synthesizer",
    [
        sf.Vote(gate=sf.Gate("agreement", ">=", 0.9, otherwise=_label_judge())),
        # the scores judge uses another model; the fallback judge uses the writer's model
        sf.Vote(
            extract="last_number",
            normalize="numeric",
            weights=sf.signal("score:judge"),
            judge=_judge("openrouter/c/d"),
            gate=sf.Gate("agreement", ">=", 0.9, otherwise=_label_judge()),
        ),
        # both judges use the writer's model: still one warning
        sf.Vote(
            extract="last_number",
            normalize="numeric",
            weights=sf.signal("score:judge"),
            judge=_judge(),
            gate=sf.Gate("agreement", ">=", 0.9, otherwise=_label_judge()),
        ),
    ],
    ids=["gate-fallback-judge", "scores-judge-and-gate-fallback-judge", "both-judges-same-route"],
)
def test_gate_fallback_judge_then_same_model_writer_warns(synthesizer: Reducer) -> None:
    pipeline = sf.Pipeline(
        [sf.Fusion(MEMBERS, synthesizer=synthesizer), JUDGE_ROUTE], name="judged"
    )
    with pytest.warns(JudgeWriterWarning) as recorded:
        _compile(pipeline)

    judge_writer = [w for w in recorded if issubclass(w.category, JudgeWriterWarning)]
    assert len(judge_writer) == 1
    assert str(judge_writer[0].message) == MESSAGE_1_2


def test_gate_fallback_writer_on_the_same_model_does_not_warn() -> None:
    vote = sf.Vote(gate=sf.Gate("agreement", ">=", 0.9, otherwise=sf.Model(JUDGE_ROUTE)))
    _quiet(sf.Pipeline([sf.Fusion(MEMBERS, synthesizer=vote), JUDGE_ROUTE], name="judged"))
