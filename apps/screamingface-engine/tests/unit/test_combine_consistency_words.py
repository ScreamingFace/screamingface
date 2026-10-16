"""The consistency words: the spec entry, the context key ``samples`` and the evidence record.

FEATURE: a combine spec may declare one ``{"source": "consistency", "n", "temperature", "match"}``
entry in ``signals``; its context then carries ``samples`` (each member's sample panel rows), and
its evidence carries an optional ``consistency`` record with ``matched``, ``succeeded`` and
``failed`` per member (E4b part 7, consistency-record PRD).
STORY: as a researcher, I can read from the evidence how many extra samples of each member
answered, how many failed, and how many matched the member's answer.
INVARIANT defended: a spec, context or evidence without consistency keeps its v1 bytes; a refusal
names the rule and never echoes a value; the record keys are in the pinned order, between ``cut``
and ``declared``; CS-I1..CS-I5 hold. The schema ids do not change.
AIDEV-NOTE: E4b part 7 unit 1 owns this file. Later units write their own test files.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from combine_golden_support import builtin_vote_spec
from combine_support import spec_text
from pydantic import ValidationError

from screamingface_engine.combine import evidence as evidence_module
from screamingface_engine.combine.evidence import (
    COMBINE_EVIDENCE_SCHEMA,
    CombineEvidence,
    SampleCountRecord,
)
from screamingface_engine.combine.ports import SpecInvalid
from screamingface_engine.combine.spec import (
    COMBINE_SPEC_SCHEMA,
    ConsistencySource,
    StepSpec,
    declares_consistency,
    parse_context,
    parse_spec,
)

_DATA = Path(__file__).parent / "data" / "combine_contract"
SCHEMAS = _DATA / "schemas"

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
# test-plan §6 L47: the 47 url4 files on base 633fec3a1. A fixed list, never a glob.
L47 = (
    "argmax_cost_candidate.url4",
    "corrective_vote_candidate.url4",
    "entropy_pick_min_candidate.url4",
    "filter_judge_candidate.url4",
    "filter_pipeline_candidate.url4",
    "gate_abstain_vote_candidate.url4",
    "gate_judge_vote_candidate.url4",
    "gate_verbalized_vote_candidate.url4",
    "gate_writer_vote_candidate.url4",
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
# The files of L47 that do not hold exactly one combine spec (counted by hand on 633fec3a1).
_SPEC_COUNTS = {
    "corrective_vote_candidate.url4": 2,
    "model_synthesizer_candidate.url4": 0,
    "two_reducers_candidate.url4": 2,
}
_SPEC_START = '{"extract":'  # canonical JSON sorts the keys, so every spec starts here
_SAMPLES_KEY = re.compile(r"\bsamples\s*:")  # a url4 struct key `samples:`
_OLD_SOURCES = {"verbalized", "logprob", "entropy"}

# The shared test data. The SDK test module holds the same values (ST/test_consistency_words.py).
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
_MEMBERS = ["member_1", "member_2", "member_3"]
# CR-2: member_1's rows in url4 row order (sample_3 first); sample_2 and sample_4 failed.
_R1 = json.dumps(
    [
        {"source_position": 3, "source_name": "sample_3", "result": "z"},
        {"source_position": 1, "source_name": "sample_1", "result": "x"},
    ]
)


def _cons_spec(**entry: Any) -> dict[str, Any]:
    """CR-1: builtin_vote_spec(3) with the one consistency entry ``cons`` (plus overrides)."""
    return {**builtin_vote_spec(3), "signals": {"cons": {**copy.deepcopy(_CONS), **entry}}}


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
    value null. 4 + 0 = 2 + 2 = 0 + 4 = n. The vote: a: 2.0 [member_1, member_2], b: 1.0
    [member_3]; agreement 2 / 3 = 0.6666666666666666; the answer is member_1.
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


def _context(**body: Any) -> str:
    return json.dumps(
        {"input": "q", "outputs": {"member_1": "a", "member_2": "b", "member_3": "c"}, **body}
    )


def _samples(member_1: str = _R1, **others: str) -> dict[str, str]:
    return {"member_1": member_1, "member_2": "[]", "member_3": "[]", **others}


def _rows(*rows: tuple[int, str, Any]) -> str:
    return json.dumps([{"source_position": p, "source_name": n, "result": r} for p, n, r in rows])


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


# --- CR#1: existing evidence, specs and contexts have no consistency (CHAR) ---------------------


def test_existing_evidence_and_specs_have_no_consistency() -> None:
    cases = json.loads((_DATA / "evidence_cases.json").read_text(encoding="utf-8"))
    for name in L37:
        wire = cases[name]
        dumped = _dump(wire)
        assert _bytes(dumped) == _bytes(wire), name
        assert "consistency" not in wire, name
        assert "consistency" not in dumped, name

    total = 0
    for name in L47:
        text = (_DATA / name).read_text(encoding="utf-8")
        assert _SAMPLES_KEY.search(text) is None, name
        specs = _combine_specs(text)
        assert len(specs) == _SPEC_COUNTS.get(name, 1), name
        for spec in specs:
            assert '"consistency"' not in spec, name
            signals = parse_spec(spec).signals or {}
            assert {entry.source for entry in signals.values()} <= _OLD_SOURCES, name
        total += len(specs)
    assert total == 48


# --- CR#2: a bare consistency entry is still refused (CHAR) -------------------------------------


def test_a_bare_consistency_entry_is_still_refused() -> None:
    bare = {**builtin_vote_spec(3), "signals": {"conf": {"source": "consistency"}}}
    assert "conf" not in _spec_failure(bare)
    only_n = {**builtin_vote_spec(3), "signals": {"cons": {"source": "consistency", "n": 4}}}
    _spec_failure(only_n)


# --- CR#3: the Engine parses a consistency entry ------------------------------------------------


def test_engine_parses_a_consistency_entry() -> None:
    parsed = parse_spec(spec_text(_cons_spec()))
    assert parsed.signals is not None
    entry = parsed.signals["cons"]
    assert isinstance(entry, ConsistencySource)
    assert entry.n == 4
    assert type(entry.temperature) is float
    assert entry.temperature == 1.0
    assert entry.match.extract == StepSpec(op="last_number@1", args={})
    assert entry.match.normalize == StepSpec(op="numeric@1", args={})
    assert declares_consistency(parsed) == ("cons", entry)

    zero = parse_spec(
        spec_text(_cons_spec(n=32, temperature=0, match={**_MATCH, "normalize": None}))
    )
    assert zero.signals is not None
    zero_entry = zero.signals["cons"]
    assert isinstance(zero_entry, ConsistencySource)
    assert (zero_entry.n, zero_entry.temperature, zero_entry.match.normalize) == (32, 0.0, None)
    assert type(zero_entry.temperature) is float

    mixed = parse_spec(
        spec_text(
            {
                **builtin_vote_spec(3),
                "signals": {"conf": dict(_CONF), "cons": copy.deepcopy(_CONS)},
            }
        )
    )
    assert mixed.signals is not None
    assert declares_consistency(mixed) == ("cons", mixed.signals["cons"])
    conf_only = {**builtin_vote_spec(3), "signals": {"conf": dict(_CONF)}}
    assert declares_consistency(parse_spec(spec_text(conf_only))) is None
    assert declares_consistency(parse_spec(spec_text(builtin_vote_spec(3)))) is None


# --- CR#4: bad consistency entries are refused, and the message echoes no value -----------------

_QUIET = (
    "combine spec is invalid: signals: Value error, "
    "signals must map declared names to known sources"
)


@pytest.mark.parametrize(
    ("signals", "message"),
    [
        pytest.param({"zq": {"source": "consistency"}}, _QUIET, id="bare-zq"),
        pytest.param({"cons": {**_CONS, "n": 0}}, _QUIET, id="n-0"),
        pytest.param({"cons": {**_CONS, "n": 33}}, _QUIET, id="n-33"),
        pytest.param({"cons": {**_CONS, "n": 2.5}}, _QUIET, id="n-2-5"),
        pytest.param({"cons": {**_CONS, "n": True}}, _QUIET, id="n-true"),
        pytest.param({"cons": {**_CONS, "temperature": -0.5}}, _QUIET, id="temperature-neg"),
        pytest.param(
            {"cons": {k: v for k, v in _CONS.items() if k != "temperature"}},
            _QUIET,
            id="no-temperature",
        ),
        pytest.param(
            {"cons": {k: v for k, v in _CONS.items() if k != "match"}}, _QUIET, id="no-match"
        ),
        pytest.param(
            {"cons": {**_CONS, "match": {**_MATCH, "extract": None}}}, _QUIET, id="extract-null"
        ),
        pytest.param({"cons": {**_CONS, "flags": 1}}, _QUIET, id="extra-flags"),
        pytest.param(
            {"cons": {**_CONS, "match": {**_MATCH, "flags": 1}}}, _QUIET, id="match-extra"
        ),
        pytest.param(
            {"cons": dict(_CONS), "cons2": dict(_CONS)},
            "combine spec is invalid: spec: Value error, "
            "signals declares at most one consistency source",
            id="two-consistency",
        ),
    ],
)
def test_engine_refuses_bad_consistency_entries_without_echo(
    signals: dict[str, Any], message: str
) -> None:
    # control: the CR-1 entry itself parses, so the refusal below is the entry's own fault
    assert declares_consistency(parse_spec(spec_text(_cons_spec()))) is not None
    got = _spec_failure({**builtin_vote_spec(3), "signals": copy.deepcopy(signals)})

    assert got == message
    for value in ("zq", "33", "-0.5"):
        assert value not in got


# --- CR#5: the Engine context reads samples exactly when expected -------------------------------


def test_engine_context_reads_samples_exactly_when_expected() -> None:
    parsed = parse_context(_context(samples=_samples()), _MEMBERS, samples_n=4)
    assert parsed.samples == {"member_1": ("x", "z"), "member_2": (), "member_3": ()}
    assert parsed.samples is not None
    assert list(parsed.samples) == _MEMBERS
    assert parsed.outputs == {"member_1": "a", "member_2": "b", "member_3": "c"}

    full = _rows((4, "sample_4", "w"), (2, "sample_2", "y"), (1, "sample_1", "x"))
    three = parse_context(_context(samples=_samples(member_3=full)), _MEMBERS, samples_n=4)
    assert three.samples is not None
    assert three.samples["member_3"] == ("x", "y", "w")

    plain = parse_context(_context(), _MEMBERS)
    assert plain.samples is None


# --- CR#6: bad samples maps and rows are refused with fixed messages ----------------------------

_PRESENCE = "combine context samples are present exactly when the spec declares consistency"
_MEMBER_SET = "combine context samples do not match the spec members"
_SHAPE = "combine context has the wrong shape"
_ROWS_JSON = "combine context samples is not valid JSON"
_ROWS_SHAPE = "combine context samples has the wrong shape"
_SLOTS = "combine context samples do not match the sample slots"
_SECRET = "zq secret"  # a sample text; no message may hold it


@pytest.mark.parametrize(
    ("body", "samples_n", "message"),
    [
        pytest.param({"samples": _samples()}, None, _PRESENCE, id="present-not-declared"),
        pytest.param({}, 4, _PRESENCE, id="absent-declared"),
        pytest.param(
            {"samples": {"member_1": _R1, "member_2": "[]"}}, 4, _MEMBER_SET, id="no-member-3"
        ),
        pytest.param({"samples": _samples(member_4="[]")}, 4, _MEMBER_SET, id="extra-member-4"),
        pytest.param(
            {"samples": {"member_1": [], "member_2": "[]", "member_3": "[]"}},
            4,
            _SHAPE,
            id="value-not-text",
        ),
        pytest.param({"samples": ["[]", "[]", "[]"]}, 4, _SHAPE, id="samples-list"),
        pytest.param({"samples": _samples("not json")}, 4, _ROWS_JSON, id="rows-not-json"),
        pytest.param({"samples": _samples("{}")}, 4, _ROWS_SHAPE, id="rows-object"),
        pytest.param({"samples": _samples('[["zq secret"]]')}, 4, _ROWS_SHAPE, id="row-list"),
        pytest.param(
            {
                "samples": _samples(
                    json.dumps(
                        [
                            {
                                "source_position": 1,
                                "source_name": "sample_1",
                                "result": _SECRET,
                                "extra": 1,
                            }
                        ]
                    )
                )
            },
            4,
            _ROWS_SHAPE,
            id="row-extra-key",
        ),
        pytest.param(
            {"samples": _samples(_rows((5, "sample_5", _SECRET)))}, 4, _SLOTS, id="sample-5"
        ),
        pytest.param(
            {"samples": _samples(_rows((3, "sample_2", _SECRET)))},
            4,
            _SLOTS,
            id="wrong-position",
        ),
        pytest.param(
            {"samples": _samples(_rows((1, "sample_1", _SECRET), (1, "sample_1", "x")))},
            4,
            _SLOTS,
            id="sample-1-twice",
        ),
        pytest.param(
            {"samples": _samples(_rows((True, "sample_1", _SECRET)))},
            4,
            _SLOTS,
            id="position-true",
        ),
        pytest.param(
            {"samples": _samples(_rows((1, "sample_1", 12)))}, 4, _SLOTS, id="result-number"
        ),
    ],
)
def test_engine_context_refuses_bad_samples_maps_and_rows(
    body: dict[str, Any], samples_n: int | None, message: str
) -> None:
    # control: the CR-2 context itself parses, so the refusal below is the case's own fault
    assert parse_context(_context(samples=_samples()), _MEMBERS, samples_n=4).samples is not None
    with pytest.raises(SpecInvalid) as caught:
        parse_context(_context(**body), _MEMBERS, samples_n=samples_n)

    assert caught.value.code == "combine_spec_invalid"
    assert str(caught.value) == message
    assert "zq" not in str(caught.value)


def _panel_context(panel: str) -> str:
    return json.dumps({"input": "q", "panel": panel})


@pytest.mark.parametrize(
    ("panel", "message"),
    [
        pytest.param("not json", "combine context panel is not valid JSON", id="not-json"),
        pytest.param("{}", "combine context panel has the wrong shape", id="object"),
        pytest.param(
            _rows((4, "member_4", "x")),
            "combine context panel does not match the spec members",
            id="member-4",
        ),
    ],
)
def test_the_quorum_panel_keeps_its_messages(panel: str, message: str) -> None:
    with pytest.raises(SpecInvalid) as caught:
        parse_context(_panel_context(panel), _MEMBERS)

    assert str(caught.value) == message
    answered = parse_context(_panel_context(_rows((2, "member_2", "b"))), _MEMBERS)
    assert answered.outputs == {"member_2": "b"}
    assert answered.samples is None


# --- CR#7: the consistency record serializes in the pinned key order ----------------------------


def test_consistency_record_serializes_in_the_pinned_key_order() -> None:
    wire = _consistency_wire()

    evidence = CombineEvidence.model_validate(copy.deepcopy(wire))
    dumped = evidence.model_dump(mode="json", by_alias=True)

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
        "consistency",
        "declared",
        "result",
        "dropped",
        "finish_reason",
    ]
    for record in dumped["consistency"]["cons"]:
        assert list(record) == ["member_id", "matched", "succeeded", "failed"]
    assert _bytes(dumped) == _bytes(wire)
    assert evidence.consistency == {
        "cons": [
            SampleCountRecord(member_id="member_1", matched=2, succeeded=4, failed=0),
            SampleCountRecord(member_id="member_2", matched=2, succeeded=2, failed=2),
            SampleCountRecord(member_id="member_3", matched=None, succeeded=0, failed=4),
        ]
    }

    # a sample set that answered and never matched is valid: 0 / 2 = 0.0, not missing
    zero = copy.deepcopy(wire)
    zero["consistency"]["cons"][0] = _record("member_1", 0, 2, 2)
    zero["members"][0]["signals"]["cons"] = 0.0
    assert _bytes(_dump(zero)) == _bytes(zero)


# --- CR#8: CS-I1..CS-I5 refuse mismatches -------------------------------------------------------

_CS_I4 = "matched is at most succeeded, and a match needs a successful sample"
_CS_I1 = "a consistency record goes with one declared consistency source"
_CS_I2 = "a consistency record names every member in order"
_CS_I3 = "succeeded and failed samples add up to n"
_CS_I5 = "a consistency value is matched over succeeded"
_MIN_0 = "Input should be greater than or equal to 0"


def _with(wire: dict[str, Any], **changes: Any) -> dict[str, Any]:
    changed = copy.deepcopy(wire)
    changed.update(changes)
    return changed


def _refusals() -> list[Any]:
    wire = _consistency_wire()
    records = wire["consistency"]["cons"]
    no_value = copy.deepcopy(wire)
    no_value["consistency"]["cons"][0] = _record("member_1", None, 4, 0)
    no_key = copy.deepcopy(wire)
    no_key["members"][2]["signals"] = {}
    low = copy.deepcopy(wire)
    low["members"][0]["signals"]["cons"] = 0.4
    record = SampleCountRecord
    evidence = CombineEvidence
    return [
        pytest.param(record, _record("member_1", 3, 2, 2), _CS_I4, id="matched-over-succeeded"),
        pytest.param(record, _record("member_1", 0, 0, 4), _CS_I4, id="match-without-success"),
        pytest.param(record, _record("member_1", None, 4, -1), _MIN_0, id="failed-negative"),
        pytest.param(record, _record("member_1", -1, 4, 0), _MIN_0, id="matched-negative"),
        pytest.param(
            evidence, _with(wire, declared={"conf": dict(_CONF)}), _CS_I1, id="no-declared-entry"
        ),
        pytest.param(
            evidence, {k: v for k, v in wire.items() if k != "consistency"}, _CS_I1, id="no-record"
        ),
        pytest.param(
            evidence, _with(wire, consistency={"other": records}), _CS_I1, id="other-name"
        ),
        pytest.param(
            evidence,
            _with(wire, consistency={"cons": [records[0], records[2]]}),
            _CS_I2,
            id="leaves-out-member-2",
        ),
        pytest.param(
            evidence,
            _with(wire, consistency={"cons": [records[1], records[0], records[2]]}),
            _CS_I2,
            id="swaps-1-and-2",
        ),
        pytest.param(
            evidence,
            _with(wire, consistency={"cons": [_record("member_1", 2, 4, 1), *records[1:]]}),
            _CS_I3,
            id="adds-up-to-5",
        ),
        pytest.param(evidence, low, _CS_I5, id="value-0-4"),
        pytest.param(evidence, no_value, _CS_I5, id="value-without-match"),
        pytest.param(evidence, no_key, _CS_I5, id="no-value-key"),
    ]


@pytest.mark.parametrize(("model", "payload", "rule"), _refusals())
def test_sample_count_and_evidence_invariants_refuse_mismatches(
    model: type[SampleCountRecord | CombineEvidence], payload: dict[str, Any], rule: str
) -> None:
    with pytest.raises(ValidationError, match=re.escape(rule)):
        model.model_validate(payload)


# --- CR#9: every optional key in the order signal, cut, consistency, declared, gate -------------


def test_evidence_with_every_optional_key_orders_cut_consistency_declared_gate() -> None:
    wire = _all_optional_wire()

    dumped = _dump(wire)

    keys = list(dumped)
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
    assert _bytes(dumped) == _bytes(wire)
    fields = list(CombineEvidence.model_fields)
    assert fields[fields.index("cut") + 1] == "consistency"
    assert fields[fields.index("consistency") + 1] == "declared"
    doc = " ".join((evidence_module.__doc__ or "").split())
    assert "``consistency`` (written only when the spec declares a consistency source)" in doc


# --- CR#13: the schema snapshots hold the consistency entry and record (PIN) --------------------


def test_schema_snapshots_hold_the_consistency_entry_and_record() -> None:
    spec = _pinned(COMBINE_SPEC_SCHEMA)
    union = spec["properties"]["signals"]["anyOf"][0]["additionalProperties"]
    assert union["discriminator"]["mapping"]["consistency"] == "#/$defs/ConsistencySource"
    assert {"$ref": "#/$defs/ConsistencySource"} in union["oneOf"]
    source = spec["$defs"]["ConsistencySource"]
    assert source["required"] == ["source", "n", "temperature", "match"]
    assert source["additionalProperties"] is False
    assert source["properties"]["source"] == {
        "const": "consistency",
        "title": "Source",
        "type": "string",
    }
    assert source["properties"]["n"]["type"] == "integer"
    assert source["properties"]["n"]["minimum"] == 1
    assert source["properties"]["n"]["maximum"] == 32
    assert source["properties"]["temperature"]["type"] == "number"
    assert source["properties"]["temperature"]["minimum"] == 0
    match = spec["$defs"]["ConsistencyMatch"]
    assert match["required"] == ["extract", "normalize"]
    assert match["additionalProperties"] is False
    assert len(spec["required"]) == 8

    evidence = _pinned(COMBINE_EVIDENCE_SCHEMA)
    assert evidence["properties"]["consistency"] == {
        "anyOf": [
            {
                "additionalProperties": {
                    "items": {"$ref": "#/$defs/SampleCountRecord"},
                    "type": "array",
                },
                "type": "object",
            },
            {"type": "null"},
        ],
        "default": None,
        "title": "Consistency",
    }
    assert "consistency" not in evidence["required"]
    assert len(evidence["required"]) == 18
    record = evidence["$defs"]["SampleCountRecord"]
    assert record["required"] == ["member_id", "matched", "succeeded", "failed"]
    assert record["additionalProperties"] is False
    assert COMBINE_SPEC_SCHEMA == "screamingface.combine-spec.v1"
    assert COMBINE_EVIDENCE_SCHEMA == "screamingface.combine-evidence.v1"
