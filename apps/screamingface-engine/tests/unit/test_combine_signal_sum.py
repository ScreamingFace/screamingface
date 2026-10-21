"""A declared sum of signals: parse, value per member, rules and gate read it (E4b part 6, unit 1).

FEATURE: a spec ``signals`` entry ``{"source": "sum", "coefficients": {name: number}}`` gives each
member one number, the exact sum of coefficient x value over the named declared signals, rounded
once to a float (signal-sum PRD SM-1 to SM-5, SM-E1, SM-E2, SM-D1 to SM-D4, SM-D6).
STORY: as a benchmark author, I declare ``risk = 0.5 x sev_a + 0.3 x sev_b`` once, and a vote
weight, a Pick, a Rank, a Filter or a gate reads ``risk`` by name, as any declared signal.
INVARIANT defended: SU-I1 to SU-I4 (erd §1); missing is not zero; a refusal names the rule and
never echoes a name or a number; a rule still reads at most one signal (P6); the one reader call
of a combine call stays one (C5).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from combine_golden_support import builtin_vote_spec
from combine_signal_support import argmax_spec, filter_spec, rank_signal_spec, sources
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import CombineOutcome
from screamingface_engine.combine.ports import (
    REPLY_LOGPROB_SUM,
    REPLY_TOKENS,
    AccountingReader,
    CombineError,
    MemberSources,
    SpecInvalid,
)
from screamingface_engine.combine.signal_sum import sum_value
from screamingface_engine.combine.spec import SumSource, parse_spec

_LOGGER = "screamingface_engine.combine.endpoint"
SUM = {"source": "sum", "coefficients": {"sev_a": 0.5, "sev_b": 0.3}}
SEV_A = {"source": "verbalized", "pattern": "A: ([0-9]+)"}
SEV_B = {"source": "verbalized", "pattern": "B: ([0-9]+)"}
# Signals S of signal-sum §3: the sum first, then its two components.
SIGNALS: dict[str, Any] = {"risk": SUM, "sev_a": SEV_A, "sev_b": SEV_B}
# Fixture S of signal-sum §3. Oracle by hand with fractions.Fraction: 0.5 x 4 + 0.3 x 10 is
# 4.99999999999999988898..., which rounds to 5.0; 0.5 x 2 + 0.3 x 5 is 2.49999999999999994449...,
# which rounds to 2.5; member_3 states no "B:", so sev_b and risk are None.
TEXTS = ["A: 4\nB: 10\nThe answer is 9", "A: 2\nB: 5\nSo 9", "A: 6\nI get 12"]


def _outcome(
    spec: dict[str, Any], context: str, accounting: AccountingReader | None = None
) -> CombineOutcome:
    return run(spec_text(spec), context, registry=BUILTIN_OPERATORS, accounting=accounting)


def _wire(outcome: CombineOutcome) -> dict[str, Any]:
    return outcome.evidence.model_dump(mode="json", by_alias=True)


def _statuses(evidence: dict[str, Any]) -> list[tuple[str, str | None]]:
    return [(row["status"], row["reason"]) for row in evidence["members"]]


def _with_sum(spec: dict[str, Any]) -> dict[str, Any]:
    return {**spec, "signals": SIGNALS}


def _spec_failure(signals: dict[str, Any]) -> str:
    with pytest.raises(SpecInvalid) as caught:
        parse_spec(spec_text({**builtin_vote_spec(3), "signals": signals}))
    assert caught.value.code == "combine_spec_invalid"
    return str(caught.value)


# --- SM#2: the Engine parses a sum source ------------------------------------------------------


def test_engine_parses_a_sum_source() -> None:
    parsed = parse_spec(spec_text(_with_sum(argmax_spec(3, "risk", "min"))))

    assert parsed.signals is not None
    assert parsed.signals["risk"] == SumSource(
        source="sum", coefficients={"sev_a": 0.5, "sev_b": 0.3}
    )
    assert list(parsed.signals) == ["risk", "sev_a", "sev_b"]


# --- SM#3: a bad sum is refused, and the message echoes no name and no number -------------------

_QUIET = "signals must map declared names to known sources"
_EIGHT = {"sev_a": 0.5, "sev_b": 0.3, **{f"c{index}": 1.0 for index in range(3, 9)}}
_BAD_SUMS: list[Any] = [
    pytest.param(
        {"risk": {"source": "sum", "coefficients": {"zzz": 0.5}}},
        "a sum adds only names the spec declares",
        id="not-declared",
    ),
    pytest.param(
        {
            "risk": {"source": "sum", "coefficients": {"risk2": 1.0}},
            "risk2": {"source": "sum", "coefficients": {"sev_a": 1.0}},
        },
        "a sum does not add another sum",
        id="sum-of-a-sum",
    ),
    pytest.param(
        {"risk": {"source": "sum", "coefficients": {"risk": 1.0}}},
        "a sum does not add another sum",
        id="itself",
    ),
    pytest.param(
        {"risk": {"source": "sum", "coefficients": {"sev_a": 0.0}}},
        "a sum coefficient is not zero",
        id="zero",
    ),
    pytest.param(
        {"risk": {"source": "sum", "coefficients": {"sev_a": -0.0}}},
        "a sum coefficient is not zero",
        id="minus-zero",
    ),
    pytest.param({"risk": {"source": "sum", "coefficients": {}}}, _QUIET, id="empty"),
    pytest.param({"risk": {"source": "sum", "coefficients": _EIGHT}}, _QUIET, id="eight"),
    pytest.param({"risk": {"source": "sum", "coefficients": {"sev_a": True}}}, _QUIET, id="bool"),
    pytest.param({"risk": {"source": "sum", "coefficients": {"sev_a": "0.5"}}}, _QUIET, id="text"),
    pytest.param({"risk": {"source": "sum", "coefficients": {"sev_a": None}}}, _QUIET, id="null"),
    pytest.param({"risk": {**SUM, "note": 1}}, _QUIET, id="extra-key"),
    pytest.param({"risk": {"source": "sum"}}, _QUIET, id="no-coefficients"),
]


@pytest.mark.parametrize(("bad", "rule"), _BAD_SUMS)
def test_engine_refuses_bad_sums_without_echo(bad: dict[str, Any], rule: str) -> None:
    message = _spec_failure({"sev_a": SEV_A, "sev_b": SEV_B, **bad})

    assert message.endswith(rule)
    for echo in ("zzz", "sev_a", "0.5", "risk"):
        assert echo not in message


# --- SM#4: the sum is the exact rational sum, rounded once --------------------------------------


def test_sum_value_is_the_exact_sum_rounded_once() -> None:
    # Oracle by hand: 0.1 x 3 + 0.1 x 0.1 is exactly 0.31000000000000000943..., nearest float 0.31;
    # the float sum of the rounded products, math.fsum([0.1 * 3.0, 0.1 * 0.1]), is
    # 0.31000000000000005.
    values = {"a": 3.0, "b": 0.1}
    assert sum_value((("a", 0.1), ("b", 0.1)), values) == 0.31
    assert sum_value((("b", 0.1), ("a", 0.1)), values) == 0.31
    # 2 x 3 - 0.5 x 8 = 6 - 4 = 2; 0.5 x 7 = 3.5 (all exact in binary).
    assert sum_value((("a", 2.0), ("b", -0.5)), {"a": 3.0, "b": 8.0}) == 2.0
    assert sum_value((("b", -0.5), ("a", 2.0)), {"a": 3.0, "b": 8.0}) == 2.0
    assert sum_value((("a", 0.5),), {"a": 7.0}) == 3.5


# --- SM#5: missing when a component is missing, or when the sum is outside the float range ------


def test_sum_value_is_missing_when_a_component_is_missing_or_out_of_range() -> None:
    assert sum_value((("a", 0.1), ("b", 0.1)), {"a": 3.0, "b": None}) is None
    assert sum_value((("a", 0.1), ("b", 0.1)), {"a": None, "b": 3.0}) is None
    # 1e308 x 10 + 1e308 x 10 = 2e309 > the largest float (about 1.797e308): no float holds it.
    assert sum_value((("a", 1e308), ("b", 1e308)), {"a": 10.0, "b": 10.0}) is None
    # 1e308 x 10 - 1e308 x 10 = 0 exactly; the float products would be inf - inf.
    assert sum_value((("a", 1e308), ("b", -1e308)), {"a": 10.0, "b": 10.0}) == 0.0


# --- SM#6: every member records the sum, in the recorded key order -----------------------------


def test_every_member_records_the_sum_after_its_components() -> None:
    evidence = _wire(_outcome(_with_sum(argmax_spec(3, "risk", "min")), context_text(TEXTS)))

    assert [list(row["signals"].items()) for row in evidence["members"]] == [
        [("risk", 5.0), ("sev_a", 4.0), ("sev_b", 10.0)],
        [("risk", 2.5), ("sev_a", 2.0), ("sev_b", 5.0)],
        [("risk", None), ("sev_a", 6.0), ("sev_b", None)],
    ]


# --- SM#7: a Pick, a Rank and a Filter read the sum by name -------------------------------------


def test_a_pick_reads_the_sum_by_name_and_excludes_a_member_with_no_sum() -> None:
    outcome = _outcome(_with_sum(argmax_spec(3, "risk", "min")), context_text(TEXTS))
    evidence = _wire(outcome)

    assert _statuses(evidence) == [
        ("answered", None),
        ("answered", None),
        ("excluded", "no_signal"),
    ]
    assert evidence["chosen"] == ["member_2"]
    assert evidence["signal"] == {"key": "risk", "order": "min"}
    assert evidence["result"]["member_id"] == "member_2"
    assert outcome.output == TEXTS[1]


def test_a_rank_and_a_filter_read_the_sum_by_name() -> None:
    # Rank k=1, min: risk 5.0, 2.5, None -> member_2 is rank 1, member_1 rank 2, member_3 no rank.
    ranked = _wire(_outcome(_with_sum(rank_signal_spec(3, 1, "risk", "min")), context_text(TEXTS)))
    assert ranked["chosen"] == ["member_2"]
    assert [row.get("rank") for row in ranked["members"]] == [2, 1, None]
    assert _statuses(ranked)[2] == ("excluded", "no_signal")

    # Filter risk <= 3.0: 5.0 fails, 2.5 passes, None is excluded.
    kept_spec = filter_spec(3, {"key": "risk", "cmp": "le", "value": 3.0})
    kept = _wire(_outcome(_with_sum(kept_spec), context_text(TEXTS)))
    assert kept["chosen"] == ["member_2"]
    assert _statuses(kept)[2] == ("excluded", "no_signal")


# --- SM#8: a vote weight reads the sum; a zero sum is no usable weight --------------------------


def test_a_vote_weight_reads_the_sum_and_a_zero_sum_has_no_weight() -> None:
    spec = vote_spec(
        3,
        extract={"op": "last_number@1", "args": {}},
        normalize={"op": "numeric@1", "args": {}},
        reduce={"op": "weighted_mode@1", "args": {}},
        select={"op": "max_weight_holder@1", "args": {}},
        weights={"signal": "risk"},
        signals=SIGNALS,
    )
    texts = ["A: 4\nB: 10\nThe answer is 9", "A: 2\nB: 5\nI get 12", "A: 0\nB: 0\nSo 12"]
    outcome = _outcome(spec, context_text(texts))
    evidence = _wire(outcome)

    # member_3: risk = 0.5 x 0 + 0.3 x 0 = 0.0, not above zero, so no weight (endpoint _weight).
    assert _statuses(evidence)[2] == ("excluded", "no_weight")
    assert evidence["members"][2]["signals"] == {"risk": 0.0, "sev_a": 0.0, "sev_b": 0.0}
    assert evidence["tally"] == [
        {"value": "9", "score": 5.0, "holders": ["member_1"]},
        {"value": "12", "score": 2.5, "holders": ["member_2"]},
    ]
    assert evidence["chosen"] == ["member_1"]
    assert evidence["agreement"] == 0.6666666666666666  # 5.0 / (5.0 + 2.5)
    assert outcome.output == texts[0]


# --- SM#9: a gate reads the sum as chosen:<name> and as mean:<name> -----------------------------


def test_a_gate_reads_a_sum_as_chosen_and_as_mean() -> None:
    # The majority is 9 (member_1, member_2); first_holder chooses member_1.
    chosen_gate = {"observe": "chosen:risk", "cmp": "<=", "threshold": 3.0, "otherwise": "abstain"}
    chosen = _outcome({**_with_sum(builtin_vote_spec(3)), "gate": chosen_gate}, context_text(TEXTS))
    record = _wire(chosen)
    assert (record["gate"]["observed"], record["gate"]["passed"]) == (5.0, False)
    assert record["result"]["status"] == "abstain"
    assert record["result"]["reason"] == "gate_not_met"
    assert chosen.output == ""

    # mean over the members with a value: (5.0 + 2.5) / 2 = 3.75 <= 4.0.
    mean_gate = {"observe": "mean:risk", "cmp": "<=", "threshold": 4.0, "otherwise": "abstain"}
    mean = _outcome({**_with_sum(builtin_vote_spec(3)), "gate": mean_gate}, context_text(TEXTS))
    record = _wire(mean)
    assert (record["gate"]["observed"], record["gate"]["passed"]) == (3.75, True)
    assert record["result"]["member_id"] == "member_1"
    assert mean.output == TEXTS[0]


# --- SM#10: the evidence declares the sum entry as the spec wrote it ----------------------------


def test_the_evidence_declares_the_sum_entry() -> None:
    evidence = _wire(_outcome(_with_sum(argmax_spec(3, "risk", "min")), context_text(TEXTS)))

    assert evidence["declared"] == {
        "risk": {"source": "sum", "coefficients": {"sev_a": 0.5, "sev_b": 0.3}},
        "sev_a": {"source": "verbalized", "pattern": "A: ([0-9]+)"},
        "sev_b": {"source": "verbalized", "pattern": "B: ([0-9]+)"},
    }


# --- SM#11: a sum of a logprob name uses the one reader call ------------------------------------

_BLEND: dict[str, Any] = {
    "blend": {"source": "sum", "coefficients": {"conf": 0.01, "lp": 1.0}},
    "conf": {"source": "verbalized", "pattern": "Confidence: ([0-9]+)"},
    "lp": {"source": "logprob", "form": "prob"},
}
# ln(0.25) = -1.3862943611198906; over 2 tokens the mean is ln(0.5), so "prob" is 0.5.
_ROW = {REPLY_TOKENS: 2, REPLY_LOGPROB_SUM: -1.3862943611198906}


def _reader(asked: list[list[str]]) -> AccountingReader:
    def reader(known: MemberSources, /) -> dict[str, dict[str, float | None]]:
        asked.append(sorted(known))
        return {"member_1": dict(_ROW)}  # member_2 has no reply numbers

    return reader


def test_a_sum_of_a_logprob_name_uses_the_one_reader_call() -> None:
    asked: list[list[str]] = []
    context = {**json.loads(context_text(["Confidence: 80\nA", "Confidence: 90\nB"]))}
    context["sources"] = sources(2)
    spec = {**argmax_spec(2, "blend", "max"), "signals": _BLEND}
    evidence = _wire(_outcome(spec, json.dumps(context), _reader(asked)))

    # blend = 0.01 x 80 + 1.0 x 0.5 = 0.8 + 0.5 = 1.3 (exact sum 1.30000000000000001665...).
    assert [row["signals"] for row in evidence["members"]] == [
        {"blend": 1.3, "conf": 80.0, "lp": 0.5},
        {"blend": None, "conf": 90.0, "lp": None},
    ]
    assert _statuses(evidence)[1] == ("excluded", "no_signal")
    assert evidence["chosen"] == ["member_1"]
    assert asked == [["member_1", "member_2"]]


def test_a_member_a_panel_left_out_has_no_sum_and_no_reader_row() -> None:
    asked: list[list[str]] = []
    rows = [
        {"source_position": 1, "source_name": "member_1", "result": "Confidence: 80\nA"},
        {"source_position": 2, "source_name": "member_2", "result": "Confidence: 90\nB"},
    ]
    context = {"input": "q", "panel": json.dumps(rows), "sources": sources(3)}
    spec = {**argmax_spec(3, "blend", "max"), "signals": _BLEND}
    evidence = _wire(_outcome(spec, json.dumps(context), _reader(asked)))

    assert evidence["members"][2]["signals"] == {"blend": None, "conf": None, "lp": None}
    assert _statuses(evidence)[2] == ("fail", "missing")
    assert asked == [["member_1", "member_2"]]  # one call, and never for member_3


# --- SM#14: a rule still reads at most one signal; the log line keeps its format ---------------


def test_the_one_signal_rule_is_unchanged_for_a_sum() -> None:
    # The weights read the sum "risk", and the reduce args read "sev_a": two signals in one step.
    spec = vote_spec(
        3,
        extract={"op": "last_number@1", "args": {}},
        normalize={"op": "numeric@1", "args": {}},
        reduce={"op": "by_signal@1", "args": {"key": "sev_a", "order": "max"}},
        select={"op": "best_holder@1", "args": {"order": "max"}},
        weights={"signal": "risk"},
        signals=SIGNALS,
    )
    with pytest.raises(CombineError) as caught:
        _outcome(spec, context_text(TEXTS))

    assert caught.value.code == "combine_spec_invalid"
    assert "a combine step reads at most one signal" in str(caught.value)


def test_a_sum_run_logs_the_one_combine_line(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger=_LOGGER):
        _outcome(_with_sum(argmax_spec(3, "risk", "min")), context_text(TEXTS))
    lines = [
        item.getMessage()
        for item in caplog.records
        if item.name == _LOGGER and item.levelname == "INFO"
    ]

    assert len(lines) == 1
    assert lines[0].startswith("combine binding=synthesis_1 reducer=pick ")
    assert lines[0].endswith(" outcome=ok")


# --- SM#12 (PIN): the contract case pick_sum_min ----------------------------------------------

_CONTRACT = Path(__file__).parent / "data" / "combine_contract" / "evidence_cases.json"


def test_contract_case_pick_sum_min_is_byte_equal_on_both_sides() -> None:
    pinned = json.loads(_CONTRACT.read_text(encoding="utf-8"))["pick_sum_min"]
    outcome = _outcome(_with_sum(argmax_spec(3, "risk", "min")), context_text(TEXTS))
    written = json.dumps(
        outcome.evidence.model_dump(by_alias=True), ensure_ascii=False, separators=(",", ":")
    )

    assert written == json.dumps(pinned, ensure_ascii=False, separators=(",", ":"))
    assert [row["signals"] for row in pinned["members"]] == [
        {"risk": 5.0, "sev_a": 4.0, "sev_b": 10.0},
        {"risk": 2.5, "sev_a": 2.0, "sev_b": 5.0},
        {"risk": None, "sev_a": 6.0, "sev_b": None},
    ]
    assert pinned["chosen"] == ["member_2"]
    assert pinned["declared"]["risk"] == {
        "source": "sum",
        "coefficients": {"sev_a": 0.5, "sev_b": 0.3},
    }


# --- SM#4 (review fix, unit 1): an underflowing negative sum is +0.0, never -0.0 ----------------


def test_sum_value_never_gives_negative_zero() -> None:
    # The exact sum -1e-200 x 1e-200 = -1e-400 underflows to -0.0 in float(Fraction); the invariant
    # of signal_sum.py says the result is never -0.0 (logprob_forms.py guards it with + 0.0).
    assert str(sum_value((("a", -1e-200),), {"a": 1e-200})) == "0.0"
    # The exact sum -5e-324 x 0.5 + 1.0 x 0.0 = -2^-1075 is a tie that rounds to -0.0.
    assert str(sum_value((("a", -5e-324), ("b", 1.0)), {"a": 0.5, "b": 0.0})) == "0.0"
