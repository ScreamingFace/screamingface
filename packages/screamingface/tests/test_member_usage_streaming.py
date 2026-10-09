"""Member totals retain nullable semantics with memory independent of case count."""

import tracemalloc
from dataclasses import replace
from decimal import Decimal

import pytest
from test_accounting_breakdown import accounting

import screamingface as sf
from screamingface.accounting import member_usage
from screamingface.case_result import CaseOperation


def case(index, usage):
    return sf.CaseResult(
        case_id=index,
        input="input",
        output="answer",
        finish_reason="stop",
        grade=sf.CaseGrade(method="deterministic", score=1.0, metrics={}, checks=[]),
        failures=[],
        metadata={},
        operations=[
            CaseOperation(
                operation_id="member",
                output="answer",
                finish_reason="stop",
                accounting=replace(accounting(), usage=usage),
            )
        ],
    )


def generated(count):
    for index in range(count):
        yield case(index, sf.Usage(input_tokens=10, output_tokens=2, cost_usd="0.1"))


def test_member_usage_memory_does_not_grow_with_lazy_cases():
    peaks = []
    for count in (1000, 20000):
        tracemalloc.start()
        try:
            summary = member_usage(generated(count), "member")
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
        assert summary is not None and summary.input_tokens == count * 10
        assert summary.cost_usd == Decimal("0.1") * count
    # INVARIANT: only the current Case and field totals survive each iteration.
    assert peaks[1] < peaks[0] + 200_000, peaks


@pytest.mark.parametrize(
    "field",
    [
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_creation_tokens",
        "reasoning_tokens",
        "cost_usd",
    ],
)
def test_member_usage_unknown_field_poisons_only_that_field(field):
    values = sf.Usage(
        input_tokens=1,
        output_tokens=2,
        cache_read_tokens=3,
        cache_creation_tokens=4,
        reasoning_tokens=5,
        cost_usd=Decimal("0.1"),
    )
    unknown = replace(values, **{field: None})
    result = member_usage(iter([case(0, values), case(1, unknown)]), "member")
    assert result is not None
    for name in values.__dataclass_fields__:
        value = getattr(values, name)
        assert getattr(result, name) == (None if name == field else value * 2)


@pytest.mark.parametrize("missing", ["operation", "accounting", "duplicate"])
def test_member_usage_missing_observation_is_unavailable(missing):
    first = case(0, sf.Usage(input_tokens=0, output_tokens=0, cost_usd="0"))
    operations = [] if missing == "operation" else list(first.operations or ())
    if missing == "accounting":
        operations = [replace(operations[0], accounting=None)]
    elif missing == "duplicate":
        operations *= 2
    second = sf.CaseResult(
        case_id=1,
        input=first.input,
        output=first.output,
        finish_reason=first.finish_reason,
        grade=first.grade,
        failures=[],
        metadata={},
        operations=operations,
    )
    assert member_usage(iter([first, second]), "member") is None


def test_empty_member_usage_is_unavailable_and_zero_is_known():
    assert member_usage(iter(()), "member") is None
    assert member_usage(
        iter([case(0, sf.Usage(input_tokens=0, cost_usd="0"))]), "member"
    ) == sf.Usage(input_tokens=0, cost_usd="0")
