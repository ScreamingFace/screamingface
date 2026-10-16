"""The abstain band of a vote gate: the spec key ``gate.abstain_band`` (E4b part 6, unit 3).

FEATURE: a vote gate may hold a closed band ``[lo, hi]``. Inside the band the Case abstains;
outside it the gate compares as in part 5 (abstain-band PRD, ans:Q2). This unit parses the key.
STORY: as a benchmark author, I write ``"abstain_band": [lo, hi]`` on a vote gate, and the Engine
parses it, or refuses it with a fixed message that holds no value.
INVARIANT defended: a spec or an evidence without a band keeps its part 5 bytes; a band is two
finite numbers ``lo <= hi`` (``0 <= lo <= hi <= 1`` for an agreement gate); an explicit null is
refused; a refusal names the rule and never echoes a value; the schema id does not change.
AIDEV-NOTE: unit 4 (band-record) appends its tests (AB#4-11, the evidence half of AB#15) below the
last marker of this file. Do not edit the tests above that marker.
"""

from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from typing import Any, get_args

import pytest
from combine_golden_support import builtin_vote_spec
from combine_support import context_text, run, spec_text
from pydantic import ValidationError

from screamingface_engine.benchmarks.contract import OperationOutput
from screamingface_engine.benchmarks.operation_outputs import final_operation_abstained
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import COMBINE_ROUTE, CombineOutcome
from screamingface_engine.combine.evidence import CombineEvidence, GateRecord, ResultRecord
from screamingface_engine.combine.ports import (
    ABSTAIN_REASONS,
    AbstainReason,
    AnswerReason,
    GateBranch,
    NoVotes,
    SpecInvalid,
)
from screamingface_engine.combine.spec import COMBINE_SPEC_SCHEMA, GateSpec, parse_spec
from url4 import RelExpr, Text, expr, render, src

_DATA = Path(__file__).parent / "data" / "combine_contract"
SCHEMAS = _DATA / "schemas"

# test-plan §6 L37: the five part 5 gate cases. A fixed tuple, never the file: units 1 and 4 of
# this part add cases to the same file.
L37_GATE_CASES = (
    "vote_gate_abstain",
    "vote_gate_judge",
    "vote_gate_majority",
    "vote_gate_not_run",
    "vote_gate_writer",
)
# test-plan §6 L47: the four part 5 gate url4 files. A fixed tuple, never a glob.
L47_GATE_FILES = (
    "gate_abstain_vote_candidate.url4",
    "gate_judge_vote_candidate.url4",
    "gate_verbalized_vote_candidate.url4",
    "gate_writer_vote_candidate.url4",
)
_PART_5_GATE_KEYS = ["observe", "observed", "cmp", "threshold", "passed", "branch", "otherwise"]
_SPEC_START = '{"extract":'  # canonical JSON sorts the keys, so every spec starts here
_CONF = {"pattern": "Confidence: ([0-9]+)", "source": "verbalized"}
_INVALID_OBJECT = "gate must be a valid gate object"
_NOT_A_PAIR = "gate abstain_band must be a pair when present"
_LO_ABOVE_HI = "a gate abstain_band needs lo <= hi"
_AGREEMENT_RANGE = "an agreement gate abstain_band is between 0 and 1"
# The numbers and words of the refused bands below. No refusal message may hold one of them.
_ECHO = ("0.75", "1.5", "0.7", "0.6", "0.5", "0.1", "True", "true")


def _band_gate(lo: float, hi: float, threshold: float, otherwise: str) -> dict[str, Any]:
    """The PRD's ``band(lo, hi, threshold, otherwise)``: an agreement ``>=`` gate with a band."""
    return {
        "observe": "agreement",
        "cmp": ">=",
        "threshold": threshold,
        "otherwise": otherwise,
        "abstain_band": [lo, hi],
    }


def _vote_with_band(band: Any) -> dict[str, Any]:
    """Fixture B's vote spec with the AB-1 gate, its band value replaced by ``band`` (any JSON)."""
    return {
        **builtin_vote_spec(3),
        "gate": {**_band_gate(0.6, 0.7, 0.7, "abstain"), "abstain_band": band},
    }


