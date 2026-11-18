"""The final operation's abstain reason, and the abstain mark that reads the same operation.

FEATURE: chat run (U3, Q1 option A): the chat handler takes the abstain reason of the final step
from the attributed final operation, the one the abstain mark reads too.
"""

from __future__ import annotations

import pytest
from test_abstain_mark import _abstain_evidence, _answered_evidence, _combine_final, _operations
from test_e4c_gate_attribution import _decision, _gate_block, _model

from screamingface_engine.benchmarks.contract import OperationOutput
from screamingface_engine.benchmarks.operation_outputs import (
    final_operation,
    final_operation_abstain_reason,
    final_operation_abstained,
)
from url4 import expr, render, text


def _gate_final(result: dict | None) -> tuple[str, list[OperationOutput]]:
    """A candidate whose root is `$gate_1_block`, and its JOIN `op_gate_1` with the given result."""
    candidate = render(
        expr(
            _gate_block(1, (_model("model_1", "/a"),), "$model_1", (), "''"),
            intent=text("$gate_1_block"),
        )
    )
    operations = [
        OperationOutput(
            operation_id="op_gate_1",
            output="",
            finish_reason="stop",
            accounting=None,
            decision=_decision(1, "then", result=result),
        )
    ]
    return candidate, operations


def test_final_operation_is_the_single_op_named_by_the_root_intent() -> None:
    operations = _operations(_answered_evidence(), "a x")

    assert final_operation(_combine_final("$synthesis_1"), operations) is operations[0]
    assert final_operation(_combine_final("$model_2"), operations) is None
    assert final_operation(_combine_final("Summarize $synthesis_1"), operations) is None
    assert final_operation(_combine_final("$synthesis_1"), None) is None
    doubled = operations + _operations(_answered_evidence(), "a x")
    assert final_operation(_combine_final("$synthesis_1"), doubled) is None


def test_abstain_reason_of_a_combine_final() -> None:
    reason = _abstain_evidence().result.reason

    assert reason is not None
    assert (
        final_operation_abstain_reason(
            _combine_final("$synthesis_1"), _operations(_abstain_evidence())
        )
        == reason
    )
    assert (
        final_operation_abstain_reason(
            _combine_final("$synthesis_1"), _operations(_answered_evidence(), "a x")
        )
        is None
    )


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        ({"status": "abstain", "reason": "gate_not_met"}, "gate_not_met"),
        ({"status": "answered", "reason": None}, None),
        (None, None),
    ],
)
def test_abstain_reason_of_a_gate_final(result, reason) -> None:
    candidate, operations = _gate_final(result)

    assert final_operation_abstain_reason(candidate, operations) == reason


def test_abstained_mark_is_unchanged() -> None:
    gate_cases = [
        ({"status": "abstain", "reason": "gate_not_met"}, True),
        ({"status": "answered", "reason": None}, False),
        (None, False),
    ]
    for result, abstained in gate_cases:
        candidate, operations = _gate_final(result)
        assert final_operation_abstained(candidate, operations) is abstained
        assert (final_operation_abstain_reason(candidate, operations) is not None) is abstained

    combine_cases = [
        (_abstain_evidence(), True),
        (_answered_evidence(), False),
    ]
    for evidence, abstained in combine_cases:
        operations = _operations(evidence, "a x")
        expression = _combine_final("$synthesis_1")
        assert final_operation_abstained(expression, operations) is abstained
        assert (final_operation_abstain_reason(expression, operations) is not None) is abstained
