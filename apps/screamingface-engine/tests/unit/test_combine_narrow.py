"""Narrow steps before the reduce, in one combine call (E4b map-reduce surface, narrow.md §3, §4).

FEATURE: a spec with ``narrow`` runs each narrow step (a filter or a top-k) on the live set, in
order, and the main step reads only the members that every narrow step kept. ``sf.Fanout(J) >>
sf.Filter(...) >> sf.Mean(...)`` and ``sf.Fanout(R) >> sf.Rank(k=3, ...) >> sf.Vote()`` run in one
call.
STORY: as a researcher, I narrow the panel to the members I trust before the vote, and I read in
the evidence which step left each member out and why.
INVARIANT defended: a member that a narrow step leaves out is ``excluded`` with ``not_selected``
(or ``no_signal`` when it had no value for the step's signal), by the first step that left it out,
and is never chosen (NR-I2, NR-I3); the main step's score and rank are on the live members only
(AR-I4); a narrow abstain stops the call and the gate does not run (NR-I5); a judge reply is
parsed over every answered member and scores only the live ones (the judged set). Every expected
value is computed by hand from the texts in ``combine_narrow_support``.
The contract file ``data/combine_contract/narrow_evidence_cases.json`` pins the bytes the core
writes for each scenario of narrow.md §7; the SDK twin only READS it. A deliberate change is made
by running this file as a script (``write_fixture()``) and reviewing the diff.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from combine_narrow_support import (
    CONF_SIGNAL,
    FILTER_MEAN_OUTPUTS,
    FILTER_RANK_OUTPUTS,
    GATE_OUTPUTS,
    JUDGED_OUTPUTS,
    MEAN_GATE,
    RANK_VOTE_OUTPUTS,
    context,
    filter_mean,
    filter_rank_envelope,
    gate_after_narrow,
    json_text,
    judge_argmax_after_filter,
    judge_rank_after_filter,
    judge_rank_weighted_vote,
    keep_matching,
    keep_where,
    mean_spec,
    narrow_cut_not_met,
    narrow_no_signal,
    narrow_no_votes,
    outcome,
    rank_vote,
    rows,
    step,
    vote_spec,
    wire,
)
from test_combine_evidence_contract_fixture import canonical_evidence

from screamingface_engine.combine.endpoint import CombineOutcome
from screamingface_engine.combine.evidence import CombineEvidence
from screamingface_engine.combine.operators.judge import scores
from screamingface_engine.combine.ports import Answer, CombineInput, canonical_json

FIXTURE = Path(__file__).parent / "data" / "combine_contract" / "narrow_evidence_cases.json"
_ANSWERED = ("answered", None)
_NOT_SELECTED = ("excluded", "not_selected")
_NO_SIGNAL = ("excluded", "no_signal")


def _marks(*passed: str, members: int) -> dict[str, float]:
    """A filter step's scores: 1.0 for each member that passed, 0.0 for the others."""
    return {f"member_{k}": 1.0 if f"member_{k}" in passed else 0.0 for k in range(1, members + 1)}


# --- NR-4: filter then mean ---------------------------------------------------------------------


def test_filter_then_mean_reads_only_the_kept_members() -> None:
    result = filter_mean()

    # Oracle: (10 + 20) / 2 = 15; with every member the mean would be (10+100+20+7)/4.
    assert result.output == "15"
    assert result.evidence.mean == "15"
    assert rows(result) == [_ANSWERED, _NOT_SELECTED, _ANSWERED, _NO_SIGNAL]
    assert wire(result)["narrow"] == [
        {
            "select": "kept@1",
            "signal": "field:confidence",
            "kept": ["member_1", "member_3"],
            "scores": _marks("member_1", "member_3", members=4),
        }
    ]


def test_a_spec_without_narrow_writes_no_narrow_key() -> None:
    result = outcome(mean_spec(4, None), context(FILTER_MEAN_OUTPUTS))

    # Oracle: (10 + 100 + 20 + 7) / 4 = 34.25; no member is excluded.
    assert result.output == "34.25"
    assert "narrow" not in wire(result)
    assert rows(result) == [_ANSWERED] * 4


