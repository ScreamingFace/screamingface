"""The ``narrow`` evidence record and its invariants (E4b map-reduce surface, narrow.md §4).

FEATURE: the evidence of a spec with narrow steps holds one record per narrow step that ran
(``select``, ``signal``, ``kept``, and for a top k ``cut``, ``scores``, ``ranks``), and a member
that a narrow step left out is ``excluded`` with ``not_selected`` or ``no_signal``.
STORY: as a reader of a Case, I can check each narrow decision from the evidence alone, and a
record that contradicts itself never reaches me.
INVARIANT defended: NR-I1..NR-I6 and AR-I3′ refuse bad records (each refusal names its rule);
the record keys that are not set are absent; an evidence with no ``narrow`` keeps its v1 bytes.
The base record below is written by hand (a filter keeps three of four members, a top 1 keeps
member_2, the vote answers b); every mutation breaks exactly one rule.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from screamingface_engine.combine.evidence import AnswerRecord, CombineEvidence, NarrowRecord

_CONFIDENCE = {"member_1": 0.6, "member_2": 0.9, "member_3": 0.7, "member_4": 0.1}


def _row(member: str, status: str = "answered", reason: str | None = None) -> dict[str, Any]:
    return {
        "member_id": member,
        "raw": member[-1],
        "value": member[-1],
        "status": status,
        "reason": reason,
        "signals": {"field:confidence": _CONFIDENCE[member]},
        "weight": None,
        "score": None,
    }


def _narrow_wire() -> dict[str, Any]:
    """Filter (confidence > 0.5) keeps 1, 2, 3; top 1 by confidence keeps 2; the vote says "2"."""
    return {
        "schema": "screamingface.combine-evidence.v1",
        "kind": "answer",
        "reducer": "vote",
        "operators": ["last_line@1", "text@1", "mode@1", "first_holder@1"],
        "members": [
            _row("member_1", "excluded", "not_selected"),
            _row("member_2"),
            _row("member_3", "excluded", "not_selected"),
            _row("member_4", "excluded", "not_selected"),
        ],
        "tally": [{"value": "2", "score": 1.0, "holders": ["member_2"]}],
        "judge": None,
        "fields": None,
        "chosen": ["member_2"],
        "built": False,
        "agreement": 1.0,
        "tie": False,
        "median": None,
        "presentation_order": None,
        "separator_collision": None,
        "signal": None,
        "narrow": [
            {
                "select": "kept@1",
                "signal": "field:confidence",
                "kept": ["member_1", "member_2", "member_3"],
                "scores": {"member_1": 1.0, "member_2": 1.0, "member_3": 1.0, "member_4": 0.0},
            },
            {
                "select": "top_k@1",
                "signal": "field:confidence",
                "kept": ["member_2"],
                "cut": {"k": 1, "order": "max"},
                "scores": {"member_1": 0.6, "member_2": 0.9, "member_3": 0.7},
                "ranks": {"member_1": 3, "member_2": 1, "member_3": 2},
            },
        ],
        "result": {"member_id": "member_2", "value": "2", "status": "answered", "reason": None},
        "dropped": 0,
        "finish_reason": "stop",
    }


def _valid(wire: dict[str, Any]) -> CombineEvidence:
    return CombineEvidence.model_validate(wire)


def _refused(wire: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        _valid(wire)


def _main_abstain(wire: dict[str, Any]) -> dict[str, Any]:
    """The same evidence with the main vote abstained: no tally and no choice."""
    wire.update(tally=None, chosen=[], agreement=None)
    wire["result"] = {"member_id": None, "value": None, "status": "abstain", "reason": "no_votes"}
    return wire


def test_the_hand_written_narrow_evidence_is_valid_and_round_trips() -> None:
    wire = _narrow_wire()

    evidence = _valid(wire)

    assert evidence.narrow is not None
    assert [record.kept for record in evidence.narrow] == [
        ["member_1", "member_2", "member_3"],
        ["member_2"],
    ]
    assert evidence.model_dump(mode="json", by_alias=True) == wire


def test_unset_record_keys_are_absent() -> None:
    record = NarrowRecord(select="kept@1", kept=["member_1"])

    assert record.model_dump(mode="json") == {"select": "kept@1", "kept": ["member_1"]}


def test_an_evidence_without_narrow_writes_no_key() -> None:
    wire = _narrow_wire()
    del wire["narrow"]
    for row in wire["members"]:
        row.update(status="answered", reason=None)

    assert "narrow" not in _valid(wire).model_dump(by_alias=True)


@pytest.mark.parametrize("count", [0, 5])
def test_the_narrow_record_list_holds_one_to_four_steps(count: int) -> None:
    wire = _narrow_wire()
    wire["narrow"] = [wire["narrow"][0]] * count

    _refused(wire, "narrow")


# --- AR-I3′ ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "reason", "match"),
    [
        ("answered", "not_selected", "has a reason exactly when it did not answer"),
        ("fail", "not_selected", "an excluded answer has an exclude reason"),
        ("excluded", "empty", "an excluded answer has an exclude reason"),
    ],
)
def test_not_selected_goes_with_excluded_only(status: str, reason: str, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        AnswerRecord.model_validate(
            {**_row("member_1"), "status": status, "reason": reason, "value": None}
        )


def test_an_excluded_not_selected_record_is_valid() -> None:
    record = AnswerRecord.model_validate(_row("member_1", "excluded", "not_selected"))

    assert (record.status, record.reason) == ("excluded", "not_selected")


# --- NR-I1 ----------------------------------------------------------------------------------------


def test_a_later_kept_is_a_subset_of_the_one_before() -> None:
    wire = _narrow_wire()
    wire["narrow"][1] = {"select": "kept@1", "kept": ["member_2", "member_4"]}

    _refused(wire, "kept of a narrow step is a subset of the step before")


def test_the_first_kept_names_only_members_that_answered() -> None:
    wire = _narrow_wire()
    wire["members"][0].update(status="fail", reason="empty", value=None)
    wire["dropped"] = 1

    _refused(wire, "kept of the first narrow step names only members that answered")


def test_a_kept_list_is_unique_and_in_author_order() -> None:
    wire = _narrow_wire()
    wire["narrow"][0]["kept"] = ["member_2", "member_1", "member_3"]

    _refused(wire, "narrow kept lists unique members in author order")


def test_scores_name_only_the_members_live_at_that_step() -> None:
    wire = _narrow_wire()
    wire["narrow"][1]["scores"]["member_4"] = 0.1
    wire["narrow"][1]["ranks"]["member_4"] = 4

    _refused(wire, "narrow scores name only the members live at that step")


# --- NR-I2 ----------------------------------------------------------------------------------------


def test_a_not_selected_member_is_in_no_later_kept() -> None:
    wire = _main_abstain(_narrow_wire())
    wire["members"][1].update(status="excluded", reason="not_selected")

    _refused(wire, "a not_selected member is in no later narrow kept")


def test_a_not_selected_member_is_never_chosen() -> None:
    wire = _narrow_wire()
    wire["members"][1].update(status="excluded", reason="not_selected")

    _refused(wire, "never chooses an excluded member")


# --- NR-I3 ----------------------------------------------------------------------------------------


def test_a_member_a_narrow_step_left_out_is_excluded() -> None:
    wire = _narrow_wire()
    wire["members"][3].update(status="answered", reason=None)

    _refused(wire, "a member that a narrow step left out is excluded")


def test_a_narrow_no_signal_member_was_left_out_by_a_step_that_reads_a_signal() -> None:
    wire = _narrow_wire()
    del wire["narrow"][0]["signal"]
    wire["members"][3].update(reason="no_signal", signals={"field:confidence": None})

    _refused(wire, "a narrow no_signal member has no value for the signal of its step")


def test_a_narrow_no_signal_member_has_no_value_for_that_signal() -> None:
    wire = _narrow_wire()
    wire["members"][3]["reason"] = "no_signal"

    _refused(wire, "a narrow no_signal member has no value for the signal of its step")


def test_a_narrow_no_signal_member_with_no_value_is_valid() -> None:
    wire = _narrow_wire()
    wire["members"][3].update(reason="no_signal", signals={"field:confidence": None})

    assert _valid(wire).members[3].reason == "no_signal"


# --- NR-I4 ----------------------------------------------------------------------------------------


def test_not_selected_needs_a_narrow_record() -> None:
    wire = _narrow_wire()
    del wire["narrow"]

    _refused(wire, "not_selected goes with a narrow record")


# --- NR-I5 ----------------------------------------------------------------------------------------


def _narrow_abstain() -> dict[str, Any]:
    """The top 1 found fewer than one scored member: the call abstained with cut_not_met."""
    wire = _main_abstain(_narrow_wire())
    wire["result"]["reason"] = "cut_not_met"
    wire["narrow"][1]["kept"] = []
    del wire["narrow"][1]["scores"]
    del wire["narrow"][1]["ranks"]
    wire["members"][1].update(status="excluded", reason="not_selected")
    return wire


def test_a_narrow_abstain_is_valid() -> None:
    assert _valid(_narrow_abstain()).result.reason == "cut_not_met"


def test_a_narrow_abstain_has_an_abstain_result() -> None:
    wire = _narrow_abstain()
    wire["result"] = {"member_id": None, "value": None, "status": "abstain", "reason": "in_band"}

    _refused(wire, "in_band goes with a gate")
    wire["result"]["reason"] = "output_missing"
    _refused(wire, "a narrow abstain ends with no_votes or cut_not_met and runs no gate")


def test_a_narrow_abstain_runs_no_gate() -> None:
    wire = _narrow_abstain()
    wire["gate"] = {
        "observe": "agreement",
        "observed": None,
        "cmp": ">=",
        "threshold": 0.5,
        "passed": True,
        "branch": "majority",
        "otherwise": "abstain",
    }

    _refused(wire, "a narrow abstain ends with no_votes or cut_not_met and runs no gate")


def test_a_narrow_abstain_has_no_main_step_reading() -> None:
    wire = _narrow_abstain()
    wire["members"][0]["score"] = 0.5

    _refused(wire, "a narrow abstain has no main step score, tally or choice")


def test_only_the_last_narrow_step_may_keep_no_member() -> None:
    wire = _narrow_abstain()
    wire["narrow"][0]["kept"] = []

    _refused(wire, "only the last narrow step may keep no member")


# --- NR-I6 ----------------------------------------------------------------------------------------


def test_dropped_counts_failed_members_only() -> None:
    wire = _narrow_wire()
    wire["dropped"] = 3

    _refused(wire, "dropped must count the failed members")


# --- the top-k record rules (part 2 rules, per narrow step) --------------------------------------


def test_ranks_go_with_a_cut() -> None:
    wire = _narrow_wire()
    del wire["narrow"][1]["cut"]

    _refused(wire, "a narrow record has ranks only with a cut")


def test_ranks_are_one_to_n_over_the_scored_members() -> None:
    wire = _narrow_wire()
    wire["narrow"][1]["ranks"] = {"member_1": 3, "member_2": 1, "member_3": 3}

    _refused(wire, "narrow ranks are 1..n over the scored members")


def test_a_top_k_record_keeps_the_members_ranked_within_its_cut() -> None:
    wire = _narrow_wire()
    wire["narrow"][1]["ranks"] = {"member_1": 3, "member_2": 2, "member_3": 1}

    _refused(wire, "a narrow top-k record keeps the members ranked within its cut")
