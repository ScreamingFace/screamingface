"""The SDK mirror of the abstain band record and the word in_band (E4b part 6, unit 4).

FEATURE: ``sf.report.CombineGate`` holds the optional ``abstain_band`` and the branch ``band``;
the evidence decoder reads them; ``in_band`` is an abstain word on both sides.
STORY: as a researcher, I read from the decoded evidence that a Case abstained because its number
was inside the band, and the SDK writes the same bytes back.
INVARIANT defended: a gate record without a band keeps its part 5 bytes; the decoder is strict
(exact keys, a list of two numbers); GB-I1 to GB-I4 hold; the SDK words equal the Engine words.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import math
import re
from pathlib import Path
from typing import Any, get_args

import pytest
from _combine_contract import COMBINE_CONTRACT, requires_engine_app

import screamingface as sf
from screamingface import report
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface.answer import ABSTAIN_REASONS, ANSWER_REASONS
from screamingface.combine_evidence import (
    CombineEvidence,
    CombineGate,
    CombineResult,
    GateBranch,
)
from screamingface.errors import ExecutionError

_LABEL = "Case Operation combine"
_T = 0.6666666666666666
_BAND_REASON = "in_band goes with a gate that abstained inside its band, and only with it"
_EVIDENCE_V1 = COMBINE_CONTRACT / "schemas" / "screamingface.combine-evidence.v1.json"
_ANSWER_V1 = Path(__file__).parent / "data" / "schemas" / "screamingface.answer.v1.json"
_SURFACE = Path(__file__).parent / "public_surface_snapshot.json"
_PART5_KEYS = ["observe", "observed", "cmp", "threshold", "passed", "branch", "otherwise"]
_FIVE_WORDS = ["no_votes", "cut_not_met", "output_missing", "gate_not_met", "in_band"]


def _row(member_id: str, value: str) -> dict[str, Any]:
    return {
        "member_id": member_id,
        "raw": value,
        "value": value,
        "status": "answered",
        "reason": None,
        "signals": {},
        "weight": None,
        "score": None,
    }


# AB-2: the shared test data. The Engine test module holds the same values
# (ET/test_combine_band.py REC_BAND_WIRE).
_BAND_WIRE: dict[str, Any] = {
    "schema": "screamingface.combine-evidence.v1",
    "kind": "answer",
    "reducer": "vote",
    "operators": ["last_number@1", "numeric@1", "mode@1", "first_holder@1"],
    "members": [_row("member_1", "9"), _row("member_2", "9"), _row("member_3", "12")],
    "tally": [
        {"value": "9", "score": 2.0, "holders": ["member_1", "member_2"]},
        {"value": "12", "score": 1.0, "holders": ["member_3"]},
    ],
    "judge": None,
    "fields": None,
    "chosen": [],
    "built": False,
    "agreement": _T,
    "tie": False,
    "median": None,
    "presentation_order": None,
    "separator_collision": None,
    "signal": None,
    "gate": {
        "observe": "agreement",
        "observed": _T,
        "cmp": ">=",
        "threshold": 0.7,
        "passed": None,
        "branch": "band",
        "otherwise": "abstain",
        "abstain_band": [0.6, 0.7],
    },
    "result": {"member_id": None, "value": None, "status": "abstain", "reason": "in_band"},
    "dropped": 0,
    "finish_reason": "stop",
}
# A band gate in Python form (observed 0.65 inside (0.6, 0.7)).
_BAND_GATE: dict[str, Any] = {
    "observe": "agreement",
    "observed": 0.65,
    "cmp": ">=",
    "threshold": 0.7,
    "passed": None,
    "branch": "band",
    "otherwise": "abstain",
    "abstain_band": (0.6, 0.7),
}


def _decode(wire: dict[str, Any]) -> CombineEvidence:
    decoded = decode_combine_evidence(copy.deepcopy(wire), _LABEL)
    assert decoded is not None
    return decoded


def _bytes(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _enum_lists(prop: dict[str, Any]) -> list[list[str]]:
    return [branch["enum"] for branch in prop.get("anyOf", [prop]) if "enum" in branch]


def _majority_wire() -> dict[str, Any]:
    """AB-3: band(0.7, 0.9, 0.6, "abstain"): 2/3 is below the band and >= 0.6 keeps member_1."""
    wire = copy.deepcopy(_BAND_WIRE)
    wire["chosen"] = ["member_1"]
    wire["gate"].update(threshold=0.6, passed=True, branch="majority", abstain_band=[0.7, 0.9])
    wire["result"] = {"member_id": "member_1", "value": "9", "status": "answered", "reason": None}
    return wire


def _with_band_gate(**changes: Any) -> dict[str, Any]:
    wire = copy.deepcopy(_BAND_WIRE)
    wire["gate"].update(changes)
    return wire


# --- AB#12 (AB-2): decode and round trip ----------------------------------------------------------


def test_sdk_decodes_and_round_trips_a_band_record() -> None:
    decoded = _decode(_BAND_WIRE)

    assert decoded.gate == CombineGate(
        observe="agreement",
        observed=_T,
        cmp=">=",
        threshold=0.7,
        passed=None,
        branch="band",
        otherwise="abstain",
        abstain_band=(0.6, 0.7),
    )
    assert decoded.gate is not None
    assert decoded.gate.abstain_band == (0.6, 0.7)
    assert decoded.result.reason == "in_band"
    assert decoded.to_dict() == _BAND_WIRE
    assert list(decoded.to_dict()) == list(_BAND_WIRE)
    written = decoded.to_dict()["gate"]
    assert isinstance(written, dict)
    assert list(written) == [*_PART5_KEYS, "abstain_band"]

    listed = CombineGate(**{**_BAND_GATE, "abstain_band": [0, 1]})
    assert listed.abstain_band is not None
    assert listed.abstain_band == (0.0, 1.0)
    assert all(type(value) is float for value in listed.abstain_band)
    plain = CombineGate(
        observe="agreement",
        observed=_T,
        cmp=">=",
        threshold=0.6,
        passed=True,
        branch="majority",
        otherwise="abstain",
    )
    assert plain.abstain_band is None
    assert list(plain.to_dict()) == _PART5_KEYS
    majority = _majority_wire()
    assert _decode(majority).to_dict() == majority


# --- AB#13 (AB-E2, AB-E3 twins): the SDK refuses bad band records ---------------------------------

_INSIDE = "Combine gate band branch observed a number inside its band"
_GATE_REFUSALS: tuple[tuple[dict[str, Any], type[Exception], str], ...] = (
    ({"passed": False}, ValueError, "Combine gate in its band made no comparison"),
    ({"abstain_band": None}, ValueError, _INSIDE),
    ({"observed": 0.8}, ValueError, _INSIDE),
    (
        {"passed": True, "branch": "majority"},
        ValueError,
        "Combine gate that compared observed a number outside its band",
    ),
    (
        {"abstain_band": (0.7, 0.6), "passed": True, "branch": "majority", "observed": 0.8},
        ValueError,
        "Combine gate band is two numbers lo <= hi",
    ),
    ({"abstain_band": (True, 0.7)}, TypeError, "Combine gate abstain_band must be a finite number"),
    (
        {"abstain_band": (0.6, math.nan)},
        ValueError,
        "Combine gate abstain_band must be a finite number",
    ),
    ({"abstain_band": (0.6,)}, TypeError, "Combine gate abstain_band must be two finite numbers"),
    ({"abstain_band": "ab"}, TypeError, "Combine gate abstain_band must be two finite numbers"),
    # The part 5 inputs keep their part 5 messages.
    (
        {"abstain_band": None, "passed": True, "branch": "fallback"},
        ValueError,
        "Combine gate that passed keeps the majority, and only it does",
    ),
    (
        {"abstain_band": None, "passed": None, "branch": "majority"},
        ValueError,
        "Combine gate has a branch exactly when it has a comparison result",
    ),
    (
        {"abstain_band": None, "passed": None, "branch": None, "observed": 0.5},
        ValueError,
        "Combine gate that did not run observed no number",
    ),
)
_DECODER_REFUSALS: tuple[tuple[dict[str, Any], str], ...] = (
    (_with_band_gate(note=1), "gate contains unsupported field 'note'"),
    (_with_band_gate(abstain_band=[0.6]), "gate abstain_band must be two numbers"),
    (_with_band_gate(abstain_band=[0.1, 0.2, 0.3]), "gate abstain_band must be two numbers"),
    (_with_band_gate(abstain_band=[True, 0.7]), "gate abstain_band must be a number"),
    (_with_band_gate(abstain_band=None), "gate abstain_band must be a list"),
    (_with_band_gate(abstain_band="0.6,0.7"), "gate abstain_band must be a list"),
    (_with_band_gate(observed=0.8), _INSIDE),
)


def test_sdk_refuses_bad_band_records() -> None:
    # The valid forms first, so a decoder or a record that refuses every band fails here.
    base = _decode(_BAND_WIRE)
    CombineGate(**_BAND_GATE)

    for changes, error, rule in _GATE_REFUSALS:
        with pytest.raises(error, match=re.escape(rule)):
            CombineGate(**{**_BAND_GATE, **changes})

    band_gate = base.gate
    assert band_gate is not None
    fallback = dataclasses.replace(
        band_gate, passed=False, branch="fallback", abstain_band=(0.7, 0.9)
    )
    not_met = CombineResult(member_id=None, value=None, status="abstain", reason="gate_not_met")
    for change in ({"gate": fallback}, {"result": not_met}, {"gate": None}):
        with pytest.raises(ValueError, match=re.escape(_BAND_REASON)):
            dataclasses.replace(base, **change)

    for wire, rule in _DECODER_REFUSALS:
        with pytest.raises(ExecutionError, match=re.escape(rule)):
            decode_combine_evidence(wire, _LABEL)


# --- AB#14 (AB-D8): the SDK words equal the Engine words ------------------------------------------


@requires_engine_app
def test_sdk_reason_words_equal_the_engine_enum_with_in_band() -> None:
    pinned = json.loads(_EVIDENCE_V1.read_text(encoding="utf-8"))
    answer_reason = pinned["$defs"]["AnswerRecord"]["properties"]["reason"]
    result_reason = pinned["$defs"]["ResultRecord"]["properties"]["reason"]

    assert {word for words in _enum_lists(answer_reason) for word in words} == ANSWER_REASONS
    assert len(ANSWER_REASONS) == 15
    assert {word for words in _enum_lists(result_reason) for word in words} == ABSTAIN_REASONS
    assert ABSTAIN_REASONS == set(_FIVE_WORDS)
    assert get_args(GateBranch.__value__) == ("majority", "fallback", "band")
    answer = sf.Answer(
        member_id=None,
        text="",
        raw=None,
        value=None,
        status="abstain",
        reason="in_band",
        signals={},
    )
    assert answer.to_dict()["reason"] == "in_band"
    result = CombineResult(member_id=None, value=None, status="abstain", reason="in_band")
    assert result.to_dict()["reason"] == "in_band"


# --- AB#15, unit 4 half (PIN): the evidence v1 and answer.v1 snapshots hold the band --------------


@requires_engine_app
def test_evidence_and_answer_snapshots_hold_the_band() -> None:
    pinned = json.loads(_EVIDENCE_V1.read_text(encoding="utf-8"))
    record = pinned["$defs"]["GateRecord"]
    answer_v1 = json.loads(_ANSWER_V1.read_text(encoding="utf-8"))

    assert record["properties"]["abstain_band"] == {
        "anyOf": [
            {"items": {"type": "number"}, "maxItems": 2, "minItems": 2, "type": "array"},
            {"type": "null"},
        ],
        "default": None,
        "title": "Abstain Band",
    }
    assert record["required"] == _PART5_KEYS
    assert record["properties"]["branch"] == {
        "anyOf": [{"enum": ["majority", "fallback", "band"], "type": "string"}, {"type": "null"}],
        "title": "Branch",
    }
    answer_reason = _enum_lists(pinned["$defs"]["AnswerRecord"]["properties"]["reason"])
    assert answer_reason[0][-2:] == ["gate_not_met", "in_band"]
    assert _enum_lists(pinned["$defs"]["ResultRecord"]["properties"]["reason"]) == [_FIVE_WORDS]
    assert answer_v1["abstain_reason"] == sorted(_FIVE_WORDS)
    assert answer_v1["abstain_reason"] == [
        "cut_not_met",
        "gate_not_met",
        "in_band",
        "no_votes",
        "output_missing",
    ]
    assert answer_v1["reason"] == [
        "cut_not_met",
        "empty",
        "field_missing",
        "gate_not_met",
        "in_band",
        "missing",
        "no_match",
        "no_signal",
        "no_votes",
        "no_weight",
        "not_json",
        "not_numeric",
        "not_selected",
        "output_missing",
        "too_large",
    ]


# --- AB#16 (PIN): the contract case vote_gate_band on both sides ----------------------------------


@requires_engine_app
def test_contract_case_vote_gate_band_is_byte_equal_on_both_sides() -> None:
    cases = json.loads((COMBINE_CONTRACT / "evidence_cases.json").read_text(encoding="utf-8"))
    assert "vote_gate_band" in cases, "regenerate evidence_cases.json (E4b part 6 unit 4)"
    wire = cases["vote_gate_band"]

    assert _bytes(wire) == _bytes(_BAND_WIRE)
    decoded = decode_combine_evidence(wire, "Engine evidence vote_gate_band")
    assert decoded is not None
    assert _bytes(decoded.to_dict()) == _bytes(wire)


# --- AB#18 (PIN): the public surface holds CombineGate.abstain_band -------------------------------


def test_public_surface_holds_the_combine_gate_band() -> None:
    snapshot = json.loads(_SURFACE.read_text(encoding="utf-8"))
    members = snapshot["screamingface.report"]["exports"]["CombineGate"]["members"]

    assert report.CombineGate is CombineGate
    assert members["abstain_band"] == "field"
    assert members["__init__"] == (
        "method (self, observe: 'str', observed: 'float | None', cmp: 'GateCmp', "
        "threshold: 'float', passed: 'bool | None', branch: 'GateBranch | None', "
        "otherwise: 'GateOtherwise', abstain_band: 'tuple[float, float] | None' = None) -> None"
    )
