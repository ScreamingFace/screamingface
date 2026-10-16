"""The vote gate chooses and records (E4b part 5, unit 2; gate-decision PRD GD#1-21).

FEATURE: a vote keeps its majority answer only when a computed number (agreement, a declared
signal of the chosen member, or its mean over the members) passes the recipe's threshold;
otherwise an abstain, a fallback judge or a fallback writer gives the answer (ans:Q1-Q3).
STORY: as a researcher, a weak majority does not count as a confident answer, and the evidence
shows the number, the comparison and the branch, so I can replay the decision.
INVARIANT defended: FB-I1 (the majority branch never reads a fallback reply), GR-I1 (a vote with
no answer does not run the gate), GD-E6 (a fallback judge never picks an excluded member), P14 (a
writer value is the vote's normalized answer), and an ungated vote keeps its bytes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from combine_golden_support import builtin_vote_spec
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.benchmarks.contract import OperationOutput
from screamingface_engine.benchmarks.operation_outputs import final_operation_abstained
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import COMBINE_ROUTE, CombineOutcome
from screamingface_engine.combine.ports import (
    CombineError,
    InputTooLarge,
    JudgeReplyInvalid,
)
from url4 import RelExpr, Text, expr, render, src

CONTRACT = Path(__file__).parent / "data" / "combine_contract" / "evidence_cases.json"
_LOGGER = "screamingface_engine.combine.endpoint"
T = 0.6666666666666666  # float(Decimal(2) / Decimal(3)): two of three voters agree
V_TEXTS = ["A", "A", "B"]
CONF = {"conf": {"source": "verbalized", "pattern": "Confidence: ([0-9]+)"}}
CONF_TEXTS = ["Confidence: 90\nA", "Confidence: 60\nA", "Confidence: 30\nB"]
WEIGHTED: dict[str, Any] = {
    "reduce": {"op": "weighted_mode@1", "args": {}},
    "select": {"op": "max_weight_holder@1", "args": {}},
}
GATE_KEYS = ["observe", "observed", "cmp", "threshold", "passed", "branch", "otherwise"]
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
)  # test-plan §6 list L32 (ruff format will put one name on each line)
GATE_CASES = (
    "vote_gate_majority",
    "vote_gate_abstain",
    "vote_gate_judge",
    "vote_gate_writer",
    "vote_gate_not_run",
)


def _row(member: str, raw: str, value: str) -> dict[str, Any]:
    return {
        "member_id": member,
        "raw": raw,
        "value": value,
        "status": "answered",
        "reason": None,
        "signals": {},
        "weight": None,
        "score": None,
    }


V_MEMBERS = [_row("member_1", "A", "a"), _row("member_2", "A", "a"), _row("member_3", "B", "b")]
V_TALLY = [
    {"value": "a", "score": 2.0, "holders": ["member_1", "member_2"]},
    {"value": "b", "score": 1.0, "holders": ["member_3"]},
]
V_UNGATED: dict[str, Any] = {
    "schema": "screamingface.combine-evidence.v1",
    "kind": "answer",
    "reducer": "vote",
    "operators": ["last_line@1", "text@1", "mode@1", "first_holder@1"],
    "members": V_MEMBERS,
    "tally": V_TALLY,
    "judge": None,
    "fields": None,
    "chosen": ["member_1"],
    "built": False,
    "agreement": T,
    "tie": False,
    "median": None,
    "presentation_order": None,
    "separator_collision": None,
    "signal": None,
    "result": {"member_id": "member_1", "value": "a", "status": "answered", "reason": None},
    "dropped": 0,
    "finish_reason": "stop",
}
# GD-2: the whole evidence of a gate abstain on fixture V (also the GR-I3 base wire). A full
# literal in the pinned wire key order (unit 1: `gate` after `signal`, before `result`).
GATE_ABSTAIN_WIRE: dict[str, Any] = {
    "schema": "screamingface.combine-evidence.v1",
    "kind": "answer",
    "reducer": "vote",
    "operators": ["last_line@1", "text@1", "mode@1", "first_holder@1"],
    "members": V_MEMBERS,
    "tally": V_TALLY,
    "judge": None,
    "fields": None,
    "chosen": [],
    "built": False,
    "agreement": T,
    "tie": False,
    "median": None,
    "presentation_order": None,
    "separator_collision": None,
    "signal": None,
    "gate": {
        "observe": "agreement",
        "observed": T,
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


def real_vote(member_count: int = 3, **overrides: Any) -> dict[str, Any]:
    """A vote over the built-in operators (last line, text, mode, first holder): fixture V."""
    spec: dict[str, Any] = {
        "extract": {"op": "last_line@1", "args": {}},
        "normalize": {"op": "text@1", "args": {}},
        "reduce": {"op": "mode@1", "args": {}},
        "select": {"op": "first_holder@1", "args": {}},
    }
    spec.update(overrides)
    return vote_spec(member_count, **spec)


def gate(observe: str, cmp: str, threshold: float, otherwise: str) -> dict[str, Any]:
    return {"observe": observe, "cmp": cmp, "threshold": threshold, "otherwise": otherwise}


def gated(gate_value: dict[str, Any], member_count: int = 3, **overrides: Any) -> dict[str, Any]:
    return {**real_vote(member_count, **overrides), "gate": gate_value}


def record(
    threshold: float, otherwise: str, *, passed: bool, observed: float | None = T
) -> dict[str, Any]:
    """The evidence gate record of an agreement gate with cmp >= that ran."""
    return {
        "observe": "agreement",
        "observed": observed,
        "cmp": ">=",
        "threshold": threshold,
        "passed": passed,
        "branch": "majority" if passed else "fallback",
        "otherwise": otherwise,
    }


def combine(
    spec: dict[str, Any], texts: list[str], signals: dict[str, str] | None = None
) -> CombineOutcome:
    return run(spec_text(spec), context_text(texts, signals), registry=BUILTIN_OPERATORS)


def wire(outcome: CombineOutcome) -> dict[str, Any]:
    return outcome.evidence.model_dump(mode="json", by_alias=True)


def evidence_bytes(outcome: CombineOutcome) -> str:
    """The bytes the Candidate envelope writes (the contract fixture encoder)."""
    evidence = outcome.evidence.model_dump(by_alias=True)
    return json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))


def as_bytes(outcome: CombineOutcome) -> str:
    return outcome.output + "\n" + evidence_bytes(outcome)


def failure(spec: dict[str, Any], context: str) -> CombineError:
    with pytest.raises(CombineError) as caught:
        run(spec_text(spec), context, registry=BUILTIN_OPERATORS)
    return caught.value


def _panel(texts: dict[int, str], signals: dict[str, str]) -> str:
    rows = [
        {"source_position": index, "source_name": f"member_{index}", "result": answer}
        for index, answer in texts.items()
    ]
    return json.dumps({"input": "q", "panel": json.dumps(rows), "signals": signals})


# --- GD#1 (CHAR) ---------------------------------------------------------------------------------


def test_ungated_vote_evidence_and_output_are_unchanged() -> None:
    outcome = combine(real_vote(), V_TEXTS)
    evidence = wire(outcome)

    assert outcome.output == "A"
    assert evidence == V_UNGATED
    assert list(evidence) == list(V_UNGATED)
    pinned = json.loads(CONTRACT.read_text(encoding="utf-8"))
    rebuilt = {
        "vote_tie": combine(
            builtin_vote_spec(4), ["The answer is 9", "I get 12", "So 9", "Final: 12"]
        ),
        "vote_one_failed": combine(builtin_vote_spec(3), ["The answer is 42", "no idea", "So 42"]),
    }
    for name, again in rebuilt.items():
        assert evidence_bytes(again) == json.dumps(
            pinned[name], ensure_ascii=False, separators=(",", ":")
        ), name


# --- GD#2-5: the four branches on fixture V ----------------------------------------------------


def test_gate_passes_and_the_majority_answers() -> None:
    outcome = combine(gated(gate("agreement", ">=", 0.6, "abstain")), V_TEXTS)
    evidence = wire(outcome)

    assert outcome.output == "A"
    assert evidence["result"] == V_UNGATED["result"]
    assert evidence["chosen"] == ["member_1"]
    assert evidence["gate"] == record(0.6, "abstain", passed=True)
    assert list(evidence["gate"]) == GATE_KEYS
    assert {key: value for key, value in evidence.items() if key != "gate"} == V_UNGATED


def test_gate_fails_and_abstains_with_gate_not_met() -> None:
    outcome = combine(gated(gate("agreement", ">=", 0.7, "abstain")), V_TEXTS)
    evidence = wire(outcome)

    assert outcome.output == ""
    assert evidence == GATE_ABSTAIN_WIRE
    assert list(evidence) == list(GATE_ABSTAIN_WIRE)


def test_gate_fails_and_the_fallback_judge_picks_a_member() -> None:
    outcome = combine(
        gated(gate("agreement", ">=", 0.7, "judge")), V_TEXTS, {"fallback_judge": " member_3\n"}
    )
    evidence = wire(outcome)

    assert outcome.output == "B"
    assert evidence["result"] == {
        "member_id": "member_3",
        "value": "b",
        "status": "answered",
        "reason": None,
    }
    assert (evidence["chosen"], evidence["built"]) == (["member_3"], False)
    assert evidence["judge"] == {"raw": " member_3\n", "returns": "label", "parsed": "member_3"}
    assert evidence["presentation_order"] == "author"
    assert evidence["gate"] == record(0.7, "judge", passed=False)
    assert (evidence["tally"], evidence["agreement"], evidence["tie"]) == (V_TALLY, T, False)

    # GD-D4: a present member that failed is a valid label; its value is None.
    failed = combine(
        gated(gate("agreement", ">", 1.0, "judge")), ["A", "A", ""], {"fallback_judge": "member_3"}
    )
    failed_evidence = wire(failed)
    assert failed.output == ""
    assert failed_evidence["agreement"] == 1.0
    assert failed_evidence["gate"]["passed"] is False
    assert failed_evidence["result"] == {
        "member_id": "member_3",
        "value": None,
        "status": "answered",
        "reason": None,
    }
    assert failed_evidence["members"][2]["status"] == "fail"


def test_gate_fails_and_the_fallback_writer_answers() -> None:
    outcome = combine(
        gated(gate("agreement", ">=", 0.7, "writer")), V_TEXTS, {"fallback_writer": "C written"}
    )
    evidence = wire(outcome)

    assert outcome.output == "C written"
    assert evidence["result"] == {
        "member_id": None,
        "value": "c written",
        "status": "answered",
        "reason": None,
    }
    assert (evidence["built"], evidence["chosen"]) == (True, [])
    assert (evidence["presentation_order"], evidence["judge"]) == (None, None)
    assert evidence["gate"] == record(0.7, "writer", passed=False)
    assert (evidence["tally"], evidence["agreement"]) == (V_TALLY, T)


# --- GD#6-8: the number and the comparison ------------------------------------------------------


def test_chosen_signal_gate_reads_the_chosen_members_value() -> None:
    passed = combine(gated(gate("chosen:conf", ">=", 80.0, "abstain"), signals=CONF), CONF_TEXTS)
    assert passed.output == "Confidence: 90\nA"
    assert (wire(passed)["gate"]["observed"], wire(passed)["gate"]["passed"]) == (90.0, True)

    failed = combine(gated(gate("chosen:conf", ">=", 95.0, "abstain"), signals=CONF), CONF_TEXTS)
    evidence = wire(failed)
    assert failed.output == ""
    assert evidence["result"]["reason"] == "gate_not_met"
    assert (evidence["gate"]["observed"], evidence["gate"]["passed"]) == (90.0, False)


def test_mean_signal_gate_reads_the_fsum_mean_of_present_values() -> None:
    spec = gated(gate("mean:conf", ">=", 50.0, "abstain"), signals=CONF)

    every = wire(combine(spec, CONF_TEXTS))["gate"]
    assert (every["observed"], every["passed"]) == (60.0, True)
    two = wire(combine(spec, ["Confidence: 90\nA", "Confidence: 60\nA", "B"]))["gate"]
    assert two["observed"] == 75.0


def test_equality_passes_for_ge_and_fails_for_gt() -> None:
    kept = wire(combine(gated(gate("agreement", ">=", 1.0, "abstain"), 2), ["A", "A"]))
    assert (kept["gate"]["passed"], kept["gate"]["branch"]) == (True, "majority")

    replaced = combine(
        gated(gate("agreement", ">", 1.0, "writer"), 2), ["A", "A"], {"fallback_writer": "W"}
    )
    assert replaced.output == "W"
    assert wire(replaced)["gate"]["passed"] is False
    assert wire(replaced)["result"]["value"] == "w"


# --- GD#9-10: FB-I1 and GR-I1 ---------------------------------------------------------------------


def test_majority_branch_never_reads_the_fallback_reply() -> None:
    spec = gated(gate("agreement", ">=", 0.6, "judge"))
    contexts: list[dict[str, str] | None] = [
        None,
        {"fallback_judge": "member_3"},
        {"fallback_judge": "not a member id"},
    ]

    seen = [as_bytes(combine(spec, V_TEXTS, signals)) for signals in contexts]

    assert seen[0] == seen[1] == seen[2]
    output, _, evidence_text = seen[0].partition("\n")
    evidence = json.loads(evidence_text)
    assert output == "A"
    assert (evidence["judge"], evidence["presentation_order"]) == (None, None)
    assert evidence["gate"]["branch"] == "majority"


def test_no_voter_leaves_the_gate_not_run_and_reads_no_reply() -> None:
    outcome = combine(
        gated(gate("agreement", ">=", 0.6, "judge")),
        ["", "", ""],
        {"fallback_judge": "not a member id"},
    )
    evidence = wire(outcome)

    assert outcome.output == ""
    assert evidence["result"] == {
        "member_id": None,
        "value": None,
        "status": "abstain",
        "reason": "no_votes",
    }
    assert evidence["gate"] == {
        "observe": "agreement",
        "observed": None,
        "cmp": ">=",
        "threshold": 0.6,
        "passed": None,
        "branch": None,
        "otherwise": "judge",
    }


# --- GD#11-15: errors -----------------------------------------------------------------------------


@pytest.mark.parametrize("reply", ["member_9", "the third one"])
def test_fallback_judge_reply_that_names_no_present_member_fails(reply: str) -> None:
    error = failure(
        gated(gate("agreement", ">=", 0.7, "judge")),
        context_text(V_TEXTS, {"fallback_judge": reply}),
    )

    assert isinstance(error, JudgeReplyInvalid)
    assert error.code == "judge_reply_invalid"
    assert str(error) == "the judge reply is not exactly one member id"
    assert reply not in str(error)
    # GD-D5: a member that the quorum panel left out is not present, so it is not a label.
    left_out = failure(
        gated(gate("agreement", ">", 0.9, "judge")),
        _panel({1: "A", 2: "B"}, {"fallback_judge": "member_3"}),
    )
    assert left_out.code == "judge_reply_invalid"


@pytest.mark.parametrize("otherwise", ["judge", "writer"])
def test_fallback_branch_without_its_signal_is_spec_invalid(otherwise: str) -> None:
    error = failure(gated(gate("agreement", ">=", 0.7, otherwise)), context_text(V_TEXTS))

    assert error.code == "combine_spec_invalid"
    assert str(error) == f"the gate fallback needs the fallback_{otherwise} signal"


@pytest.mark.parametrize(
    ("spec", "key"),
    [
        (real_vote(), "fallback_judge"),
        (gated(gate("agreement", ">=", 0.7, "writer")), "fallback_judge"),
        (gated(gate("agreement", ">=", 0.7, "abstain")), "fallback_judge"),
        (gated(gate("agreement", ">=", 0.7, "judge")), "fallback_writer"),
    ],
)
def test_fallback_signal_without_a_matching_gate_is_spec_invalid(
    spec: dict[str, Any], key: str
) -> None:
    error = failure(spec, context_text(V_TEXTS, {key: "member_3"}))

    assert error.code == "combine_spec_invalid"
    assert str(error) == "a fallback signal needs a gate that names it"


def test_oversize_writer_reply_is_input_too_large() -> None:
    reply = "x" * (8 * 1024 * 1024 + 1)
    error = failure(
        gated(gate("agreement", ">=", 0.7, "writer")),
        context_text(V_TEXTS, {"fallback_writer": reply}),
    )

    assert isinstance(error, InputTooLarge)
    assert error.code == "combine_input_too_large"
    assert str(error) == "the combine output exceeds 8 MiB"


def test_oversize_fallback_judge_reply_is_judge_reply_invalid() -> None:
    reply = "a" * (64 * 1024 + 1)
    error = failure(
        gated(gate("agreement", ">=", 0.7, "judge")),
        context_text(V_TEXTS, {"fallback_judge": reply}),
    )

    assert isinstance(error, JudgeReplyInvalid)
    assert str(error) == "the judge reply exceeds 64 KiB"


# --- GD#16-18: derived ----------------------------------------------------------------------------


def test_missing_observed_number_takes_the_fallback() -> None:
    chosen = wire(
        combine(
            gated(gate("chosen:conf", ">=", 10.0, "abstain"), signals=CONF),
            ["A", "Confidence: 60\nA", "Confidence: 30\nB"],
        )
    )
    assert (chosen["gate"]["observed"], chosen["gate"]["passed"]) == (None, False)
    assert chosen["gate"]["branch"] == "fallback"
    assert chosen["result"]["reason"] == "gate_not_met"

    mean = wire(combine(gated(gate("mean:conf", "<=", 1000.0, "abstain"), signals=CONF), V_TEXTS))
    assert (mean["gate"]["observed"], mean["gate"]["passed"]) == (None, False)
    assert mean["result"]["reason"] == "gate_not_met"


def test_weighted_vote_gate_reads_the_weight_share() -> None:
    spec = gated(
        gate("agreement", ">=", 0.6, "abstain"),
        **WEIGHTED,
        weights={"member_1": 3.0, "member_2": 1.0, "member_3": 1.0},
    )

    evidence = wire(combine(spec, ["A", "B", "B"]))

    assert evidence["tally"] == [
        {"value": "a", "score": 3.0, "holders": ["member_1"]},
        {"value": "b", "score": 2.0, "holders": ["member_2", "member_3"]},
    ]
    assert evidence["agreement"] == 0.6
    assert (evidence["gate"]["observed"], evidence["gate"]["passed"]) == (0.6, True)
    assert evidence["chosen"] == ["member_1"]


def test_gate_abstain_marks_the_case_abstained_and_logs_its_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO", logger=_LOGGER):
        outcome = combine(gated(gate("agreement", ">=", 0.7, "abstain")), V_TEXTS)
    lines = [
        item.getMessage()
        for item in caplog.records
        if item.name == _LOGGER and item.levelname == "INFO"
    ]

    assert lines == [
        "combine binding=synthesis_1 reducer=vote voters=3/3 agreement=0.6666666666666666 "
        "tie=false outcome=abstain_gate_not_met"
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


# --- GD#19 (PIN): the contract fixture ---------------------------------------------------------


def test_evidence_contract_fixture_has_the_five_gate_cases() -> None:
    cases = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert sorted(cases) == sorted((*L32, *GATE_CASES))
    assert list(cases)[-5:] == list(GATE_CASES)
    majority, abstain, judge, writer, not_run = (cases[name] for name in GATE_CASES)
    tally = [
        {"value": "9", "score": 2.0, "holders": ["member_1", "member_2"]},
        {"value": "12", "score": 1.0, "holders": ["member_3"]},
    ]
    for case in (majority, abstain, judge, writer):
        assert (case["tally"], case["agreement"], case["tie"]) == (tally, T, False)
    assert majority["gate"] == record(0.6, "abstain", passed=True)
    assert majority["result"] == {
        "member_id": "member_1",
        "value": "9",
        "status": "answered",
        "reason": None,
    }
    assert abstain["gate"] == record(0.7, "abstain", passed=False)
    assert abstain["result"] == {
        "member_id": None,
        "value": None,
        "status": "abstain",
        "reason": "gate_not_met",
    }
    assert (abstain["chosen"], abstain["built"]) == ([], False)
    assert judge["gate"] == record(0.7, "judge", passed=False)
    assert judge["result"] == {
        "member_id": "member_3",
        "value": "12",
        "status": "answered",
        "reason": None,
    }
    assert judge["judge"] == {"raw": "member_3", "returns": "label", "parsed": "member_3"}
    assert judge["presentation_order"] == "author"
    assert writer["gate"] == record(0.7, "writer", passed=False)
    assert writer["result"] == {
        "member_id": None,
        "value": "10",
        "status": "answered",
        "reason": None,
    }
    assert (writer["built"], writer["chosen"]) == (True, [])
    assert not_run["gate"] == {
        "observe": "agreement",
        "observed": None,
        "cmp": ">=",
        "threshold": 0.6,
        "passed": None,
        "branch": None,
        "otherwise": "abstain",
    }
    assert not_run["result"]["reason"] == "no_votes"
    assert not_run["dropped"] == 3


# --- GD#20-21 -------------------------------------------------------------------------------------


def test_judge_weighted_vote_with_a_judge_fallback_reads_both_signals() -> None:
    spec = gated(
        gate("agreement", ">=", 0.7, "judge"), **WEIGHTED, weights={"signal": "score:judge"}
    )
    signals = {
        "judge": json.dumps({"member_1": 0.2, "member_2": 0.3, "member_3": 0.9}),
        "fallback_judge": "member_1",
    }

    outcome = combine(spec, V_TEXTS, signals)
    evidence = wire(outcome)

    assert evidence["tally"] == [
        {"value": "b", "score": 0.9, "holders": ["member_3"]},
        {"value": "a", "score": 0.5, "holders": ["member_1", "member_2"]},
    ]
    assert evidence["agreement"] == 0.6428571428571429
    assert evidence["gate"]["passed"] is False
    assert outcome.output == "A"
    assert evidence["result"] == {
        "member_id": "member_1",
        "value": "a",
        "status": "answered",
        "reason": None,
    }
    assert evidence["judge"] == {"raw": "member_1", "returns": "label", "parsed": "member_1"}
    assert evidence["presentation_order"] == "author"


def test_fallback_judge_cannot_pick_an_excluded_member() -> None:
    spec = {
        **vote_spec(
            3,
            extract={"op": "json_field@1", "args": {"path": "answer"}},
            normalize={"op": "text@1", "args": {}},
            weights={"signal": "field:confidence"},
            **WEIGHTED,
        ),
        "gate": gate("agreement", ">", 1.0, "judge"),
    }
    texts = [
        '{"answer":"A","confidence":0.9}',
        '{"answer":"A","confidence":0.4}',
        '{"answer":"B"}',
    ]

    error = failure(spec, context_text(texts, {"fallback_judge": "member_3"}))
    assert isinstance(error, JudgeReplyInvalid)
    assert str(error) == "the judge reply is not exactly one member id"

    evidence = wire(combine(spec, texts, {"fallback_judge": "member_2"}))
    assert evidence["agreement"] == 1.0
    assert evidence["members"][2]["status"] == "excluded"
    assert evidence["result"] == {
        "member_id": "member_2",
        "value": "a",
        "status": "answered",
        "reason": None,
    }
