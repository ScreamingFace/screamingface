"""The SDK shows an excluded member and refuses an evidence that chooses one (E4b part 2 unit 2).

FEATURE: E4b part 2 unit 2, member exclusion (ans:Q3, P1, P4, P5, P13). A member that a combine
rule left out is ``status "excluded"`` with the reason ``no_signal`` or ``no_weight``. The SDK
decodes that row, shows it as an excluded Answer, and refuses a combine evidence that chooses an
excluded member (CE-I3, EX#14, SDK side).
STORY: as a researcher, I see in my Case which member the rule left out and why, and the SDK never
reports an excluded member as the chosen answer.
INVARIANT: an excluded Answer keeps its value (AR-I3); the chosen member of a combine evidence is
never an excluded member (CE-I3).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _answer_fixtures import bound, fixture_graph
from _combine_contract import COMBINE_CONTRACT, requires_engine_app

import screamingface as sf
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface.answer import Answer
from screamingface.case_result import CaseOperation
from screamingface.errors import ExecutionError

# WHY: the same hand-computed wire as ET/test_combine_member_exclusion.py X1_WIRE (SDK tests do
# not import Engine test modules). The weighted vote: member_3 has no confidence (no_weight).
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

# WHY: the Rank wire of contracts.md C1, complete. member_3 has no cost, so it is excluded and
# has no rank (ES#10). The min order of 0.01, 0.02, 0.03 gives ranks 1, 2, 3.
RANK_WIRE: dict[str, Any] = {
    "schema": "screamingface.combine-evidence.v1",
    "kind": "selection",
    "reducer": "rank",
    "operators": ["by_signal@1", "top_k@1"],
    "members": [
        {
            "member_id": "member_1",
            "raw": None,
            "value": None,
            "status": "answered",
            "reason": None,
            "signals": {"cost_usd": 0.03},
            "weight": None,
            "score": 0.03,
            "rank": 3,
        },
        {
            "member_id": "member_2",
            "raw": None,
            "value": None,
            "status": "answered",
            "reason": None,
            "signals": {"cost_usd": 0.01},
            "weight": None,
            "score": 0.01,
            "rank": 1,
        },
        {
            "member_id": "member_3",
            "raw": None,
            "value": None,
            "status": "excluded",
            "reason": "no_signal",
            "signals": {"cost_usd": None},
            "weight": None,
            "score": None,
        },
        {
            "member_id": "member_4",
            "raw": None,
            "value": None,
            "status": "answered",
            "reason": None,
            "signals": {"cost_usd": 0.02},
            "weight": None,
            "score": 0.02,
            "rank": 2,
        },
    ],
    "tally": None,
    "judge": None,
    "fields": None,
    "chosen": ["member_2", "member_4"],
    "built": True,
    "agreement": None,
    "tie": False,
    "median": None,
    "presentation_order": None,
    "separator_collision": None,
    "signal": {"key": "cost_usd", "order": "min"},
    "cut": {"k": 2, "order": "min"},
    "result": {"member_id": None, "value": None, "status": "answered", "reason": None},
    "dropped": 0,
    "finish_reason": "stop",
}

_CASES = COMBINE_CONTRACT / "evidence_cases.json"


def _engine_cases() -> dict[str, Any]:
    assert _CASES.is_file(), f"missing Engine contract fixture {_CASES}"
    return json.loads(_CASES.read_text(encoding="utf-8"))


def _case(name: str, wire: Any) -> sf.CaseResult:
    """A Case with one model operation per member and one combine operation that holds the wire."""
    evidence = decode_combine_evidence(wire, f"Engine evidence {name}")
    assert evidence is not None
    count = len(evidence.members)
    operations = [
        CaseOperation(f"op_model_{k}", f"text {k}", "stop", None) for k in range(1, count + 1)
    ]
    operations.append(CaseOperation("op_synthesis_1", "42", "stop", None, combine=evidence))
    case = sf.CaseResult(
        case_id=1,
        input="Question",
        output="x",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
        operations=operations,
    )
    return bound(case, fixture_graph(count))


# --- ES#10: the Rank wire with an excluded member and a cut --------------------------------


def test_sdk_decodes_excluded_rank_and_cut() -> None:
    decoded = decode_combine_evidence(RANK_WIRE, "evidence")

    assert decoded is not None
    assert decoded.members[2].status == "excluded"
    assert decoded.members[2].reason == "no_signal"
    assert decoded.members[2].rank is None
    assert [member.rank for member in decoded.members] == [3, 1, None, 2]
    assert decoded.cut is not None
    assert (decoded.cut.k, decoded.cut.order) == (2, "min")
    assert decoded.to_dict() == RANK_WIRE
    assert list(decoded.to_dict()) == list(RANK_WIRE)


# --- ES#12: the excluded row as a Case answer ----------------------------------------------


@requires_engine_app
def test_case_answers_show_the_excluded_status_and_value() -> None:
    seen: set[tuple[str, str | None, str, str | None, str | None]] = set()
    for name, wire in _engine_cases().items():
        case = _case(name, wire)
        seen |= {
            (name, answer.member_id, answer.status, answer.reason, answer.value)
            for answer in case.answers()
            if answer.status == "excluded"
        }

    assert seen >= {
        ("filter_signal_excluded", "member_3", "excluded", "no_signal", None),
        ("mean_weighted_value", "member_2", "excluded", "no_weight", "99"),
        ("rank_cut_not_met", "member_2", "excluded", "no_signal", None),
        ("vote_weight_excluded", "member_3", "excluded", "no_weight", "b"),
    }


def test_case_answer_of_x1_wire_is_excluded() -> None:
    answers = _case("vote_weight_excluded", X1_WIRE).answers()

    assert answers[2] == Answer(
        member_id="member_3",
        text="text 3",
        raw="B",
        value="b",
        status="excluded",
        reason="no_weight",
        signals={"field:confidence": None},
    )
    assert answers[3].member_id == "member_1"
    assert answers[3].value == "a"
    assert answers[3].status == "answered"


# --- EX#14, SDK side: an evidence that chooses an excluded member is refused -----------------


def test_excluded_member_is_never_chosen_sdk() -> None:
    assert decode_combine_evidence(X1_WIRE, "evidence") is not None
    bad = {
        **X1_WIRE,
        "chosen": ["member_3"],
        "result": {"member_id": "member_3", "value": "b", "status": "answered", "reason": None},
    }

    with pytest.raises(ExecutionError, match="which is excluded"):
        decode_combine_evidence(bad, "evidence")
