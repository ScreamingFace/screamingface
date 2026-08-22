"""The IFEval cross-row reducer — check records in, `CandidateResult` out."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.ifeval.aggregate import (
    SCHEMA,
    AggregateError,
    aggregate,
    grade_case,
    load_specs,
    score_cases,
    selected_cases,
)
from screamingface_engine.benchmarks.ifeval.case_evaluation import (
    CASE_EVALUATION_SCHEMA,
    bind_case_evaluation,
)
from screamingface_engine.benchmarks.ifeval.definition import REVISION as IFEVAL_REVISION

_SPECS = {
    1: {
        "key": 1000,
        "prompt": "No commas; at least five words.",
        "instruction_id_list": [
            "punctuation:no_comma",
            "length_constraints:number_words",
        ],
        "kwargs": [{}, {"relation": "at least", "num_words": 5}],
    },
    2: {
        "key": 1001,
        "prompt": "Wrap the answer in quotes.",
        "instruction_id_list": ["startend:quotation"],
        "kwargs": [{}],
    },
}

# The installed selection order (cases.json file order) — row N is graded against
# _ORDER[N], never against sorted spec ids.
_ORDER = [1, 2]


def _record(case_id: int, strict: list[bool], loose: list[bool]) -> dict[str, object]:
    spec = _SPECS[case_id]
    return {
        "schema": SCHEMA,
        "case_id": case_id,
        "attempt": 1,
        "valid": True,
        "status": "completed",
        "answer": f"Answer {case_id}",
        "refusal": None,
        "finish_reason": "stop",
        "execution": None,
        "instruction_id_list": spec["instruction_id_list"],
        "descriptions": [
            f"Instruction {index}" for index in range(1, len(spec["instruction_id_list"]) + 1)
        ],
        "strict": strict,
        "loose": loose,
        "violations": [],
    }


def _rows(*rows: object) -> str:
    return json.dumps(list(rows))


def _evaluation(case_id: int, strict: list[bool], loose: list[bool]) -> dict[str, object]:
    return _case_execution(
        case_id,
        bind_case_evaluation(case_id, [_record(case_id, strict, loose)]),
    )


def _case_execution(case_id: int, grading: object) -> dict[str, object]:
    return case_execution_payload(
        case_id,
        encode_candidate_invocation(f"Answer {case_id}", "stop", None),
        [grading],
    )


def test_paper_metrics_are_computed_across_cases_and_instructions() -> None:
    # case 1: one of two instructions followed → prompt-level fail, inst-level 1/2.
    # case 2: followed → prompt-level pass, inst-level 1/1.
    payload = _rows(
        _evaluation(1, [True, False], [True, True]),
        _evaluation(2, [True], [True]),
    )

    result = aggregate(payload, _SPECS, "ifeval", _ORDER, selected_case_count=2)

    # INVARIANT: `score` IS the paper's headline metric, prompt-level strict accuracy —
    # the leaderboard number must mean what arXiv:2311.07911 says it means.
    assert result["schema"] == "screamingface.candidate-result.v1"
    assert result["benchmark_id"] == "ifeval"
    assert result["benchmark_revision"] == IFEVAL_REVISION
    assert result["score"] == 0.5
    assert result["metrics"]["inst_level_strict_accuracy"] == round(2 / 3, 4)
    assert result["metrics"]["prompt_level_loose_accuracy"] == 1.0
    assert result["metrics"]["inst_level_loose_accuracy"] == 1.0
    # Canonical report contract: pass_rate mirrors inst-level strict accuracy and
    # coverage is (checked - fallback) / selected — all 2 cases were checked here.
    assert result["metrics"]["pass_rate"] == round(2 / 3, 4)
    assert result["coverage"] == 1.0
    assert result["case_count"] == 2
    assert result["cases"][0]["input"] == _SPECS[1]["prompt"]
    assert result["cases"][0]["output"] == "Answer 1"
    assert result["cases"][0]["grade"]["checks"][0]["evidence"][0]["outcome"] == "PASS"
    # INVARIANT: each check carries its own MET/UNMET verdict (strict verifier decides) —
    # readers of the report schema judge a check by its outcome, not by digging into
    # evidence, and a check without one renders as unjudged.
    assert result["cases"][0]["grade"]["checks"][0]["outcome"] == "MET"
    assert result["cases"][0]["grade"]["checks"][1]["outcome"] == "UNMET"
    assert result["failures"] == []


def test_exact_case_evaluations_survive_the_collect_boundary() -> None:
    result = aggregate(
        _rows(
            _evaluation(1, [True, True], [True, True]),
            _evaluation(2, [True], [True]),
        ),
        _SPECS,
        "ifeval",
        _ORDER,
        selected_case_count=2,
    )

    assert result["score"] == 1.0
    assert result["case_count"] == 2


def test_live_projection_and_final_aggregation_share_case_grading_and_scorer() -> None:
    row = _evaluation(1, [True, False], [True, True])
    selected = selected_cases(_SPECS, _ORDER, 1)[0]

    projected = grade_case(row, selected, _SPECS[1])
    final = aggregate(_rows(row), _SPECS, "ifeval", _ORDER, selected_case_count=1)

    assert projected.model_dump() == final["cases"][0]
    assert score_cases([projected]).score == final["score"]


def test_a_failed_case_is_excluded_and_lowers_candidate_coverage() -> None:
    payload = _rows(
        _evaluation(1, [True, True], [True, True]),
        {
            "error": {
                "kind": "ResolutionError",
                "message": "aigateway returned neither answer content nor tool calls",
            }
        },
    )

    result = aggregate(payload, _SPECS, "ifeval", _ORDER, selected_case_count=2)

    assert result["score"] == 1.0
    assert result["coverage"] == 0.5
    assert result["case_count"] == 2
    assert result["cases"][0]["grade"]["score"] == 1.0
    assert result["cases"][1]["grade"] is None
    assert result["cases"][1]["failures"][0]["message"] == (
        "aigateway returned neither answer content nor tool calls"
    )


def test_an_invalid_case_evaluation_aborts_as_protocol_corruption() -> None:
    payload = _rows(
        "broken row",
        _evaluation(2, [True], [True]),
    )

    with pytest.raises(AggregateError, match="position 0"):
        aggregate(payload, _SPECS, "ifeval", _ORDER, selected_case_count=2)


def test_every_malformed_case_aborts_instead_of_reporting_zero() -> None:
    with pytest.raises(AggregateError, match="position 0"):
        aggregate(
            _rows("broken", "also broken"),
            _SPECS,
            "ifeval",
            _ORDER,
            selected_case_count=2,
        )


def test_all_crash_result_retains_the_collected_inner_failure() -> None:
    failed = {
        "error": {
            "kind": "ResolutionError",
            "message": "malformed aigateway response",
        }
    }

    result = aggregate(_rows(failed), {1: _SPECS[1]}, "ifeval", [1], selected_case_count=1)

    assert result["score"] is None
    assert result["cases"][0]["failures"][0]["message"] == "malformed aigateway response"


def test_metrics_are_flat_numbers_only() -> None:
    payload = _rows(_evaluation(2, [True], [True]))

    result = aggregate(payload, {2: _SPECS[2]}, "ifeval", [2], selected_case_count=1)

    assert all(isinstance(value, (int, float)) for value in result["metrics"].values())


def test_one_flake_at_realistic_size_publishes_partial_score_and_coverage() -> None:
    specs = {
        case_id: {
            "key": 1000 + case_id,
            "prompt": f"Case {case_id}: no commas.",
            "instruction_id_list": ["punctuation:no_comma"],
            "kwargs": [{}],
        }
        for case_id in range(1, 11)
    }
    order = list(range(1, 11))

    def evaluation(case_id: int, passed: bool) -> dict[str, object]:
        record = {
            "schema": SCHEMA,
            "case_id": case_id,
            "attempt": 1,
            "valid": True,
            "status": "completed",
            "answer": f"Answer {case_id}",
            "refusal": None,
            "finish_reason": "stop",
            "execution": None,
            "instruction_id_list": ["punctuation:no_comma"],
            "descriptions": ["Instruction 1"],
            "strict": [passed],
            "loose": [passed],
            "violations": [],
        }
        return _case_execution(case_id, bind_case_evaluation(case_id, [record]))

    rows = [evaluation(case_id, passed=case_id <= 4) for case_id in range(1, 10)]
    rows.append({"error": {"kind": "ResolutionError", "message": "provider flake"}})

    result = aggregate(json.dumps(rows), specs, "ifeval", order, selected_case_count=10)

    assert result["score"] == 0.4444
    assert result["coverage"] == 0.9
    assert result["case_count"] == 10
    assert result["cases"][9]["grade"] is None  # the flaked case, retained


def test_canonical_contract_metrics_are_published_for_every_scored_aggregate() -> None:
    """INVARIANT: every scored aggregate publishes the canonical trio (score,
    pass_rate, coverage) in [0, 1] — the SDK report tiles and its low-coverage
    warning read exactly these keys across all benchmarks (draco is the reference).
    """

    payload = _rows(
        _evaluation(1, [True, False], [True, True]),
        _evaluation(2, [True], [True]),
    )
    result = aggregate(payload, _SPECS, "ifeval", _ORDER, selected_case_count=2)

    assert 0.0 <= result["score"] <= 1.0
    assert 0.0 <= result["metrics"]["pass_rate"] <= 1.0
    assert 0.0 <= result["coverage"] <= 1.0
    # IFEval's mapping: pass_rate IS instruction-level strict accuracy.
    assert result["metrics"]["pass_rate"] == result["metrics"]["inst_level_strict_accuracy"]
    assert result["coverage"] == 1.0


def test_a_record_for_an_unknown_case_id_aborts() -> None:
    stray = dict(_record(2, [True], [True]), case_id=99)
    stray_evaluation = {
        "schema": CASE_EVALUATION_SCHEMA,
        "case_id": 2,
        "attempts": [stray],
    }
    payload = _rows(
        _evaluation(1, [True, True], [True, True]),
        _case_execution(2, stray_evaluation),
    )

    with pytest.raises(AggregateError, match="position 1"):
        aggregate(payload, _SPECS, "ifeval", _ORDER, selected_case_count=2)


def test_non_array_payload_raises() -> None:
    with pytest.raises(AggregateError):
        aggregate(
            '{"not": "an array"}',
            _SPECS,
            "ifeval",
            _ORDER,
            selected_case_count=2,
        )
    with pytest.raises(AggregateError):
        aggregate("not json at all", _SPECS, "ifeval", _ORDER, selected_case_count=2)


def test_load_specs_raises_on_a_missing_or_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(AggregateError):
        load_specs(tmp_path / "missing")


def test_load_specs_reads_case_keyed_files(tmp_path: Path) -> None:
    directory = tmp_path / "instructions"
    directory.mkdir()
    (directory / "1.json").write_text(json.dumps(_SPECS[1]), encoding="utf-8")

    specs = load_specs(directory)

    assert specs[1]["instruction_id_list"] == _SPECS[1]["instruction_id_list"]
