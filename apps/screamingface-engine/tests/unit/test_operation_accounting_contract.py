"""Strict retained operation-accounting wire contracts (OME-1030)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from screamingface_engine.benchmarks.contract import (
    Evidence,
    EvidenceProducer,
    OperationAccounting,
    OperationCache,
    OperationOutput,
    OperationUsage,
)


def _accounting(**overrides: Any) -> OperationAccounting:
    values: dict[str, Any] = {
        "provider": "openrouter",
        "request_model": "openrouter/anthropic/claude-sonnet-4",
        "response_model": "anthropic/claude-sonnet-4-20260801",
        "usage": OperationUsage(
            input_tokens=120,
            output_tokens=30,
            cache_read_tokens=20,
            cache_creation_tokens=10,
            reasoning_tokens=5,
            cost_usd="0.0123",
        ),
        "provider_latency_ms": 417,
        "cache": OperationCache(hits=0, misses=1, bypasses=0, unknown=0),
    }
    values.update(overrides)
    return OperationAccounting(**values)


def _evidence(**overrides: Any) -> Evidence:
    values: dict[str, Any] = {
        "sequence": 1,
        "producer": EvidenceProducer(type="model", id="judge/model"),
        "valid": True,
        "outcome": "MET",
        "explanation": "criterion satisfied",
        "raw_output": '{"outcome":"MET"}',
        "metadata": {},
        "accounting": _accounting(),
    }
    values.update(overrides)
    return Evidence(**values)


def test_accounting_round_trips_on_candidate_operations_and_grading_evidence() -> None:
    accounting = _accounting()
    operation = OperationOutput(
        operation_id="op_model_1",
        output="candidate answer",
        finish_reason="stop",
        accounting=accounting,
    )
    evidence = _evidence(accounting=accounting)

    expected = {
        "provider": "openrouter",
        "request_model": "openrouter/anthropic/claude-sonnet-4",
        "response_model": "anthropic/claude-sonnet-4-20260801",
        "usage": {
            "input_tokens": 120,
            "output_tokens": 30,
            "cache_read_tokens": 20,
            "cache_creation_tokens": 10,
            "reasoning_tokens": 5,
            "cost_usd": "0.0123",
        },
        "provider_latency_ms": 417,
        "cache": {"hits": 0, "misses": 1, "bypasses": 0, "unknown": 0},
    }
    assert operation.model_dump()["accounting"] == expected
    assert evidence.model_dump()["accounting"] == expected


def test_null_accounting_is_explicit_for_unsupported_or_deterministic_operations() -> None:
    operation = OperationOutput(
        operation_id="op_model_1",
        output=None,
        finish_reason=None,
        accounting=None,
    )
    evidence = _evidence(
        producer=EvidenceProducer(type="deterministic", id="ifeval/official-verifier"),
        accounting=None,
    )

    assert operation.model_dump()["accounting"] is None
    assert evidence.model_dump()["accounting"] is None


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            OperationOutput,
            {"operation_id": "op_model_1", "output": "answer", "finish_reason": "stop"},
        ),
        (
            Evidence,
            {
                "sequence": 1,
                "producer": {"type": "deterministic", "id": "ifeval/official-verifier"},
                "valid": True,
                "outcome": "MET",
                "explanation": "verified",
                "raw_output": True,
                "metadata": {},
            },
        ),
    ],
)
def test_pre_accounting_wire_shapes_are_rejected(
    model: type[OperationOutput] | type[Evidence], payload: dict[str, object]
) -> None:
    # INVARIANT: v1 evolves directly; a mixed producer cannot silently look like
    # an operation whose accounting was observed and found unavailable.
    with pytest.raises(ValidationError, match="accounting"):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_tokens", -1),
        ("output_tokens", True),
        ("cost_usd", "1e-3"),
        ("cost_usd", "-0.1"),
    ],
)
def test_usage_refuses_noncanonical_or_negative_values(field: str, value: object) -> None:
    payload = OperationUsage(
        input_tokens=1,
        output_tokens=1,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        reasoning_tokens=0,
        cost_usd="0.1",
    ).model_dump()
    payload[field] = value

    with pytest.raises(ValidationError):
        OperationUsage.model_validate(payload)


def test_cache_counts_are_nonnegative_and_account_for_at_least_one_response() -> None:
    with pytest.raises(ValidationError):
        OperationCache(hits=-1, misses=0, bypasses=0, unknown=0)
    with pytest.raises(ValidationError, match="one response"):
        OperationCache(hits=0, misses=0, bypasses=0, unknown=0)


def test_accounting_contracts_forbid_unknown_fields() -> None:
    payload = _accounting().model_dump()
    payload["gateway_call_id"] = "must-not-cross-the-wire"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        OperationAccounting.model_validate(payload)
