"""OME-1096: the shared step that reads a fan-out's collected rows back.

Think of it as the mailroom: the run fanned out over the selected Cases, one row came
back per Case, and this step sorts the pile by student number before any marking starts.

INVARIANT: the row is an OPAQUE board-owned envelope. The reader files it under its Case
id and never looks inside, so nothing here can freeze "a candidate's answer is text" —
the kind taxonomy is OME-1103's decision and the seam that opens the envelope is
OME-1097's `grade_case`. The stub decoder below returns a bare marker dict precisely to
prove the reader never inspects the contents.

INVARIANT: an ``on_error=collect`` row loses its Case identity, so it cannot be indexed.
It is RETAINED as an orphan and attached to whichever Case ends up with no row — dropping
it would name the symptom (a missing row) and hide the cause.

The board-varying bits are injected, so each board keeps its own error class and its own
wording after the extraction.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.spine.rows import RowReader


class BoardError(ValueError):
    """Stands in for a board's own ``AggregateError``."""


class OtherBoardError(ValueError):
    """A second board's error class — proves the reader raises the injected one."""


def _decode(grading: object, expected_case_id: int) -> dict[str, Any]:
    """Stub board decoder: marks the row without reading anything out of it."""

    if grading == "reject-me":
        raise ValueError("stub decoder rejected this envelope")
    return {"decoded_for": expected_case_id, "grading": grading}


def _reader(label: str = "TestBoard", error: type[Exception] = BoardError) -> RowReader:
    return RowReader(
        benchmark_label=label,
        error_type=error,
        decode_case_evaluation=_decode,
    )


def _envelope(case_id: int, grading: object = "graded") -> dict[str, object]:
    """One valid Case-execution envelope carrying an opaque grading outcome."""

    return case_execution_payload(
        case_id,
        encode_candidate_invocation(f"output-{case_id}", "stop", None),
        [grading],
    )


def _collected_error(message: str, case_id: int | None = None) -> dict[str, object]:
    """The shape an ``on_error=collect`` row has: an outer error, identity optional."""

    row: dict[str, object] = {"error": {"kind": "transport", "message": message}}
    if case_id is not None:
        row["case_id"] = case_id
    return row


def test_rows_are_filed_under_their_selected_case_ids() -> None:
    index = _reader().index(json.dumps([_envelope(1), _envelope(2)]), (1, 2))

    assert sorted(index.rows) == [1, 2]
    assert index.rows[1]["decoded_for"] == 1
    assert index.rows[2]["decoded_for"] == 2
    assert index.collected_errors == {}
    assert index.grading_failures == {}


def test_no_rows_indexes_nothing_rather_than_failing() -> None:
    # WHY: an empty fan-out is not a protocol error — every selected Case simply ends up
    # with no row, which the grader reports per Case as missing_case_row.
    index = _reader().index("[]", (1, 2))

    assert index.rows == {}
    assert index.collected_errors == {}
    assert index.grading_failures == {}


def test_a_non_json_payload_names_the_benchmark() -> None:
    with pytest.raises(BoardError, match="TestBoard rows are not JSON"):
        _reader().index("not json", (1,))


def test_an_empty_payload_names_the_benchmark() -> None:
    with pytest.raises(BoardError, match="TestBoard rows are not JSON"):
        _reader().index("", (1,))


def test_a_json_object_payload_is_refused_as_not_an_array() -> None:
    with pytest.raises(BoardError, match="TestBoard rows must be a JSON array"):
        _reader().index("{}", (1,))


def test_more_rows_than_selected_cases_abort_before_indexing() -> None:
    # INVARIANT: case_ids is the authoritative roll call. More rows than Cases means the
    # fan-out disagrees with the selection, so no row can be trusted to its position.
    payload = json.dumps([_envelope(1), _envelope(2)])

    with pytest.raises(BoardError, match="received 2 rows for 1 selected Cases"):
        _reader().index(payload, (1,))


def test_a_double_encoded_row_is_parsed() -> None:
    # WHY: url4 hands some rows back as JSON text rather than as objects.
    payload = json.dumps([json.dumps(_envelope(1))])

    index = _reader().index(payload, (1,))

    assert index.rows[1]["decoded_for"] == 1


def test_a_row_that_is_not_an_object_aborts_with_its_position() -> None:
    with pytest.raises(BoardError, match="Case result at position 0 must be an object"):
        _reader().index(json.dumps([[1, 2, 3]]), (1,))


