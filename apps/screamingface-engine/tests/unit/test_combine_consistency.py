"""The combine step computes and records the consistency value (E4b part 7, unit 2; CV#1-12).

FEATURE: a spec that declares ``{"source": "consistency", ...}`` gets, for each member, the
fraction of its successful extra samples whose match value equals the member's own match value
(ans:Q4), and the evidence records the counts in ``consistency``.
STORY: as a benchmark author with ``signals={"cons": sf.Consistency(n=5)}``, a weight, a Pick, a
Rank, a Filter or a gate reads ``cons``; a member whose samples all failed has no value and the
rule excludes it; the Case does not fail.
INVARIANT defended: value = matched / succeeded over the successful samples only; the samples never
vote; every exit (answer, abstain, gate) writes the record; a spec without consistency writes no
``consistency`` key; a refusal never echoes a member or sample text. Every oracle is hand-computed
in the PRD (fixtures V and W), never copied from the code's output.
"""

from __future__ import annotations

from typing import Any

import pytest
from combine_consistency_support import (
    V_ENTRY,
    V_NO_VOTES_RECORD,
    V_OUTPUTS,
    V_RECORD,
    V_SAMPLES,
    V_TALLY,
    W_OUTPUTS,
    W_RECORD,
    W_SAMPLES,
    context,
    member_panel,
    outcome,
    v_spec,
    w_spec,
    wire,
)
from combine_golden_support import builtin_vote_spec
from test_combine_evidence_contract_fixture import SCENARIOS

from screamingface_engine.combine.consistency import SampleCount, count_samples
from screamingface_engine.combine.ports import CombineError

T = 0.6666666666666666
MIB = 1024 * 1024
# test-plan §6 L37: the 37 evidence case names, as a literal (never read from the file).
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


def _step(op_id: str) -> dict[str, Any]:
    return {"op": op_id, "args": {}}


def _digits(text: str) -> str | None:
    """A stand-in match step: the text when it is all digits, else no value."""
    return text if text.isdigit() else None


def _never(text: str) -> str | None:
    raise AssertionError("read must not run when there is nothing to compare")


# --- CV#1 (CHAR): a spec without consistency writes no consistency key ----------------------


@pytest.mark.parametrize("name", L37)
def test_a_spec_without_consistency_writes_no_consistency_key(name: str) -> None:
    evidence = SCENARIOS[name]()

    assert evidence.consistency is None
    assert "consistency" not in evidence.model_dump(by_alias=True)


# --- CV#2: fixture V (CV-1, CV-3) ----------------------------------------------------------


def test_fixture_v_records_the_values_and_the_counts() -> None:
    result = outcome(v_spec(), context(outputs=V_OUTPUTS, samples=V_SAMPLES))
    data = wire(result)

    assert result.output == "so 12"
    assert data["tally"] == V_TALLY
    assert data["agreement"] == T
    assert data["chosen"] == ["member_1"]
    assert data["result"] == {
        "member_id": "member_1",
        "value": "12",
        "status": "answered",
        "reason": None,
    }
    assert [m["signals"] for m in data["members"]] == [
        {"cons": 0.5},
        {"cons": 1.0},
        {"cons": None},
    ]
    assert [m["status"] for m in data["members"]] == ["answered"] * 3
    assert data["consistency"] == {"cons": V_RECORD}
    assert [list(record) for record in data["consistency"]["cons"]] == [
        ["member_id", "matched", "succeeded", "failed"]
    ] * 3
    keys = list(data)
    assert keys[keys.index("consistency") + 1] == "declared"
    # CV-3: the declaration as written, `match` included.
    assert data["declared"] == {"cons": V_ENTRY}
    assert list(data["declared"]["cons"]) == ["source", "n", "temperature", "match"]


def test_count_samples_is_matched_over_the_successful_samples() -> None:
    counted = count_samples("12", ("12", "12", "7", "twelve"), 4, _digits)

    assert counted == SampleCount(2, 4, 0)
    assert counted.value == 0.5
    assert count_samples("12", ("12", "x"), 4, _digits) == SampleCount(1, 2, 2)
    assert count_samples("7", (), 4, _never) == SampleCount(None, 0, 4)
    assert count_samples(None, ("12",), 1, _never) == SampleCount(None, 1, 0)
    assert SampleCount(None, 0, 4).value is None
    assert SampleCount(0, 3, 0).value == 0.0
    assert SampleCount(2, 3, 0).value == T
    with pytest.raises(ValueError, match="more sample texts than samples"):
        count_samples("12", ("12", "12"), 1, _digits)


# --- CV#3: fixture W, the default match (CV-2) --------------------------------------------


def test_fixture_w_picks_the_most_consistent_member_with_the_default_match() -> None:
    result = outcome(w_spec(), context(outputs=W_OUTPUTS, samples=W_SAMPLES))
    data = wire(result)

    assert result.output == "A"
    assert data["chosen"] == ["member_3"]
    assert data["signal"] == {"key": "cons", "order": "max"}
    assert [m["signals"]["cons"] for m in data["members"]] == [T, 0.0, 1.0]
    assert data["consistency"] == {"cons": W_RECORD}


