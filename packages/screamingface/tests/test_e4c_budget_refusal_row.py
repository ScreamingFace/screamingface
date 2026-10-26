"""A budget refusal row names the first call of the refused body (E4c, OME-1291, budget BU-25).

FEATURE: OME-1291 bugfix — the ``budget`` trace row of a refused branch names the first operation
of the refused body. The SDK reads it from the operation graph: a Gate depends on its input, on a
panel Gate's decision call (named by the decision record's ``panel.operation_id``) and on each
branch's result; the body is what no other of those dependencies reads.
STORY: as a researcher, I open a Case whose Gate the Budget refused, and the refusal row points at
the model call the Budget saved, not at the Gate, at its input, or at a panel member that already
ran.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_e4c_budget_fixtures import budget_lazy_judge, budget_two_units
from test_e4c_report import case, gate_candidate, operation
from test_e4c_report_budget import _refused, _view

import screamingface as sf
from screamingface._case_views import case_trace

_AGREEMENT = {"observe": "agreement", "cmp": ">=", "value": 0.8}
_PANEL = {"operation_id": "op_synthesis_1", "branch": "majority"}


def _panel_gate(otherwise: str) -> object:
    gate = sf.Gate(
        when=sf.agreement() >= 0.8, then=sf.Estimate("prov/big", usd=0.03), otherwise=otherwise
    )
    return sf.Budgeted(sf.Fanout([sf.Model("prov/a"), sf.Model("prov/b")]) >> gate, usd=0.01)


def _as_panel(value: dict[str, Any]) -> dict[str, Any]:
    """The record of a panel Gate: it observes the panel and names its decision call."""

    value.update(kind="panel", when=_AGREEMENT, observed=1.0, panel=_PANEL)
    return value


def _refusal_rows(recipe: object, value: dict[str, Any]) -> list[tuple[object, object]]:
    item = case(1, (operation("gate_1", value, output=""),), abstained=True)
    candidate = gate_candidate(recipe, (item,))
    rows = [entry.to_dict() for entry in case_trace(item, candidate._operation_graph())]
    return [(row["operation_id"], row["stage"]) for row in rows if row["kind"] == "budget"]


@pytest.mark.parametrize("otherwise", ["prov/small", "abstain"], ids=["recipe", "word"])
def test_refused_panel_branch_row_names_the_first_operation_of_the_refused_body(
    otherwise: str,
) -> None:
    # op_model_1/2 are the panel members, op_synthesis_1 its decision call, op_model_3 `then`.
    value = _as_panel(_refused(_view(0.004, cap=0.01, estimate=0.03, refused=True), branch=None))
    if otherwise == "abstain":
        value["not_run"][1]["model_calls"] = {"min": 0, "max": 0}

    assert _refusal_rows(_panel_gate(otherwise), value) == [("op_model_3", "model")]


def test_refused_lazy_judge_row_names_the_judge_not_a_panel_member() -> None:
    # BU-18: the judge fallback reads the panel members, which ran before the Gate decided.
    value = _as_panel(_refused(_view(0.004, cap=0.005, estimate=0.01, refused=True), branch="then"))
    value["wanted"] = "otherwise"
    value["not_run"][0]["branch"] = "otherwise"
    value["passed"] = False

    assert _refusal_rows(budget_lazy_judge(), value) == [("op_judge_1", "judge")]


def test_refused_branch_row_names_the_body_not_the_gate_input() -> None:
    # BU-2: `then` reads the Gate's input (op_model_1, prep); the refused body is op_model_2 only.
    value = _refused(
        _view(0.002, cap=0.05, estimate=0.001),
        _view(120, cap=100, unit="tokens", estimate=100, refused=True),
        branch=None,
    )
    value["not_run"][1]["model_calls"] = {"min": 0, "max": 0}

    assert _refusal_rows(budget_two_units(), value) == [("op_model_2", "model")]
