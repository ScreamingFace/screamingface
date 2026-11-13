"""The report shows sf.WithBudget: spend against the cap, refusals, overspend and unknown cost.

FEATURE: E4c (OME-1291) report rows RP#11a, #15, #19, #21, #27, #28 and budget BU#25 (the
first producer of the reserved ``budget`` trace kind).
STORY: as a researcher whose result is a saving, the report shows what each decision saw of the
cap, which branch the Budget refused, and the Cases whose spend still passed the cap.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_e4c_report import case, decision, gate_candidate, operation, record
from test_report_v1_identity import _accounting

import screamingface as sf
from screamingface._case_views import case_trace
from screamingface._ui.branch_view import (
    GateSummary,
    branch_sections_html,
    condition_text,
    overspend_of,
)
from screamingface.budget import CallCharge
from screamingface.case_result import CaseOperation

_REMAINING = {"observe": "budget.remaining:usd", "cmp": ">=", "value": 0.02}


def _view(
    spent: float,
    *,
    cap: float = 0.05,
    unit: str = "usd",
    estimate: float | None = None,
    refused: bool = False,
    unpriced: int = 0,
) -> dict[str, Any]:
    return {
        "unit": unit,
        "cap": cap,
        "spent": spent,
        "unpriced": unpriced,
        "estimate": estimate,
        "refused": refused,
    }


def _kept(*views: dict[str, Any], gate: str = "gate_1") -> dict[str, Any]:
    """A decision under a Budget that refused nothing: the wanted ``then`` ran."""

    value = record(gate, when=_REMAINING, observed=0.05, selectors=[])
    value["budget"] = list(views)
    return value


def _refused(*views: dict[str, Any], branch: str | None, gate: str = "gate_1") -> dict[str, Any]:
    """A decision whose Budget refused the wanted ``then``; ``branch`` is what ran instead."""

    value = record(gate, branch=branch, wanted="then", when=_REMAINING, observed=0.05)
    value["selectors"] = []
    value["budget"] = list(views)
    value["not_run"] = [
        {
            "branch": "then",
            "reason": "budget_refused",
            "model_calls": {"min": 1, "max": 1},
        },
        *(
            [{"branch": "otherwise", "reason": "not_selected", "model_calls": {"min": 1, "max": 1}}]
            if branch is None
            else []
        ),
    ]
    if branch is None:
        value["result"] = {"status": "abstain", "reason": "budget_refused"}
    return value


def _choice() -> object:
    return sf.WithBudget(
        sf.Gate(
            when=sf.budget.remaining() >= 0.02,
            then=sf.Estimate("prov/big", usd=0.03),
            otherwise="prov/small",
        ),
        budget_usd=0.05,
    )


def _refuse_both() -> object:
    gate = sf.Gate(
        when=sf.budget.remaining() >= 0.0,
        then=sf.Estimate("prov/big", usd=0.03),
        otherwise="prov/small",
    )
    return sf.WithBudget(sf.Model("prov/prep") >> gate, budget_usd=0.0015)


def _cascade() -> object:
    stage_two = sf.Fanout(
        [sf.Model("prov/c", optional=True), sf.Model("prov/d", optional=True)], quorum=0
    ) >> sf.Gate(when=sf.agreement() >= 0.8, then=sf.Vote(), otherwise="prov/large")
    stage_one = sf.Fanout(
        [sf.Model("prov/a", optional=True), sf.Model("prov/b", optional=True)], quorum=0
    ) >> sf.Gate(
        when=sf.agreement() >= 0.8, then=sf.Vote(), otherwise=sf.Estimate(stage_two, usd=0.0025)
    )
    return sf.WithBudget(stage_one, budget_usd=0.01)


def _priced(operation_id: str) -> CaseOperation:
    # 0.002 USD, 10 + 4 tokens; under a Budget the Engine also writes the call's charge (ans:Q32).
    charge = CallCharge(usd=0.002, tokens=14.0)
    return CaseOperation(operation_id, "x", "stop", _accounting(), charges=(charge,))


# --- RP#11a ---------------------------------------------------------------------------------------


def test_budget_remaining_condition_renders_in_source_form() -> None:
    # RP-4: the record always names the unit, so the source form names it too.
    assert condition_text(decision(_kept(_view(0.0))).when) == (
        "sf.budget.remaining('usd') >= 0.02"
    )


# --- RP#15 ----------------------------------------------------------------------------------------


def test_budget_lines_show_spent_cap_estimate_and_refusal() -> None:
    # RP-10: one line per unit; estimate when set; refused names the refused branch.
    value = _refused(
        _view(0.01234, estimate=0.04, refused=True),
        _view(30, cap=100, unit="tokens", estimate=None),
        branch="otherwise",
    )
    item = case(1, (operation("gate_1", value),))
    html = branch_sections_html(gate_candidate(_choice(), (item,)), item)

    assert "budget · usd · spent <span class='sf-cmb__n' title='0.01234'>0.01234</span> of " in html
    assert "title='0.05'>0.05</span>" in html
    assert "estimate <span class='sf-cmb__n' title='0.04'>0.04</span>" in html
    assert "refused · then" in html
    assert "budget · tokens · spent <span class='sf-cmb__n' title='30.0'>30</span>" in html
    assert html.count("refused · ") == 1
    assert "not run · then · refused by the budget · avoided 1 model call" in html


# --- RP#21 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("count", "text"), [(1, "1 call with"), (3, "3 calls with")])
def test_unpriced_calls_show_counted_as_zero_warning(count: int, text: str) -> None:
    # RP-11 (ans:Q14)
    value = _kept(_view(0.0, unpriced=count))
    item = case(1, (operation("gate_1", value),))
    html = branch_sections_html(gate_candidate(_choice(), (item,)), item)

    assert f"{text} unknown cost counted as $0" in html
    assert "title='the provider gave no cost; the budget counts these calls as $0'" in html
    summary = GateSummary()
    summary.add(case(1, (operation("gate_1", value),)))
    assert summary.gates["gate_1"].unpriced == 1


# --- RP#19 ----------------------------------------------------------------------------------------


def test_overspend_line_and_count() -> None:
    # RP-34 (BU-19, ans:Q20): three calls of 0.002 USD under a 0.005 cap.
    value = _kept(_view(0.0, cap=0.005))
    over = case(1, (_priced("op_model_1"), _priced("op_model_2"), _priced("op_model_3"),
                    operation("gate_1", value)))  # fmt: skip
    under = case(2, (_priced("op_model_1"), operation("gate_1", value)))
    candidate = gate_candidate(_choice(), (over, under))

    assert overspend_of(over) == [("usd", 0.006, 0.005)]
    assert overspend_of(under) == []
    html = branch_sections_html(candidate, over)
    assert "budget · overspend · usd · spent <span class='sf-cmb__n' title='0.006'>" in html
    assert "budget · overspend" not in branch_sections_html(candidate, under)
    summary = GateSummary()
    for item in (over, under):
        summary.add(item)
    assert summary.overspend == 1
    assert "budget · overspend · 1 case" in summary.html(candidate)


# --- RP#27 ----------------------------------------------------------------------------------------


def test_budget_spent_grows_down_the_chain_and_refusals_count_per_gate() -> None:
    # RP-28 (BU-22): each section shows its own spent; the summary counts refusals per Gate.
    def chain(case_id: int, refuse_second: bool) -> sf.CaseResult:
        first = _kept(_view(0.002, cap=0.01, estimate=0.0025))
        first["branch"] = first["wanted"] = "otherwise"
        first["not_run"][0]["branch"] = "then"
        second = _kept(_view(0.004, cap=0.01, refused=refuse_second), gate="gate_2")
        if refuse_second:
            second["wanted"] = "otherwise"
            second["not_run"][0]["reason"] = "budget_refused"
        else:
            second["branch"] = second["wanted"] = "otherwise"
            second["not_run"][0]["branch"] = "then"
        return case(case_id, (operation("gate_2", second), operation("gate_1", first)))

    cases = (chain(1, True), chain(2, False))
    candidate = gate_candidate(_cascade(), cases)
    html = branch_sections_html(candidate, cases[0])

    assert html.index("title='0.002'>0.002</span>") < html.index("title='0.004'>0.004</span>")
    summary = GateSummary()
    for item in cases:
        summary.add(item)
    assert (summary.gates["gate_1"].refusals, summary.gates["gate_2"].refusals) == (0, 1)
    assert "refused by the budget 1" in summary.html(candidate)


# --- BU#25 ----------------------------------------------------------------------------------------


def test_refusal_writes_one_budget_trace_row() -> None:
    # BU-25: one row per refused branch; operation_id is the first operation of the refused body.
    value = _refused(_view(0.002, cap=0.0015, estimate=0.03, refused=True), branch=None)
    item = case(1, (_priced("op_model_1"), operation("gate_1", value, output="")), abstained=True)
    candidate = gate_candidate(_refuse_both(), (item,))

    rows = [entry.to_dict() for entry in case_trace(item, candidate._operation_graph())]
    budget_rows = [row for row in rows if row["kind"] == "budget"]
    assert budget_rows == [
        {
            "kind": "budget",
            "event": "refusal",
            "operation_id": "op_model_2",
            "member_id": None,
            "stage": "model",
            "amount": None,
            "estimated": 0.03,
            "source": None,
            "remaining_after": 0.0,
        }
    ]


def test_refused_escalation_names_the_first_operation_of_the_next_stage() -> None:
    first = _refused(_view(0.002, cap=0.003, estimate=0.0025, refused=True), branch="then")
    first["wanted"] = "otherwise"
    first["not_run"][0]["branch"] = "otherwise"
    item = case(1, (operation("gate_1", first),))
    candidate = gate_candidate(_cascade(), (item,))

    rows = [e.to_dict() for e in case_trace(item, candidate._operation_graph())]
    assert [
        (row["operation_id"], row["remaining_after"]) for row in rows if row["kind"] == "budget"
    ] == [("op_model_3", 0.001)]


def test_no_refusal_writes_no_budget_row() -> None:
    item = case(1, (operation("gate_1", _kept(_view(0.0))),))
    candidate = gate_candidate(_choice(), (item,))
    rows = case_trace(item, candidate._operation_graph())
    assert all(entry.kind != "budget" for entry in rows)
