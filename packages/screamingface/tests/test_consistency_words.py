"""The SDK mirror of the consistency record (E4b part 7, unit 1).

FEATURE: ``sf.report.CombineSampleCount`` holds one member's extra samples of the declared
``consistency`` source (``matched``, ``succeeded``, ``failed``); the evidence decoder reads the
optional ``consistency`` record; the spec decoder accepts a consistency entry in ``signals``.
STORY: as a researcher, I read from the decoded evidence how many samples of each member failed
and how many matched, and the SDK writes the same bytes back.
INVARIANT defended: an evidence without consistency keeps its v1 bytes; the decoder is strict
(exact record keys, integer counts, CS-I1..CS-I5); the record sits between ``cut`` and
``declared``.
AIDEV-NOTE: E4b part 7 unit 1 owns this file. Later units write their own test files.
"""

from __future__ import annotations

import copy
import dataclasses
import inspect
import json
import re
from typing import Any

import pytest
from _combine_contract import COMBINE_CONTRACT, ENGINE_APP, requires_engine_app

from screamingface import report
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface._evaluation.combine_spec import decode_combine_spec
from screamingface.combine_evidence import CombineEvidence, CombineSampleCount
from screamingface.errors import ExecutionError

_LABEL = "Case Operation combine"
_EVIDENCE_CASES: dict[str, Any] = (
    json.loads((COMBINE_CONTRACT / "evidence_cases.json").read_text(encoding="utf-8"))
    if ENGINE_APP.exists()
    else {}
)
# test-plan §6 L37: the 37 evidence case names on base 633fec3a1. A fixed list, never the file.
L37 = (
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
    "vote_gate_abstain",
    "vote_gate_judge",
    "vote_gate_majority",
    "vote_gate_not_run",
    "vote_gate_writer",
    "vote_judge_weights",
    "vote_one_failed",
    "vote_tie",
    "vote_weight_excluded",
    "vote_weighted",
)

# The shared test data. The Engine test module holds the same values
# (ET/test_combine_consistency_words.py).
_MATCH: dict[str, Any] = {
    "extract": {"op": "last_number@1", "args": {}},
    "normalize": {"op": "numeric@1", "args": {}},
}
_CONS: dict[str, Any] = {"source": "consistency", "n": 4, "temperature": 1.0, "match": _MATCH}
_CONF = {"pattern": "Confidence: ([0-9]+)", "source": "verbalized"}
_GATE: dict[str, Any] = {
    "observe": "agreement",
    "observed": 0.6666666666666666,
    "cmp": ">=",
    "threshold": 0.6,
    "passed": True,
    "branch": "majority",
    "otherwise": "abstain",
}
# CR-D4: builtin_vote_spec(3) + the consistency entry, as canonical JSON (sorted keys).
_SPEC_TEXT = (
    '{"extract":{"args":{},"op":"last_number@1"},'
    '"members":["member_1","member_2","member_3"],"normalize":{"args":{},"op":"numeric@1"},'
    '"reduce":{"args":{},"op":"mode@1"},"reducer":"vote",'
    '"schema":"screamingface.combine-spec.v1","select":{"args":{},"op":"first_holder@1"},'
    '"signals":{"cons":{"match":{"extract":{"args":{},"op":"last_number@1"},'
    '"normalize":{"args":{},"op":"numeric@1"}},"n":4,"source":"consistency",'
    '"temperature":1.0}},"weights":null}'
)


def _row(member_id: str, raw: str, value: str, cons: float | None) -> dict[str, Any]:
    return {
        "member_id": member_id,
        "raw": raw,
        "value": value,
        "status": "answered",
        "reason": None,
        "signals": {"cons": cons},
        "weight": None,
        "score": None,
    }


def _record(member_id: str, matched: int | None, succeeded: int, failed: int) -> dict[str, Any]:
    return {"member_id": member_id, "matched": matched, "succeeded": succeeded, "failed": failed}