# --- NR-5: rank then vote -----------------------------------------------------------------------


def test_rank_then_vote_votes_over_the_top_k() -> None:
    result = rank_vote()
    evidence = wire(result)

    # Oracle: all five vote b 3-2; the top two by confidence (0.9, 0.8) both vote a.
    assert result.output == RANK_VOTE_OUTPUTS[0]
    assert evidence["chosen"] == ["member_1"]
    assert evidence["tally"] == [{"value": "a", "score": 2.0, "holders": ["member_1", "member_2"]}]
    assert evidence["agreement"] == 1.0
    assert rows(result) == [_ANSWERED, _ANSWERED, _NOT_SELECTED, _NOT_SELECTED, _NOT_SELECTED]
    assert evidence["narrow"] == [
        {
            "select": "top_k@1",
            "signal": "field:confidence",
            "kept": ["member_1", "member_2"],
            "cut": {"k": 2, "order": "max"},
            "scores": {
                "member_1": 0.9,
                "member_2": 0.8,
                "member_3": 0.1,
                "member_4": 0.2,
                "member_5": 0.3,
            },
            "ranks": {"member_1": 1, "member_2": 2, "member_3": 5, "member_4": 4, "member_5": 3},
        }
    ]
    # The main vote is not a top-k step: no row rank, no top-level cut.
    assert "cut" not in evidence
    assert all("rank" not in row for row in evidence["members"])


# --- NR-6: filter then rank then the selection envelope -----------------------------------------


def test_filter_then_rank_hands_on_the_final_live_set() -> None:
    result = filter_rank_envelope()
    evidence = wire(result)

    # Oracle: the filter drops member_2 (0.4 < 0.5, the best score 9); the top 2 by score of the
    # rest are member_3 (5) and member_4 (3).
    assert json.loads(result.output) == {
        "input": "q",
        "selected": [
            {"id": "member_3", "text": FILTER_RANK_OUTPUTS[2]},
            {"id": "member_4", "text": FILTER_RANK_OUTPUTS[3]},
        ],
    }
    assert evidence["chosen"] == ["member_3", "member_4"]
    assert evidence["cut"] == {"k": 2, "order": "max"}
    assert evidence["signal"] == {"key": "field:score", "order": "max"}
    assert evidence["narrow"] == [
        {
            "select": "kept@1",
            "signal": "field:confidence",
            "kept": ["member_1", "member_3", "member_4"],
            "scores": _marks("member_1", "member_3", "member_4", members=4),
        }
    ]


# --- NR-10c: member rows ------------------------------------------------------------------------


def test_a_left_out_member_has_no_main_score_no_rank_and_every_read_key() -> None:
    members = wire(filter_rank_envelope())["members"]

    assert [(row["score"], row.get("rank")) for row in members] == [
        (1.0, 3),
        (None, None),
        (5.0, 1),
        (3.0, 2),
    ]
    assert "rank" not in members[1]
    # The narrow key first (step order), then the main key.
    assert [row["signals"] for row in members] == [
        {"field:confidence": 0.9, "field:score": 1.0},
        {"field:confidence": 0.4, "field:score": 9.0},
        {"field:confidence": 0.6, "field:score": 5.0},
        {"field:confidence": 0.7, "field:score": 3.0},
    ]


def test_a_left_out_member_keeps_the_main_step_value() -> None:
    members = wire(filter_mean())["members"]

    assert [row["value"] for row in members] == ["10", "100", "20", "7"]
    assert [row["score"] for row in members] == [None, None, None, None]
    assert [row["signals"] for row in members] == [
        {"field:confidence": 0.9},
        {"field:confidence": 0.2},
        {"field:confidence": 0.8},
        {"field:confidence": None},
    ]


# --- NR-7: a narrow abstain ---------------------------------------------------------------------


