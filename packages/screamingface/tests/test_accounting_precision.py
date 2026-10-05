"""Small real charges remain distinguishable from a free operation."""

import pytest
from test_accounting_breakdown import accounting, replace, result

from screamingface._ui.accounting_view import case_accounting, run_accounting_note


@pytest.mark.parametrize("cost", ["0.00001", "0.000049", "0.000000001"])
def test_tiny_operation_cost_keeps_exact_nonzero_amount(cost):
    candidate = result()
    case = candidate.cases[0]
    operation = replace(case.operations[0], accounting=accounting(cost))
    candidate = replace(candidate, cases=[replace(case, operations=[operation])])
    assert f"${cost}" in case_accounting(candidate)[case.case_id]


def test_tiny_unattributed_remainder_is_not_displayed_as_zero():
    candidate = result(root="0.30001")
    assert "Unattributed run cost: $0.00001." in run_accounting_note(candidate)


def test_actual_zero_and_normal_costs_keep_existing_format():
    candidate = result()
    case = candidate.cases[0]
    operation = replace(case.operations[0], accounting=accounting("0"))
    candidate = replace(candidate, cases=[replace(case, operations=[operation])])
    html = case_accounting(candidate)[case.case_id]
    assert "$0.0000" in html
    assert "$0.2000" in html
