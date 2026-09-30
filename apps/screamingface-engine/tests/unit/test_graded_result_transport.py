"""Typed grades survive transport without calling the board grader again."""

import json

import pytest
from test_shared_grading_aggregation import _aggregate, _envelope, _grading, _Hook, _path, _selected

from screamingface_engine.benchmarks.contract import CaseResult
from screamingface_engine.benchmarks.graded_results import decode_results, encode_result


def _result():
    payload = _aggregate(_path(_Hook()), [_envelope(1, _grading(1))], _selected(1))
    return CaseResult.model_validate(payload["cases"][0])


def _decode(rows):
    return decode_results(
        json.dumps(rows),
        benchmark_id="board",
        revision="v2",
        selected=_selected(1),
        failure=lambda *_: pytest.fail("unexpected failure mapping"),
    )


def test_round_trip_preserves_complete_case_result() -> None:
    result = _result()
    row = encode_result(result, benchmark_id="board", revision="v2")
    assert _decode([row]) == [result]


@pytest.mark.parametrize(
    "field,value", [("benchmark_id", "other"), ("revision", "v1"), ("schema", "old")]
)
def test_foreign_or_old_grade_is_rejected(field, value) -> None:
    row = json.loads(encode_result(_result(), benchmark_id="board", revision="v2"))
    row[field] = value
    with pytest.raises(ValueError):
        _decode([row])


def test_mismatched_case_input_is_rejected() -> None:
    row = json.loads(encode_result(_result(), benchmark_id="board", revision="v2"))
    row["result"]["input"] = "different prompt"
    with pytest.raises(ValueError):
        _decode([row])


@pytest.mark.parametrize("rows", [{}, [None], [{"error": "invalid"}], [{"error": {}, "extra": 1}]])
def test_malformed_transport_is_rejected(rows) -> None:
    with pytest.raises(ValueError):
        _decode(rows)


def test_wrong_position_and_duplicate_result_are_rejected() -> None:
    row = json.loads(encode_result(_result(), benchmark_id="board", revision="v2"))
    row["result"]["case_id"] = 2
    with pytest.raises(ValueError):
        _decode([row])
    with pytest.raises(ValueError):
        _decode([row, row])


def test_missing_and_anonymous_failures_keep_their_selected_positions() -> None:
    seen = []

    def failure(case, index, errors):
        seen.append((case.case_id, index, errors))
        return _result().model_copy(update={"case_id": case.case_id})

    error = {"error": {"message": "unavailable"}}
    decode_results(
        json.dumps([error]),
        benchmark_id="board",
        revision="v2",
        selected=_selected(1, 2),
        failure=failure,
    )
    assert seen == [(1, 0, [error]), (2, 1, None)]
