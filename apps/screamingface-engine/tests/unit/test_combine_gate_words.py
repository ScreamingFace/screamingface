"""The gate words, the spec key ``gate`` and the evidence record ``gate`` (E4b part 5, unit 1).

FEATURE: a vote spec holds an optional ``gate`` (a comparison of one named number against one
threshold, written as data), and the evidence holds an optional ``gate`` record (what the gate
compared and the branch the step took) and a reserved ``verifier`` key (gate-record and
verifier-slot PRDs).
STORY: as a researcher, I can read from the evidence alone which number the gate compared, the
comparison, and whether the step kept the majority or took the fallback.
INVARIANT defended: an evidence or a spec without a gate keeps its v1 bytes; a gate refusal names
the rule and never echoes a value; the record keys are in the pinned order; GR-I1, GR-I2, GR-I4
and GR-I5 hold; ``verifier`` is null only and never written. The schema ids do not change.
AIDEV-NOTE: unit 2 appends its tests (the word ``gate_not_met``, GR-I3) to this file. Do not
edit the tests above its marker.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from combine_signal_support import rank_signal_spec
from combine_support import spec_text, vote_spec
from pydantic import ValidationError

from screamingface_engine.combine.evidence import (
    COMBINE_EVIDENCE_SCHEMA,
    CombineEvidence,
    GateRecord,
)
from screamingface_engine.combine.ports import SpecInvalid
from screamingface_engine.combine.spec import COMBINE_SPEC_SCHEMA, GateSpec, parse_spec

_DATA = Path(__file__).parent / "data" / "combine_contract"
SCHEMAS = _DATA / "schemas"

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
# test-plan §6 L43: the 43 url4 files on base 4e622af75. A fixed list, never a glob.
L43 = (
    "argmax_cost_candidate.url4",
    "corrective_vote_candidate.url4",
    "entropy_pick_min_candidate.url4",
    "filter_judge_candidate.url4",
    "filter_pipeline_candidate.url4",
    "judge_order_min_candidate.url4",
    "judge_vote_candidate.url4",
    "logprob_entropy_shared_candidate.url4",
    "logprob_filter_mean_candidate.url4",
    "logprob_filter_prob_candidate.url4",
    "logprob_pick_mean_candidate.url4",
    "logprob_pick_sum_candidate.url4",
    "logprob_rank_mean_candidate.url4",
    "logprob_samples_pick_candidate.url4",
    "logprob_steer_filter_candidate.url4",
    "logprob_vote_prob_candidate.url4",
    "model_synthesizer_candidate.url4",
    "quorum_judge_vote_candidate.url4",
    "quorum_vote_candidate.url4",
    "recipe_s1.url4",
    "recipe_s10.url4",
    "recipe_s11_max.url4",
    "recipe_s12.url4",
    "recipe_s13.url4",
    "recipe_s14.url4",
    "recipe_s15.url4",
    "recipe_s16.url4",
    "recipe_s2.url4",
    "recipe_s3.url4",
    "recipe_s4.url4",
    "recipe_s4_median.url4",
    "recipe_s5.url4",
    "recipe_s5_pick_output.url4",
    "recipe_s7.url4",
    "recipe_s8.url4",
    "recipe_s8_pick_output.url4",
    "recipe_s9.url4",
    "samples_vote_candidate.url4",
    "signal_vote_candidate.url4",
    "two_reducers_candidate.url4",
    "verbalized_vote_candidate.url4",
    "vote_candidate.url4",
    "weighted_median_confidence_candidate.url4",
)
# The files of L43 that do not hold exactly one combine spec (counted by hand on 4e622af75).
_SPEC_COUNTS = {
    "corrective_vote_candidate.url4": 2,
    "model_synthesizer_candidate.url4": 0,
    "two_reducers_candidate.url4": 2,
}
_SPEC_START = '{"extract":'  # canonical JSON sorts the keys, so every spec starts here

# The shared test data. The SDK test module holds the same values (ST/test_gate_words.py).
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
_SPEC_GATE = {"cmp": ">=", "observe": "agreement", "otherwise": "abstain", "threshold": 0.7}


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


def _real_vote(**overrides: Any) -> dict[str, Any]:
    """A vote over the built-in operators (last line, text, mode, first holder)."""
    steps: dict[str, Any] = {
        "extract": {"op": "last_line@1", "args": {}},
        "normalize": {"op": "text@1", "args": {}},
        "reduce": {"op": "mode@1", "args": {}},
        "select": {"op": "first_holder@1", "args": {}},
    }
    steps.update(overrides)
    return vote_spec(3, **steps)


def _median_spec() -> dict[str, Any]:
    return vote_spec(
        3,
        reducer="median",
        extract={"op": "last_number@1", "args": {}},
        normalize={"op": "numeric@1", "args": {}},
        reduce={"op": "median@1", "args": {}},
        select={"op": "nearest@1", "args": {}},
    )


def _bytes(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _dump(wire: dict[str, Any]) -> dict[str, Any]:
    return CombineEvidence.model_validate(copy.deepcopy(wire)).model_dump(
        mode="json", by_alias=True
    )


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


# --- GR#1: existing evidence and specs have no gate key (CHAR) --------------------------------


def test_existing_evidence_and_specs_have_no_gate_key() -> None:
    cases = json.loads((_DATA / "evidence_cases.json").read_text(encoding="utf-8"))
    for name in L32:
        wire = cases[name]
        dumped = _dump(wire)
        assert _bytes(dumped) == _bytes(wire), name
        assert "gate" not in dumped, name
        assert "verifier" not in dumped, name

    total = 0
    for name in L43:
        specs = _combine_specs((_DATA / name).read_text(encoding="utf-8"))
        assert len(specs) == _SPEC_COUNTS.get(name, 1), name
        for text in specs:
            assert '"gate"' not in text, name
            assert "gate" not in parse_spec(text).model_fields_set, name
        total += len(specs)
    assert total == 44


# --- GR#3: the Engine parses a gate on a vote spec ---------------------------------------------


def test_engine_parses_a_gate_on_a_vote_spec() -> None:
    parsed = parse_spec(spec_text({**_real_vote(), "gate": dict(_SPEC_GATE)}))
    assert parsed.gate == GateSpec(
        observe="agreement", cmp=">=", threshold=0.7, otherwise="abstain"
    )

    whole = parse_spec(spec_text({**_real_vote(), "gate": {**_SPEC_GATE, "threshold": 1}}))
    assert whole.gate is not None
    assert type(whole.gate.threshold) is float
    assert whole.gate.threshold == 1.0

    declared = {"conf": dict(_CONF)}
    chosen = parse_spec(
        spec_text(
            {
                **_real_vote(),
                "signals": declared,
                "gate": {**_SPEC_GATE, "observe": "chosen:conf", "threshold": 80},
            }
        )
    )
    assert chosen.gate == GateSpec(
        observe="chosen:conf", cmp=">=", threshold=80.0, otherwise="abstain"
    )
    mean = parse_spec(
        spec_text(
            {
                **_real_vote(),
                "signals": declared,
                "gate": {
                    "cmp": "<=",
                    "observe": "mean:conf",
                    "otherwise": "writer",
                    "threshold": -5,
                },
            }
        )
    )
    assert mean.gate == GateSpec(observe="mean:conf", cmp="<=", threshold=-5.0, otherwise="writer")


# --- GR#4: only a vote takes a gate, and an explicit null is refused ---------------------------


def test_engine_refuses_a_gate_on_another_reducer_and_an_explicit_null() -> None:
    assert "only a vote takes a gate" in _spec_failure({**_median_spec(), "gate": dict(_SPEC_GATE)})
    rank = rank_signal_spec(3, 2, "cost_usd", "min")
    assert "only a vote takes a gate" in _spec_failure({**rank, "gate": dict(_SPEC_GATE)})
    assert "gate must be an object when present" in _spec_failure({**_real_vote(), "gate": None})


# --- GR#5: bad gate fields are refused, and the message echoes no value ------------------------

_DECLARED_VOTE = {**_real_vote(), "signals": {"conf": dict(_CONF)}}
_INVALID_OBJECT = "gate must be a valid gate object"


@pytest.mark.parametrize(
    ("spec", "rule"),
    [
        pytest.param(
            {**_real_vote(), "gate": {**_SPEC_GATE, "observe": "chosen:zzz"}},
            "gate reads a name the spec does not declare",
            id="chosen-zzz-no-signals",
        ),
        pytest.param(
            {**_DECLARED_VOTE, "gate": {**_SPEC_GATE, "observe": "chosen:cost_usd"}},
            "gate reads a name the spec does not declare",
            id="chosen-cost-usd",
        ),
        pytest.param(
            {**_real_vote(), "gate": {**_SPEC_GATE, "observe": "consensus"}},
            "gate observe must be agreement, chosen:<name> or mean:<name>",
            id="observe-consensus",
        ),
        pytest.param(
            {**_real_vote(), "gate": {**_SPEC_GATE, "cmp": "=="}}, _INVALID_OBJECT, id="cmp-eq"
        ),
        pytest.param(
            {**_real_vote(), "gate": {**_SPEC_GATE, "cmp": "<"}},
            "an agreement gate compares with >= or >",
            id="agreement-lt",
        ),
        pytest.param(
            {**_real_vote(), "gate": {**_SPEC_GATE, "threshold": 9.5}},
            "an agreement gate threshold is between 0 and 1",
            id="agreement-9-5",
        ),
        pytest.param(
            {**_real_vote(), "gate": {**_SPEC_GATE, "otherwise": "retry"}},
            _INVALID_OBJECT,
            id="otherwise-retry",
        ),
        pytest.param(
            {**_real_vote(), "gate": {k: v for k, v in _SPEC_GATE.items() if k != "threshold"}},
            _INVALID_OBJECT,
            id="missing-threshold",
        ),
        pytest.param(
            {**_real_vote(), "gate": {**_SPEC_GATE, "note": 1}}, _INVALID_OBJECT, id="extra-note"
        ),
        pytest.param(
            {**_real_vote(), "gate": {**_SPEC_GATE, "threshold": True}},
            _INVALID_OBJECT,
            id="bool-threshold",
        ),
    ],
)
def test_engine_refuses_bad_gate_fields_without_echo(spec: dict[str, Any], rule: str) -> None:
    message = _spec_failure(spec)

    assert rule in message
    for value in ("cost_usd", "zzz", "9.5", "consensus", "retry", "note", "=="):
        assert value not in message


# --- GR#6: the gate record serializes in the pinned key order ----------------------------------


def test_gate_record_serializes_in_the_pinned_key_order() -> None:
    wire = _gate_wire()

    dumped = _dump(wire)

    assert list(dumped) == [
        "schema",
        "kind",
        "reducer",
        "operators",
        "members",
        "tally",
        "judge",
        "fields",
        "chosen",
        "built",
        "agreement",
        "tie",
        "median",
        "presentation_order",
        "separator_collision",
        "signal",
        "gate",
        "result",
        "dropped",
        "finish_reason",
    ]
    assert list(dumped["gate"]) == [
        "observe",
        "observed",
        "cmp",
        "threshold",
        "passed",
        "branch",
        "otherwise",
    ]
    assert _bytes(dumped) == _bytes(wire)


# --- GR#7: GR-I1, GR-I2, GR-I4, GR-I5 refuse mismatches ---------------------------------------


_RECORD_REFUSALS = (
    (
        {"passed": True, "branch": "fallback"},
        "a gate that passed keeps the majority, and only it does",
    ),
    (
        {"passed": False, "branch": "majority"},
        "a gate that passed keeps the majority, and only it does",
    ),
    (
        {"passed": None, "branch": "majority"},
        "a gate record has a branch exactly when it has a comparison result",
    ),
    (
        {"passed": True, "branch": None},
        "a gate record has a branch exactly when it has a comparison result",
    ),
    (
        {"passed": None, "branch": None, "observed": 0.5},
        "a gate that did not run observed no number",
    ),
    ({"observe": "consensus"}, "a gate record observes agreement, chosen:<name> or mean:<name>"),
)


def test_gate_record_and_evidence_invariants_refuse_mismatches() -> None:
    # The valid forms first: a record that did not run, and a fallback record with no number.
    GateRecord.model_validate(dict(_NOT_RUN_GATE))
    GateRecord.model_validate({**_GATE, "observed": None, "passed": False, "branch": "fallback"})
    for wire in (_gate_wire(), _writer_fallback_wire(), _judge_fallback_wire(), _not_run_wire()):
        assert _dump(wire) == wire
    # GR-I5 reads only the fallback branch: a majority gate with a judge or writer fallback,
    # judge null and the chosen member's result, is valid.
    for otherwise in ("judge", "writer"):
        majority = _gate_wire()
        majority["gate"]["otherwise"] = otherwise
        assert _dump(majority) == majority

    for changes, rule in _RECORD_REFUSALS:
        with pytest.raises(ValidationError, match=re.escape(rule)):
            GateRecord.model_validate({**_GATE, **changes})
    _assert_evidence_refusals()


def _assert_evidence_refusals() -> None:
    mismatch = _gate_wire()  # GR-I4: observed 0.5 is not the agreement 2/3
    mismatch["gate"].update(observed=0.5, threshold=0.4)
    not_built = _writer_fallback_wire()  # GR-I5 (a)
    not_built["built"] = False
    no_reading = _judge_fallback_wire()  # GR-I5 (b)
    no_reading.update(judge=None, presentation_order=None)
    scores = _judge_fallback_wire()  # GR-I5 (b): the reading must be a label
    scores["judge"] = {"raw": "{}", "returns": "scores", "parsed": {"member_3": 1.0}}
    answered = _gate_wire()  # GR-I1: a gate that did not run goes with an abstain
    answered["gate"] = dict(_NOT_RUN_GATE)
    for wire, rule in (
        (mismatch, "an agreement gate observes the evidence agreement"),
        (not_built, "a writer fallback builds the answer and chooses no member"),
        (no_reading, "a judge fallback records its label reading and chooses that one member"),
        (scores, "a judge fallback records its label reading and chooses that one member"),
        (answered, "a gate that did not run goes with an abstained result"),
    ):
        with pytest.raises(ValidationError, match=re.escape(rule)):
            CombineEvidence.model_validate(wire)


# --- GR#8: every optional key in its place -----------------------------------------------------


def test_evidence_with_every_optional_key_orders_signal_cut_declared_gate_result() -> None:
    wire = _all_optional_wire()

    dumped = _dump(wire)

    keys = list(dumped)
    assert keys[keys.index("signal") :] == [
        "signal",
        "cut",
        "declared",
        "gate",
        "result",
        "dropped",
        "finish_reason",
    ]
    assert _bytes(dumped) == _bytes(wire)


# --- GR#13: the schema snapshots hold the gate and the verifier (PIN) --------------------------


def test_schema_snapshots_hold_the_gate_and_the_verifier() -> None:
    assert COMBINE_SPEC_SCHEMA == "screamingface.combine-spec.v1"
    assert COMBINE_EVIDENCE_SCHEMA == "screamingface.combine-evidence.v1"
    spec = _pinned(COMBINE_SPEC_SCHEMA)
    assert spec["properties"].get("gate") == {
        "anyOf": [{"$ref": "#/$defs/GateSpec"}, {"type": "null"}],
        "default": None,
    }
    assert "gate" not in spec["required"]
    assert len(spec["required"]) == 8
    gate_spec = spec["$defs"].get("GateSpec", {})
    assert gate_spec.get("required") == ["observe", "cmp", "threshold", "otherwise"]
    assert gate_spec.get("additionalProperties") is False
    assert gate_spec["properties"]["cmp"]["enum"] == [">=", ">", "<=", "<"]
    assert gate_spec["properties"]["otherwise"]["enum"] == ["abstain", "judge", "writer"]
    assert gate_spec["properties"]["threshold"] == {"title": "Threshold", "type": "number"}

    evidence = _pinned(COMBINE_EVIDENCE_SCHEMA)
    assert evidence["properties"].get("gate") == {
        "anyOf": [{"$ref": "#/$defs/GateRecord"}, {"type": "null"}],
        "default": None,
    }
    assert "verifier" in evidence["properties"]
    assert "gate" not in evidence["required"]
    assert "verifier" not in evidence["required"]
    assert len(evidence["required"]) == 18
    record = evidence["$defs"].get("GateRecord", {})
    assert record.get("required") == [
        "observe",
        "observed",
        "cmp",
        "threshold",
        "passed",
        "branch",
        "otherwise",
    ]
    assert record.get("additionalProperties") is False
    assert record["properties"]["branch"] == {
        "anyOf": [{"enum": ["majority", "fallback"], "type": "string"}, {"type": "null"}],
        "title": "Branch",
    }
    assert record["properties"]["passed"] == {
        "anyOf": [{"type": "boolean"}, {"type": "null"}],
        "title": "Passed",
    }


# --- VS#1: the evidence schema reserves an optional null verifier ------------------------------


def test_evidence_schema_reserves_an_optional_null_verifier() -> None:
    evidence = _pinned(COMBINE_EVIDENCE_SCHEMA)

    assert evidence["properties"].get("verifier") == {
        "default": None,
        "title": "Verifier",
        "type": "null",
    }
    assert "verifier" not in evidence["required"]
    fields = list(CombineEvidence.model_fields)
    assert fields[fields.index("declared") + 1 : fields.index("result")] == ["gate", "verifier"]


# --- VS#2: the Engine refuses a non-null verifier and never writes the key ---------------------


def test_engine_evidence_refuses_a_non_null_verifier_and_never_writes_it() -> None:
    with_null = {**_gate_wire(), "verifier": None}
    evidence = CombineEvidence.model_validate(with_null)
    assert evidence.verifier is None
    assert evidence.model_dump(mode="json", by_alias=True) == _gate_wire()

    for value in ({}, "ok", False):
        with pytest.raises(ValidationError, match="Input should be None"):
            CombineEvidence.model_validate({**_gate_wire(), "verifier": value})

    # VS-D1 loops over the whole file on purpose: unit 2 adds cases, and none writes a verifier.
    cases = json.loads((_DATA / "evidence_cases.json").read_text(encoding="utf-8"))
    for name, wire in cases.items():
        assert "verifier" not in wire, name
        assert "verifier" not in _dump(wire), name