# --- CV#4: every sample failed (CV-4) -------------------------------------------------------


def test_every_failed_sample_gives_a_missing_value_and_the_rule_excludes_the_member() -> None:
    samples = {**W_SAMPLES, "member_3": {}}
    result = outcome(w_spec(), context(outputs=W_OUTPUTS, samples=samples))
    data = wire(result)
    member_3 = data["members"][2]

    assert data["consistency"]["cons"][2] == {
        "member_id": "member_3",
        "matched": None,
        "succeeded": 0,
        "failed": 3,
    }
    assert member_3["signals"] == {"cons": None}
    assert (member_3["status"], member_3["reason"]) == ("excluded", "no_signal")
    assert data["chosen"] == ["member_1"]
    assert result.output == "B"
    assert data["result"]["status"] == "answered"


# --- CV#5: a weighted vote reads consistency as the weight (CV-5) ---------------------------


def test_a_weighted_vote_reads_consistency_as_the_weight() -> None:
    spec = v_spec(
        reduce=_step("weighted_mode@1"),
        select=_step("max_weight_holder@1"),
        weights={"signal": "cons"},
    )
    result = outcome(spec, context(outputs=V_OUTPUTS, samples=V_SAMPLES))
    data = wire(result)

    assert [m["weight"] for m in data["members"]] == [0.5, 1.0, None]
    assert (data["members"][2]["status"], data["members"][2]["reason"]) == (
        "excluded",
        "no_weight",
    )
    assert data["tally"] == [{"value": "12", "score": 1.5, "holders": ["member_1", "member_2"]}]
    assert data["chosen"] == ["member_2"]
    assert result.output == "it is 12"


# --- CV#6: bad samples contexts (CV-E1) ------------------------------------------------------

_PRESENCE = "combine context samples are present exactly when the spec declares consistency"


@pytest.mark.parametrize(
    ("spec", "context_text", "message"),
    [
        pytest.param(v_spec(), context(outputs=V_OUTPUTS), _PRESENCE, id="no-samples-key"),
        pytest.param(
            v_spec(),
            context(outputs=V_OUTPUTS, samples={**V_SAMPLES, "member_1": {1: "12", 5: "12"}}),
            "combine context samples do not match the sample slots",
            id="sample-5-with-n-4",
        ),
        pytest.param(
            builtin_vote_spec(3),
            context(outputs=V_OUTPUTS, samples=V_SAMPLES),
            _PRESENCE,
            id="samples-without-a-declaration",
        ),
    ],
)
def test_bad_samples_contexts_are_spec_invalid_without_echo(
    spec: dict[str, Any], context_text: str, message: str
) -> None:
    with pytest.raises(CombineError) as caught:
        outcome(spec, context_text)

    assert caught.value.code == "combine_spec_invalid"
    assert str(caught.value) == message
    for text in (*V_OUTPUTS.values(), "twelve", "x 12"):
        assert text not in str(caught.value)


# --- CV#7: bad match operators use the step codes (CV-E2) -----------------------------------


@pytest.mark.parametrize(
    ("stage", "step", "code", "message"),
    [
        (
            "extract",
            _step("nope@1"),
            "combine_operator_unknown",
            "combine operator 'nope@1' is not registered",
        ),
        (
            "extract",
            _step("numeric@1"),
            "combine_spec_invalid",
            "combine operator 'numeric@1' is a normalize operator, not extract",
        ),
        (
            "extract",
            _step("regex@1"),
            "combine_spec_invalid",
            "regex@1 args are invalid: regex@1 needs a pattern and takes only pattern, group, "
            "occurrence and ignore_case",
        ),
        (
            "normalize",
            _step("last_line@1"),
            "combine_spec_invalid",
            "combine operator 'last_line@1' is a extract operator, not normalize",
        ),
    ],
)
def test_bad_match_operators_use_the_step_codes(
    stage: str, step: dict[str, Any], code: str, message: str
) -> None:
    entry = {**V_ENTRY, "match": {**V_ENTRY["match"], stage: step}}

    with pytest.raises(CombineError) as caught:
        outcome(v_spec(signals={"cons": entry}), context(outputs=V_OUTPUTS, samples=V_SAMPLES))

    assert caught.value.code == code
    assert str(caught.value) == message


# --- CV#8: the samples never vote (CV-D2) ---------------------------------------------------


def test_the_samples_never_vote() -> None:
    sevens = {member: {1: "7", 2: "7", 3: "7", 4: "7"} for member in V_OUTPUTS}
    result = outcome(v_spec(), context(outputs=V_OUTPUTS, samples=sevens))
    data = wire(result)

    assert data["tally"] == V_TALLY
    assert data["chosen"] == ["member_1"]
    assert result.output == "so 12"
    assert [m["signals"]["cons"] for m in data["members"]] == [0.0, 0.0, 1.0]
    assert [(r["succeeded"], r["failed"]) for r in data["consistency"]["cons"]] == [(4, 0)] * 3