def _consistency_wire() -> dict[str, Any]:
    """CR-3: a vote over "A", "A", "B" with the declared consistency source ``cons`` (n = 4).

    Oracle by hand: member_1 matched 2 of 4 succeeded -> 2 / 4 = 0.5; member_2 matched 2 of 2
    succeeded (2 failed) -> 2 / 2 = 1.0; member_3 had 0 succeeded (4 failed) -> matched null and
    value null. 4 + 0 = 2 + 2 = 0 + 4 = n.
    """
    return {
        "schema": "screamingface.combine-evidence.v1",
        "kind": "answer",
        "reducer": "vote",
        "operators": ["last_line@1", "text@1", "mode@1", "first_holder@1"],
        "members": [
            _row("member_1", "A", "a", 0.5),
            _row("member_2", "A", "a", 1.0),
            _row("member_3", "B", "b", None),
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
        "consistency": {
            "cons": [
                _record("member_1", 2, 4, 0),
                _record("member_2", 2, 2, 2),
                _record("member_3", None, 0, 4),
            ]
        },
        "declared": {"cons": copy.deepcopy(_CONS)},
        "result": {"member_id": "member_1", "value": "a", "status": "answered", "reason": None},
        "dropped": 0,
        "finish_reason": "stop",
    }


def _all_optional_wire() -> dict[str, Any]:
    """CR-D1: signal, cut, consistency, declared and gate all set, in the order of the wire."""
    ordered: dict[str, Any] = {}
    for key, value in _consistency_wire().items():
        if key == "consistency":
            ordered["cut"] = {"k": 1, "order": "max"}
        if key == "result":
            ordered["gate"] = dict(_GATE)
        ordered[key] = value
    ordered["signal"] = {"key": "cons", "order": None}
    return ordered


def _decode(wire: dict[str, Any]) -> CombineEvidence:
    decoded = decode_combine_evidence(copy.deepcopy(wire), _LABEL)
    assert decoded is not None
    return decoded


def _changed(**changes: Any) -> dict[str, Any]:
    wire = _consistency_wire()
    wire.update(changes)
    return wire


def _record_changed(**changes: Any) -> dict[str, Any]:
    wire = _consistency_wire()
    wire["consistency"]["cons"][0].update(changes)
    return wire


# --- CR#1: existing evidence has no consistency key after the SDK round trip (CHAR) -------------


@requires_engine_app
def test_existing_evidence_has_no_consistency_after_the_sdk_round_trip() -> None:
    for name in L37:
        wire = _EVIDENCE_CASES[name]
        written = _decode(wire).to_dict()
        assert written == wire, name
        assert list(written) == list(wire), name
        assert "consistency" not in written, name


# --- CR#10: the SDK decodes a consistency record and writes the same wire back -----------------


def test_sdk_decodes_and_round_trips_a_consistency_record() -> None:
    wire = _consistency_wire()

    decoded = _decode(wire)

    assert decoded.consistency is not None
    assert list(decoded.consistency) == ["cons"]
    assert decoded.consistency["cons"] == (
        CombineSampleCount("member_1", 2, 4, 0),
        CombineSampleCount("member_2", 2, 2, 2),
        CombineSampleCount("member_3", None, 0, 4),
    )
    written = decoded.to_dict()
    assert written == wire
    assert list(written) == list(wire)
    assert list(decoded.consistency["cons"][0].to_dict()) == [
        "member_id",
        "matched",
        "succeeded",
        "failed",
    ]
    assert [record.to_dict() for record in decoded.consistency["cons"]] == wire["consistency"][
        "cons"
    ]
    assert CombineSampleCount("member_3", None, 0, 4).to_dict() == _record("member_3", None, 0, 4)

    every = _all_optional_wire()
    written_every = _decode(every).to_dict()
    assert written_every == every
    keys = list(written_every)
    assert keys[keys.index("signal") :] == [
        "signal",
        "cut",
        "consistency",
        "declared",
        "gate",
        "result",
        "dropped",
        "finish_reason",
    ]


# --- CR#11: the SDK decoder refuses bad consistency records -------------------------------------

_INVALID = f"{_LABEL} is invalid: "
_RECORD = f"{_LABEL} consistency 'cons'[0]"


def _bad_records() -> list[Any]:
    wire = _consistency_wire()
    records = wire["consistency"]["cons"]
    extra = _record_changed(extra=1)
    missing = _consistency_wire()
    del missing["consistency"]["cons"][0]["failed"]
    return [
        pytest.param(extra, f"{_RECORD} contains unsupported field 'extra'", id="extra-key"),
        pytest.param(missing, f"{_RECORD} is missing 'failed'", id="missing-key"),
        pytest.param(
            _record_changed(matched="2"), f"{_RECORD} matched must be an integer", id="matched-text"
        ),
        pytest.param(
            _record_changed(succeeded=True),
            f"{_RECORD} succeeded must be an integer",
            id="succeeded-true",
        ),
        pytest.param(
            _changed(consistency={"cons": {"member_1": records[0]}}),
            f"{_LABEL} consistency 'cons' must be a list",
            id="records-mapping",
        ),
        pytest.param(
            _changed(consistency=[records]),
            f"{_LABEL} consistency must be an object with text keys",
            id="consistency-list",
        ),
        pytest.param(
            _record_changed(failed=1),
            _INVALID + "Combine evidence succeeded and failed samples add up to n",
            id="cs-i3",
        ),
        pytest.param(
            _changed(declared={"conf": dict(_CONF)}),
            _INVALID
            + "Combine evidence consistency record goes with one declared consistency source",
            id="cs-i1-no-entry",
        ),
        pytest.param(
            {k: v for k, v in wire.items() if k != "consistency"},
            _INVALID
            + "Combine evidence consistency record goes with one declared consistency source",
            id="cs-i1-no-record",
        ),
        pytest.param(
            _changed(consistency={"cons": [records[1], records[0], records[2]]}),
            _INVALID + "Combine evidence consistency record names every member in order",
            id="cs-i2-swap",
        ),
        pytest.param(
            _record_changed(matched=3, succeeded=2, failed=2),
            _INVALID + "Combine sample count matched is at most succeeded, "
            "and a match needs a successful sample",
            id="cs-i4",
        ),
        pytest.param(
            _record_changed(matched=1),
            _INVALID + "Combine evidence consistency value is matched over succeeded",
            id="cs-i5",
        ),
    ]


@pytest.mark.parametrize(("wire", "message"), _bad_records())
def test_sdk_decoder_refuses_bad_consistency_records(wire: dict[str, Any], message: str) -> None:
    with pytest.raises(ExecutionError) as caught:
        decode_combine_evidence(wire, _LABEL)

    assert str(caught.value) == message


# --- CR#12: CombineSampleCount refuses bad values -----------------------------------------------


@pytest.mark.parametrize(
    ("fields", "error", "message"),
    [
        pytest.param(
            {"matched": True},
            TypeError,
            "Combine sample count matched must be an integer",
            id="matched-true",
        ),
        pytest.param(
            {"succeeded": -1},
            ValueError,
            "Combine sample count succeeded must not be negative",
            id="succeeded-negative",
        ),
        pytest.param(
            {"failed": 1.0},
            TypeError,
            "Combine sample count failed must be an integer",
            id="failed-float",
        ),
        pytest.param(
            {"member_id": ""},
            ValueError,
            "Combine sample count member_id must look like 'member_1'",
            id="member-blank",
        ),
        pytest.param(
            {"matched": 3, "succeeded": 2},
            ValueError,
            "Combine sample count matched is at most succeeded, "
            "and a match needs a successful sample",
            id="matched-over-succeeded",
        ),
        pytest.param(
            {"matched": 0, "succeeded": 0},
            ValueError,
            "Combine sample count matched is at most succeeded, "
            "and a match needs a successful sample",
            id="match-without-success",
        ),
    ],
)
def test_sdk_sample_count_refuses_bad_values(
    fields: dict[str, Any], error: type[Exception], message: str
) -> None:
    values: dict[str, Any] = {"member_id": "member_1", "matched": 2, "succeeded": 4, "failed": 0}
    values.update(fields)

    with pytest.raises(error, match=re.escape(message)):
        CombineSampleCount(**values)


# --- CR#14: sf.report exports CombineSampleCount (PIN: the public surface snapshot) -------------


def test_sdk_report_exports_combine_sample_count() -> None:
    assert report.CombineSampleCount is CombineSampleCount
    assert "CombineSampleCount" in report.__all__
    parameter = inspect.signature(CombineEvidence.__init__).parameters["consistency"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None
    assert [field.name for field in dataclasses.fields(CombineSampleCount)] == [
        "member_id",
        "matched",
        "succeeded",
        "failed",
    ]


# --- CR#15: the SDK spec decoder accepts a consistency entry (CHAR) -----------------------------


def test_sdk_spec_decoder_accepts_a_consistency_entry() -> None:
    spec = decode_combine_spec(_SPEC_TEXT)

    assert spec["signals"] == {"cons": _CONS}
