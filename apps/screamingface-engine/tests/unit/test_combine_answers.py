"""The member ``Answer`` and the computed result of a combine call (OME-1289 E4a gap-closure,
unit 1: AR#2-8, AR#15, AB#2, AB#2b, AB#8, AB#19, AB#20).

FEATURE: every member has a status ("answered" or "fail") and a reason, the evidence names the
computed result, and a vote with no usable member abstains instead of failing.
Every test uses the fake operators of ``combine_support``.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest
from combine_support import context_text, run, spec_text, vote_spec
from pydantic import ValidationError

from screamingface_engine.combine.evidence import AnswerRecord, ResultRecord
from screamingface_engine.combine.ports import (
    READING_TO_ANSWER,
    Answer,
    CombineError,
    ReadingStatus,
    answer_status,
)

_MIB = 1024 * 1024

_TABLE = {
    "voted": ("answered", None),
    "empty": ("fail", "empty"),
    "not_numeric": ("fail", "not_numeric"),
    "not_json": ("fail", "not_json"),
    "field_missing": ("fail", "field_missing"),
    "too_large": ("fail", "too_large"),
    "no_match": ("fail", "no_match"),
}


def _rows(spec: dict[str, Any], texts: list[str]) -> list[tuple[str, str | None]]:
    members = run(spec_text(spec), context_text(texts)).evidence.members
    return [(row.status, row.reason) for row in members]


# --- AR#2 -------------------------------------------------------------------------------------


def test_every_reading_status_maps_to_one_answer_status_and_reason() -> None:
    assert dict(READING_TO_ANSWER) == _TABLE
    assert set(READING_TO_ANSWER) == set(get_args(ReadingStatus))
    for status, expected in _TABLE.items():
        assert answer_status(status) == expected
    for bogus in ("bogus", 1, None, ["voted"]):
        with pytest.raises(RuntimeError):
            answer_status(bogus)


# --- AR#3 -------------------------------------------------------------------------------------


def test_answered_answer_without_value_is_rejected_by_core() -> None:
    spec = vote_spec(2, extract={"op": "fake_bad_stage@1", "args": {}})
    with pytest.raises(RuntimeError, match=r"fake_bad_stage@1") as caught:
        run(spec_text(spec), context_text(["a 1", "b 2"]))
    assert not isinstance(caught.value, CombineError)


# --- AR#4 / AR#5 ------------------------------------------------------------------------------


def test_unparseable_member_is_fail_with_reason_not_exception() -> None:
    spec = vote_spec(3, extract={"op": "fake_digits@1", "args": {}})
    outcome = run(spec_text(spec), context_text(["no idea", "a 7", "b 7"]))
    first = outcome.evidence.members[0]
    assert (first.status, first.reason, first.value) == ("fail", "empty", None)
    assert outcome.output == "a 7"


def test_oversized_member_is_fail_too_large() -> None:
    outcome = run(spec_text(vote_spec(3)), context_text(["a x", "w " * _MIB, "c x"]))
    row = outcome.evidence.members[1]
    assert (row.status, row.reason, row.raw, row.value) == ("fail", "too_large", None, None)


# --- AR#15 ------------------------------------------------------------------------------------


def test_member_answer_is_never_abstain() -> None:
    spec = vote_spec(2, extract={"op": "fake_abstain_stage@1", "args": {}})
    with pytest.raises(RuntimeError, match=r"fake_abstain_stage@1"):
        run(spec_text(spec), context_text(["a", "b"]))
    row = {
        "member_id": "member_1",
        "raw": None,
        "value": None,
        "status": "abstain",
        "reason": "no_votes",
        "signals": {},
        "weight": None,
        "score": None,
    }
    with pytest.raises(ValidationError):
        AnswerRecord.model_validate(row)
    with pytest.raises(ValueError):
        Answer("member_1", None, None, "abstain", "no_votes")  # type: ignore[arg-type]


# --- AR#6 / AR#7 ------------------------------------------------------------------------------


def test_vote_result_is_computed_answer_naming_the_winner() -> None:
    outcome = run(spec_text(vote_spec(3)), context_text(["a 42", "b 42", "c 41"]))
    assert outcome.evidence.result == ResultRecord(
        member_id="member_1", value="42", status="answered", reason=None
    )


def test_compute_mode_result_has_no_member_id() -> None:
    built = vote_spec(2, select={"op": "fake_constant@1", "args": {}})
    result = run(spec_text(built), context_text(["a x", "b y"])).evidence.result
    assert result.member_id is None
    assert result.value == "BUILT"
    concat = vote_spec(
        3,
        reducer="concat",
        extract=None,
        normalize=None,
        reduce={"op": "fake_all_parts@1", "args": {}},
        select={"op": "fake_constant@1", "args": {}},
    )
    selection = run(spec_text(concat), context_text(["a", "b", "c"])).evidence.result
    assert (selection.member_id, selection.value, selection.status) == (None, None, "answered")


# --- AB#19 ------------------------------------------------------------------------------------


def test_one_usable_member_wins_with_dropped_count() -> None:
    outcome = run(spec_text(vote_spec(3)), context_text(["", " ", "c x"]))
    assert outcome.output == "c x"
    assert outcome.evidence.dropped == 2
    assert outcome.evidence.result.member_id == "member_3"
    assert outcome.evidence.result.status == "answered"
