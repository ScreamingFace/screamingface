"""The member ``Answer`` and the computed result of a combine call (OME-1289 E4a gap-closure,
unit 1: AR#2-8, AR#15, AB#2, AB#2b, AB#8, AB#19, AB#20).

FEATURE: every member has a status ("answered" or "fail") and a reason, the evidence names the
computed result, and a vote with no usable member abstains instead of failing.
Every test uses the fake operators of ``combine_support``.
"""

from __future__ import annotations

import json
from typing import Any, get_args

import pytest
from combine_support import (
    FAKE_REGISTRY,
    context_text,
    request,
    run,
    run_recorded,
    spec_text,
    vote_spec,
)
from pydantic import ValidationError

from screamingface_engine.combine.evidence import AnswerRecord, ResultRecord
from screamingface_engine.combine.ports import (
    READING_TO_ANSWER,
    Answer,
    CombineError,
    NoVotes,
    OpArgs,
    OperatorDescriptor,
    ReadingStatus,
    StageResult,
    answer_status,
)
from screamingface_engine.combine.registry import OperatorRegistry
from screamingface_engine.operation_calls import capture_operation_calls
from screamingface_engine.world.combine import CombineRoute
from url4.core.errors import ResolutionError

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


# --- AB#2 / AB#2b / AB#8 ----------------------------------------------------------------------

_ABSTAIN_NO_VOTES = ResultRecord(member_id=None, value=None, status="abstain", reason="no_votes")


def test_no_usable_member_returns_abstain_result_not_error() -> None:
    outcome = run(spec_text(vote_spec(3)), context_text(["", " ", "\n"]))
    evidence = outcome.evidence
    assert outcome.output == ""
    assert evidence.result == _ABSTAIN_NO_VOTES
    assert (evidence.chosen, evidence.built, evidence.tally) == ([], False, None)
    assert evidence.dropped == 3
    assert (evidence.agreement, evidence.tie, evidence.finish_reason) == (None, False, "stop")


def test_a_reducer_may_ask_the_core_to_abstain() -> None:
    spec = vote_spec(3, reduce={"op": "fake_no_votes@1", "args": {}})
    outcome = run(spec_text(spec), context_text(["a x", "b y", "c z"]))
    evidence = outcome.evidence
    assert outcome.output == ""
    assert evidence.result == _ABSTAIN_NO_VOTES
    assert (evidence.chosen, evidence.built, evidence.tally, evidence.dropped) == (
        [],
        False,
        None,
        0,
    )


def test_cut_not_met_from_select_keeps_the_tally() -> None:
    spec = vote_spec(2, select={"op": "fake_cut@1", "args": {}})
    outcome = run(spec_text(spec), context_text(["a x", "b y"]))
    evidence = outcome.evidence
    assert outcome.output == ""
    assert evidence.result == ResultRecord(
        member_id=None, value=None, status="abstain", reason="cut_not_met"
    )
    assert evidence.tally is not None
    assert [row.value for row in evidence.tally] == ["x", "y"]
    assert (evidence.chosen, evidence.built) == ([], False)


def test_empty_concat_is_not_abstain() -> None:
    spec = vote_spec(
        3,
        reducer="concat",
        extract=None,
        normalize=None,
        reduce={"op": "fake_all_parts@1", "args": {}},
        select={"op": "fake_empty_join@1", "args": {}},
    )
    outcome = run(spec_text(spec), context_text(["a", "b", "c"]))
    assert outcome.output == ""
    assert outcome.evidence.result.status == "answered"
    assert outcome.evidence.result.reason is None


def test_no_votes_is_an_internal_signal_that_checks_its_reason() -> None:
    assert not issubclass(NoVotes, CombineError)
    assert not hasattr(NoVotes, "code")
    with pytest.raises(ValueError):
        NoVotes("x", reason="nonsense")  # type: ignore[arg-type]
    assert NoVotes("x").reason == "no_votes"
    assert str(NoVotes()) == "no_votes"


def test_a_stage_plugin_that_raises_no_votes_is_a_plugin_bug() -> None:
    def extract(text: str, args: OpArgs, /) -> StageResult:
        raise NoVotes("not allowed here")

    registry = OperatorRegistry(
        (*FAKE_REGISTRY, OperatorDescriptor("fake_abstaining", 1, "extract", "t.", extract))
    )
    spec = vote_spec(2, extract={"op": "fake_abstaining@1", "args": {}})
    with pytest.raises(NoVotes):
        run(spec_text(spec), context_text(["a", "b"]), registry=registry)


# --- AB#20 ------------------------------------------------------------------------------------


def _abstain_wire() -> tuple[str, str]:
    outcome = run(spec_text(vote_spec(3)), context_text(["", " ", "\n"]))
    wire = json.dumps(outcome.evidence.model_dump(by_alias=True), separators=(",", ":"))
    return outcome.output, wire


def test_abstain_replays_identically() -> None:
    assert len({_abstain_wire() for _ in range(100)}) == 1
    texts = context_text(["", " ", "\n"])
    first = run_recorded(spec_text(vote_spec(3)), texts)[1][0].combine
    second = run_recorded(spec_text(vote_spec(3)), texts)[1][0].combine
    assert first is not None
    assert first == second


# --- AB#10 sentinel: an abstain never carries member text -------------------------------------

_SENTINEL = "SENTINEL-TEXT-42"


def test_abstain_evidence_never_carries_member_text() -> None:
    spec = vote_spec(1)
    outcome = run(spec_text(spec), context_text([_SENTINEL + "x" * _MIB]))
    assert outcome.evidence.result == _ABSTAIN_NO_VOTES
    dumped = outcome.evidence.model_dump_json(by_alias=True)
    assert _SENTINEL not in dumped
    assert _SENTINEL not in outcome.output


# --- AB#5 -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "code"),
    [
        (vote_spec(3, extract={"op": "fake_last_word@9", "args": {}}), "combine_operator_unknown"),
        (vote_spec(3, extract={"op": "fake_args@1", "args": {"sep": 1}}), "combine_spec_invalid"),
    ],
    ids=["operator-unknown", "bad-args"],
)
def test_spec_errors_still_fail_the_case(spec: dict[str, Any], code: str) -> None:
    """An all-empty context must not hide a spec error behind an abstain."""
    with capture_operation_calls() as calls:
        with pytest.raises(ResolutionError) as caught:
            CombineRoute(FAKE_REGISTRY)(request(spec_text(spec), context_text(["", " ", "\n"])))
    assert caught.value.code == code
    assert caught.value.permanent is True
    assert calls == []