def _bytes(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _spec_failure(spec: dict[str, Any]) -> str:
    with pytest.raises(SpecInvalid) as caught:
        parse_spec(spec_text(spec))
    assert caught.value.code == "combine_spec_invalid"
    return str(caught.value)


def _combine_specs(text: str) -> list[str]:
    """Every combine spec text in one url4 file (a spec may sit in a quoted loop body)."""
    decoder = json.JSONDecoder()
    specs: list[str] = []
    start = text.find(_SPEC_START)
    while start != -1:
        _, end = decoder.raw_decode(text, start)
        specs.append(text[start:end])
        start = text.find(_SPEC_START, end)
    return specs


def _pinned(schema_id: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / f"{schema_id}.json").read_text(encoding="utf-8"))


# --- AB#1: the part 5 gate records and gate specs have no band (CHAR) --------------------------


def test_part_5_gate_records_and_specs_have_no_band() -> None:
    cases = json.loads((_DATA / "evidence_cases.json").read_text(encoding="utf-8"))
    for name in L37_GATE_CASES:
        wire = cases[name]
        assert list(wire["gate"]) == _PART_5_GATE_KEYS, name
        dumped = CombineEvidence.model_validate(copy.deepcopy(wire)).model_dump(
            mode="json", by_alias=True
        )
        assert _bytes(dumped) == _bytes(wire), name

    for name in L47_GATE_FILES:
        specs = _combine_specs((_DATA / name).read_text(encoding="utf-8"))
        assert len(specs) == 1, name
        assert '"abstain_band"' not in specs[0], name
        gate = parse_spec(specs[0]).gate
        assert gate is not None, name
        assert getattr(gate, "abstain_band", None) is None, name
        assert "abstain_band" not in gate.model_fields_set, name


# --- AB#2: the Engine parses a gate band -------------------------------------------------------


def test_engine_parses_a_gate_band() -> None:
    parsed = parse_spec(
        spec_text({**builtin_vote_spec(3), "gate": _band_gate(0.6, 0.7, 0.7, "abstain")})
    ).gate
    assert parsed is not None
    assert parsed == GateSpec(
        observe="agreement", cmp=">=", threshold=0.7, otherwise="abstain", abstain_band=[0.6, 0.7]
    )
    assert parsed.abstain_band == [0.6, 0.7]
    assert "abstain_band" in parsed.model_fields_set

    point = parse_spec(spec_text(_vote_with_band([0.5, 0.5]))).gate
    assert point is not None
    assert point.abstain_band == [0.5, 0.5]

    whole = parse_spec(spec_text(_vote_with_band([0, 1]))).gate
    assert whole is not None
    band = whole.abstain_band
    assert band == [0.0, 1.0]
    assert band is not None
    assert [type(edge) for edge in band] == [float, float]

    # P8: no rule ties the band to the threshold (0.7 is above this band).
    low = parse_spec(spec_text(_vote_with_band([0.1, 0.2]))).gate
    assert low is not None
    assert low.abstain_band == [0.1, 0.2]

    # AB-E1, last sentence: a chosen:<name> band is not limited to [0, 1].
    chosen = parse_spec(
        spec_text(
            {
                **builtin_vote_spec(3),
                "signals": {"conf": dict(_CONF)},
                "gate": {
                    "observe": "chosen:conf",
                    "cmp": ">=",
                    "threshold": 80,
                    "otherwise": "abstain",
                    "abstain_band": [-5.0, 1.5],
                },
            }
        )
    ).gate
    assert chosen == GateSpec(
        observe="chosen:conf",
        cmp=">=",
        threshold=80.0,
        otherwise="abstain",
        abstain_band=[-5.0, 1.5],
    )

    plain_gate = _band_gate(0.6, 0.7, 0.7, "abstain")
    del plain_gate["abstain_band"]
    plain = parse_spec(spec_text({**builtin_vote_spec(3), "gate": plain_gate})).gate
    assert plain is not None
    assert plain.abstain_band is None
    assert "abstain_band" not in plain.model_fields_set


