"""A member that a combine rule leaves out is recorded as excluded (E4b part 2 unit 2).

FEATURE: E4b part 2 unit 2, member exclusion (ans:Q3, P1, P4, P5, P13). A weighted vote, a Pick,
a Rank or a Filter by a signal records a member with no usable weight or no signal as
``status "excluded"`` with the reason ``no_weight`` or ``no_signal``.
STORY: as a researcher, I read the evidence of a Case and see which member the rule left out, and
why, also when the step abstains.
INVARIANT: an excluded member keeps its raw, value, signals, weight and score; a failed member
stays "fail"; the operators and the Case answers do not change; an excluded member is never
chosen (CE-I3).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from combine_fields_support import step
from combine_golden_support import combine_input, member_readings, reduce_result
from combine_signal_support import argmax_spec, costs, filter_spec, rank_signal_spec, sources
from combine_support import context_text, fake_first, run, spec_text, vote_spec
from pydantic import ValidationError
from test_combine_evidence_contract_fixture import SCENARIOS, canonical_evidence

from screamingface_engine.combine import endpoint
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import CombineOutcome
from screamingface_engine.combine.evidence import CombineEvidence
from screamingface_engine.combine.operators.signals import filter_members
from screamingface_engine.combine.ports import OperatorDescriptor, TallyRow, canonical_json
from screamingface_engine.combine.spec import MAX_WEIGHT

# WHY: the two oracles are computed by hand (unit spec 2.9) and are the contract of EX#3/EX#4.
X1_WIRE: dict[str, Any] = {
    "schema": "screamingface.combine-evidence.v1",
    "kind": "answer",
    "reducer": "vote",
    "operators": ["json_field@1", "text@1", "weighted_mode@1", "max_weight_holder@1"],
    "members": [
        {
            "member_id": "member_1",
            "raw": "A",
            "value": "a",
            "status": "answered",
            "reason": None,
            "signals": {"field:confidence": 0.9},
            "weight": 0.9,
            "score": None,
        },
        {
            "member_id": "member_2",
            "raw": "A",
            "value": "a",
            "status": "answered",
            "reason": None,
            "signals": {"field:confidence": 0.4},
            "weight": 0.4,
            "score": None,
        },
        {
            "member_id": "member_3",
            "raw": "B",
            "value": "b",
            "status": "excluded",
            "reason": "no_weight",
            "signals": {"field:confidence": None},
            "weight": None,
            "score": None,
        },
    ],
    "tally": [{"value": "a", "score": 1.3, "holders": ["member_1", "member_2"]}],
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
    "result": {"member_id": "member_1", "value": "a", "status": "answered", "reason": None},
    "dropped": 0,
    "finish_reason": "stop",
}

X2_WIRE: dict[str, Any] = {
    "schema": "screamingface.combine-evidence.v1",
    "kind": "selection",
    "reducer": "filter",
    "operators": ["filter@1", "kept@1"],
    "members": [
        {
            "member_id": "member_1",
            "raw": None,
            "value": None,
            "status": "answered",
            "reason": None,
            "signals": {"field:confidence": 0.8},
            "weight": None,
            "score": 1.0,
        },
        {
            "member_id": "member_2",
            "raw": None,
            "value": None,
            "status": "answered",
            "reason": None,
            "signals": {"field:confidence": 0.2},
            "weight": None,
            "score": 0.0,
        },
        {
            "member_id": "member_3",
            "raw": None,
            "value": None,
            "status": "excluded",
            "reason": "no_signal",
            "signals": {"field:confidence": None},
            "weight": None,
            "score": 0.0,
        },
    ],
    "tally": None,
    "judge": None,
    "fields": None,
    "chosen": ["member_1"],
    "built": True,
    "agreement": None,
    "tie": False,
    "median": None,
    "presentation_order": None,
    "separator_collision": None,
    "signal": {"key": "field:confidence", "order": None},
    "result": {"member_id": None, "value": None, "status": "answered", "reason": None},
    "dropped": 0,
    "finish_reason": "stop",
}

_CONFIDENCE = {"signal": "field:confidence"}


def _x1_spec(count: int) -> dict[str, Any]:
    """The weighted vote of X1_WIRE over ``count`` members."""
    return vote_spec(
        count,
        extract=step("json_field@1", path="answer"),
        normalize=step("text@1"),
        reduce=step("weighted_mode@1"),
        select=step("max_weight_holder@1"),
        weights=_CONFIDENCE,
    )


def _threshold(count: int) -> dict[str, Any]:
    return filter_spec(count, {"key": "field:confidence", "cmp": "ge", "value": 0.5})


def _panel(texts: dict[int, str]) -> str:
    """A quorum panel context: only the listed members answered (test_combine_quorum_panel)."""
    rows = [
        {"source_position": index, "source_name": f"member_{index}", "result": text}
        for index, text in texts.items()
    ]
    return json.dumps({"input": "q", "panel": json.dumps(rows)})


def _run(spec: dict[str, Any], context: str, **kwargs: Any) -> CombineOutcome:
    return run(spec_text(spec), context, registry=BUILTIN_OPERATORS, **kwargs)


def _rows(outcome: CombineOutcome) -> list[tuple[str, str | None]]:
    return [(row.status, row.reason) for row in outcome.evidence.members]


def _as_answered(row: dict[str, Any]) -> dict[str, Any]:
    """An excluded row as it reads with no rule: answered, no reason, everything else kept."""
    if row["status"] != "excluded":
        return row
    return {**row, "status": "answered", "reason": None}


def _scenario_wires() -> dict[str, dict[str, Any]]:
    return {name: json.loads(canonical_evidence(build())) for name, build in SCENARIOS.items()}


# --- CHAR: the behavior that exists before this unit ---------------------------------------


def test_weighted_vote_drops_a_member_with_no_usable_weight() -> None:
    readings = member_readings(
        ["9", "9", "12"],
        weights=["0.5", None, "0.2"],
        signals=[{"field:confidence": 0.5}, {"field:confidence": None}, {"field:confidence": 0.2}],
    )
    tally = reduce_result("weighted_mode@1", readings).tally

    assert tally == (
        TallyRow("9", Decimal("0.5"), ("member_1",)),
        TallyRow("12", Decimal("0.2"), ("member_3",)),
    )


def test_filter_gives_a_missing_signal_mark_zero() -> None:
    readings = member_readings(
        ["x", "y", "z"],
        signals=[{"field:confidence": 0.8}, {"field:confidence": 0.2}, {"field:confidence": None}],
    )
    marks = filter_members(
        combine_input(readings), {"key": "field:confidence", "cmp": "ge", "value": 0.5}
    ).scores

    assert marks == {"member_1": Decimal(1), "member_2": Decimal(0), "member_3": Decimal(0)}


# --- the rule is computed once and changes no answer ---------------------------------------


def test_case_answers_do_not_change_with_exclusion(monkeypatch: pytest.MonkeyPatch) -> None:
    with_rule = _scenario_wires()
    monkeypatch.setattr(endpoint, "_exclusion", lambda spec, reduce, bound: None)
    without = _scenario_wires()

    for name in with_rule:
        assert {
            **with_rule[name],
            "members": [_as_answered(row) for row in with_rule[name]["members"]],
        } == without[name], name
    changed = {
        name
        for name in with_rule
        if any(row["status"] == "excluded" for row in with_rule[name]["members"])
    }
    assert changed >= {
        "filter_signal_excluded",
        "mean_weighted_value",
        "rank_cut_not_met",
        "vote_weight_excluded",
    }


def test_all_members_without_weight_abstain_and_are_all_excluded() -> None:
    outcome = _run(
        _x1_spec(3),
        context_text(
            ['{"answer":"A"}', '{"answer":"A","confidence":0}', '{"answer":"B","confidence":-1}']
        ),
    )
    evidence = outcome.evidence

    assert outcome.output == ""
    assert evidence.result.model_dump() == {
        "member_id": None,
        "value": None,
        "status": "abstain",
        "reason": "no_votes",
    }
    assert _rows(outcome) == [("excluded", "no_weight")] * 3
    assert [row.value for row in evidence.members] == ["a", "a", "b"]
    assert [row.signals["field:confidence"] for row in evidence.members] == [None, 0.0, -1.0]
    assert evidence.dropped == 0
    assert evidence.chosen == []


# --- X1: a weighted vote by a signal ----------------------------------------------------------


def test_weighted_vote_records_no_weight_member_as_excluded() -> None:
    texts = [
        '{"answer":"A","confidence":0.9}',
        '{"answer":"A","confidence":0.4}',
        '{"answer":"B"}',
    ]
    outcome = _run(_x1_spec(3), context_text(texts))
    evidence = outcome.evidence

    assert outcome.output == texts[0]
    assert _rows(outcome) == [("answered", None), ("answered", None), ("excluded", "no_weight")]
    assert (evidence.members[2].raw, evidence.members[2].value, evidence.members[2].weight) == (
        "B",
        "b",
        None,
    )
    assert json.loads(canonical_evidence(SCENARIOS["vote_weight_excluded"]())) == X1_WIRE


def test_zero_negative_and_over_cap_weights_exclude_with_no_weight() -> None:
    texts = [
        '{"answer":"A","confidence":0.5}',
        '{"answer":"A","confidence":0}',
        '{"answer":"B","confidence":-1}',
        f'{{"answer":"B","confidence":{MAX_WEIGHT!r}}}',
        '{"answer":"B","confidence":1e307}',
    ]
    outcome = _run(_x1_spec(5), context_text(texts))
    evidence = outcome.evidence

    assert outcome.output == texts[3]
    assert evidence.chosen == ["member_4"]
    assert _rows(outcome) == [
        ("answered", None),
        ("excluded", "no_weight"),
        ("excluded", "no_weight"),
        ("answered", None),
        ("excluded", "no_weight"),
    ]
    assert [row.weight for row in evidence.members] == [0.5, None, None, MAX_WEIGHT, None]
    assert [row.signals["field:confidence"] for row in evidence.members] == [
        0.5,
        0.0,
        -1.0,
        MAX_WEIGHT,
        1e307,
    ]


@pytest.mark.parametrize(
    ("spec", "context", "expected"),
    [
        (
            _x1_spec(4),
            context_text(
                [
                    '{"answer":"A","confidence":0.9}',
                    "not json",
                    '{"answer":"B","confidence":0.5}',
                    '{"answer":"B"}',
                ]
            ),
            [
                ("answered", None),
                ("fail", "not_json"),
                ("answered", None),
                ("excluded", "no_weight"),
            ],
        ),
        (
            _x1_spec(4),
            _panel(
                {
                    1: '{"answer":"A","confidence":0.9}',
                    3: '{"answer":"B","confidence":0.5}',
                    4: '{"answer":"B"}',
                }
            ),
            [
                ("answered", None),
                ("fail", "missing"),
                ("answered", None),
                ("excluded", "no_weight"),
            ],
        ),
        (
            _threshold(4),
            _panel({1: '{"confidence":0.8}', 3: '{"confidence":0.9}', 4: "{}"}),
            [
                ("answered", None),
                ("fail", "missing"),
                ("answered", None),
                ("excluded", "no_signal"),
            ],
        ),
    ],
    ids=["not_json", "panel_x1", "panel_x2"],
)
def test_a_failed_member_stays_failed_when_its_signal_is_missing(
    spec: dict[str, Any], context: str, expected: list[tuple[str, str | None]]
) -> None:
    outcome = _run(spec, context)

    assert _rows(outcome) == expected
    assert outcome.evidence.members[1].signals == {"field:confidence": None}
    assert outcome.evidence.dropped == 1


def test_authored_weights_never_exclude() -> None:
    spec = vote_spec(
        5,
        extract=step("last_number@1"),
        normalize=step("numeric@1"),
        reduce=step("weighted_mode@1"),
        select=step("max_weight_holder@1"),
        weights={
            "member_1": 3.0,
            "member_2": 3.0,
            "member_3": 1.0,
            "member_4": 1.0,
            "member_5": 1.0,
        },
    )
    outcome = _run(spec, context_text(["9", "9", "12", "12", "no number"]))

    assert outcome.output == "9"
    assert _rows(outcome) == [("answered", None)] * 4 + [("fail", "empty")]
    assert [row.weight for row in outcome.evidence.members] == [3.0, 3.0, 1.0, 1.0, 1.0]


@pytest.mark.parametrize(
    ("reducer", "reduce_op", "select_op"),
    [
        ("vote", "mode@1", "first_holder@1"),
        ("median", "median@1", "nearest@1"),
        ("mean", "mean@1", "value@1"),
    ],
)
def test_signal_weight_on_an_unweighted_op_never_excludes(
    reducer: str, reduce_op: str, select_op: str
) -> None:
    spec = vote_spec(
        3,
        reducer=reducer,
        extract=step("json_field@1", path="answer"),
        normalize=step("numeric@1"),
        reduce=step(reduce_op),
        select=step(select_op),
        weights=_CONFIDENCE,
    )
    texts = [
        '{"answer":10,"confidence":0.9}',
        '{"answer":10}',
        '{"answer":30,"confidence":0.5}',
    ]
    outcome = _run(spec, context_text(texts))

    assert _rows(outcome) == [("answered", None)] * 3
    assert [row.weight for row in outcome.evidence.members] == [0.9, None, 0.5]


def test_only_the_three_weighted_reduce_ops_read_weights() -> None:
    assert {d.id for d in BUILTIN_OPERATORS if d.reads_weights} == {
        "weighted_mode@1",
        "weighted_median@1",
        "weighted_mean@1",
    }
    with pytest.raises(ValueError, match="only a reduce operator may read the member weights"):
        OperatorDescriptor("x", 1, "select", "s", fake_first, reads_weights=True)


# --- X2: a Pick, a Rank and a Filter by a signal ------------------------------------------------


def test_pick_by_signal_records_no_signal_member_as_excluded() -> None:
    texts = [
        canonical_json({"confidence": 0.4}),
        canonical_json({}),
        canonical_json({"confidence": 0.7}),
    ]
    outcome = _run(argmax_spec(3, "field:confidence", "max"), context_text(texts))
    evidence = outcome.evidence

    assert outcome.output == texts[2]
    assert evidence.chosen == ["member_3"]
    assert _rows(outcome) == [("answered", None), ("excluded", "no_signal"), ("answered", None)]
    assert [row.score for row in evidence.members] == [0.4, None, 0.7]


def test_rank_by_signal_records_no_signal_member_as_excluded() -> None:
    outcome = _run(
        rank_signal_spec(3, 2, "cost_usd", "min"),
        context_text(["alpha", "beta", "gamma"], None, sources(3)),
        accounting=costs(0.004, None, 0.002),
    )
    evidence = outcome.evidence

    assert evidence.chosen == ["member_3", "member_1"]
    assert _rows(outcome) == [("answered", None), ("excluded", "no_signal"), ("answered", None)]
    assert evidence.members[1].signals == {"cost_usd": None}
    assert evidence.members[1].score is None
    assert "member_2" not in evidence.chosen


def test_rank_with_no_signal_anywhere_abstains_with_all_excluded() -> None:
    outcome = _run(rank_signal_spec(3, 2, "field:score", "max"), context_text(["{}", "{}", "{}"]))
    evidence = outcome.evidence

    assert outcome.output == '{"input":"q","selected":[]}'
    assert evidence.result.status == "abstain"
    assert evidence.result.reason == "no_votes"
    assert _rows(outcome) == [("excluded", "no_signal")] * 3
    assert [row.score for row in evidence.members] == [None, None, None]


def test_filter_excludes_a_missing_signal_but_not_a_low_one() -> None:
    texts = [
        canonical_json({"confidence": 0.8}),
        canonical_json({"confidence": 0.2}),
        canonical_json({}),
    ]
    outcome = _run(_threshold(3), context_text(texts))
    evidence = outcome.evidence

    assert _rows(outcome) == [("answered", None), ("answered", None), ("excluded", "no_signal")]
    assert [row.score for row in evidence.members] == [1.0, 0.0, 0.0]
    assert evidence.chosen == ["member_1"]
    assert json.loads(canonical_evidence(SCENARIOS["filter_signal_excluded"]())) == X2_WIRE
    # WHY: the pattern form reads no signal, so it never excludes (its signal_read is None).
    pattern = _run(
        filter_spec(3, {"pattern": "ANSWER: \\d+"}),
        context_text(["ANSWER: 7", "no marker", "so ANSWER: 12"]),
    )
    assert _rows(pattern) == [("answered", None)] * 3


@pytest.mark.parametrize("score", [0, -0.5])
def test_judge_weight_of_zero_excludes_with_no_weight(score: float) -> None:
    reply = canonical_json({"member_1": 0.2, "member_2": score, "member_3": 0.5})
    spec = vote_spec(
        3,
        extract=step("last_number@1"),
        normalize=step("numeric@1"),
        reduce=step("weighted_mode@1"),
        select=step("max_weight_holder@1"),
        weights={"signal": "score:judge"},
    )
    outcome = _run(spec, context_text(["9", "9", "12"], {"judge": reply}))
    evidence = outcome.evidence

    assert outcome.output == "12"
    assert evidence.chosen == ["member_3"]
    assert _rows(outcome) == [("answered", None), ("excluded", "no_weight"), ("answered", None)]
    assert evidence.members[1].signals == {"score:judge": float(score)}


# --- X3, P3: a failure wins; dropped and the quorum count failures only -------------------------


def test_dropped_and_quorum_ignore_excluded_members() -> None:
    outcome = _run(_x1_spec(3), _panel({1: '{"answer":"A","confidence":0.9}', 3: '{"answer":"B"}'}))
    evidence = outcome.evidence

    assert outcome.output == '{"answer":"A","confidence":0.9}'
    assert _rows(outcome) == [("answered", None), ("fail", "missing"), ("excluded", "no_weight")]
    assert evidence.dropped == 1
    assert evidence.dropped == sum(row.status == "fail" for row in evidence.members)


# --- CE-I3: an excluded member is never chosen ----------------------------------------------------


def test_excluded_member_is_never_chosen() -> None:
    assert CombineEvidence.model_validate(X1_WIRE) is not None
    bad = {
        **X1_WIRE,
        "chosen": ["member_3"],
        "result": {"member_id": "member_3", "value": "b", "status": "answered", "reason": None},
    }

    with pytest.raises(ValidationError, match="never chooses an excluded member"):
        CombineEvidence.model_validate(bad)


# --- EX#15: the nearest pick never picks a member the rule left out ----------------------


def test_weighted_median_nearest_never_picks_an_excluded_member() -> None:
    spec = vote_spec(
        4,
        reducer="median",
        extract=step("json_field@1", path="answer"),
        normalize=step("numeric@1"),
        reduce=step("weighted_median@1"),
        select=step("nearest@1"),
        weights=_CONFIDENCE,
    )
    texts = [
        '{"answer":7}',
        '{"answer":3,"confidence":0.3}',
        '{"answer":7,"confidence":0.3}',
        '{"answer":9,"confidence":0.4}',
    ]
    outcome = _run(spec, context_text(texts))
    evidence = outcome.evidence

    assert outcome.output == texts[2]
    assert evidence.median == "7"
    assert evidence.chosen == ["member_3"]
    assert _rows(outcome) == [
        ("excluded", "no_weight"),
        ("answered", None),
        ("answered", None),
        ("answered", None),
    ]