def test_a_narrow_filter_that_keeps_no_member_abstains_and_the_gate_does_not_run() -> None:
    result = narrow_no_votes()
    evidence = wire(result)

    assert result.output == ""
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
        "threshold": 0.5,
        "passed": None,
        "branch": None,
        "otherwise": "abstain",
    }
    assert evidence["narrow"] == [
        {
            "select": "kept@1",
            "signal": "field:confidence",
            "kept": [],
            "scores": _marks(members=5),
        }
    ]
    assert rows(result) == [_NOT_SELECTED] * 5
    assert evidence["tally"] is None
    assert evidence["chosen"] == []


def test_a_narrow_cut_not_met_records_the_steps_up_to_the_abstain() -> None:
    result = narrow_cut_not_met()
    evidence = wire(result)

    assert evidence["result"]["reason"] == "cut_not_met"
    # Three narrow items; the third never ran, so two records.
    assert evidence["narrow"] == [
        {
            "select": "kept@1",
            "signal": "field:confidence",
            "kept": ["member_1", "member_2"],
            "scores": _marks("member_1", "member_2", members=5),
        },
        {
            "select": "top_k@1",
            "signal": "field:confidence",
            "kept": [],
            "cut": {"k": 3, "order": "max"},
            "scores": {"member_1": 0.9, "member_2": 0.8},
            "ranks": {"member_1": 1, "member_2": 2},
        },
    ]
    assert rows(result) == [_NOT_SELECTED] * 5


def test_a_narrow_spec_with_no_voter_abstains_at_the_first_step() -> None:
    spec = vote_spec(3, [keep_where("field:confidence", "gt", 0.5)])

    result = outcome(spec, context([], panel={}))
    evidence = wire(result)

    assert evidence["result"]["reason"] == "no_votes"
    assert evidence["narrow"] == [{"select": "kept@1", "signal": "field:confidence", "kept": []}]
    assert rows(result) == [("fail", "missing")] * 3
    assert evidence["dropped"] == 3


# --- NR-8: a narrow no_signal -------------------------------------------------------------------


def test_a_member_with_no_value_for_a_narrow_signal_is_left_out_by_that_step() -> None:
    result = narrow_no_signal()
    evidence = wire(result)

    # member_2 has no score (step 1); member_3 has no confidence (step 2); member_4 is the third by
    # confidence (0.9, 0.5, 0.3), so the top 2 leaves it out.
    assert rows(result) == [_ANSWERED, _NO_SIGNAL, _NO_SIGNAL, _NOT_SELECTED, _ANSWERED]
    assert [record["kept"] for record in evidence["narrow"]] == [
        ["member_1", "member_3", "member_4", "member_5"],
        ["member_1", "member_5"],
    ]
    assert evidence["narrow"][1]["scores"] == {"member_1": 0.9, "member_4": 0.3, "member_5": 0.5}
    assert evidence["narrow"][1]["ranks"] == {"member_1": 1, "member_4": 3, "member_5": 2}
    assert evidence["members"][1]["signals"] == {"field:score": None, "field:confidence": 0.8}
    assert evidence["members"][2]["signals"] == {"field:score": 2.0, "field:confidence": None}
    assert evidence["chosen"] == ["member_1"]


# --- NR-9: a judge read by a narrow rank and by the main vote weights ---------------------------


def test_a_judge_read_by_a_narrow_rank_and_the_main_weights() -> None:
    result = judge_rank_weighted_vote()
    evidence = wire(result)

    # Oracle: the top two by the judge are member_2 (b, 9) and member_3 (c, 8): b wins 9 to 8,
    # agreement 9/17. Over all four, c would win 8 + 7 = 15.
    assert result.output == "B"
    assert evidence["tally"] == [
        {"value": "b", "score": 9.0, "holders": ["member_2"]},
        {"value": "c", "score": 8.0, "holders": ["member_3"]},
    ]
    assert evidence["agreement"] == float(Decimal(9) / Decimal(17))
    assert evidence["signal"] == {"key": "score:judge", "order": None}
    assert evidence["presentation_order"] == "author"
    assert rows(result) == [_NOT_SELECTED, _ANSWERED, _ANSWERED, _NOT_SELECTED]
    assert [row["weight"] for row in evidence["members"]] == [2.0, 9.0, 8.0, 7.0]
    assert [row["signals"] for row in evidence["members"]] == [
        {"score:judge": 2.0},
        {"score:judge": 9.0},
        {"score:judge": 8.0},
        {"score:judge": 7.0},
    ]
    assert evidence["narrow"] == [
        {
            "select": "top_k@1",
            "signal": "score:judge",
            "kept": ["member_2", "member_3"],
            "cut": {"k": 2, "order": "max"},
            "scores": {"member_1": 2.0, "member_2": 9.0, "member_3": 8.0, "member_4": 7.0},
            "ranks": {"member_1": 4, "member_2": 1, "member_3": 2, "member_4": 3},
        }
    ]