# --- CV#9: an unreadable sample is succeeded and not matched (CV-D3) ------------------------


@pytest.mark.parametrize(
    ("fourth", "matched"),
    [
        pytest.param("twelve", 2, id="nothing-extracted"),
        pytest.param("1" * (MIB + 1), 2, id="over-the-read-cap"),
        # Its last number is 12: only the read cap stops the match (the control below matches).
        pytest.param("x" * MIB + " 12", 2, id="a-twelve-over-the-read-cap"),
        pytest.param("x" * 10 + " 12", 3, id="control-a-twelve-under-the-cap"),
    ],
)
def test_an_unreadable_sample_counts_as_succeeded_and_not_matched(
    fourth: str, matched: int
) -> None:
    samples = {**V_SAMPLES, "member_1": {1: "12", 2: "12", 3: "7", 4: fourth}}
    data = wire(outcome(v_spec(), context(outputs=V_OUTPUTS, samples=samples)))

    assert data["consistency"]["cons"][0] == {
        "member_id": "member_1",
        "matched": matched,
        "succeeded": 4,
        "failed": 0,
    }
    assert data["members"][0]["signals"] == {"cons": matched / 4}


# --- CV#10: a left-out member and no voters (CV-D4, CV-D5) ----------------------------------


def test_a_left_out_member_keeps_its_sample_counts() -> None:
    panel = member_panel({1: "so 12", 3: "maybe 7"})
    data = wire(outcome(v_spec(), context(panel=panel, samples=V_SAMPLES)))

    assert data["consistency"]["cons"] == [
        {"member_id": "member_1", "matched": 2, "succeeded": 4, "failed": 0},
        {"member_id": "member_2", "matched": None, "succeeded": 2, "failed": 2},
        {"member_id": "member_3", "matched": None, "succeeded": 0, "failed": 4},
    ]
    assert [m["signals"]["cons"] for m in data["members"]] == [0.5, None, None]
    assert (data["members"][1]["status"], data["members"][1]["reason"]) == ("fail", "missing")


def test_no_voters_still_record_the_counts() -> None:
    result = outcome(v_spec(), context(panel="[]", samples=V_SAMPLES))
    data = wire(result)

    assert result.output == ""
    assert data["result"] == {
        "member_id": None,
        "value": None,
        "status": "abstain",
        "reason": "no_votes",
    }
    assert data["consistency"] == {"cons": V_NO_VOTES_RECORD}
    assert [m["signals"] for m in data["members"]] == [{"cons": None}] * 3


# --- CV#11: the part 5 gate reads the value (CV-D6) -----------------------------------------


@pytest.mark.parametrize(
    ("threshold", "passed", "branch", "output"),
    [(0.6, False, "fallback", ""), (0.5, True, "majority", "so 12")],
)
def test_a_gate_reads_the_chosen_members_consistency(
    threshold: float, passed: bool, branch: str, output: str
) -> None:
    gate = {"observe": "chosen:cons", "cmp": ">=", "threshold": threshold, "otherwise": "abstain"}
    result = outcome(v_spec(gate=gate), context(outputs=V_OUTPUTS, samples=V_SAMPLES))
    data = wire(result)

    assert data["gate"] == {
        "observe": "chosen:cons",
        "observed": 0.5,
        "cmp": ">=",
        "threshold": threshold,
        "passed": passed,
        "branch": branch,
        "otherwise": "abstain",
    }
    assert result.output == output
    assert data["result"]["status"] == ("answered" if passed else "abstain")
    assert data["result"]["reason"] == (None if passed else "gate_not_met")
    assert data["consistency"] == {"cons": V_RECORD}


# --- CV#12: no match value; the row order (CV-D7, CV-D8) ------------------------------------


@pytest.mark.parametrize("text", ["so twelve", "x" * MIB + " 12"], ids=["no-number", "too-large"])
def test_a_member_with_no_match_value_has_no_value(text: str) -> None:
    outputs = {**V_OUTPUTS, "member_1": text}
    data = wire(outcome(v_spec(), context(outputs=outputs, samples=V_SAMPLES)))

    assert data["consistency"]["cons"][0] == {
        "member_id": "member_1",
        "matched": None,
        "succeeded": 4,
        "failed": 0,
    }
    assert data["members"][0]["signals"] == {"cons": None}
    assert data["members"][0]["status"] == "fail"


def test_the_row_order_does_not_change_the_counts() -> None:
    turned_rows = {**V_SAMPLES, "member_1": {4: "twelve", 3: "7", 2: "12", 1: "12"}}
    plain = outcome(v_spec(), context(outputs=V_OUTPUTS, samples=V_SAMPLES))
    turned = outcome(v_spec(), context(outputs=V_OUTPUTS, samples=turned_rows))

    assert wire(turned) == wire(plain)
    assert wire(turned)["consistency"]["cons"][0] == V_RECORD[0]
