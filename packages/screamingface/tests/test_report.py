from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

import screamingface as sf
from screamingface._evaluation.model import _compiled_operation


def case_results() -> tuple[sf.CaseResult, ...]:
    return tuple(
        sf.CaseResult(
            case_id=case_id,
            input=f"Question {case_id}",
            output=f"Answer {case_id}",
            finish_reason="stop",
            grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
            failures=(),
            metadata={},
        )
        for case_id in (1, 2)
    )


def benchmark() -> sf.BenchmarkInfo:
    return sf.BenchmarkInfo(
        id="draco",
        revision="fixture-revision",
        case_count=100,
    )


def candidate(
    name: str,
    *,
    url4: str | None = None,
    score: float | None = 0.5,
    cases: tuple[sf.CaseResult, ...] | None = None,
    failures: tuple[sf.Failure, ...] = (),
    usage: sf.Usage | None = None,
    trace_id: str | None = None,
) -> sf.CandidateResult:
    selected_cases = case_results() if cases is None else cases
    if score is None and cases is None:
        selected_cases = tuple(
            sf.CaseResult(
                case_id=case.case_id,
                input=case.input,
                output=case.output,
                finish_reason=case.finish_reason,
                grade=sf.CaseGrade(method="fixture", score=None, metrics={}, checks=()),
                failures=(
                    sf.Failure(
                        stage="grading",
                        code="fixture_ungraded",
                        message="the fixture Case could not be graded",
                        case_id=case.case_id,
                    ),
                ),
                metadata={},
            )
            for case in selected_cases
        )
    coverage = round(
        sum(case.grade is not None and case.grade.score is not None for case in selected_cases)
        / len(selected_cases),
        4,
    )
    return sf.CandidateResult(
        benchmark=benchmark(),
        run_id=f"run_{name}",
        started_at=datetime(2026, 7, 25, 16, 0, tzinfo=UTC),
        completed_at=datetime(2026, 7, 25, 16, 0, 1, 200000, tzinfo=UTC),
        name=name,
        kind="model",
        url4=url4 or f"(@)!'{name}'",
        models=(f"provider/{name}",),
        operations=(
            _compiled_operation(
                id=f"op_{name}",
                kind="model",
                label=f"{name} answer",
                depends_on=(),
            ),
            _compiled_operation(
                id=f"op_{name}_aggregate",
                kind="aggregation",
                label=f"{name} aggregation",
                depends_on=(f"op_{name}",),
            ),
        ),
        score=score,
        coverage=coverage,
        metrics={},
        cases=selected_cases,
        members=(),
        failures=failures,
        usage=usage or sf.Usage(input_tokens=100, output_tokens=20, cost_usd="0.12"),
        trace_id=trace_id,
    )


def report(*candidates: sf.CandidateResult) -> sf.Report:
    return sf.Report(
        benchmark=benchmark(),
        case_count=2,
        candidates=candidates,
    )


def test_report_has_one_ordered_candidate_collection_for_one_or_many_candidates() -> None:
    opus = candidate("opus")
    gpt = candidate("gpt")
    value = report(opus, gpt)

    assert tuple(value.candidates) == (opus, gpt)
    assert value.candidates[0] is opus
    assert value.candidates[-1] is gpt
    assert value.candidates["gpt"] is gpt
    assert value.candidates == (opus, gpt)
    assert repr(value.candidates).startswith("(")
    assert value.duration_ms == 1200

    with pytest.raises(ValueError, match="exactly one"):
        _ = value.candidates.only


def test_report_reuses_public_benchmark_info_and_records_the_selected_case_count() -> None:
    benchmark = sf.BenchmarkInfo(
        id="draco",
        revision="fixture-revision",
        case_count=100,
    )

    value = sf.Report(
        benchmark=benchmark,
        case_count=2,
        candidates=(candidate("opus"),),
    )

    assert value.benchmark is benchmark
    assert value.case_count == 2
    assert value.to_dict()["benchmark"] == {
        "id": "draco",
        "revision": "fixture-revision",
        "case_count": 2,
    }


def test_only_returns_the_single_candidate() -> None:
    opus = candidate("opus")

    assert report(opus).candidates.only is opus


