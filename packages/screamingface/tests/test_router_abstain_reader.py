"""C10: the SDK reads a Router ``no_selection`` abstention before any writer exists.

FEATURE: Router Recipe extension (Unit 6, C10). A Router that selects no candidate and has no
default abstains with the ``answer.v1`` reason ``no_selection``. Readers accept the word first,
as E4c did for ``budget_refused``; the Router writer comes later.
STORY: as a researcher reading a Router run, a case whose Router selected nothing is one more
abstention in my Report, not a record the SDK refuses.

INVARIANT (C10): the word is read only with status ``abstain`` and refused everywhere else.
Every legacy word keeps its bytes, and the ``answer.v1`` schema ID stays as it is. The Engine
twin test decodes the very same bytes.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, get_args

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, requires_engine_app

from screamingface._evaluation.combine_evidence import _result as _wire_result
from screamingface._evaluation.gate_decision import _result as _gate_result
from screamingface.answer import (
    ABSTAIN_REASONS,
    ANSWER_REASONS,
    ANSWER_SCHEMA,
    AbstainReason,
    Answer,
    AnswerReason,
)
from screamingface.combine_evidence import CombineResult
from screamingface.errors import ExecutionError

# The one synthetic Router abstention; the Engine twin test reads the same bytes.
SYNTHETIC = b'{"member_id":null,"value":null,"status":"abstain","reason":"no_selection"}'
_LEGACY_ABSTAIN = (
    "no_votes",
    "cut_not_met",
    "output_missing",
    "gate_not_met",
    "in_band",
    "budget_refused",
)
_LEGACY_FAILURE = (
    "empty",
    "not_numeric",
    "not_json",
    "field_missing",
    "too_large",
    "no_match",
    "missing",
)
_EXCLUDE = ("no_signal", "no_weight", "not_selected")
_SNAPSHOTS = Path(__file__).parent / "data" / "schemas"
_ENGINE_TWIN = ENGINE_APP / "tests" / "unit" / "test_router_abstain_reader.py"
_REFUSAL = (ExecutionError, ValueError, TypeError)


def _record(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "member_id": None,
        "value": None,
        "status": "abstain",
        "reason": "no_selection",
    }
    body.update(changes)
    return body


def _answer(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "member_id": None,
        "text": None,
        "raw": None,
        "value": None,
        "status": "abstain",
        "reason": "no_selection",
        "signals": {},
    }
    body.update(changes)
    return body


def _bytes(body: Mapping[str, object]) -> bytes:
    return json.dumps(body, separators=(",", ":")).encode()


# --- one answer, both readers -------------------------------------------------------------------


def test_the_synthetic_abstention_reads_and_writes_back_the_same_bytes() -> None:
    result = _wire_result(json.loads(SYNTHETIC), "result")

    assert result == CombineResult(
        member_id=None, value=None, status="abstain", reason="no_selection"
    )
    assert _bytes(result.to_dict()) == SYNTHETIC


def test_the_answer_v1_record_reads_the_word_as_an_abstention() -> None:
    answer = Answer.from_dict(_answer())

    assert (answer.member_id, answer.value, answer.status, answer.reason) == (
        None,
        None,
        "abstain",
        "no_selection",
    )
    assert answer.to_dict() == _answer()


def test_a_gate_result_reads_the_word_as_an_abstention() -> None:
    # WHY: C10 widens the reader vocabulary the Gate record shares; no Gate writes the word.
    result = _gate_result({"status": "abstain", "reason": "no_selection"}, "gate result")

    assert result is not None
    assert (result.status, result.reason) == ("abstain", "no_selection")


def test_the_derived_word_sets_carry_the_word() -> None:
    # WHY the abstain group: the word joins the abstain words, ahead of the exclude words.
    assert get_args(AbstainReason.__value__) == (*_LEGACY_ABSTAIN, "no_selection")
    assert get_args(AnswerReason.__value__) == (
        *_LEGACY_FAILURE,
        *_LEGACY_ABSTAIN,
        "no_selection",
        *_EXCLUDE,
    )
    assert ABSTAIN_REASONS == {*_LEGACY_ABSTAIN, "no_selection"}
    assert ANSWER_REASONS == {*_LEGACY_FAILURE, *_LEGACY_ABSTAIN, "no_selection", *_EXCLUDE}


@requires_engine_app
def test_the_engine_twin_decodes_the_very_same_bytes() -> None:
    tree = ast.parse(_ENGINE_TWIN.read_text("utf-8"))
    declared = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and [getattr(target, "id", None) for target in node.targets] == ["SYNTHETIC"]
        and isinstance(node.value, ast.Constant)
    ]

    assert declared == [SYNTHETIC]


# --- refused everywhere else --------------------------------------------------------------------

_REFUSED_RESULTS = {
    "answered": _record(status="answered"),
    "answered-with-value": _record(status="answered", value="A"),
    "fail": _record(status="fail"),
    "excluded": _record(status="excluded"),
    "with-member": _record(member_id="member_1"),
    "with-value": _record(value="A"),
    "reversed": _record(status="no_selection", reason="abstain"),
    "extra-key": _record(text=None),
    "missing-key": {"member_id": None, "status": "abstain", "reason": "no_selection"},
    "other-case": _record(reason="No_Selection"),
    "padded": _record(reason="no_selection "),
    "abstain-without-reason": _record(reason=None),
    "reason-not-text": _record(reason=["no_selection"]),
}


@pytest.mark.parametrize("body", list(_REFUSED_RESULTS.values()), ids=list(_REFUSED_RESULTS))
def test_a_result_of_any_other_shape_is_refused(body: dict[str, Any]) -> None:
    with pytest.raises(_REFUSAL):
        _wire_result(body, "result")


_REFUSED_ANSWERS = {
    "answered": _answer(status="answered"),
    "fail": _answer(status="fail"),
    "excluded": _answer(status="excluded", member_id="member_1"),
    "with-member": _answer(member_id="member_1"),
    "with-value": _answer(value="A"),
    "reversed": _answer(status="no_selection", reason="abstain"),
    "extra-key": {**_answer(), "verdict": None},
    "missing-key": {key: value for key, value in _answer().items() if key != "signals"},
    "other-case": _answer(reason="No_Selection"),
    "padded": _answer(reason="no_selection "),
    "abstain-without-reason": _answer(reason=None),
}


@pytest.mark.parametrize("body", list(_REFUSED_ANSWERS.values()), ids=list(_REFUSED_ANSWERS))
def test_an_answer_of_any_other_shape_is_refused(body: dict[str, Any]) -> None:
    with pytest.raises(_REFUSAL):
        Answer.from_dict(body)


@pytest.mark.parametrize("status", ["answered", "fail_closed"])
def test_a_gate_result_refuses_the_word_without_an_abstention(status: str) -> None:
    with pytest.raises(_REFUSAL):
        _gate_result({"status": status, "reason": "no_selection"}, "gate result")


# --- legacy identity ----------------------------------------------------------------------------


@pytest.mark.parametrize("reason", _LEGACY_ABSTAIN)
def test_a_legacy_abstention_keeps_its_bytes(reason: str) -> None:
    body = _bytes(_record(reason=reason))

    assert _bytes(_wire_result(json.loads(body), "result").to_dict()) == body
    assert Answer.from_dict(_answer(reason=reason)).to_dict() == _answer(reason=reason)


def test_the_answer_v1_snapshot_keeps_its_id_and_lists_the_word() -> None:
    assert ANSWER_SCHEMA == "screamingface.answer.v1"
    pinned = json.loads((_SNAPSHOTS / f"{ANSWER_SCHEMA}.json").read_text("utf-8"))

    assert pinned["abstain_reason"] == sorted([*_LEGACY_ABSTAIN, "no_selection"])
    assert pinned["reason"] == sorted(ANSWER_REASONS)
    assert pinned["fields"] == ["member_id", "text", "raw", "value", "status", "reason", "signals"]


@requires_engine_app
def test_the_sdk_words_equal_the_engine_pinned_evidence_enums() -> None:
    pinned = json.loads(
        (COMBINE_CONTRACT / "schemas" / "screamingface.combine-evidence.v1.json").read_text("utf-8")
    )
    result = _reason_enum(pinned, "ResultRecord")

    assert result == [*_LEGACY_ABSTAIN, "no_selection"]
    assert set(result) == ABSTAIN_REASONS
    assert _reason_enum(pinned, "AnswerRecord")[-1] == "no_selection"


def _reason_enum(pinned: dict[str, Any], record: str) -> list[str]:
    return pinned["$defs"][record]["properties"]["reason"]["anyOf"][0]["enum"]