def test_a_malformed_row_string_aborts_with_its_position() -> None:
    with pytest.raises(BoardError, match="Case result at position 0 is not JSON"):
        _reader().index(json.dumps(["{not json"]), (1,))


def test_an_orphan_collected_error_is_retained_against_its_position() -> None:
    # INVARIANT: the cause is never dropped. Without this the report would say
    # "no row for Case 1" and hide the transport failure that caused it.
    index = _reader().index(json.dumps([_collected_error("upstream 503")]), (1,))

    assert index.rows == {}
    assert index.grading_failures == {}
    assert index.collected_errors[1][0]["error"]["message"] == "upstream 503"


def test_two_orphan_errors_for_one_case_are_both_retained() -> None:
    payload = json.dumps([_collected_error("first"), _collected_error("second")])

    index = _reader().index(payload, (1, 1))

    assert [row["error"]["message"] for row in index.collected_errors[1]] == [
        "first",
        "second",
    ]


def test_an_identified_error_row_is_filed_as_the_cases_row() -> None:
    # WHY: an error row that kept its identity IS that Case's row — the grader reads the
    # "error" key off it and reports case_error, rather than missing_case_row.
    index = _reader().index(json.dumps([_collected_error("judge down", case_id=1)]), (1,))

    assert index.rows[1]["error"]["message"] == "judge down"
    assert index.collected_errors == {}


def test_an_error_row_claiming_another_case_aborts() -> None:
    # INVARIANT: a row whose claimed identity disagrees with the selection cannot be
    # trusted to its position; scoring the wrong Case is worse than failing the run.
    payload = json.dumps([_collected_error("wrong case", case_id=99)])

    with pytest.raises(BoardError, match="claims case_id 99"):
        _reader().index(payload, (1,))


def test_an_error_that_is_not_an_object_aborts() -> None:
    with pytest.raises(BoardError, match="position 0 has an invalid error"):
        _reader().index(json.dumps([{"error": "boom"}]), (1,))


def test_a_grading_error_lands_in_grading_failures_not_rows() -> None:
    payload = json.dumps([_envelope(1, {"error": {"message": "grader crashed"}})])

    index = _reader().index(payload, (1,))

    assert index.rows == {}
    assert index.grading_failures[1].error == {"message": "grader crashed"}


def test_an_envelope_claiming_another_case_aborts() -> None:
    payload = json.dumps([_envelope(99)])

    with pytest.raises(BoardError, match="claims case_id"):
        _reader().index(payload, (1,))


def test_a_decoder_rejection_aborts_with_its_position() -> None:
    # INVARIANT: the board's decoder is the only authority on its envelope shape; its
    # rejection must surface as the board's own error, not leak a bare ValueError.
    payload = json.dumps([_envelope(1, "reject-me")])

    with pytest.raises(BoardError, match="position 0 is invalid: stub decoder rejected"):
        _reader().index(payload, (1,))


def test_a_malformed_envelope_aborts_with_its_position() -> None:
    payload = json.dumps([{"schema": "wrong", "case_id": 1}])

    with pytest.raises(BoardError, match="Case result at position 0 is invalid"):
        _reader().index(payload, (1,))


def test_each_reader_raises_its_own_error_class_with_its_own_wording() -> None:
    # INVARIANT: extraction must not merge the boards' error identities — a test that
    # asserts gdpval raised must keep failing when healthbench raises.
    other = _reader(label="OtherBoard", error=OtherBoardError)

    with pytest.raises(OtherBoardError, match="OtherBoard rows are not JSON"):
        other.index("not json", (1,))
    with pytest.raises(BoardError, match="TestBoard rows are not JSON"):
        _reader().index("not json", (1,))


def test_the_reader_never_reads_a_case_input_or_answer() -> None:
    # INVARIANT (OME-1103): the row is an opaque payload. This reader files envelopes; it
    # must not grow a `.answer: str`, or the agentic answer shape becomes a rewrite
    # instead of a new kind. The stub decoder returns a marker with no text fields at
    # all — if the reader ever inspects the answer, this stops working.
    index = _reader().index(json.dumps([_envelope(1, {"opaque": ["anything", 42]})]), (1,))

    assert index.rows[1]["grading"] == {"opaque": ["anything", 42]}