def test_candidate_cases_keep_order_and_use_explicit_identity_lookup() -> None:
    first = case_results()[0]
    second = sf.CaseResult(
        status="scored",
        case_id="healthbench-case-2",
        input="Question two",
        output="Answer two",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
    )
    cases = candidate("opus", cases=(first, second)).cases

    assert cases[0] is first
    assert cases[1] is second
    assert cases.by_id(1) is first
    assert cases.by_id("healthbench-case-2") is second
    with pytest.raises(KeyError, match="unknown Case id"):
        cases.by_id("missing")


def test_report_json_and_export_preserve_refusal_and_failure_fields(tmp_path: Path) -> None:
    refused = sf.CaseResult(
        status="refused",
        case_id="refusal-case",
        input="A request",
        output=None,
        finish_reason="stop",
        refusal="I cannot comply.",
        grade=sf.CaseGrade(
            method="fixture",
            score=0.0,
            metrics={},
            checks=(),
        ),
        failures=(),
        metadata={},
    )
    failed = sf.CaseResult(
        status="failed",
        case_id=2,
        input="Another request",
        output=None,
        finish_reason=None,
        grade=None,
        failures=(
            sf.Failure(
                stage="candidate",
                code="provider_error",
                message="the provider was unavailable",
                retryable=True,
                case_id=2,
                metadata={},
            ),
        ),
        metadata={},
    )
    value = report(candidate("opus", score=0.0, cases=(refused, failed)))

    selected = value.export(tmp_path / "report.json")
    payload = json.loads(selected.read_text(encoding="utf-8"))
    exported_cases = payload["candidates"][0]["cases"]
    assert exported_cases[0]["status"] == "refused"
    assert exported_cases[0]["refusal"] == "I cannot comply."
    assert exported_cases[0]["grade"]["score"] == 0.0
    assert exported_cases[0]["failures"] == []
    assert exported_cases[1]["status"] == "failed"


def test_candidate_result_preserves_its_operation_map_in_portable_json() -> None:
    opus = candidate("opus")

    assert isinstance(opus.url4, sf.Url4)
    assert tuple(operation.id for operation in opus.operations) == (
        "op_opus",
        "op_opus_aggregate",
    )
    assert opus.to_dict()["operations"] == [
        {
            "id": "op_opus",
            "kind": "model",
            "label": "opus answer",
            "depends_on": [],
        },
        {
            "id": "op_opus_aggregate",
            "kind": "aggregation",
            "label": "opus aggregation",
            "depends_on": ["op_opus"],
        },
    ]


def test_candidate_result_rejects_a_non_url4_workflow() -> None:
    with pytest.raises(ValueError, match="Candidate URL4"):
        candidate("opus", url4="not a URL4 expression")


def test_report_derives_study_timing_and_complete_usage_from_candidate_runs() -> None:
    opus = candidate("opus")
    gpt = sf.CandidateResult(
        benchmark=benchmark(),
        run_id="run_gpt",
        started_at=datetime(2026, 7, 25, 15, 59, 59, tzinfo=UTC),
        completed_at=datetime(2026, 7, 25, 16, 0, 3, tzinfo=UTC),
        name="gpt",
        kind="model",
        url4="(@)!'gpt'",
        models=("provider/gpt",),
        operations=(
            _compiled_operation(
                id="op_gpt",
                kind="model",
                label="gpt answer",
                depends_on=(),
            ),
        ),
        score=0.5,
        coverage=1.0,
        metrics={},
        cases=case_results(),
        members=(),
        failures=(),
        usage=sf.Usage(input_tokens=50, output_tokens=None, cost_usd="0.03"),
    )

    value = report(opus, gpt)

    assert value.started_at == gpt.started_at
    assert value.completed_at == gpt.completed_at
    assert value.duration_ms == 4000
    assert value.usage.input_tokens == 150
    assert value.usage.output_tokens is None
    assert value.usage.cost_usd == Decimal("0.15")
    assert not hasattr(value, "run_id")
    assert not hasattr(value, "url4")


