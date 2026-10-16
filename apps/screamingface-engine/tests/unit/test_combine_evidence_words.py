"""The part 2 words and wire keys of the Engine evidence (E4b part 2, unit 1).

FEATURE: an evidence record can say a member was "excluded" by a rule of the combine step, with
the reason "no_signal" or "no_weight"; a top_k@1 step writes the member ``rank`` and the evidence
``cut``.
STORY: as a researcher, I can read which members a step left out and why, and in what order a
top-k step ranked them.
INVARIANT defended: an evidence without a new value keeps its v1 bytes; each refusal names the
rule it breaks; the ranks of one evidence are 1..n over the members with a score; a failed
member is never counted as excluded in ``dropped``. The schema ids do not change (ans:Q5).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from screamingface_engine.combine.evidence import (
    COMBINE_EVIDENCE_SCHEMA,
    AnswerRecord,
    CombineEvidence,
)

SCHEMAS = Path(__file__).parent / "data" / "combine_contract" / "schemas"
EVIDENCE_CASES = json.loads(
    (Path(__file__).parent / "data" / "combine_contract" / "evidence_cases.json").read_text(
        encoding="utf-8"
    )
)

# The shared test data. The SDK test module holds the same values (ST/test_evidence_words.py).


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


def _valid(wire: dict[str, Any]) -> CombineEvidence:
    return CombineEvidence.model_validate(copy.deepcopy(wire))


def _bytes(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


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


# --- ES#1: an evidence without a new value keeps its v1 bytes (CHAR) ---------------------------


@pytest.mark.parametrize("name", sorted(EVIDENCE_CASES))
def test_evidence_without_new_values_keeps_v1_bytes(name: str) -> None:
    wire = EVIDENCE_CASES[name]

    assert _bytes(_valid(wire).model_dump(by_alias=True)) == _bytes(wire)


# --- ES#2: an excluded record with an exclude reason ---------------------------------------------


def test_answer_record_accepts_excluded_with_an_exclude_reason() -> None:
    record = AnswerRecord.model_validate(_ROW)

    assert record.model_dump() == _ROW
    assert list(record.model_dump()) == list(_ROW)
    assert AnswerRecord.model_validate({**_ROW, "reason": "no_signal"}).model_dump() == {
        **_ROW,
        "reason": "no_signal",
    }


# --- ES#3: excluded needs an exclude reason ------------------------------------------------------


def test_answer_record_refuses_excluded_without_an_exclude_reason() -> None:
    assert AnswerRecord.model_validate(_ROW).status == "excluded"

    for reason in (None, "missing", "no_votes"):
        with pytest.raises(ValidationError):
            AnswerRecord.model_validate({**_ROW, "reason": reason})
    with pytest.raises(ValidationError, match="exclude reason"):
        AnswerRecord.model_validate({**_ROW, "reason": "empty"})


# --- ES#4: an exclude reason belongs to an excluded member only ----------------------------------


def test_answer_record_refuses_an_exclude_reason_on_a_failed_member() -> None:
    failed = {**_ROW, "status": "fail", "reason": "empty", "value": None, "raw": None}
    assert AnswerRecord.model_validate(failed).status == "fail"
    assert AnswerRecord.model_validate({**_ROW, "reason": "no_signal"}).reason == "no_signal"

    with pytest.raises(ValidationError):
        AnswerRecord.model_validate({**failed, "reason": "no_signal"})
    with pytest.raises(ValidationError):
        AnswerRecord.model_validate({**failed, "reason": "no_weight"})
    with pytest.raises(ValidationError):
        AnswerRecord.model_validate({**_ROW, "status": "answered", "reason": "no_signal"})


# --- ES#6: the member rank and its 1..n rule -----------------------------------------------------


def test_rank_outside_one_to_scored_count_is_refused() -> None:  # noqa: PLR0915
    assert _bytes(_valid(_ranked_wire()).model_dump(by_alias=True)) == _bytes(_ranked_wire())

    # A member without a score has no rank; n counts only the members with a score.
    unscored = _ranked_wire()
    unscored["members"][3].update(
        status="excluded", reason="no_signal", signals={"field:score": None}, score=None
    )
    del unscored["members"][3]["rank"]
    assert _valid(unscored).members[3].rank is None

    # Without any rank and without a cut, the evidence is still valid.
    plain = _ranked_wire()
    del plain["cut"]
    for member in plain["members"]:
        del member["rank"]
    assert _valid(plain).cut is None

    def wire_with(member: str, **change: Any) -> dict[str, Any]:
        wire = _ranked_wire()
        for row in wire["members"]:
            if row["member_id"] == member:
                row.update(change)
        return wire

    with pytest.raises(ValidationError, match="positive integer"):
        _valid(wire_with("member_1", rank=0))
    with pytest.raises(ValidationError, match="positive integer"):
        _valid(wire_with("member_1", rank=-1))
    with pytest.raises(ValidationError):
        _valid(wire_with("member_1", rank=True))
    with pytest.raises(ValidationError):
        _valid(wire_with("member_1", rank=1.0))
    with pytest.raises(ValidationError, match="positive integer"):
        _valid(wire_with("member_4", score=None, rank=4))
    with pytest.raises(ValidationError, match="1..n"):
        _valid(wire_with("member_1", rank=1))
    with pytest.raises(ValidationError, match="1..n"):
        _valid(wire_with("member_4", rank=5))
    with pytest.raises(ValidationError, match="1..n"):
        bad = _ranked_wire()
        del bad["members"][3]["rank"]
        _valid(bad)


# --- ES#7: the cut of a top_k@1 step -------------------------------------------------------------


def test_cut_k_and_order_are_checked() -> None:
    for cut in (
        {"k": 1, "order": "max"},
        {"k": 256, "order": "max"},
        {"k": 2, "order": "min"},
    ):
        wire = _ranked_wire()
        wire["cut"] = cut
        assert _valid(wire).model_dump(by_alias=True)["cut"] == cut

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
        with pytest.raises(ValidationError, match="cut"):
            _valid(wire)


# --- ES#9: a failed member is counted in dropped, an excluded member is not ----------------------


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
    assert _valid(wire).dropped == 1

    wire["dropped"] = 2
    with pytest.raises(ValidationError, match="dropped must count the failed members"):
        _valid(wire)


# --- ES#14: the pinned v1 schemas hold the new words and keys ------------------------------------


def test_answer_v1_and_evidence_v1_snapshots_match() -> None:
    pinned = json.loads((SCHEMAS / "screamingface.combine-evidence.v1.json").read_text("utf-8"))
    record = pinned["$defs"]["AnswerRecord"]

    assert record["properties"]["status"]["enum"] == ["answered", "fail", "excluded"]
    assert [b["enum"] for b in record["properties"]["reason"]["anyOf"] if "enum" in b] == [
        [
            "empty",
            "not_numeric",
            "not_json",
            "field_missing",
            "too_large",
            "no_match",
            "missing",
            "no_votes",
            "cut_not_met",
            "output_missing",
            "gate_not_met",
        ],
        ["no_signal", "no_weight"],
    ]
    assert record["properties"]["rank"] == {
        "anyOf": [{"type": "integer"}, {"type": "null"}],
        "default": None,
        "title": "Rank",
    }
    assert record["required"] == [
        "member_id",
        "raw",
        "value",
        "status",
        "reason",
        "signals",
        "weight",
        "score",
    ]
    assert pinned["$defs"]["CutRecord"]["properties"] == {
        "k": {"maximum": 256, "minimum": 1, "title": "K", "type": "integer"},
        "order": {"enum": ["max", "min"], "title": "Order", "type": "string"},
    }
    assert pinned["$defs"]["CutRecord"]["required"] == ["k", "order"]
    assert pinned["properties"]["cut"] == {
        "anyOf": [{"$ref": "#/$defs/CutRecord"}, {"type": "null"}],
        "default": None,
    }
    assert "cut" not in pinned["required"]
    assert len(pinned["required"]) == 18

    assert list(AnswerRecord.model_fields)[-2:] == ["score", "rank"]
    fields = list(CombineEvidence.model_fields)
    assert fields[fields.index("signal") + 1] == "cut"
    assert COMBINE_EVIDENCE_SCHEMA == "screamingface.combine-evidence.v1"
