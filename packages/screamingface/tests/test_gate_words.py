"""The SDK mirror of the gate record and the reserved verifier key (E4b part 5, unit 1).

FEATURE: ``sf.report.CombineGate`` holds what the gate of a vote compared and the branch the step
took; the evidence decoder reads the optional ``gate`` record and accepts the reserved
``verifier`` key only as null; the spec decoder accepts the optional spec key ``gate``.
STORY: as a researcher, I read the gate of a Case from the decoded evidence, and the SDK writes
the same bytes back.
INVARIANT defended: an evidence without a gate keeps its v1 bytes; the decoder is strict (exact
keys, known words, GR-I1, GR-I2, GR-I4, GR-I5); ``verifier`` is null only and is not kept.
AIDEV-NOTE: unit 2 appends its tests (the word ``gate_not_met``, GR-I3) to this file. Do not
edit the tests above its marker.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, requires_engine_app

import screamingface as sf
from screamingface import report
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface._evaluation.combine_spec import decode_combine_spec
from screamingface.answer import ABSTAIN_REASONS, ANSWER_REASONS
from screamingface.combine_evidence import CombineEvidence, CombineGate, CombineResult
from screamingface.errors import ExecutionError

_LABEL = "Case Operation combine"
_EVIDENCE_CASES: dict[str, Any] = (
    json.loads((COMBINE_CONTRACT / "evidence_cases.json").read_text(encoding="utf-8"))
    if ENGINE_APP.exists()
    else {}
)
# test-plan §6 L32: the 32 evidence case names on base 4e622af75. A fixed list, never the file.
L32 = (
    "argmax_cost_min",
    "concat_collision",
    "filter_none_pass",
    "filter_pattern",
    "filter_signal_excluded",
    "filter_threshold",
    "judge_label",
    "judge_scores",
    "mean_weighted_value",
    "median_nearest",
    "median_value",
    "merge_abstain",
    "merge_model_field",
    "pick",
    "pick_output",
    "pick_output_missing",
    "projection",
    "rank_by_judge",
    "rank_by_signal",
    "rank_cut_not_met",
    "rank_min_cost",
    "rank_reduce_abstain",
    "regex_no_match",
    "set_normalized",
    "vote_abstain",
    "vote_cost_signal",
    "vote_field_signal",
    "vote_judge_weights",
    "vote_one_failed",
    "vote_tie",
    "vote_weight_excluded",
    "vote_weighted",
)

# The shared test data. The Engine test module holds the same values
# (ET/test_combine_gate_words.py).
_GATE: dict[str, Any] = {
    "observe": "agreement",
    "observed": 0.6666666666666666,
    "cmp": ">=",
    "threshold": 0.6,
    "passed": True,
    "branch": "majority",
    "otherwise": "abstain",
}
_NOT_RUN_GATE: dict[str, Any] = {
    "observe": "agreement",
    "observed": None,
    "cmp": ">=",
    "threshold": 0.6,
    "passed": None,
    "branch": None,
    "otherwise": "judge",
}
_CONF = {"pattern": "Confidence: ([0-9]+)", "source": "verbalized"}
_SPEC_TEXT = (
    '{"extract":{"args":{},"op":"last_line@1"},'
    '"gate":{"cmp":">=","observe":"agreement","otherwise":"abstain","threshold":0.7},'
    '"members":["member_1","member_2","member_3"],"normalize":{"args":{},"op":"text@1"},'
    '"reduce":{"args":{},"op":"mode@1"},"reducer":"vote",'
    '"schema":"screamingface.combine-spec.v1","select":{"args":{},"op":"first_holder@1"},'
    '"weights":null}'
)


def _row(member_id: str, raw: str, value: str) -> dict[str, Any]:
    return {
        "member_id": member_id,
        "raw": raw,
        "value": value,
        "status": "answered",
        "reason": None,
        "signals": {},
        "weight": None,
        "score": None,
    }


def _gate_wire() -> dict[str, Any]:
    """Fixture V of gate-decision §3 on the majority branch (GR-2, GR-3).

    Oracle by hand: the texts "A", "A", "B" give the values "a", "a", "b"; the tally is
    a: 2.0 [member_1, member_2], b: 1.0 [member_3]; agreement = 2/3 = 0.6666666666666666 >= 0.6,
    so the gate passes and the answer is member_1.
    """
    return {
        "schema": "screamingface.combine-evidence.v1",
        "kind": "answer",
        "reducer": "vote",
        "operators": ["last_line@1", "text@1", "mode@1", "first_holder@1"],
        "members": [
            _row("member_1", "A", "a"),
            _row("member_2", "A", "a"),
            _row("member_3", "B", "b"),
        ],
        "tally": [
            {"value": "a", "score": 2.0, "holders": ["member_1", "member_2"]},
            {"value": "b", "score": 1.0, "holders": ["member_3"]},
        ],
        "judge": None,
        "fields": None,
        "chosen": ["member_1"],
        "built": False,
        "agreement": 0.6666666666666666,
        "tie": False,
        "median": None,
        "presentation_order": None,
        "separator_collision": None,
        "signal": None,
        "gate": dict(_GATE),
        "result": {"member_id": "member_1", "value": "a", "status": "answered", "reason": None},
        "dropped": 0,
        "finish_reason": "stop",
    }


def _writer_fallback_wire() -> dict[str, Any]:
    """GD-4: threshold 0.7 fails (2/3 < 0.7); the writer text "C written" is the built answer."""
    wire = _gate_wire()
    wire["gate"].update(threshold=0.7, passed=False, branch="fallback", otherwise="writer")
    wire.update(
        chosen=[],
        built=True,
        result={"member_id": None, "value": "c written", "status": "answered", "reason": None},
    )
    return wire


def _judge_fallback_wire() -> dict[str, Any]:
    """GD-3: threshold 0.7 fails; the label judge names member_3, whose text is the answer."""
    wire = _gate_wire()
    wire["gate"].update(threshold=0.7, passed=False, branch="fallback", otherwise="judge")
    wire.update(
        chosen=["member_3"],
        judge={"raw": " member_3\n", "returns": "label", "parsed": "member_3"},
        presentation_order="author",
        result={"member_id": "member_3", "value": "b", "status": "answered", "reason": None},
    )
    return wire


def _not_run_wire() -> dict[str, Any]:
    """GD-D1: no voter, so the vote abstains with no_votes and the gate does not run."""
    failed = {
        "raw": None,
        "value": None,
        "status": "fail",
        "reason": "empty",
        "signals": {},
        "weight": None,
        "score": None,
    }
    wire = _gate_wire()
    wire.update(
        members=[{"member_id": f"member_{index}", **failed} for index in (1, 2, 3)],
        tally=None,
        chosen=[],
        agreement=None,
        gate=dict(_NOT_RUN_GATE),
        result={"member_id": None, "value": None, "status": "abstain", "reason": "no_votes"},
        dropped=3,
    )
    return wire


def _all_optional_wire() -> dict[str, Any]:
    """GR-D1: signal, cut, declared and gate all set, in the order of the wire."""
    wire = _gate_wire()
    for row in wire["members"]:
        row["signals"] = {"conf": None}
    ordered: dict[str, Any] = {}
    for key, value in wire.items():
        if key == "gate":
            ordered["cut"] = {"k": 1, "order": "max"}
            ordered["declared"] = {"conf": dict(_CONF)}
        ordered[key] = value
    ordered["signal"] = {"key": "conf", "order": None}
    return ordered


def _decode(wire: dict[str, Any]) -> CombineEvidence:
    decoded = decode_combine_evidence(copy.deepcopy(wire), _LABEL)
    assert decoded is not None
    return decoded


# --- GR#1 (SDK half): existing evidence keeps its bytes and has no gate (CHAR) -----------------


@requires_engine_app
def test_existing_evidence_has_no_gate_key_after_the_sdk_round_trip() -> None:
    for name in L32:
        wire = _EVIDENCE_CASES[name]
        written = _decode(wire).to_dict()
        assert written == wire, name
        assert list(written) == list(wire), name
        assert "gate" not in written, name
        assert "verifier" not in written, name


# --- GR#9: the SDK decodes a gate record and writes the same wire back -------------------------


def test_sdk_decodes_and_round_trips_a_gate_record() -> None:
    assert report.CombineGate is CombineGate
    wire = _gate_wire()

    decoded = _decode(wire)

    assert decoded.gate == CombineGate(
        observe="agreement",
        observed=0.6666666666666666,
        cmp=">=",
        threshold=0.6,
        passed=True,
        branch="majority",
        otherwise="abstain",
    )
    assert decoded.to_dict() == wire
    assert list(decoded.to_dict()) == list(wire)
    written_gate = decoded.to_dict()["gate"]
    assert isinstance(written_gate, dict)
    assert list(written_gate) == list(_GATE)
    assert CombineGate(**_GATE).to_dict() == _GATE
    whole = CombineGate(**{**_GATE, "threshold": 1})
    assert type(whole.threshold) is float
    assert whole.threshold == 1.0
    for other in (
        _writer_fallback_wire(),
        _judge_fallback_wire(),
        _not_run_wire(),
        _all_optional_wire(),
    ):
        assert _decode(other).to_dict() == other
        assert list(_decode(other).to_dict()) == list(other)


# --- GR#10: the decoder refuses a bad gate record ----------------------------------------------


def _with_gate(**changes: Any) -> dict[str, Any]:
    wire = _gate_wire()
    wire["gate"].update(changes)
    return wire


def _without_otherwise() -> dict[str, Any]:
    wire = _gate_wire()
    del wire["gate"]["otherwise"]
    return wire


def _writer_not_built() -> dict[str, Any]:
    wire = _writer_fallback_wire()
    wire["built"] = False
    return wire


def _judge_without_reading() -> dict[str, Any]:
    wire = _judge_fallback_wire()
    wire.update(judge=None, presentation_order=None)
    return wire


def _judge_picks_excluded() -> dict[str, Any]:
    wire = _judge_fallback_wire()
    wire["members"][2].update(status="excluded", reason="no_weight")
    return wire


def _not_run_but_answered() -> dict[str, Any]:
    wire = _gate_wire()
    wire["gate"] = dict(_NOT_RUN_GATE)
    return wire


@pytest.mark.parametrize(
    ("wire", "rule"),
    [
        pytest.param(_with_gate(note=1), "gate contains unsupported field 'note'", id="extra-key"),
        pytest.param(_without_otherwise(), "gate is missing 'otherwise'", id="missing-key"),
        pytest.param(_with_gate(passed="no"), "gate passed must be a boolean", id="passed-no"),
        pytest.param(
            _with_gate(branch="maybe"),
            "Combine gate branch must be one of fallback, majority",
            id="branch-maybe",
        ),
        pytest.param(
            _with_gate(observed=0.5, threshold=0.4),
            "Combine evidence agreement gate observes the evidence agreement",
            id="gr-i4",
        ),
        pytest.param(
            _writer_not_built(),
            "Combine evidence writer fallback builds the answer and chooses no member",
            id="gr-i5-writer",
        ),
        pytest.param(
            _judge_without_reading(),
            "Combine evidence judge fallback records its label reading and chooses that member",
            id="gr-i5-judge",
        ),
        pytest.param(_judge_picks_excluded(), "which is excluded", id="judge-picks-excluded"),
        pytest.param(
            _not_run_but_answered(),
            "Combine evidence gate that did not run goes with an abstained result",
            id="gr-i1",
        ),
    ],
)
def test_sdk_decoder_refuses_bad_gate_records(wire: dict[str, Any], rule: str) -> None:
    # The valid fallback forms first, so a decoder that refuses every gate fails here.
    for valid in (_gate_wire(), _writer_fallback_wire(), _judge_fallback_wire()):
        assert _decode(valid).to_dict() == valid

    with pytest.raises(ExecutionError, match=re.escape(rule)):
        decode_combine_evidence(wire, _LABEL)


# --- GR#11: CombineGate refuses bad values ------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "error", "rule"),
    [
        ({"observed": float("nan")}, ValueError, "Combine gate observed must be a finite number"),
        ({"threshold": True}, TypeError, "Combine gate threshold must be a finite number"),
        (
            {"observe": "chosen:Cost"},
            ValueError,
            "Combine gate observe must be agreement, chosen:<name> or mean:<name>",
        ),
        (
            {"observe": "chosen:cost_usd"},
            ValueError,
            "Combine gate observe must be agreement, chosen:<name> or mean:<name>",
        ),
        ({"observe": 3}, TypeError, "Combine gate observe must be text"),
        ({"cmp": "=>"}, ValueError, "Combine gate cmp must be one of <, <=, >, >="),
        ({"passed": "yes"}, TypeError, "Combine gate passed must be a bool"),
        (
            {"otherwise": "retry"},
            ValueError,
            "Combine gate otherwise must be one of abstain, judge, writer",
        ),
        (
            {"passed": True, "branch": "fallback"},
            ValueError,
            "Combine gate that passed keeps the majority, and only it does",
        ),
        (
            {"passed": None, "branch": "majority"},
            ValueError,
            "Combine gate has a branch exactly when it has a comparison result",
        ),
        (
            {"passed": None, "branch": None, "observed": 0.5},
            ValueError,
            "Combine gate that did not run observed no number",
        ),
    ],
    ids=[
        "observed-nan",
        "threshold-bool",
        "observe-upper",
        "observe-e4a-key",
        "observe-not-text",
        "cmp-unknown",
        "passed-text",
        "otherwise-retry",
        "gr-i2",
        "gr-i1-branch",
        "gr-i1-observed",
    ],
)
def test_sdk_combine_gate_refuses_bad_values(
    changes: dict[str, Any], error: type[Exception], rule: str
) -> None:
    with pytest.raises(error, match=re.escape(rule)):
        CombineGate(**{**_GATE, **changes})


# --- GR#17: the spec decoder accepts a gate object and refuses any other gate -----------------


def test_sdk_spec_decoder_accepts_a_gate_dict_and_refuses_a_gate_list() -> None:
    spec = decode_combine_spec(_SPEC_TEXT)

    assert spec["gate"] == {
        "cmp": ">=",
        "observe": "agreement",
        "otherwise": "abstain",
        "threshold": 0.7,
    }
    for bad in ("[1]", "null", '"agreement"'):
        text = _SPEC_TEXT.replace(
            '{"cmp":">=","observe":"agreement","otherwise":"abstain","threshold":0.7}', bad
        )
        with pytest.raises(ValueError, match="URL4 Candidate has an invalid combine spec"):
            decode_combine_spec(text)


# --- VS#3: the decoder accepts a null verifier, drops it, and refuses any other value ----------


def test_sdk_decoder_accepts_a_null_verifier_and_refuses_any_other_value() -> None:
    decoded = _decode({**_gate_wire(), "verifier": None})

    assert decoded.to_dict() == _gate_wire()
    assert "verifier" not in decoded.to_dict()
    for value in ({}, "ok", False):
        with pytest.raises(ExecutionError, match="verifier is reserved and must be null"):
            decode_combine_evidence({**_gate_wire(), "verifier": value}, _LABEL)


# E4b part 5 unit 2: the whole evidence of a gate abstain on fixture V (the GR-I3 base wire).
_GATE_ABSTAIN_WIRE: dict[str, Any] = {
    "schema": "screamingface.combine-evidence.v1",
    "kind": "answer",
    "reducer": "vote",
    "operators": ["last_line@1", "text@1", "mode@1", "first_holder@1"],
    "members": [
        {
            "member_id": "member_1",
            "raw": "A",
            "value": "a",
            "status": "answered",
            "reason": None,
            "signals": {},
            "weight": None,
            "score": None,
        },
        {
            "member_id": "member_2",
            "raw": "A",
            "value": "a",
            "status": "answered",
            "reason": None,
            "signals": {},
            "weight": None,
            "score": None,
        },
        {
            "member_id": "member_3",
            "raw": "B",
            "value": "b",
            "status": "answered",
            "reason": None,
            "signals": {},
            "weight": None,
            "score": None,
        },
    ],
    "tally": [
        {"value": "a", "score": 2.0, "holders": ["member_1", "member_2"]},
        {"value": "b", "score": 1.0, "holders": ["member_3"]},
    ],
    "judge": None,
    "fields": None,
    "chosen": [],
    "built": False,
    "agreement": 0.6666666666666666,
    "tie": False,
    "median": None,
    "presentation_order": None,
    "separator_collision": None,
    "signal": None,
    "gate": {
        "observe": "agreement",
        "observed": 0.6666666666666666,
        "cmp": ">=",
        "threshold": 0.7,
        "passed": False,
        "branch": "fallback",
        "otherwise": "abstain",
    },
    "result": {"member_id": None, "value": None, "status": "abstain", "reason": "gate_not_met"},
    "dropped": 0,
    "finish_reason": "stop",
}
_EVIDENCE_V1 = COMBINE_CONTRACT / "schemas" / "screamingface.combine-evidence.v1.json"
_ANSWER_V1 = Path(__file__).parent / "data" / "schemas" / "screamingface.answer.v1.json"
_GATE_NOT_MET_WORDS = {"no_votes", "cut_not_met", "output_missing", "gate_not_met"}


def _enum_lists(prop: dict[str, Any]) -> list[list[str]]:
    return [branch["enum"] for branch in prop.get("anyOf", [prop]) if "enum" in branch]


# --- GR#12 (unit 2) -------------------------------------------------------------------------------


def test_sdk_answer_and_result_accept_gate_not_met() -> None:
    answer = sf.Answer(
        member_id=None,
        text="",
        raw=None,
        value=None,
        status="abstain",
        reason="gate_not_met",
        signals={},
    )
    result = CombineResult(member_id=None, value=None, status="abstain", reason="gate_not_met")

    assert answer.to_dict()["reason"] == "gate_not_met"
    assert result.to_dict() == {
        "member_id": None,
        "value": None,
        "status": "abstain",
        "reason": "gate_not_met",
    }
    assert "gate_not_met" in ABSTAIN_REASONS
    assert "gate_not_met" in ANSWER_REASONS


# --- GR#14 (unit 2) -------------------------------------------------------------------------------


@requires_engine_app
def test_sdk_reason_words_equal_the_engine_enum() -> None:
    pinned = json.loads(_EVIDENCE_V1.read_text(encoding="utf-8"))
    answer_reason = pinned["$defs"]["AnswerRecord"]["properties"]["reason"]
    result_reason = pinned["$defs"]["ResultRecord"]["properties"]["reason"]

    assert {word for words in _enum_lists(answer_reason) for word in words} == ANSWER_REASONS
    assert len(ANSWER_REASONS) == 13
    assert {word for words in _enum_lists(result_reason) for word in words} == ABSTAIN_REASONS
    assert ABSTAIN_REASONS == _GATE_NOT_MET_WORDS


# --- GR#15 (unit 2, PIN) --------------------------------------------------------------------------


@requires_engine_app
def test_schema_snapshots_hold_gate_not_met() -> None:
    pinned = json.loads(_EVIDENCE_V1.read_text(encoding="utf-8"))
    answer_reason = _enum_lists(pinned["$defs"]["AnswerRecord"]["properties"]["reason"])[0]
    result_reason = _enum_lists(pinned["$defs"]["ResultRecord"]["properties"]["reason"])[0]
    answer_v1 = json.loads(_ANSWER_V1.read_text(encoding="utf-8"))

    assert answer_reason[-2:] == ["output_missing", "gate_not_met"]
    assert result_reason == ["no_votes", "cut_not_met", "output_missing", "gate_not_met"]
    assert answer_v1["abstain_reason"] == [
        "cut_not_met",
        "gate_not_met",
        "no_votes",
        "output_missing",
    ]
    assert "gate_not_met" in answer_v1["reason"]


# --- GR#16 (unit 2): GR-I3 on the SDK CombineEvidence ---------------------------------------------


def test_sdk_gate_not_met_needs_a_fallback_abstain_gate() -> None:
    base = decode_combine_evidence(copy.deepcopy(_GATE_ABSTAIN_WIRE), "gate abstain")
    assert base is not None
    assert base.result.reason == "gate_not_met"
    abstain_gate = base.gate
    assert abstain_gate is not None
    majority = dataclasses.replace(abstain_gate, passed=True, branch="majority")
    judge = dataclasses.replace(abstain_gate, otherwise="judge")
    answered = CombineResult(member_id="member_1", value="a", status="answered", reason=None)
    broken = [
        {"gate": None},
        {"gate": majority},
        {"gate": judge},
        {"result": answered, "chosen": ("member_1",)},
    ]

    for change in broken:
        with pytest.raises(ValueError, match="gate_not_met goes with"):
            dataclasses.replace(base, **change)