# --- AB#3: bad bands are refused, and the message echoes no value ------------------------------


@pytest.mark.parametrize(
    ("band", "rule"),
    [
        pytest.param(None, _NOT_A_PAIR, id="explicit-null"),
        pytest.param([0.75, 0.7], _LO_ABOVE_HI, id="lo-above-hi"),
        pytest.param([0.6], _INVALID_OBJECT, id="one-number"),
        pytest.param([0.1, 0.2, 0.3], _INVALID_OBJECT, id="three-numbers"),
        pytest.param(["a", 0.7], _INVALID_OBJECT, id="a-string"),
        pytest.param([True, 0.7], _INVALID_OBJECT, id="a-bool"),
        pytest.param([0.5, 1.5], _AGREEMENT_RANGE, id="agreement-above-one"),
        pytest.param([-0.1, 0.5], _AGREEMENT_RANGE, id="agreement-below-zero"),
    ],
)
def test_engine_refuses_bad_bands_without_echo(band: Any, rule: str) -> None:
    message = _spec_failure(_vote_with_band(band))

    assert rule in message
    for value in _ECHO:
        assert value not in message


@pytest.mark.parametrize(
    ("edge", "rule"),
    [
        pytest.param("1e400", _INVALID_OBJECT, id="overflows-to-infinity"),
        pytest.param("-1e400", _INVALID_OBJECT, id="overflows-to-minus-infinity"),
        pytest.param("NaN", "combine spec is not valid JSON", id="nan"),
        pytest.param("Infinity", "combine spec is not valid JSON", id="infinity"),
    ],
)
def test_engine_refuses_a_band_that_is_not_finite_without_echo(edge: str, rule: str) -> None:
    good = spec_text(_vote_with_band([0.6, 0.7]))
    assert good.count("[0.6,0.7]") == 1
    text = good.replace("[0.6,0.7]", f"[{edge},0.7]")

    with pytest.raises(SpecInvalid) as caught:
        parse_spec(text)

    assert caught.value.code == "combine_spec_invalid"
    assert rule in str(caught.value)
    assert edge not in str(caught.value)


# --- AB#15 (spec v1 half): the spec schema snapshot holds the band (PIN) -----------------------


def test_spec_schema_snapshot_holds_the_band() -> None:
    assert COMBINE_SPEC_SCHEMA == "screamingface.combine-spec.v1"
    gate_spec = _pinned(COMBINE_SPEC_SCHEMA)["$defs"]["GateSpec"]

    assert gate_spec["properties"].get("abstain_band") == {
        "anyOf": [
            {"items": {"type": "number"}, "maxItems": 2, "minItems": 2, "type": "array"},
            {"type": "null"},
        ],
        "default": None,
        "title": "Abstain Band",
    }
    assert gate_spec["required"] == ["observe", "cmp", "threshold", "otherwise"]
    assert gate_spec["additionalProperties"] is False
    assert list(GateSpec.model_fields) == [
        "observe",
        "cmp",
        "threshold",
        "otherwise",
        "abstain_band",
    ]


# --- unit 4 (band-record) appends its tests below this line ------------------------------------


# ==================================================================================================
# E4b part 6 unit 4 (band-record): AB#4-11 and AB#17. Unit 3's tests above do not change.
# Fixture B: builtin_vote_spec(3) and REC_TEXTS (the part 5 _GATE_TEXTS). Oracle by hand: the
# values are 9, 9, 12; the tally is 9: 2.0 [member_1, member_2], 12: 1.0 [member_3]; the chosen
# member is member_1; agreement = 2/3 = 0.6666666666666666; tie false; 3 of 3 voters.
# ==================================================================================================

