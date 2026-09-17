"""The pure report→EvalLog payload mapping (OME-1117).

Mental model: a translator, not a runtime — these tests pin the exact JSON-safe
document we hand to inspect's own `EvalLog.model_validate`, without inspect
installed. The shapes asserted here were verified live against the pinned
`inspect-ai==0.3.263` (see the OME-1117 spec §1 probe notes).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

import screamingface as sf
from screamingface._evaluation.model import _compiled_operation
from screamingface._inspect_log.payload import eval_log_payload


def _case(
    case_id: int,
    *,
    input_text: str | None = None,
    output: str | None = "Answer",
    score: float | None = 1.0,
    finish_reason: str | None = "stop",
    refusal: str | None = None,
    failures: tuple[sf.Failure, ...] = (),
) -> sf.CaseResult:
    grade = sf.CaseGrade(method="fixture", score=score, metrics={}, checks=())
    return sf.CaseResult(
        case_id=case_id,
        input=input_text or f"Question {case_id}",
        output=output,
        finish_reason=finish_reason,
        refusal=refusal,
        grade=grade,
        failures=failures,
        metadata={},
    )


def _failed_case(case_id: int) -> sf.CaseResult:
    return sf.CaseResult(
        case_id=case_id,
        input=f"Question {case_id}",
        output=None,
        finish_reason=None,
        grade=sf.CaseGrade(method="fixture", score=None, metrics={}, checks=()),
        failures=(
            sf.Failure(
                stage="candidate",
                code="provider_timeout",
                message="the provider timed out",
                case_id=case_id,
            ),
        ),
        metadata={},
    )


def _benchmark() -> sf.BenchmarkInfo:
    return sf.BenchmarkInfo(id="draco", revision="fixture-revision", case_count=100)


def _candidate(
    name: str,
    *,
    cases: tuple[sf.CaseResult, ...],
    score: float | None = 0.5,
    usage: sf.Usage | None = None,
    answer_seed: int | None = None,
) -> sf.CandidateResult:
    coverage = round(
        sum(case.grade is not None and case.grade.score is not None for case in cases) / len(cases),
        4,
    )
    return sf.CandidateResult(
        benchmark=_benchmark(),
        run_id=f"run_{name}",
        started_at=datetime(2026, 9, 16, 8, 0, tzinfo=UTC),
        completed_at=datetime(2026, 9, 16, 8, 5, tzinfo=UTC),
        name=name,
        kind="model",
        url4=f"(@)!'{name}'",
        models=(f"provider/{name}",),
        operations=(
            _compiled_operation(id=f"op_{name}", kind="model", label=name, depends_on=()),
            _compiled_operation(
                id=f"op_{name}_aggregate",
                kind="aggregation",
                label="aggregate",
                depends_on=(f"op_{name}",),
            ),
        ),
        score=score,
        coverage=coverage,
        metrics={},
        cases=cases,
        members=(),
        failures=(),
        usage=usage or sf.Usage(input_tokens=100, output_tokens=20, cost_usd="0.12"),
        answer_seed=answer_seed,
    )


def _report(*candidates: sf.CandidateResult, case_count: int = 2) -> sf.Report:
    return sf.Report(benchmark=_benchmark(), case_count=case_count, candidates=candidates)


def _payload(**kwargs: Any) -> dict[str, Any]:
    cases = (_case(1), _case(2, score=0.0, output="Wrong"))
    value = _report(_candidate("opus", cases=cases, **kwargs))
    return eval_log_payload(value)


def test_payload_is_json_serializable_and_carries_the_document_frame() -> None:
    # INVARIANT: the payload is plain JSON data — it must cross into
    # EvalLog.model_validate without any inspect types on our side.
    payload = _payload()
    json.dumps(payload)
    assert payload["version"] == 2
    assert payload["status"] == "success"
    assert set(payload) == {"version", "status", "eval", "results", "stats", "samples"}


def test_spec_names_the_benchmark_task_and_selected_dataset_size() -> None:
    payload = _payload()
    spec = payload["eval"]
    assert spec["task"] == "draco"
    # WHY the SELECTED size: the report root's case_count convention — a limited
    # run must stay recognisably partial in the exported log too.
    assert spec["dataset"] == {"name": "draco", "samples": 2}
    assert spec["model"] == "opus"
    assert spec["created"] == "2026-09-16T08:00:00Z"
    assert spec["tags"] == ["screamingface-export"]


def test_provenance_metadata_stamps_the_exporter_not_the_board() -> None:
    # INVARIANT (Don't regress): one-way export — the log names US as producer
    # and carries no expression_sha, so nothing in the leaderboard path can
    # mistake it for a submission source.
    metadata = _payload()["eval"]["metadata"]
    assert metadata["produced_by"] == "ScreamingFace engine"
    assert metadata["source_schema"] == "screamingface.report.v1"
    assert metadata["one_way_export"] is True
    assert metadata["benchmark_revision"] == "fixture-revision"
    assert metadata["run_id"] == "run_opus"
    assert metadata["recipe_kind"] == "model"
    assert metadata["recipe_url4"] == "(@)!'opus'"
    assert metadata["cost_usd"] == "0.12"
    assert "expression_sha" not in json.dumps(_payload())


def test_answer_seed_rides_the_provenance_block() -> None:
    assert _payload(answer_seed=7)["eval"]["metadata"]["answer_seed"] == 7
    assert _payload()["eval"]["metadata"]["answer_seed"] is None


def test_samples_map_case_identity_input_output_and_score() -> None:
    samples = _payload()["samples"]
    assert [sample["id"] for sample in samples] == [1, 2]
    assert all(sample["epoch"] == 1 for sample in samples)
    first = samples[0]
    assert first["input"] == "Question 1"
    # WHY empty target: the client never holds gold answers — grading already
    # happened engine-side, so the truth of the sample lives in its score.
    assert first["target"] == ""
    assert first["output"]["model"] == "opus"
    assert first["output"]["choices"][0]["message"]["content"] == "Answer"
    assert first["scores"]["screamingface"]["value"] == 1.0
    assert samples[1]["scores"]["screamingface"]["value"] == 0.0


def test_multi_turn_envelope_input_becomes_chat_messages() -> None:
    envelope = json.dumps(
        {
            "schema": "screamingface.candidate-input.v1",
            "messages": [
                {"role": "system", "content": "Be brief."},
                {"role": "user", "content": "What is 2+2?"},
            ],
        }
    )
    cases = (_case(1, input_text=envelope), _case(2))
    payload = eval_log_payload(_report(_candidate("opus", cases=cases)))
    assert payload["samples"][0]["input"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "What is 2+2?"},
    ]
    # Plain text stays a plain string — the decoder is the SDK's one decode point.
    assert payload["samples"][1]["input"] == "Question 2"


def test_failed_case_keeps_failures_in_metadata_and_omits_output_and_scores() -> None:
    cases = (_case(1), _failed_case(2))
    payload = eval_log_payload(_report(_candidate("opus", cases=cases, score=0.5)))
    failed = payload["samples"][1]
    assert "output" not in failed
    assert "scores" not in failed
    assert failed["metadata"]["status"] == "failed"
    failure = failed["metadata"]["failures"][0]
    assert failure["stage"] == "candidate"
    assert failure["code"] == "provider_timeout"


def test_graded_refusal_rides_metadata_and_becomes_the_scored_answer() -> None:
    # INVARIANT (OME-1037): a scored Case carries exactly ONE of output/refusal —
    # a graded refusal is an ordinary scored Case whose answer is the refusal text.
    cases = (
        _case(
            1,
            output=None,
            refusal="I cannot answer that.",
            finish_reason="content_filter",
            score=1.0,
        ),
        _case(2),
    )
    sample = eval_log_payload(_report(_candidate("opus", cases=cases)))["samples"][0]
    assert sample["metadata"]["refusal"] == "I cannot answer that."
    assert sample["metadata"]["finish_reason"] == "content_filter"
    assert "output" not in sample
    assert sample["scores"]["screamingface"]["answer"] == "I cannot answer that."


def test_finish_reason_translates_to_inspect_stop_reason_vocabulary() -> None:
    cases = (
        _case(1, finish_reason="length"),
        _case(2, finish_reason="weird_provider_word"),
    )
    samples = eval_log_payload(_report(_candidate("opus", cases=cases)))["samples"]
    assert samples[0]["output"]["choices"][0]["stop_reason"] == "max_tokens"
    assert samples[1]["output"]["choices"][0]["stop_reason"] == "unknown"


def test_results_carry_candidate_score_and_coverage_as_metrics() -> None:
    results = _payload()["results"]
    assert results["total_samples"] == 2
    assert results["completed_samples"] == 2
    (score_block,) = results["scores"]
    assert score_block["name"] == "screamingface"
    assert score_block["scorer"] == "screamingface"
    assert score_block["metrics"]["score"] == {"name": "score", "value": 0.5}
    assert score_block["metrics"]["coverage"] == {"name": "coverage", "value": 1.0}


def test_unscored_candidate_exports_as_error_status_with_coverage_only() -> None:
    cases = (_failed_case(1), _failed_case(2))
    payload = eval_log_payload(_report(_candidate("opus", cases=cases, score=None)))
    assert payload["status"] == "error"
    (score_block,) = payload["results"]["scores"]
    assert score_block["metrics"] == {"coverage": {"name": "coverage", "value": 0.0}}
    assert payload["results"]["completed_samples"] == 0


def test_stats_pass_the_metered_cost_through_untouched() -> None:
    # INVARIANT: reported cost IS the gateway meter, passed through — never
    # recomputed, never fabricated.
    stats = _payload()["stats"]
    assert stats["started_at"] == "2026-09-16T08:00:00Z"
    assert stats["completed_at"] == "2026-09-16T08:05:00Z"
    usage = stats["model_usage"]["opus"]
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 20
    assert usage["total_tokens"] == 120
    assert usage["total_cost"] == 0.12


def test_unpriced_usage_never_fabricates_a_cost() -> None:
    unpriced = sf.Usage(input_tokens=100, output_tokens=20, cost_usd=None)
    cases = (_case(1), _case(2))
    payload = eval_log_payload(_report(_candidate("opus", cases=cases, usage=unpriced)))
    assert "total_cost" not in payload["stats"]["model_usage"]["opus"]
    assert payload["eval"]["metadata"]["cost_usd"] is None


def test_single_candidate_report_needs_no_selector() -> None:
    cases = (_case(1), _case(2))
    value = _report(_candidate("opus", cases=cases))
    assert eval_log_payload(value)["eval"]["model"] == "opus"
    assert eval_log_payload(value, candidate="opus")["eval"]["model"] == "opus"


def test_multi_candidate_report_requires_a_named_candidate() -> None:
    cases = (_case(1), _case(2))
    value = _report(_candidate("opus", cases=cases), _candidate("gpt", cases=cases))
    with pytest.raises(ValueError, match="opus.*gpt|gpt.*opus"):
        eval_log_payload(value)
    assert eval_log_payload(value, candidate="gpt")["eval"]["model"] == "gpt"


def test_unknown_candidate_name_fails_loudly() -> None:
    cases = (_case(1), _case(2))
    value = _report(_candidate("opus", cases=cases))
    with pytest.raises(ValueError, match="nope"):
        eval_log_payload(value, candidate="nope")


def test_member_usage_rides_metadata_so_the_meter_is_never_double_counted() -> None:
    # INVARIANT: stats.model_usage carries the gateway meter EXACTLY ONCE —
    # inspect's viewer SUMS that map, so member rows there would display an
    # inflated total (aggregate + members). The per-member breakdown is
    # provenance, so it rides eval.metadata, which nothing sums.
    full_usage = sf.Usage(
        input_tokens=10,
        output_tokens=5,
        cache_read_tokens=3,
        cache_creation_tokens=2,
        reasoning_tokens=1,
        cost_usd="0.05",
    )
    members = tuple(
        sf.MemberResult(
            operation_id=f"op_m{index}",
            name="haiku",
            kind="model",
            models=("provider/haiku",),
            failures=(),
            duration_ms=100,
            usage=full_usage,
        )
        for index in (1, 2)
    )
    cases = (_case(1), _case(2))
    fusion = sf.CandidateResult(
        benchmark=_benchmark(),
        run_id="run_fusion",
        started_at=datetime(2026, 9, 16, 8, 0, tzinfo=UTC),
        completed_at=datetime(2026, 9, 16, 8, 5, tzinfo=UTC),
        name="fusion",
        kind="fusion",
        url4="(@)!'fusion'",
        models=("provider/haiku",),
        operations=(
            _compiled_operation(id="op_m1", kind="model", label="haiku", depends_on=()),
            _compiled_operation(id="op_m2", kind="model", label="haiku", depends_on=()),
            _compiled_operation(
                id="op_agg", kind="aggregation", label="agg", depends_on=("op_m1", "op_m2")
            ),
        ),
        score=0.5,
        coverage=1.0,
        metrics={},
        cases=cases,
        members=members,
        failures=(),
        usage=sf.Usage(input_tokens=100, output_tokens=20, cost_usd="0.12"),
    )
    payload = eval_log_payload(_report(fusion))
    model_usage = payload["stats"]["model_usage"]
    # The meter appears once: summing this map yields the run's real cost.
    assert set(model_usage) == {"fusion"}
    assert model_usage["fusion"]["total_cost"] == 0.12
    member_usage = payload["eval"]["metadata"]["member_usage"]
    assert [entry["operation_id"] for entry in member_usage] == ["op_m1", "op_m2"]
    assert all(entry["name"] == "haiku" for entry in member_usage)
    row = member_usage[0]["usage"]
    assert row["input_tokens_cache_read"] == 3
    assert row["input_tokens_cache_write"] == 2
    assert row["reasoning_tokens"] == 1
    assert row["total_cost"] == 0.05