# --- NR-10b: the judged set ---------------------------------------------------------------------


def test_a_judge_rank_after_a_filter_parses_every_member_and_ranks_the_live_ones() -> None:
    result = judge_rank_after_filter()
    evidence = wire(result)

    # Oracle: the filter drops member_2 (the judge's 10). Of the rest, member_3 (6) is first.
    assert result.output == JUDGED_OUTPUTS[2]
    assert evidence["narrow"][1] == {
        "select": "top_k@1",
        "signal": "score:judge",
        "kept": ["member_3"],
        "cut": {"k": 1, "order": "max"},
        "scores": {"member_1": 5.0, "member_3": 6.0, "member_4": 1.0},
        "ranks": {"member_1": 2, "member_3": 1, "member_4": 3},
    }
    assert rows(result) == [_NOT_SELECTED, _NOT_SELECTED, _ANSWERED, _NOT_SELECTED]
    assert evidence["members"][1]["signals"] == {"field:confidence": 0.1, "score:judge": 10.0}


def test_a_judge_pick_after_a_filter_picks_among_the_live_members() -> None:
    result = judge_argmax_after_filter()
    evidence = wire(result)

    assert result.output == JUDGED_OUTPUTS[2]
    assert evidence["chosen"] == ["member_3"]
    assert evidence["result"]["member_id"] == "member_3"
    assert [row["score"] for row in evidence["members"]] == [5.0, None, 6.0, 1.0]
    # The judge reading keeps the whole parse: the judge saw every answered member.
    assert evidence["judge"]["parsed"] == {
        "member_1": 5.0,
        "member_2": 10.0,
        "member_3": 6.0,
        "member_4": 1.0,
    }
    assert rows(result) == [_ANSWERED, _NOT_SELECTED, _ANSWERED, _ANSWERED]


def _judge_input(members: tuple[str, ...], judged: tuple[str, ...] | None) -> CombineInput:
    answers = tuple(Answer(member, None, None, "answered", None) for member in members)
    outputs: dict[str, str] = dict.fromkeys(("member_1", "member_2", "member_3"), "x")
    reply = canonical_json({"member_1": 1, "member_2": 2, "member_3": 3})
    signals: dict[str, str] = {"judge": reply}
    return CombineInput(answers, outputs, signals, "q", judged)


def test_scores_parses_over_the_judged_set_and_keeps_the_live_scores() -> None:
    reduction = scores(
        _judge_input(("member_1", "member_3"), ("member_1", "member_2", "member_3")),
        {"source": "judge"},
    )

    assert dict(reduction.scores or {}) == {"member_1": Decimal(1), "member_3": Decimal(3)}
    assert reduction.judge is not None
    assert reduction.judge.parsed == {"member_1": 1.0, "member_2": 2.0, "member_3": 3.0}


def test_scores_with_no_judged_set_parses_over_the_present_members() -> None:
    reduction = scores(
        _judge_input(("member_1", "member_2", "member_3"), None), {"source": "judge"}
    )

    assert dict(reduction.scores or {}) == {
        "member_1": Decimal(1),
        "member_2": Decimal(2),
        "member_3": Decimal(3),
    }


# --- NR-10: an abstain-fallback gate after a narrow step ----------------------------------------