def test_report_flattens_candidate_failures_without_duplicating_them_on_the_wire() -> None:
    owned = sf.Failure(
        stage="candidate",
        code="gateway_timeout",
        message="The model timed out.",
        retryable=True,
        operation_id="op_opus",
        case_id=None,
    )
    value = report(candidate("opus", score=None, failures=(owned,)))

    assert value.ok is False
    assert value.failures.count(owned) == 1
    assert len(value.failures) == 3
    payload = value.to_dict()
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    candidate_payload = candidates[0]
    assert isinstance(candidate_payload, dict)
    assert "failures" not in payload
    assert candidate_payload["failures"] == [owned.to_dict()]


def test_report_is_not_ok_when_a_candidate_has_no_score_and_ungraded_cases() -> None:
    value = report(candidate("opus", score=None))

    assert len(value.failures) == 2
    assert value.ok is False


def test_failure_serializes_the_locked_domain_contract() -> None:
    failure = sf.Failure(
        stage="grading",
        code="judge_invalid_response",
        message="The judge returned an invalid verdict.",
        retryable=True,
        operation_id="op_grade_1",
        case_id="case-42",
    )

    assert failure.to_dict() == {
        "stage": "grading",
        "code": "judge_invalid_response",
        "message": "The judge returned an invalid verdict.",
        "retryable": True,
        "operation_id": "op_grade_1",
        "case_id": "case-42",
        "metadata": {},
    }


def test_scored_fusion_preserves_partial_member_failure_evidence() -> None:
    member_failure = sf.Failure(
        stage="candidate",
        code="gateway_timeout",
        message="One panel member timed out.",
        retryable=True,
        operation_id="op_panel_2",
        case_id="case-2",
    )
    value = sf.CandidateResult(
        benchmark=benchmark(),
        run_id="run_frontier_pair",
        started_at=datetime(2026, 7, 25, 16, 0, tzinfo=UTC),
        completed_at=datetime(2026, 7, 25, 16, 0, 2, tzinfo=UTC),
        name="frontier-pair",
        kind="fusion",
        url4="(@)!'frontier pair'",
        models=("provider/opus", "provider/gpt"),
        operations=(
            _compiled_operation(
                id="op_opus",
                kind="model",
                label="opus answer",
                depends_on=(),
            ),
            _compiled_operation(
                id="op_gpt",
                kind="model",
                label="gpt answer",
                depends_on=(),
            ),
            _compiled_operation(
                id="op_panel_2",
                kind="model_call",
                label="gpt failed attempt",
                depends_on=("op_gpt",),
            ),
            _compiled_operation(
                id="op_synthesis",
                kind="synthesis",
                label="frontier pair synthesis",
                depends_on=("op_opus", "op_gpt"),
            ),
        ),
        score=0.6,
        coverage=1.0,
        metrics={},
        cases=case_results(),
        members=(
            sf.MemberResult(
                operation_id="op_opus",
                name="opus",
                kind="model",
                models=("provider/opus",),
                failures=(),
                duration_ms=1200,
                usage=sf.Usage(input_tokens=100, output_tokens=20, cost_usd="0.12"),
            ),
            sf.MemberResult(
                operation_id="op_gpt",
                name="gpt",
                kind="model",
                models=("provider/gpt",),
                failures=(member_failure,),
                duration_ms=2000,
                usage=sf.Usage(input_tokens=100, output_tokens=0, cost_usd="0.03"),
            ),
        ),
        failures=(),
        usage=sf.Usage(input_tokens=200, output_tokens=20, cost_usd="0.15"),
    )

    result = report(value)

    assert result.candidates.only.score == 0.6
    assert result.failures == (member_failure,)
    assert result.ok is False
    payload = result.to_dict()
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    candidate_payload = candidates[0]
    assert isinstance(candidate_payload, dict)
    members = candidate_payload["members"]
    assert isinstance(members, list)
    failed_member = members[1]
    assert isinstance(failed_member, dict)
    assert failed_member["operation_id"] == "op_gpt"
    assert failed_member["failures"] == [member_failure.to_dict()]


def test_report_json_is_complete_portable_json_with_decimal_money_as_text() -> None:
    value = report(candidate("opus"))

    payload = json.loads(value.to_json())

    assert payload["schema"] == "screamingface.report.v1"
    assert payload["benchmark"]["id"] == "draco"
    assert payload["candidates"][0]["run_id"] == "run_opus"
    assert payload["candidates"][0]["name"] == "opus"
    assert payload["usage"]["cost_usd"] == "0.12"
    assert "ok" not in payload


