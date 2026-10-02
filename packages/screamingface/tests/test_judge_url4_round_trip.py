"""A compiled Judge survives url4: replay, editable Python and tampering refusal (OME-1289)."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

import pytest
from _combine_flow_fixtures import RUBRIC, flow_operators, judge_fusion, members3
from url4 import Expression, build, expr, render, src, text

import screamingface as sf
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec
from screamingface._evaluation.url4 import _candidate_from_url4
from screamingface.judge import JUDGE_TEMPLATES
from screamingface.reducer import _ModelSignal
from screamingface.url4 import _calls

_SURFACE = _CheckSurface(
    check_route="/benchmarks/ifeval/revision-1/check-surface",
    feedback_intent="feedback",
    expected_check_cost="free",
)
_MODEL_CALLS = "does not match its model calls"
_INVALID_REDUCER = "invalid Reducer topology metadata"


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


def test_judge_round_trips_through_url4() -> None:
    compiled = _compiled(judge_fusion())

    source = sf.Url4(compiled.url4).to_python()
    assert (
        "synthesizer=sf.Judge('provider/j', returns='label', rubric='Pick the most correct "
        "answer.'),"
    ) in source
    assert _compiled(_recovered(compiled.url4)).url4 == compiled.url4

    replayed = _candidate_from_url4(_linked(compiled.url4))
    assert replayed.operations == compiled.operations
    assert [operation.label for operation in replayed.operations[3:]] == [
        "a+b+c judge",
        "a+b+c combine",
    ]
    assert (
        replayed.models
        == compiled.models
        == ("provider/a", "provider/b", "provider/c", "provider/j")
    )
    assert [member.operation_id for member in replayed.members] == [
        member.operation_id for member in compiled.members
    ]
    assert [member.models for member in replayed.members] == [
        member.models for member in compiled.members
    ]


def test_judge_round_trip_keeps_params_and_scores() -> None:
    original = sf.Judge(
        "provider/j",
        returns="scores",
        rubric="Score each.\nLine two costs $5 and \"quotes\" and 'single'.",
        params={"temperature": 0, "seed": 7, "top_p": 0.5, "flag": True},
    )
    compiled = _compiled(sf.Fusion(members3(), synthesizer=original))

    rebuilt = _recovered(compiled.url4)

    assert isinstance(rebuilt, sf.Fusion)
    assert rebuilt.synthesizer == original
    assert isinstance(rebuilt.synthesizer, sf.Judge)
    for field in ("name", "model", "returns", "rubric", "params"):
        assert getattr(rebuilt.synthesizer, field) == getattr(original, field)
    assert _compiled(rebuilt).url4 == compiled.url4


def _tamperings() -> dict[str, tuple[str, str, str]]:
    """name -> (text to replace, replacement, expected error)."""

    node = '{"binding":"judge_1","kind":"model","name":"j","named":false,"role":"judge"}'
    signals = f'"signals":[{{"key":"judge","source":{node}}}]'
    return {
        "binding param removed": (
            "?binding=judge_1&temperature=0&q=",
            "?temperature=0&q=",
            _MODEL_CALLS,
        ),
        "binding param of another call": (
            "?binding=judge_1&temperature=0&q=",
            "?binding=judge_2&temperature=0&q=",
            _MODEL_CALLS,
        ),
        "binding param after another param": (
            "?binding=judge_1&temperature=0&q=",
            "?temperature=0&binding=judge_1&q=",
            _MODEL_CALLS,
        ),
        "template version": (
            "judge-template@1 returns=label",
            "judge-template@2 returns=label",
            "unsupported judge call",
        ),
        "template of the other shape": (
            "judge-template@1 returns=label",
            "judge-template@1 returns=scores",
            "unsupported judge call",
        ),
        "spec of the other shape": (
            '"reduce":{"args":{},"op":"label@1"}',
            '"reduce":{"args":{"source":"judge"},"op":"scores@1"}',
            "cannot rebuild",
        ),
        "signal key renamed in the combine context": (
            "signals: {judge: '$judge_1'}",
            "signals: {jury: '$judge_1'}",
            _MODEL_CALLS,
        ),
        "signals removed from the combine context": (
            ", signals: {judge: '$judge_1'}",
            "",
            _MODEL_CALLS,
        ),
        "binding param on a member": (
            "/provider/a($input)",
            "/provider/a?binding=model_1&q=($input)",
            _MODEL_CALLS,
        ),
        "no signals": (signals, '"signals":[]', _INVALID_REDUCER),
        "signal key": ('{"key":"judge","source"', '{"key":"jury","source"', _INVALID_REDUCER),
        "source role": (
            '"named":false,"role":"judge"',
            '"named":false,"role":"model"',
            _INVALID_REDUCER,
        ),
        "source binding": (
            '"binding":"judge_1","kind":"model"',
            '"binding":"model_9","kind":"model"',
            _INVALID_REDUCER,
        ),
        "extra key in the signal": (
            '{"key":"judge","source"',
            '{"extra":1,"key":"judge","source"',
            _INVALID_REDUCER,
        ),
        "extra key in the source": (
            '"named":false,"role":"judge"',
            '"extra":1,"named":false,"role":"judge"',
            _INVALID_REDUCER,
        ),
        "named not a bool": (
            '"named":false,"role":"judge"',
            '"named":0,"role":"judge"',
            _INVALID_REDUCER,
        ),
        "signals not a list": (signals, '"signals":{}', _INVALID_REDUCER),
        "duplicate signal key": (
            signals,
            f'"signals":[{{"key":"judge","source":{node}}},{{"key":"judge","source":{node}}}]',
            _INVALID_REDUCER,
        ),
        "judge role on a member": (
            '{"binding":"model_1","kind":"model","name":"a","named":false,"role":"model"}',
            '{"binding":"model_1","kind":"model","name":"a","named":false,"role":"judge"}',
            "invalid Model topology metadata",
        ),
        "judge source on the combine route": (
            "/provider/j?binding=judge_1",
            "/ensemble/combine/v1?binding=judge_1",
            _MODEL_CALLS,
        ),
    }


@pytest.mark.parametrize("case", sorted(_tamperings()))
def test_judge_topology_tampering_is_refused(case: str) -> None:
    old, new, message = _tamperings()[case]
    url4 = _compiled(judge_fusion(params={"temperature": 0})).url4
    assert old in url4
    tampered = url4.replace(old, new, 1)

    with pytest.raises(ValueError, match=message):
        sf.Url4(tampered).to_python()


def test_a_pure_rule_reducer_refuses_signals() -> None:
    spec = decode_combine_spec(
        combine_spec_text(sf.Median(), member_count=3, operators=flow_operators())
    )
    signal = _ModelSignal("judge", "provider/j", JUDGE_TEMPLATES["label"], MappingProxyType({}))

    with pytest.raises(ValueError, match=_INVALID_REDUCER):
        sf.Median._rebuild(spec, (signal,))
    assert sf.Median._rebuild(spec, ()) == sf.Median(extract="last_number@1", select="nearest@1")


def test_a_vote_reads_a_scores_judge_call_only() -> None:
    spec = decode_combine_spec(
        combine_spec_text(sf.Vote(), member_count=3, operators=flow_operators())
    )
    signal = _ModelSignal("judge", "provider/j", JUDGE_TEMPLATES["label"], MappingProxyType({}))

    assert sf.Vote._rebuild(spec, ()) == sf.Vote(extract="last_line@1", normalize="text@1")
    with pytest.raises(ValueError, match="unsupported judge call"):
        sf.Vote._rebuild(spec, (signal,))


def test_a_judge_spec_without_its_judge_call_is_refused() -> None:
    spec = decode_combine_spec(
        combine_spec_text(
            sf.Judge("provider/j", returns="label", rubric=RUBRIC),
            member_count=3,
            operators=flow_operators(),
        )
    )

    with pytest.raises(ValueError, match="without its judge call"):
        sf.Judge._from_spec(spec)
    with pytest.raises(ValueError, match="unsupported judge call"):
        sf.Judge._rebuild(spec, ())


def test_corrective_replay_recompiles_a_judge_member() -> None:
    loop = sf.CorrectiveLoop([judge_fusion(), "provider/d"], judge="provider/x", max_rounds=2)
    compiled = _compiled(loop)

    source = sf.Url4(compiled.url4).to_python()
    assert "synthesizer=sf.Judge(" in source
    replayed = _candidate_from_url4(_linked(compiled.url4))
    assert replayed.kind == "corrective_loop"
    assert "ensemble/combine/v1" not in replayed.models
    assert "provider/j" in replayed.models
    # each round recompiles the member Fusion, so the judge call is numbered per round
    operations = {operation.id: operation for operation in compiled.operations}
    for round_number in (1, 2):
        judge = operations[f"op_judge_{round_number}"]
        combine = operations[f"op_synthesis_{round_number}"]
        assert judge.kind == "judge"
        assert judge.label == "a+b+c judge"
        assert combine.depends_on == (*judge.depends_on, judge.id)
        assert len(judge.depends_on) == 3
    assert operations["op_judge_1"].depends_on != operations["op_judge_2"].depends_on
    root = build(compiled.url4)
    assert isinstance(root, Expression)
    calls = _calls(root)
    for round_number in (1, 2):
        assert calls[f"judge_{round_number}"].params == (("binding", f"judge_{round_number}"),)
        assert f"judge_{round_number}" in calls[f"synthesis_{round_number}"].dependencies


def _nested_shapes() -> dict[str, sf.Recipe]:
    scores = sf.Judge("provider/k", returns="scores", rubric="Score each member.")
    return {
        "judge inside judge": sf.Fusion([judge_fusion(), "provider/d"], synthesizer=scores),
        "judge in a recipe synthesizer": sf.Fusion(
            members3(), synthesizer=sf.Pipeline([judge_fusion("scores"), "provider/s"])
        ),
        "judge fusion in a model fusion": sf.Fusion(
            [judge_fusion(), "provider/d"], synthesizer="provider/s"
        ),
        "judge fusion in a pipeline": sf.Pipeline([judge_fusion(), judge_fusion("scores")]),
    }


@pytest.mark.parametrize("shape", sorted(_nested_shapes()))
def test_nested_judge_shapes_round_trip_and_replay_equal(shape: str) -> None:
    compiled = _compiled(_nested_shapes()[shape])

    assert _compiled(_recovered(compiled.url4)).url4 == compiled.url4
    replayed = _candidate_from_url4(_linked(compiled.url4))
    assert replayed.operations == compiled.operations
    assert replayed.models == compiled.models
    assert [member.operation_id for member in replayed.members] == [
        member.operation_id for member in compiled.members
    ]


def test_a_self_corrective_judge_round_trips() -> None:
    compiled = _compiled(sf.SelfCorrective(judge_fusion(), max_rounds=2))

    assert _compiled(_recovered(compiled.url4)).url4 == compiled.url4
    replayed = _candidate_from_url4(_linked(compiled.url4))
    assert replayed.kind == "self_corrective"
    assert "provider/j" in replayed.models