def test_a_gate_after_a_narrow_step_reads_the_mean_over_the_live_set() -> None:
    result = gate_after_narrow()
    evidence = wire(result)

    # Oracle: (0.75 + 0.875) / 2 = 0.8125 >= 0.6, so the majority stays: a, 2 of 2.
    assert result.output == GATE_OUTPUTS[0]
    assert evidence["gate"] == {
        "observe": "mean:conf",
        "observed": 0.8125,
        "cmp": ">=",
        "threshold": 0.6,
        "passed": True,
        "branch": "majority",
        "otherwise": "abstain",
    }
    assert evidence["agreement"] == 1.0
    assert rows(result) == [_ANSWERED, _NOT_SELECTED, _ANSWERED, _NOT_SELECTED]


def test_the_same_gate_without_the_narrow_step_reads_every_member() -> None:
    spec = vote_spec(4, None, extract=step("last_line@1"), signals=CONF_SIGNAL, gate=MEAN_GATE)

    evidence = wire(outcome(spec, context(GATE_OUTPUTS)))

    # Oracle: (0.75 + 0.125 + 0.875 + 0.25) / 4 = 0.5 < 0.6.
    assert evidence["gate"]["observed"] == 0.5
    assert evidence["result"]["reason"] == "gate_not_met"


# --- a narrow step's own extract ----------------------------------------------------------------


def test_a_live_member_that_fails_the_narrow_extract_is_not_selected() -> None:
    texts = [
        json_text(answer="A", tag="ok"),
        json_text(answer="B"),
        json_text(answer="A", tag="ok"),
    ]
    narrow = [keep_matching("ok", extract=step("json_field@1", path="tag"))]

    result = outcome(vote_spec(3, narrow), context(texts))

    # member_2 has no "tag": the step's extract fails, so the step never marks it.
    assert rows(result) == [_ANSWERED, _NOT_SELECTED, _ANSWERED]
    assert wire(result)["narrow"] == [
        {
            "select": "kept@1",
            "kept": ["member_1", "member_3"],
            "scores": {"member_1": 1.0, "member_3": 1.0},
        }
    ]


# --- the contract file (narrow.md §7) -----------------------------------------------------------

SCENARIOS: dict[str, Callable[[], CombineOutcome]] = {
    "filter_mean": filter_mean,
    "rank_vote": rank_vote,
    "filter_rank_envelope": filter_rank_envelope,
    "narrow_no_votes": narrow_no_votes,
    "narrow_cut_not_met": narrow_cut_not_met,
    "narrow_no_signal": narrow_no_signal,
    "judge_rank_weighted_vote": judge_rank_weighted_vote,
    "judge_rank_after_filter": judge_rank_after_filter,
    "judge_argmax_after_filter": judge_argmax_after_filter,
    "gate_after_narrow": gate_after_narrow,
}


def _evidence(name: str) -> CombineEvidence:
    evidence = SCENARIOS[name]().evidence
    assert isinstance(evidence, CombineEvidence)
    return evidence


def write_fixture() -> None:
    """Regenerate ``narrow_evidence_cases.json`` from the real core (run as a script)."""
    cases = {name: json.loads(canonical_evidence(_evidence(name))) for name in SCENARIOS}
    FIXTURE.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fixture() -> dict[str, Any]:
    assert FIXTURE.is_file(), f"missing contract fixture {FIXTURE}; run write_fixture()"
    loaded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_the_engine_narrow_evidence_is_the_fixture_byte_for_byte(name: str) -> None:
    pinned = _fixture()[name]

    assert canonical_evidence(_evidence(name)) == json.dumps(
        pinned, ensure_ascii=False, separators=(",", ":")
    )


def test_the_narrow_fixture_holds_exactly_the_scenarios() -> None:
    assert list(_fixture()) == list(SCENARIOS)


def test_every_narrow_fixture_case_has_the_narrow_key_after_cut() -> None:
    for case in _fixture().values():
        keys = list(case)
        assert "narrow" in keys
        assert keys.index("narrow") > keys.index("signal")
        assert keys.index("narrow") < keys.index("result")
        if "cut" in keys:
            assert keys.index("cut") < keys.index("narrow")
        if "declared" in keys:
            assert keys.index("narrow") < keys.index("declared")


if __name__ == "__main__":
    write_fixture()