def test_report_json_marks_unavailable_usage_fields_as_null() -> None:
    value = report(candidate("opus", usage=sf.Usage(input_tokens=100, output_tokens=20)))

    payload = json.loads(value.to_json())

    assert payload["usage"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_read_tokens": None,
        "cache_creation_tokens": None,
        "reasoning_tokens": None,
        "cost_usd": None,
    }


def test_report_export_writes_the_complete_json_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = report(candidate("opus"), candidate("gpt"))
    monkeypatch.chdir(tmp_path)

    default_path = value.export()
    nested_path = value.export(tmp_path / "runs" / "draco.JSON")
    default_path.write_text("stale", encoding="utf-8")
    repeated_path = value.export()

    assert default_path == Path("report.json")
    assert repeated_path == default_path
    assert default_path.read_text(encoding="utf-8") == value.to_json()
    assert nested_path == tmp_path / "runs" / "draco.JSON"
    assert nested_path.read_text(encoding="utf-8") == value.to_json()


def test_report_export_rejects_jsonl_for_one_aggregate_report(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\.json file"):
        report(candidate("opus")).export(tmp_path / "report.jsonl")


def test_report_treats_metrics_as_diagnostics_not_a_second_score() -> None:
    value = candidate("opus")
    inconsistent = sf.CandidateResult(
        benchmark=value.benchmark,
        run_id=value.run_id,
        started_at=value.started_at,
        completed_at=value.completed_at,
        name=value.name,
        kind=value.kind,
        url4=value.url4,
        models=value.models,
        operations=value.operations,
        score=0.7,
        coverage=1.0,
        metrics={"diagnostic": "retained"},
        cases=value.cases,
        members=(),
        failures=(),
        usage=sf.Usage(),
    )

    result = report(inconsistent)

    assert result.candidates.only.score == 0.7
    assert result.candidates.only.coverage == 1.0
    assert result.candidates.only.metrics == {"diagnostic": "retained"}


def test_candidate_names_must_be_unique() -> None:
    with pytest.raises(ValueError, match="duplicate Candidate name"):
        report(candidate("opus"), candidate("opus"))


@pytest.mark.parametrize("cost", ["nan", "-0.1", "Infinity"])
def test_usage_rejects_invalid_cost(cost: str) -> None:
    with pytest.raises(ValueError, match="cost_usd"):
        sf.Usage(cost_usd=cost)


def test_report_representation_is_a_compact_run_summary() -> None:
    value = report(candidate("opus"), candidate("gpt"))

    assert repr(value) == ("Report(benchmark='draco', candidates=['opus', 'gpt'], ok=True)")


def test_duplicate_member_display_names_do_not_fail_a_finished_run() -> None:
    # INVARIANT: fail-before-spend — Report construction happens AFTER the paid
    # evaluation, so a cosmetic display-name collision (same model via two
    # providers) must never raise here; members stay keyed by operation_id.
    value = sf.CandidateResult(
        benchmark=benchmark(),
        run_id="run_same_model_twice",
        started_at=datetime(2026, 7, 25, 16, 0, tzinfo=UTC),
        completed_at=datetime(2026, 7, 25, 16, 0, 2, tzinfo=UTC),
        name="gpt-5.5+gpt-5.5",
        kind="fusion",
        url4="(@)!'same model, two providers'",
        models=("openrouter/openai/gpt-5.5", "azure/openai/gpt-5.5", "provider/synth"),
        operations=(
            _compiled_operation(
                id="op_model_1", kind="model", label="gpt-5.5 answer", depends_on=()
            ),
            _compiled_operation(
                id="op_model_2", kind="model", label="gpt-5.5 answer", depends_on=()
            ),
            _compiled_operation(
                id="op_synthesis_1",
                kind="synthesis",
                label="gpt-5.5+gpt-5.5 synthesis",
                depends_on=("op_model_1", "op_model_2"),
            ),
        ),
        score=0.5,
        coverage=1.0,
        metrics={},
        cases=case_results(),
        members=(
            sf.MemberResult(
                operation_id="op_model_1",
                name="gpt-5.5",
                kind="model",
                models=("openrouter/openai/gpt-5.5",),
                failures=None,
                duration_ms=None,
                usage=None,
            ),
            sf.MemberResult(
                operation_id="op_model_2",
                name="gpt-5.5",
                kind="model",
                models=("azure/openai/gpt-5.5",),
                failures=None,
                duration_ms=None,
                usage=None,
            ),
        ),
        failures=(),
        usage=sf.Usage(input_tokens=200, output_tokens=20),
    )

    result = report(value)

    assert tuple(member.name for member in result.candidates.only.members) == (
        "gpt-5.5",
        "gpt-5.5",
    )

    with pytest.raises(ValueError, match="operation IDs must be unique"):
        sf.CandidateResult(
            **{
                **{
                    "benchmark": benchmark(),
                    "run_id": "run_same_model_twice",
                    "started_at": datetime(2026, 7, 25, 16, 0, tzinfo=UTC),
                    "completed_at": datetime(2026, 7, 25, 16, 0, 2, tzinfo=UTC),
                    "name": "gpt-5.5+gpt-5.5",
                    "kind": "fusion",
                    "url4": "(@)!'same model, two providers'",
                    "models": ("openrouter/openai/gpt-5.5", "provider/synth"),
                    "operations": (
                        _compiled_operation(
                            id="op_model_1", kind="model", label="a", depends_on=()
                        ),
                    ),
                    "score": 0.5,
                    "coverage": 1.0,
                    "metrics": {},
                    "cases": case_results(),
                    "members": tuple(
                        sf.MemberResult(
                            operation_id="op_model_1",
                            name="gpt-5.5",
                            kind="model",
                            models=("openrouter/openai/gpt-5.5",),
                            failures=None,
                            duration_ms=None,
                            usage=None,
                        )
                        for _ in range(2)
                    ),
                    "failures": (),
                    "usage": sf.Usage(),
                }
            }
        )


def test_candidate_export_preserves_full_benchmark_size_beside_report_selection() -> None:
    value = report(candidate("opus"))

    payload = value.to_dict()

    assert payload["benchmark"] == {
        "id": "draco",
        "revision": "fixture-revision",
        "case_count": 2,
    }
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    candidate_payload = candidates[0]
    assert isinstance(candidate_payload, dict)
    assert candidate_payload["benchmark"] == {
        "id": "draco",
        "revision": "fixture-revision",
        "case_count": 100,
    }


# --- the run's trace id on the public result (OME-1121) -----------------------------------


def _outcome_for_trace(trace_id: str | None):
    """A minimal `_RunOutcome` carrying whatever the transport stamped."""
    from screamingface._core.ports import _RunOutcome

    return _RunOutcome(
        run_id="run-1",
        started_at=datetime(2026, 9, 4, tzinfo=UTC),
        completed_at=datetime(2026, 9, 4, tzinfo=UTC),
        result_body=None,
        media_type=None,
        root_usage=None,
        trace_id=trace_id,
    )


def test_a_candidate_result_carries_the_trace_id_of_the_run_that_produced_it() -> None:
    # INVARIANT (OME-1121): one run, one trace id, stored beside the `run_id` that already
    # identifies that run. A Report may hold several candidates, each an independently
    # executed run with its own client-minted trace — so this cannot live on Report.
    result = candidate("model", trace_id="4bf92f3577b34da6a3ce929d0e0e4736")

    assert result.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_two_candidates_in_one_report_keep_their_own_trace_ids() -> None:
    # WHY this test exists: it is the reason `trace_id` is NOT a Report attribute. Two
    # candidates are two independent runs; a single Report-level id would have to pick one.
    first = candidate("a", trace_id="a" * 32)
    second = candidate("b", trace_id="b" * 32)

    built = report(first, second)

    assert [c.trace_id for c in built.candidates] == ["a" * 32, "b" * 32]


def test_a_run_without_a_trace_id_reports_none_rather_than_raising() -> None:
    # WHY nullable (OME-1121): `_RunOutcome.trace_id` is `str | None`, and a Report decoded
    # from a stored url4 replay has no live run behind it. Forcing a value would mean
    # inventing one, and an invented id joins to nothing.
    assert _outcome_for_trace(None).trace_id is None
