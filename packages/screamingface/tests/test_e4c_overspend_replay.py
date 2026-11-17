"""A replay shows the overspend of the live run: the line adds the Budget's charges (E4c, Q32).

FEATURE: OME-1291 report RP-34, budget BU-27, owner decision ans:Q32. A cache hit costs $0 now,
so a sum of ``accounting.usage.cost_usd`` shows no overspend on a replay. The Engine writes what
the Budget charged each provider call (a hit: its original cost) as ``charges`` on the operation,
and the overspend line adds those numbers.
STORY: as a researcher who replays a run, I see the same overspend line as the live run.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from test_e4c_report import case, gate_candidate, operation, record
from test_e4c_report_budget import _choice
from test_report_v1_identity import _accounting

from screamingface._evaluation.results import _case_operation
from screamingface._ui.branch_view import branch_sections_html, overspend_of
from screamingface.budget import CallCharge
from screamingface.case_result import CaseOperation
from screamingface.errors import ExecutionError
from screamingface.operation_accounting import OperationCache

_REMAINING = {"observe": "budget.remaining:usd", "cmp": ">=", "value": 0.0001}


def _gate(cap: float = 0.0035) -> CaseOperation:
    value = record("gate_1", when=_REMAINING, observed=cap, selectors=[])
    value["budget"] = [
        {"unit": "usd", "cap": cap, "spent": 0.0, "unpriced": 0, "estimate": None, "refused": False}
    ]
    return operation("gate_1", value)


def _hit(operation_id: str, *charges: CallCharge) -> CaseOperation:
    """A replayed call: $0 now in accounting, the live run's charge in ``charges``."""

    live = _accounting()
    accounting = type(live)(
        provider=live.provider,
        request_model=live.request_model,
        response_model=live.response_model,
        usage=type(live.usage)(input_tokens=0, output_tokens=0, cost_usd=Decimal(0)),
        provider_latency_ms=None,
        provider_attempts=0,
        cache=OperationCache(hits=1, misses=0, bypasses=0, unknown=0),
    )
    return CaseOperation(operation_id, "x", "stop", accounting, charges=charges)


def test_a_replay_shows_the_overspend_of_the_live_run() -> None:
    charge = CallCharge(usd=0.002, tokens=14.0)
    replay = case(1, (_hit("op_model_1", charge), _hit("op_model_2", charge), _gate()))

    assert overspend_of(replay) == [("usd", 0.004, 0.0035)]
    html = branch_sections_html(gate_candidate(_choice(), (replay,)), replay)
    assert "budget · overspend · usd · spent <span class='sf-cmb__n' title='0.004'>" in html


def test_an_unpriced_charge_adds_nothing() -> None:
    # The Engine fold rule: an unpriced call counts as $0 (ans:Q14).
    replay = case(
        1,
        (
            _hit("op_model_1", CallCharge(usd=0.002, tokens=14.0)),
            _hit("op_model_2", CallCharge(usd=None, tokens=9.0), CallCharge(usd=0.001, tokens=3.0)),
            _gate(),
        ),
    )

    assert overspend_of(replay) == []
    more = _hit("op_model_3", CallCharge(usd=0.001, tokens=1.0))
    assert overspend_of(case(2, (*(replay.operations or ()), more))) == [("usd", 0.004, 0.0035)]


def test_charges_decode_and_export_and_absence_stays_absence() -> None:
    raw = CaseOperation("op_model_1", "x", "stop", None).to_dict()
    assert "charges" not in raw
    assert _case_operation(raw).charges is None

    raw["charges"] = [{"usd": 0.002, "tokens": 14.0}, {"usd": None, "tokens": 9.0}]
    decoded = _case_operation(raw)

    assert decoded.charges == (CallCharge(usd=0.002, tokens=14.0), CallCharge(usd=None, tokens=9.0))
    assert decoded.to_dict()["charges"] == raw["charges"]


@pytest.mark.parametrize(
    "bad",
    [{"usd": -0.1, "tokens": 1.0}, {"usd": 0.1}, {"usd": 0.1, "tokens": 1.0, "source": "live"}, 3],
)
def test_a_malformed_charge_is_refused(bad: object) -> None:
    raw = CaseOperation("op_model_1", "x", "stop", None).to_dict()
    raw["charges"] = [bad]

    with pytest.raises(ExecutionError, match="Case Operation"):
        _case_operation(raw)


def test_the_gate_decision_alone_is_not_a_charge() -> None:
    # A Gate record holds no provider call; only the charges on model operations add up.
    assert overspend_of(case(1, (_gate(),))) == []
