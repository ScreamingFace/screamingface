"""A real sf.Vote / sf.Median run joins its Answers and its trace (OME-1289 gap, AR#10-11, RT#4).

CHAR: these pass at once by design. The Answer join and the trace are unit 4's; this unit supplies
the named reducer whose Fusion produces the operations they read.
STORY: as a researcher, I read what every member said, and what the vote did with it, for a Case I
ran through ``sf.Client``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from _vote_run_fixtures import (
    ScriptedTransport,
    benchmark_resource,
    engine_handler,
    vote_case,
)

import screamingface as sf

_MEMBERS = ["provider/a", "provider/b", "provider/c"]
_MODELS = ("op_model_1", "op_model_2", "op_model_3")
_VOTE = sf.Vote(over="last_number", normalize="numeric")
_VOTE_TEXTS = ["The answer is 42", "no idea", "So 42"]


def _run(recipe: sf.Recipe, case: dict[str, Any]) -> sf.Report:
    transport = ScriptedTransport("draco", "fixture-revision", lambda _: [case])
    resources = {"draco": benchmark_resource("draco")}
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(engine_handler([], resources=resources)),
        run_transport=transport,
    ) as client:
        return client.evaluate(recipe, benchmark="draco", progress=False)


def _vote_report(*, models: tuple[str, ...] = ()) -> sf.Report:
    case = vote_case(
        _VOTE_TEXTS, "vote_one_failed", model_ops=_MODELS, output=_VOTE_TEXTS[0], models=models
    )
    return _run(sf.Fanout(_MEMBERS) >> _VOTE, case)


def test_case_answers_join_text_through_depends_on() -> None:
    report = _vote_report()

    operations = report.candidates[0].operations
    assert [operation.id for operation in operations] == [*_MODELS, "op_synthesis_1"]
    assert operations[-1].depends_on == _MODELS
    case = report.candidates[0].cases.by_id(1)
    assert case.operations is not None
    answers = case.answers()
    assert len(answers) == 4
    members, computed = answers[:3], answers[3]
    assert [answer.text for answer in members] == [op.output for op in case.operations[:3]]
    assert [answer.value for answer in members] == ["42", None, "42"]
    assert [answer.status for answer in members] == ["answered", "fail", "answered"]
    assert [answer.reason for answer in members] == [None, "empty", None]
    assert (computed.member_id, computed.value) == ("member_1", "42")
    assert computed.text == case.operations[3].output


def test_vote_trace_is_model_calls_then_extracts_then_reduce() -> None:
    report = _vote_report(models=tuple(_MEMBERS))

    case = report.candidates[0].cases.by_id(1)
    entries = [entry.to_dict() for entry in case.trace()]
    assert [entry["kind"] for entry in entries] == ["model_call"] * 3 + ["extract"] * 3 + ["reduce"]
    model_calls = entries[:3]
    assert [entry["member_id"] for entry in model_calls] == ["member_1", "member_2", "member_3"]
    assert [entry["model"] for entry in model_calls] == [
        "provider/a",
        "provider/b",
        "provider/c",
    ]
    extracts = entries[3:6]
    assert all(entry["rule"] == ["last_number@1", "numeric@1"] for entry in extracts)
    assert [entry["status"] for entry in extracts] == ["answered", "fail", "answered"]
    reduce = entries[6]
    assert reduce["op"] == "vote"
    assert reduce["rule"] == ["mode@1", "first_holder@1"]
    assert reduce["mode"] == "select"
    assert reduce["chosen"] == ["member_1"]
    assert reduce["result"] == {
        "member_id": "member_1",
        "value": "42",
        "status": "answered",
        "reason": None,
    }
    assert reduce["dropped"] == 1

    traced = report.trace_dict()
    assert traced["schema"] == "screamingface.report-trace.v1"
    first_case: Any = traced["candidates"][0]["cases"][0]  # type: ignore[index]
    assert first_case["entries"] == entries
    json.dumps(traced)
