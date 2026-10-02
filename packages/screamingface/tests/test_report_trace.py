"""The per-Case trace and screamingface.report-trace.v1 (OME-1289 gap, RT#5-15, RT#17).

STORY: as a researcher, I read what every block did for one Case, in order: the model calls, what
was extracted from each member, and how the reduce step decided, without any member text.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _answer_fixtures import bound, evidence_cases, evidence_wires, fixture_case, fixture_graph
from _reducer_fixtures import evidence_wire
from test_combine_evidence import _judge_variant

import screamingface as sf
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface.case_result import CaseOperation
from screamingface.combine_evidence import CombineEvidence
from screamingface.operation import OperationInfo
from screamingface.operation_accounting import OperationAccounting, OperationCache
from screamingface.report import TraceEntry
from screamingface.report_trace import TRACE_FIELDS, TRACE_SCHEMA


def _accounting(cache: OperationCache | None = None) -> OperationAccounting:
    return OperationAccounting(
        provider="provider",
        request_model="provider/opus",
        response_model="provider/opus",
        usage=sf.Usage(input_tokens=10, output_tokens=4, cost_usd="0.002"),
        provider_latency_ms=30,
        provider_attempts=1,
        cache=cache or OperationCache(hits=0, misses=1, bypasses=0, unknown=0),
    )


def _kinds(case: sf.CaseResult) -> list[str]:
    return [entry.kind for entry in case.trace()]


def _entry_dicts(case: sf.CaseResult, kind: str) -> list[dict[str, Any]]:
    return [entry.to_dict() for entry in case.trace() if entry.kind == kind]


def test_model_call_entry_carries_accounting() -> None:
    case = bound(fixture_case("vote_one_failed", accounting=_accounting()), fixture_graph(3))

    first = _entry_dicts(case, "model_call")[0]
    assert first == {
        "kind": "model_call",
        "operation_id": "op_model_1",
        "member_id": "member_1",
        "provider": "provider",
        "model": "provider/opus",
        "cache": "miss",
        "cost_usd": "0.002",
        "latency_ms": 30,
        "tokens_in": 10,
        "tokens_out": 4,
        "status": "completed",
    }
    bare = bound(fixture_case("vote_one_failed"), fixture_graph(3))
    assert _entry_dicts(bare, "model_call")[0] == {
        "kind": "model_call",
        "operation_id": "op_model_1",
        "member_id": "member_1",
        "provider": None,
        "model": None,
        "cache": "unknown",
        "cost_usd": None,
        "latency_ms": None,
        "tokens_in": None,
        "tokens_out": None,
        "status": "completed",
    }
    missing = bound(
        fixture_case("vote_one_failed", outputs=["text 1", None, "text 3"]), fixture_graph(3)
    )
    assert _entry_dicts(missing, "model_call")[1]["status"] == "unattributed"


def test_reduce_entry_carries_tally_chosen_signal_result() -> None:
    wire = evidence_wires()["vote_field_signal"]
    case = bound(fixture_case("vote_field_signal"), fixture_graph(3))

    reduce_entry = _entry_dicts(case, "reduce")[0]
    assert reduce_entry["op"] == "vote"
    assert reduce_entry["rule"] == ["weighted_mode@1", "max_weight_holder@1"]
    assert reduce_entry["mode"] == "select"
    assert reduce_entry["tally"] == wire["tally"]
    assert reduce_entry["chosen"] == ["member_1"]
    assert reduce_entry["signal"] == {
        "key": "field:confidence",
        "order": None,
        "values": {"member_1": 0.9, "member_2": 0.3, "member_3": 0.4},
    }
    assert reduce_entry["result"] == wire["result"]
    assert reduce_entry["dropped"] == 0
    assert list(reduce_entry) == ["kind", *TRACE_FIELDS["reduce"]]
    extracts = _entry_dicts(case, "extract")
    assert [e["member_id"] for e in extracts] == ["member_1", "member_2", "member_3"]
    assert extracts[0]["rule"] == ["json_field@1", "text@1"]
    assert extracts[0]["raw"] == "A"
    assert (extracts[0]["status"], extracts[0]["reason"]) == ("answered", None)
    compute = bound(fixture_case("median_value"), fixture_graph(4))
    assert _entry_dicts(compute, "reduce")[0]["mode"] == "compute"
    select = bound(fixture_case("median_nearest"), fixture_graph(4))
    assert _entry_dicts(select, "reduce")[0]["mode"] == "select"
    assert _entry_dicts(select, "reduce")[0]["signal"] is None


def _candidate(name: str, run: str) -> sf.CandidateResult:
    from test_report import candidate

    base = candidate(name)
    cases = (
        fixture_case("vote_one_failed", case_id=1),
        fixture_case("median_nearest", case_id=2),
    )
    return sf.CandidateResult(
        benchmark=base.benchmark,
        run_id=run,
        started_at=base.started_at,
        completed_at=base.completed_at,
        name=name,
        kind=base.kind,
        url4=base.url4,
        models=base.models,
        operations=fixture_graph(4),
        score=1.0,
        coverage=1.0,
        metrics={},
        cases=cases,
        members=(),
        failures=(),
        usage=base.usage,
    )


def test_trace_dict_emits_report_trace_v1_per_candidate_and_case() -> None:
    first, second = _candidate("opus", "run_1"), _candidate("gpt", "run_2")
    report = sf.Report(benchmark=first.benchmark, case_count=2, candidates=(first, second))

    value: Any = report.trace_dict()

    assert value["schema"] == TRACE_SCHEMA == "screamingface.report-trace.v1"
    candidates = value["candidates"]
    assert [c["candidate"] for c in candidates] == ["opus", "gpt"]
    assert [case["case_id"] for case in candidates[0]["cases"]] == [1, 2]
    assert all(
        isinstance(case["entries"], list) and case["entries"]
        for c in candidates
        for case in c["cases"]
    )
    json.dumps(value)
    assert candidates[0]["cases"][0]["entries"][0]["kind"] == "model_call"
    # the trace never changes the Report bytes
    before = report.to_json()
    report.trace_dict()
    assert report.to_json() == before


def test_trace_entry_has_a_closed_set_of_kinds_and_fields() -> None:
    with pytest.raises(ValueError, match=r"report-trace\.v2"):
        TraceEntry("branch", {})  # type: ignore[arg-type]
    budget = TraceEntry("budget", dict.fromkeys(TRACE_FIELDS["budget"]))
    assert list(budget.to_dict()) == ["kind", *TRACE_FIELDS["budget"]]
    with pytest.raises(ValueError, match="fields"):
        TraceEntry("budget", {"event": "x"})
    with pytest.raises(ValueError, match="fields"):
        TraceEntry("extract", {**dict.fromkeys(TRACE_FIELDS["extract"]), "extra": 1})
    with pytest.raises(TypeError):
        TraceEntry("extract", {**dict.fromkeys(TRACE_FIELDS["extract"]), "raw": object()})
    with pytest.raises(TypeError):
        budget.data["event"] = "x"  # type: ignore[index]


def test_failed_case_trace_is_empty() -> None:
    failed = sf.CaseResult(
        case_id=9,
        input="q",
        output=None,
        finish_reason=None,
        grade=None,
        failures=(
            sf.Failure(stage="candidate", code="candidate_failed", message="failed", case_id=9),
        ),
        metadata={},
    )

    assert failed.trace() == ()
    assert failed.answers() == ()


def test_pre_e4a_engine_case_traces_model_calls_only() -> None:
    operations = [CaseOperation(f"op_model_{k}", f"text {k}", "stop") for k in (1, 2, 3)]
    operations.append(CaseOperation("op_synthesis_1", "42", "stop"))
    case = bound(_case(operations), fixture_graph(3))

    assert _kinds(case) == ["model_call"] * 3


def _case(operations: list[CaseOperation]) -> sf.CaseResult:
    return sf.CaseResult(
        case_id=1,
        input="Question",
        output="x",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
        operations=operations,
    )


def _evidence(wire: dict[str, Any]) -> CombineEvidence:
    value = decode_combine_evidence(wire, "Case Operation combine")
    assert value is not None
    return value


def _info(op_id: str, kind: str, *depends: str) -> OperationInfo:
    return OperationInfo(id=op_id, kind=kind, label=op_id, depends_on=depends)


def _model(op_id: str) -> CaseOperation:
    return CaseOperation(op_id, f"text of {op_id}", "stop", _accounting())


def _member_ids(case: sf.CaseResult) -> dict[str, Any]:
    return {e["operation_id"]: e["member_id"] for e in _entry_dicts(case, "model_call")}


def test_nested_pipeline_of_fusions_traces_two_groups_in_order() -> None:
    operations = [
        *(_model(f"op_model_{k}") for k in (1, 2, 3)),
        CaseOperation("op_synthesis_1", "42", "stop", combine=evidence_cases()["vote_one_failed"]),
        *(_model(f"op_model_{k}") for k in (4, 5)),
        CaseOperation("op_synthesis_2", "12", "stop", combine=_evidence(evidence_wire(2))),
    ]
    graph = (
        *(_info(f"op_model_{k}", "model") for k in (1, 2, 3)),
        _info("op_synthesis_1", "combine", "op_model_1", "op_model_2", "op_model_3"),
        _info("op_model_4", "model", "op_synthesis_1"),
        _info("op_model_5", "model", "op_synthesis_1"),
        _info("op_synthesis_2", "combine", "op_model_4", "op_model_5"),
    )
    case = bound(_case(operations), graph)

    assert _kinds(case) == (
        ["model_call"] * 3
        + ["extract"] * 3
        + ["reduce"]
        + ["model_call"] * 2
        + ["extract"] * 2
        + ["reduce"]
    )
    assert _member_ids(case) == {
        "op_model_1": "member_1",
        "op_model_2": "member_2",
        "op_model_3": "member_3",
        "op_model_4": "member_1",
        "op_model_5": "member_2",
    }
    assert [e["operation_id"] for e in _entry_dicts(case, "reduce")] == [
        "op_synthesis_1",
        "op_synthesis_2",
    ]


def test_judge_calls_trace_before_reduce() -> None:
    operations = [
        *(_model(f"op_model_{k}") for k in (1, 2, 3)),
        _model("op_judge_1"),
        CaseOperation("op_synthesis_1", "12", "stop", combine=_evidence(_judge_variant())),
    ]
    graph = (
        *(_info(f"op_model_{k}", "model") for k in (1, 2, 3)),
        _info("op_judge_1", "judge", "op_model_1", "op_model_2", "op_model_3"),
        _info("op_synthesis_1", "combine", "op_model_1", "op_model_2", "op_model_3", "op_judge_1"),
    )
    case = bound(_case(operations), graph)

    assert _kinds(case) == ["model_call"] * 4 + ["extract"] * 3 + ["reduce"]
    calls = _entry_dicts(case, "model_call")
    assert calls[3]["operation_id"] == "op_judge_1"
    assert calls[3]["member_id"] is None
    assert _entry_dicts(case, "reduce")[0]["op"] == "judge"


def test_abstained_reduce_entry_shows_abstain_result() -> None:
    case = bound(fixture_case("vote_abstain"), fixture_graph(3))

    reduce_entry = _entry_dicts(case, "reduce")[0]
    assert reduce_entry["result"]["status"] == "abstain"
    assert reduce_entry["result"]["reason"] == "no_votes"
    assert reduce_entry["chosen"] == []
    assert reduce_entry["mode"] == "select"
    assert reduce_entry["dropped"] == 3


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ((1, 0, 0, 0), "hit"),
        ((2, 0, 0, 1), "hit"),
        ((1, 1, 0, 0), "miss"),
        ((0, 1, 1, 0), "miss"),
        ((0, 0, 1, 0), "bypass"),
        ((1, 0, 1, 0), "bypass"),
        ((0, 0, 0, 1), "unknown"),
    ],
)
def test_cache_value_follows_count_rule(counts: tuple[int, int, int, int], expected: str) -> None:
    hits, misses, bypasses, unknown = counts
    cache = OperationCache(hits=hits, misses=misses, bypasses=bypasses, unknown=unknown)
    case = bound(fixture_case("vote_one_failed", accounting=_accounting(cache)), fixture_graph(3))

    assert _entry_dicts(case, "model_call")[0]["cache"] == expected


def test_trace_holds_no_member_text() -> None:
    outputs = [f"I worked it out. The number is 42 SENTINEL-{k}" for k in (1, 2, 3)]
    case = bound(fixture_case("vote_one_failed", outputs=outputs), fixture_graph(3))
    base = _candidate("opus", "run_1")
    result = sf.CandidateResult(
        benchmark=base.benchmark,
        run_id="run_s",
        started_at=base.started_at,
        completed_at=base.completed_at,
        name="opus",
        kind=base.kind,
        url4=base.url4,
        models=base.models,
        operations=fixture_graph(3),
        score=1.0,
        coverage=1.0,
        metrics={},
        cases=(case,),
        members=(),
        failures=(),
        usage=base.usage,
    )
    report = sf.Report(benchmark=result.benchmark, case_count=1, candidates=(result,))

    assert "SENTINEL" not in json.dumps(report.trace_dict())
    assert "SENTINEL" in json.dumps(report.to_dict())  # the Case itself still holds the text


def test_pipeline_member_earlier_stages_carry_member_id() -> None:
    def case_of(graph: tuple[OperationInfo, ...], evidence: CombineEvidence) -> sf.CaseResult:
        ops = [_model(info.id) for info in graph if info.kind != "combine"]
        ops.append(CaseOperation("op_synthesis_1", "12", "stop", combine=evidence))
        return bound(_case(ops), graph)

    # Fusion([Pipeline([a, b]), c, d]): a and b belong to member 1
    nested = (
        _info("op_a", "model"),
        _info("op_b", "model", "op_a"),
        _info("op_c", "model"),
        _info("op_d", "model"),
        _info("op_synthesis_1", "combine", "op_b", "op_c", "op_d"),
    )
    labelled = _member_ids(case_of(nested, _evidence(evidence_wire(3))))
    assert labelled == {
        "op_a": "member_1",
        "op_b": "member_1",
        "op_c": "member_2",
        "op_d": "member_3",
    }

    # Pipeline([Model x, Fusion([a, b, c], R)]): x feeds every member, so it has no label
    shared = (
        _info("op_x", "model"),
        _info("op_a", "model", "op_x"),
        _info("op_b", "model", "op_x"),
        _info("op_c", "model", "op_x"),
        _info("op_synthesis_1", "combine", "op_a", "op_b", "op_c"),
    )
    labelled = _member_ids(case_of(shared, _evidence(evidence_wire(3))))
    assert labelled == {"op_x": None, "op_a": "member_1", "op_b": "member_2", "op_c": "member_3"}

    # one member: only its producer is labelled
    single = (
        _info("op_u", "model"),
        _info("op_p", "model", "op_u"),
        _info("op_synthesis_1", "combine", "op_p"),
    )
    labelled = _member_ids(case_of(single, _evidence(evidence_wire(1))))
    assert labelled == {"op_u": None, "op_p": "member_1"}


def test_unbound_case_labels_no_member() -> None:
    case = fixture_case("vote_one_failed")

    assert {e["member_id"] for e in _entry_dicts(case, "model_call")} == {None}
    assert _kinds(case).count("reduce") == 1
