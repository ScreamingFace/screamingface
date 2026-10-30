"""The part 2 words and keys of the SDK evidence, Answer and trace (E4b part 2, unit 1).

FEATURE: an evidence row can be "excluded" by a rule of the combine step (reasons "no_signal" and
"no_weight"); a top-k step writes the member ``rank`` and the evidence ``cut``; ``sf.Answer`` and
the trace keep the status "excluded".
STORY: as a researcher, I can read which members a combine step left out, why, and in what order a
top-k step ranked the members, on the same Case that carries the combined output.
INVARIANT defended: an evidence without a new value keeps its v1 bytes; each refusal names the
rule it breaks; the SDK words equal the Engine evidence schema; ``dropped`` counts only the
failed members.
The schema ids do not change (ans:Q5), and the SDK words are not public (P12, Q3).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, requires_engine_app
from test_frozen_record_fields import _fixture_case

import screamingface.answer
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface.answer import (
    ANSWER_REASONS,
    ANSWER_SCHEMA,
    ANSWER_STATUSES,
    MEMBER_STATUSES,
    SIGNAL_ORDERS,
    Answer,
)
from screamingface.combine_evidence import CombineAnswerRow, CombineCut
from screamingface.errors import ExecutionError
from screamingface.report_trace import TRACE_FIELDS

_LABEL = "Case Operation combine"
SCHEMAS = Path(__file__).parent / "data" / "schemas"
_EVIDENCE_CASES: dict[str, Any] = (
    json.loads((COMBINE_CONTRACT / "evidence_cases.json").read_text(encoding="utf-8"))
    if ENGINE_APP.exists()
    else {}
)


def _ranked_wire() -> dict[str, Any]:
    """A top_k@1 evidence: scores 0.3, 0.9, 0.6, 0.1, order max, k 2.

    Oracle by hand: high first -> member_2 (0.9) rank 1, member_3 (0.6) 2, member_1 (0.3) 3,
    member_4 (0.1) 4. chosen = the ranks <= 2 = [member_2, member_3].
    """
    scores = {"member_1": 0.3, "member_2": 0.9, "member_3": 0.6, "member_4": 0.1}
    ranks = {"member_1": 3, "member_2": 1, "member_3": 2, "member_4": 4}
    return {
        "schema": "screamingface.combine-evidence.v1",
        "kind": "selection",
        "reducer": "rank",
        "operators": ["by_signal@1", "top_k@1"],
        "members": [
            {
                "member_id": member,
                "raw": None,
                "value": None,
                "status": "answered",
                "reason": None,
                "signals": {"field:score": score},
                "weight": None,
                "score": score,
                "rank": ranks[member],
            }
            for member, score in scores.items()
        ],
        "tally": None,
        "judge": None,
        "fields": None,
        "chosen": ["member_2", "member_3"],
        "built": True,
        "agreement": None,
        "tie": False,
        "median": None,
        "presentation_order": None,
        "separator_collision": None,
        "signal": {"key": "field:score", "order": "max"},
        "cut": {"k": 2, "order": "max"},
        "result": {"member_id": None, "value": None, "status": "answered", "reason": None},
        "dropped": 0,
        "finish_reason": "stop",
    }


def _excluded_wire() -> dict[str, Any]:
    """An X1 weighted vote: member_2 answered "12" with no usable weight, so it is excluded."""
    weights = {"member_1": 0.9, "member_2": None, "member_3": 0.4}
    members = [
        {
            "member_id": member,
            "raw": "12",
            "value": "12",
            "status": "answered",
            "reason": None,
            "signals": {"field:confidence": weight},
            "weight": weight,
            "score": None,
        }
        for member, weight in weights.items()
    ]
    members[1].update(status="excluded", reason="no_weight")
    return {
        "schema": "screamingface.combine-evidence.v1",
        "kind": "answer",
        "reducer": "vote",
        "operators": ["last_number@1", "numeric@1", "weighted_mode@1", "max_weight_holder@1"],
        "members": members,
        "tally": [{"value": "12", "score": 1.3, "holders": ["member_1", "member_3"]}],
        "judge": None,
        "fields": None,
        "chosen": ["member_1"],
        "built": False,
        "agreement": 1.0,
        "tie": False,
        "median": None,
        "presentation_order": None,
        "separator_collision": None,
        "signal": {"key": "field:confidence", "order": None},
        "result": {"member_id": "member_1", "value": "12", "status": "answered", "reason": None},
        "dropped": 0,
        "finish_reason": "stop",
    }


def _decode(wire: dict[str, Any]) -> Any:
    return decode_combine_evidence(copy.deepcopy(wire), _LABEL)


# A single answer row for the record tests.
_ROW: dict[str, Any] = {
    "member_id": "member_2",
    "raw": "12",
    "value": "12",
    "status": "excluded",
    "reason": "no_weight",
    "signals": {"field:confidence": None},
    "weight": None,
    "score": None,
}


def _words(prop: dict[str, Any]) -> list[str]:
    return [word for branch in prop.get("anyOf", [prop]) for word in branch.get("enum", [])]


# --- ES#1: an evidence without a new value keeps its v1 bytes (CHAR) ---------------------------


@requires_engine_app
@pytest.mark.parametrize("name", sorted(_EVIDENCE_CASES))
def test_evidence_without_new_values_keeps_v1_bytes(name: str) -> None:
    wire = _EVIDENCE_CASES[name]

    assert json.dumps(_decode(wire).to_dict()) == json.dumps(wire)


# --- ES#2: an excluded row and an excluded Answer ------------------------------------------------


def test_answer_record_accepts_excluded_with_an_exclude_reason() -> None:
    assert CombineAnswerRow(**_ROW).to_dict() == _ROW

    answer = Answer(
        member_id="member_2",
        text=None,
        raw="12",
        value="12",
        status="excluded",
        reason="no_weight",
    )
    assert answer.to_dict()["status"] == "excluded"
    assert answer.to_dict()["reason"] == "no_weight"
    assert answer.to_dict()["value"] == "12"


# --- ES#3: excluded needs an exclude reason, and an Answer excluded needs its member -------------


def test_answer_record_refuses_excluded_without_an_exclude_reason() -> None:
    assert CombineAnswerRow(**_ROW).status == "excluded"
    assert (
        Answer(
            member_id="member_2",
            text=None,
            raw="12",
            value="12",
            status="excluded",
            reason="no_weight",
        ).status
        == "excluded"
    )

    for reason in (None, "empty", "missing", "no_votes"):
        with pytest.raises(ValueError):
            CombineAnswerRow(**{**_ROW, "reason": reason})
        with pytest.raises(ValueError):
            Answer(
                member_id="member_2",
                text=None,
                raw="12",
                value="12",
                status="excluded",
                reason=reason,
            )

    with pytest.raises(ValueError, match="names its member"):
        Answer(
            member_id=None,
            text=None,
            raw="12",
            value="12",
            status="excluded",
            reason="no_weight",
        )


# --- ES#4: an exclude reason belongs to an excluded member only ----------------------------------


def test_answer_record_refuses_an_exclude_reason_on_a_failed_member() -> None:
    failed = {**_ROW, "status": "fail", "reason": "empty", "value": None, "raw": None}
    assert CombineAnswerRow(**failed).status == "fail"
    assert (
        Answer(
            member_id="member_2", text=None, raw=None, value=None, status="fail", reason="empty"
        ).status
        == "fail"
    )
    assert CombineAnswerRow(**{**_ROW, "reason": "no_signal"}).reason == "no_signal"

    for reason in ("no_signal", "no_weight"):
        with pytest.raises(ValueError):
            CombineAnswerRow(**{**failed, "reason": reason})
        with pytest.raises(ValueError):
            Answer(
                member_id="member_2", text=None, raw=None, value=None, status="fail", reason=reason
            )
    with pytest.raises(ValueError):
        CombineAnswerRow(**{**_ROW, "status": "answered", "reason": "no_signal"})
    with pytest.raises(ValueError):
        Answer(
            member_id="member_2",
            text=None,
            raw="12",
            value="12",
            status="answered",
            reason="no_signal",
        )


# --- ES#6: the member rank and its 1..n rule -----------------------------------------------------


def test_rank_outside_one_to_scored_count_is_refused() -> None:  # noqa: PLR0915
    assert _decode(_ranked_wire()).to_dict() == _ranked_wire()
    assert list(_decode(_ranked_wire()).to_dict()) == list(_ranked_wire())

    unscored = _ranked_wire()
    unscored["members"][3].update(
        status="excluded", reason="no_signal", signals={"field:score": None}, score=None
    )
    del unscored["members"][3]["rank"]
    assert _decode(unscored).members[3].rank is None

    plain = _ranked_wire()
    del plain["cut"]
    for member in plain["members"]:
        del member["rank"]
    assert _decode(plain).cut is None

    def wire_with(member: str, **change: Any) -> dict[str, Any]:
        wire = _ranked_wire()
        for row in wire["members"]:
            if row["member_id"] == member:
                row.update(change)
        return wire

    def without_rank_of_member_4() -> dict[str, Any]:
        wire = _ranked_wire()
        del wire["members"][3]["rank"]
        return wire

    with pytest.raises(ExecutionError, match="rank must be an integer"):
        _decode(wire_with("member_1", rank=True))
    with pytest.raises(ExecutionError, match="rank must be an integer"):
        _decode(wire_with("member_1", rank=1.0))
    for wire in (
        wire_with("member_1", rank=0),
        wire_with("member_1", rank=-1),
        wire_with("member_4", score=None, rank=4),
        wire_with("member_1", rank=1),
        wire_with("member_4", rank=5),
        without_rank_of_member_4(),
    ):
        with pytest.raises(ExecutionError, match="is invalid"):
            _decode(wire)

    assert (
        CombineAnswerRow(
            **{**_ROW, "status": "answered", "reason": None, "score": 0.5, "rank": 1}
        ).rank
        == 1
    )
    with pytest.raises(TypeError):
        CombineAnswerRow(
            **{**_ROW, "status": "answered", "reason": None, "score": 0.5, "rank": True}
        )
    with pytest.raises(ValueError):
        CombineAnswerRow(**{**_ROW, "status": "answered", "reason": None, "score": 0.5, "rank": 0})
    with pytest.raises(ValueError):
        CombineAnswerRow(**{**_ROW, "status": "answered", "reason": None, "score": None, "rank": 1})


# --- ES#7: the cut of a top_k@1 step -------------------------------------------------------------


def test_cut_k_and_order_are_checked() -> None:
    assert CombineCut(k=2, order="max").to_dict() == {"k": 2, "order": "max"}
    assert CombineCut(k=256, order="min").k == 256
    assert _decode(_ranked_wire()).cut == CombineCut(k=2, order="max")

    for k in (0, 257):
        with pytest.raises(ValueError):
            CombineCut(k=k, order="max")
    for k in (True, 2.0):
        bad_k: dict[str, Any] = {"k": k, "order": "max"}
        with pytest.raises(TypeError):
            CombineCut(**bad_k)
    bad_order: dict[str, Any] = {"k": 2, "order": "desc"}
    with pytest.raises(ValueError):
        CombineCut(**bad_order)

    refused: list[dict[str, Any]] = [
        {"k": 0, "order": "max"},
        {"k": 257, "order": "max"},
        {"k": True, "order": "max"},
        {"k": 2.0, "order": "max"},
        {"k": 2, "order": "desc"},
        {"k": 2, "order": None},
        {"k": 2},
        {"k": 2, "order": "max", "x": 1},
    ]
    for cut in refused:
        wire = _ranked_wire()
        wire["cut"] = cut
        with pytest.raises(ExecutionError, match="cut"):
            _decode(wire)


# --- ES#8: the SDK words equal the Engine evidence schema (M x M) -------------------------------


@requires_engine_app
def test_sdk_record_words_equal_the_evidence_schema_enums() -> None:
    pinned = json.loads(
        (COMBINE_CONTRACT / "schemas" / "screamingface.combine-evidence.v1.json").read_text(
            encoding="utf-8"
        )
    )
    record = pinned["$defs"]["AnswerRecord"]

    assert sorted(_words(record["properties"]["status"])) == sorted(MEMBER_STATUSES)
    assert sorted(MEMBER_STATUSES) == ["answered", "excluded", "fail"]
    assert set(_words(record["properties"]["reason"])) == ANSWER_REASONS
    assert len(ANSWER_REASONS) == 12
    assert _words(pinned["$defs"]["CutRecord"]["properties"]["order"]) == sorted(SIGNAL_ORDERS)
    assert sorted(SIGNAL_ORDERS) == ["max", "min"]
    assert ANSWER_STATUSES == {"answered", "abstain", "fail", "excluded"}
    assert "RecordStatus" in (screamingface.answer.__doc__ or "")
    assert "ExcludeReason" in (screamingface.answer.__doc__ or "")


# --- ES#9: dropped counts the failed members, not the excluded ones ------------------------------


def test_dropped_does_not_count_excluded_members() -> None:
    wire = _excluded_wire()
    wire["members"].append(
        {
            "member_id": "member_4",
            "raw": None,
            "value": None,
            "status": "fail",
            "reason": "empty",
            "signals": {"field:confidence": None},
            "weight": None,
            "score": None,
        }
    )
    wire["dropped"] = 1
    assert _decode(wire).dropped == 1

    wire["dropped"] = 2
    with pytest.raises(ExecutionError, match="is invalid"):
        _decode(wire)


# --- ES#11: the decoder still refuses unknown keys -----------------------------------------------


def test_sdk_decoder_still_refuses_unknown_keys() -> None:
    assert _decode(_ranked_wire()).cut == CombineCut(k=2, order="max")

    def mutated(change: Any) -> dict[str, Any]:
        wire = _ranked_wire()
        change(wire)
        return wire

    refused = [
        mutated(lambda wire: wire.update(bogus=1)),
        mutated(lambda wire: wire["members"][0].update(bogus=1)),
        mutated(lambda wire: wire["result"].update(rank=1)),
        mutated(lambda wire: wire["members"][0].update(cut={"k": 2, "order": "max"})),
        mutated(lambda wire: wire["cut"].update(bogus=1)),
    ]
    for wire in refused:
        with pytest.raises(ExecutionError, match="unsupported field"):
            _decode(wire)


# --- ES#13: the trace extract entry shows the excluded status -----------------------------------


def test_trace_extract_entry_carries_the_excluded_status() -> None:
    case, count = _fixture_case("excluded", _excluded_wire())
    assert count == 3

    extracts = [entry.to_dict() for entry in case.trace() if entry.kind == "extract"]
    assert extracts[1] == {
        "kind": "extract",
        "operation_id": "op_synthesis_1",
        "member_id": "member_2",
        "rule": ["last_number@1", "numeric@1"],
        "raw": "12",
        "value": "12",
        "status": "excluded",
        "reason": "no_weight",
    }
    assert all(list(entry) == ["kind", *TRACE_FIELDS["extract"]] for entry in extracts)

    reduces = [entry.to_dict() for entry in case.trace() if entry.kind == "reduce"]
    assert reduces[0]["dropped"] == 0


# --- ES#14: the pinned SDK answer schema holds the new words -----------------------------------


def test_answer_v1_and_evidence_v1_snapshots_match() -> None:
    pinned = json.loads((SCHEMAS / "screamingface.answer.v1.json").read_text(encoding="utf-8"))

    assert pinned == {
        "abstain_reason": ["cut_not_met", "no_votes", "output_missing"],
        "fields": ["member_id", "text", "raw", "value", "status", "reason", "signals"],
        "member_status": ["answered", "excluded", "fail"],
        "reason": [
            "cut_not_met",
            "empty",
            "field_missing",
            "missing",
            "no_match",
            "no_signal",
            "no_votes",
            "no_weight",
            "not_json",
            "not_numeric",
            "output_missing",
            "too_large",
        ],
        "signal_order": ["max", "min"],
        "status": ["abstain", "answered", "excluded", "fail"],
    }
    assert ANSWER_SCHEMA == "screamingface.answer.v1"