REC_T = 0.6666666666666666
REC_TEXTS = ["The answer is 9", "So 9", "I get 12"]
REC_NO_ANSWER = ["none", "no number", "nothing"]
REC_CASES = Path(__file__).parent / "data" / "combine_contract" / "evidence_cases.json"
REC_LOGGER = "screamingface_engine.combine.endpoint"
REC_BAND_REASON = "in_band goes with a gate that abstained inside its band, and only with it"
REC_CONF: dict[str, Any] = {"conf": {"source": "verbalized", "pattern": "Confidence: ([0-9]+)"}}
REC_GATE_KEYS = [
    "observe",
    "observed",
    "cmp",
    "threshold",
    "passed",
    "branch",
    "otherwise",
    "abstain_band",
]


def _rec_member(member_id: str, value: str) -> dict[str, Any]:
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


# AB-2: the whole evidence of fixture B with band(0.6, 0.7, 0.7, "abstain"), in wire key order.
REC_BAND_WIRE: dict[str, Any] = {
    "schema": "screamingface.combine-evidence.v1",
    "kind": "answer",
    "reducer": "vote",
    "operators": ["last_number@1", "numeric@1", "mode@1", "first_holder@1"],
    "members": [
        _rec_member("member_1", "9"),
        _rec_member("member_2", "9"),
        _rec_member("member_3", "12"),
    ],
    "tally": [
        {"value": "9", "score": 2.0, "holders": ["member_1", "member_2"]},
        {"value": "12", "score": 1.0, "holders": ["member_3"]},
    ],
    "judge": None,
    "fields": None,
    "chosen": [],
    "built": False,
    "agreement": REC_T,
    "tie": False,
    "median": None,
    "presentation_order": None,
    "separator_collision": None,
    "signal": None,
    "gate": {
        "observe": "agreement",
        "observed": REC_T,
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
REC_GATE_NOT_MET = {"member_id": None, "value": None, "status": "abstain", "reason": "gate_not_met"}
REC_IN_BAND = {"member_id": None, "value": None, "status": "abstain", "reason": "in_band"}


def _rec_band(lo: float, hi: float, threshold: float, otherwise: str) -> dict[str, Any]:
    """The PRD ``band(lo, hi, threshold, otherwise)``: an agreement gate ``>=`` with a band."""
    return {
        "observe": "agreement",
        "cmp": ">=",
        "threshold": threshold,
        "otherwise": otherwise,
        "abstain_band": [lo, hi],
    }


def _rec_run(
    gate: dict[str, Any],
    texts: list[str] | None = None,
    signals: dict[str, str] | None = None,
    *,
    declared: dict[str, Any] | None = None,
) -> CombineOutcome:
    """Run fixture B (or ``texts``) through the real combine core with ``gate``."""
    spec: dict[str, Any] = {**builtin_vote_spec(3), "gate": gate}
    if declared is not None:
        spec["signals"] = declared
    context = context_text(REC_TEXTS if texts is None else texts, signals)
    return run(spec_text(spec), context, registry=BUILTIN_OPERATORS)


def _rec_wire(outcome: CombineOutcome) -> dict[str, Any]:
    return outcome.evidence.model_dump(mode="json", by_alias=True)


def _rec_bytes(value: Any) -> str:
    """The contract fixture encoder: the bytes the Candidate envelope writes."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _rec_evidence_bytes(outcome: CombineOutcome) -> str:
    return _rec_bytes(outcome.evidence.model_dump(by_alias=True))


def _rec_with_band(name: str, band: list[float]) -> dict[str, Any]:
    """A part 5 contract case (list L37: its bytes never change) with ``abstain_band`` last."""
    wire = json.loads(REC_CASES.read_text(encoding="utf-8"))[name]
    wire["gate"]["abstain_band"] = band
    return wire


def _rec_band_gate(observed: float, band: list[float]) -> dict[str, Any]:
    return {
        "observe": "agreement",
        "observed": observed,
        "cmp": ">=",
        "threshold": 0.7,
        "passed": None,
        "branch": "band",
        "otherwise": "abstain",
        "abstain_band": band,
    }


# --- AB#4 (AB-2) ----------------------------------------------------------------------------------


def test_a_number_inside_the_band_abstains_with_in_band() -> None:
    outcome = _rec_run(_rec_band(0.6, 0.7, 0.7, "abstain"))

    assert outcome.output == ""
    assert _rec_evidence_bytes(outcome) == _rec_bytes(REC_BAND_WIRE)


# --- AB#5 (AB-D1): the band is closed -------------------------------------------------------------


def test_band_edges_are_closed() -> None:
    assert math.nextafter(REC_T, 0.0) == 0.6666666666666665
    assert math.nextafter(REC_T, 1.0) == 0.6666666666666667

    for lo, hi in ((REC_T, 0.8), (0.6, REC_T)):
        edge = _rec_wire(_rec_run(_rec_band(lo, hi, 0.7, "abstain")))
        assert edge["gate"] == _rec_band_gate(REC_T, [lo, hi]), (lo, hi)
        assert edge["result"] == REC_IN_BAND, (lo, hi)
    for lo, hi in ((0.6, 0.6666666666666665), (0.6666666666666667, 0.9)):
        outside = _rec_wire(_rec_run(_rec_band(lo, hi, 0.7, "abstain")))
        assert outside["gate"] == {
            "observe": "agreement",
            "observed": REC_T,
            "cmp": ">=",
            "threshold": 0.7,
            "passed": False,
            "branch": "fallback",
            "otherwise": "abstain",
            "abstain_band": [lo, hi],
        }, (lo, hi)
        assert outside["result"] == REC_GATE_NOT_MET, (lo, hi)


# --- AB#6 (AB-3, AB-4): outside the band the gate compares as in part 5 ---------------------------


def test_outside_the_band_the_gate_compares_as_today() -> None:
    below = _rec_run(_rec_band(0.7, 0.9, 0.6, "abstain"))
    above = _rec_run(_rec_band(0.1, 0.5, 0.7, "abstain"))

    below_gate = _rec_wire(below)["gate"]
    assert (below_gate["passed"], below_gate["branch"]) == (True, "majority")
    assert below_gate["abstain_band"] == [0.7, 0.9]
    assert below.output == "The answer is 9"
    assert above.output == ""
    assert _rec_evidence_bytes(above) == _rec_bytes(_rec_with_band("vote_gate_abstain", [0.1, 0.5]))


# --- AB#7 (AB-D2, FB-I1, C8): the band wins and reads no fallback reply ---------------------------


@pytest.mark.parametrize(
    ("otherwise", "signals"),
    [
        pytest.param("judge", {"fallback_judge": "member_3"}, id="judge"),
        pytest.param("writer", {"fallback_writer": "It is 10"}, id="writer"),
    ],
)
def test_the_band_wins_over_a_fallback_and_reads_no_fallback_reply(
    otherwise: str, signals: dict[str, str]
) -> None:
    with_reply = _rec_run(_rec_band(0.6, 0.7, 0.7, otherwise), signals=signals)
    without_reply = _rec_run(_rec_band(0.6, 0.7, 0.7, otherwise))

    assert with_reply.output == without_reply.output == ""
    assert _rec_evidence_bytes(with_reply) == _rec_evidence_bytes(without_reply)
    expected = copy.deepcopy(REC_BAND_WIRE)
    expected["gate"]["otherwise"] = otherwise
    assert _rec_wire(with_reply) == expected


# --- AB#8 (AB-D3, P10): a missing number skips the band -------------------------------------------


def test_a_missing_number_skips_the_band() -> None:
    gate = {
        "observe": "chosen:conf",
        "cmp": ">=",
        "threshold": 80.0,
        "otherwise": "abstain",
        "abstain_band": [50.0, 90.0],
    }

    wire = _rec_wire(_rec_run(gate, declared=REC_CONF))

    assert wire["gate"] == {
        "observe": "chosen:conf",
        "observed": None,
        "cmp": ">=",
        "threshold": 80.0,
        "passed": False,
        "branch": "fallback",
        "otherwise": "abstain",
        "abstain_band": [50.0, 90.0],
    }
    assert wire["result"] == REC_GATE_NOT_MET


# --- AB#9 (AB-D4, GR-I1): a vote with no answer keeps the band and does not run -------------------


def test_a_vote_with_no_answer_records_the_band_and_does_not_run() -> None:
    outcome = _rec_run(_rec_band(0.6, 0.7, 0.6, "abstain"), REC_NO_ANSWER)

    assert outcome.output == ""
    assert _rec_evidence_bytes(outcome) == _rec_bytes(
        _rec_with_band("vote_gate_not_run", [0.6, 0.7])
    )


# --- AB#10 (AB-E2): the record invariants GB-I1 to GB-I3, GR-I1' ----------------------------------

REC_BAND_RECORD: dict[str, Any] = _rec_band_gate(0.65, [0.6, 0.7])
REC_PART5_RECORD: dict[str, Any] = {
    "observe": "agreement",
    "observed": 0.65,
    "cmp": ">=",
    "threshold": 0.6,
    "passed": True,
    "branch": "majority",
    "otherwise": "abstain",
}
REC_VALID_RECORDS: tuple[dict[str, Any], ...] = (
    REC_BAND_RECORD,
    {**REC_BAND_RECORD, "observed": 0.6},
    {**REC_BAND_RECORD, "observed": 0.7},
    {**REC_BAND_RECORD, "abstain_band": [0.65, 0.65]},
    {**REC_BAND_RECORD, "passed": True, "branch": "majority", "observed": 0.8},
    {**REC_BAND_RECORD, "passed": False, "branch": "fallback", "observed": 0.5},
    {**REC_BAND_RECORD, "passed": False, "branch": "fallback", "observed": None},
    {**REC_BAND_RECORD, "passed": None, "branch": None, "observed": None},
    {**REC_BAND_RECORD, "observe": "chosen:risk", "observed": -2.0, "abstain_band": [-5.0, 1.5]},
    REC_PART5_RECORD,
)
REC_INSIDE = "a gate band branch observed a number inside its band"
REC_OUTSIDE = "a gate that compared observed a number outside its band"
REC_RECORD_REFUSALS: tuple[tuple[dict[str, Any], str], ...] = (
    ({**REC_BAND_RECORD, "passed": False}, "a gate in its band made no comparison"),
    ({**REC_BAND_RECORD, "passed": True}, "a gate in its band made no comparison"),
    ({**REC_BAND_RECORD, "abstain_band": None}, REC_INSIDE),
    ({**REC_BAND_RECORD, "observed": 0.8}, REC_INSIDE),
    ({**REC_BAND_RECORD, "observed": None}, REC_INSIDE),
    ({**REC_BAND_RECORD, "passed": True, "branch": "majority"}, REC_OUTSIDE),
    ({**REC_BAND_RECORD, "passed": False, "branch": "fallback", "observed": 0.6}, REC_OUTSIDE),
    (
        {
            **REC_BAND_RECORD,
            "abstain_band": [0.7, 0.6],
            "passed": True,
            "branch": "majority",
            "observed": 0.8,
        },
        "a gate band is two numbers lo <= hi",
    ),
    # The part 5 inputs keep their part 5 messages.
    (
        {**REC_PART5_RECORD, "passed": True, "branch": "fallback"},
        "a gate that passed keeps the majority, and only it does",
    ),
    (
        {**REC_PART5_RECORD, "passed": None, "branch": "majority"},
        "a gate record has a branch exactly when it has a comparison result",
    ),
    (
        {**REC_PART5_RECORD, "passed": None, "branch": None, "observed": 0.5},
        "a gate that did not run observed no number",
    ),
)
REC_BAD_BAND_SHAPES: tuple[list[Any], ...] = (
    [0.6],
    [0.1, 0.2, 0.3],
    [True, 0.7],
    ["a", 0.7],
    [0.6, math.inf],
    [math.nan, 0.7],
)


def test_gate_record_band_invariants_refuse_mismatches() -> None:
    # The valid forms first, so a model that refuses every band fails here.
    for valid in REC_VALID_RECORDS:
        GateRecord.model_validate(valid)
    part5 = GateRecord.model_validate(REC_PART5_RECORD)
    assert part5.abstain_band is None
    assert list(part5.model_dump(mode="json")) == REC_GATE_KEYS[:-1]

    for record, rule in REC_RECORD_REFUSALS:
        with pytest.raises(ValidationError, match=re.escape(rule)):
            GateRecord.model_validate(record)
    for band in REC_BAD_BAND_SHAPES:
        with pytest.raises(ValidationError):
            GateRecord.model_validate({**REC_BAND_RECORD, "abstain_band": band})


# --- AB#10 (AB-E3, GB-I4): in_band goes with the band branch only ---------------------------------


def test_in_band_needs_the_band_branch() -> None:
    assert CombineEvidence.model_validate(copy.deepcopy(REC_BAND_WIRE)).result.reason == "in_band"
    fallback_gate = copy.deepcopy(REC_BAND_WIRE)  # in_band with a gate that compared
    fallback_gate["gate"].update(passed=False, branch="fallback", abstain_band=[0.7, 0.9])
    band_not_met = copy.deepcopy(REC_BAND_WIRE)  # a band gate with the reason gate_not_met
    band_not_met["result"]["reason"] = "gate_not_met"
    no_gate = copy.deepcopy(REC_BAND_WIRE)  # in_band with no gate
    del no_gate["gate"]

    for wire in (fallback_gate, band_not_met, no_gate):
        with pytest.raises(ValidationError, match=re.escape(REC_BAND_REASON)):
            CombineEvidence.model_validate(wire)


# --- AB#11 (AB-D6, AB-D7, P18): a final abstain, one log line -------------------------------------


def test_in_band_is_a_final_abstain_and_logs_its_outcome(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO", logger=REC_LOGGER):
        outcome = _rec_run(_rec_band(0.6, 0.7, 0.7, "abstain"))
    lines = [
        item.getMessage()
        for item in caplog.records
        if item.name == REC_LOGGER and item.levelname == "INFO"
    ]

    assert lines == [
        "combine binding=synthesis_1 reducer=vote voters=3/3 agreement=0.6666666666666666 "
        "tie=false outcome=abstain_in_band"
    ]
    expression = render(
        expr(
            src(
                RelExpr(path=COMBINE_ROUTE, context="$input", intent=Text("spec")),
                name="synthesis_1",
                weight=0.0,
            ),
            intent=Text("$synthesis_1"),
        )
    )
    operations = [
        OperationOutput(
            operation_id="op_synthesis_1",
            output=outcome.output,
            finish_reason="stop",
            accounting=None,
            combine=outcome.evidence,
        )
    ]
    assert final_operation_abstained(expression, operations) is True


# --- AB#11 (AB-D8, P12): the Engine words ---------------------------------------------------------


def test_in_band_is_an_abstain_word() -> None:
    words = ("no_votes", "cut_not_met", "output_missing", "gate_not_met", "in_band")

    assert get_args(AbstainReason) == words
    assert ABSTAIN_REASONS == words
    assert get_args(AnswerReason)[-2:] == ("gate_not_met", "in_band")
    assert get_args(GateBranch) == ("majority", "fallback", "band")
    assert NoVotes(reason="in_band").reason == "in_band"
    result = ResultRecord(member_id=None, value=None, status="abstain", reason="in_band")
    assert result.reason == "in_band"


# --- AB#17 (AB-3, AB-D5): the majority record with a band = the part 5 record + the band ----------


def test_the_majority_branch_record_with_a_band_is_the_part_5_record_plus_the_band() -> None:
    outcome = _rec_run(_rec_band(0.7, 0.9, 0.6, "abstain"))
    expected = _rec_with_band("vote_gate_majority", [0.7, 0.9])

    assert outcome.output == "The answer is 9"
    assert _rec_evidence_bytes(outcome) == _rec_bytes(expected)
    assert list(expected["gate"]) == REC_GATE_KEYS
