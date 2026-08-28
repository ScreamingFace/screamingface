"""The Client decodes the Engine's retained per-operation accounting (OME-1032).

The Engine (OME-1030) retains, on the two records that already own the semantics,
what one semantic operation actually consumed: which provider answered, the six
usage fields, summed provider latency, and the response-cache outcomes. These
tests pin the CLIENT half of that contract — decoding it without inventing
anything.

The invariant every case here defends is the parent spec's exact-only rule
(`docs/spec/2026-08-27-OME-901-operation-accounting.md` §0): **absence stays
absence**. A null accounting must never become a zeroed value, an unparseable
field must never degrade into a plausible one, and a partial record must never
publish as an exact subtotal. A false zero here would be read as "this operation
was free", which is worse than no answer at all.

`accounting` is REQUIRED-nullable on both owners: the Engine emits the key
unconditionally, so a payload missing it is an Engine/Client version mismatch and
must fail loudly rather than default to None — that strictness is exactly why
this slice has to land together with the Engine branch.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

import screamingface as sf
from screamingface._evaluation.results import _case_operation, _evidence
from screamingface.errors import ExecutionError

# -- wire fixtures -------------------------------------------------------------------


def _usage_wire(**overrides: object) -> dict[str, object]:
    usage: dict[str, object] = {
        "input_tokens": 1200,
        "output_tokens": 340,
        "cache_read_tokens": 0,
        # A field the Engine could not observe — the fixture carries it explicitly
        # so the "null is not zero" assertion has something real to stand on.
        "cache_creation_tokens": None,
        "reasoning_tokens": 900,
        "cost_usd": "0.0123450000",
    }
    usage.update(overrides)
    return usage


def _accounting_wire(**overrides: object) -> dict[str, object]:
    wire: dict[str, object] = {
        "provider": "openrouter",
        "request_model": "openrouter/openai/gpt-oss-120b",
        "response_model": "openai/gpt-oss-120b",
        "usage": _usage_wire(),
        "provider_latency_ms": 4200,
        "provider_attempts": 1,
        "cache": {"hits": 0, "misses": 1, "bypasses": 0, "unknown": 0},
    }
    wire.update(overrides)
    return wire


def _operation_wire(accounting: object) -> dict[str, object]:
    return {
        "operation_id": "op_model_1",
        "output": "an answer",
        "finish_reason": "stop",
        "accounting": accounting,
    }


def _evidence_wire(accounting: object) -> dict[str, object]:
    return {
        "sequence": 1,
        "producer": {"type": "model", "id": "openrouter/openai/gpt-5.4"},
        "valid": True,
        "outcome": "MET",
        "explanation": "the response met the criterion",
        "raw_output": '{"criterion_status": "MET"}',
        "metadata": {},
        "accounting": accounting,
    }


# -- the happy path, on both owners --------------------------------------------------


@pytest.mark.parametrize(
    "decode,wire", [(_case_operation, _operation_wire), (_evidence, _evidence_wire)]
)
def test_full_accounting_decodes_into_the_typed_value(decode, wire) -> None:
    decoded = decode(wire(_accounting_wire()))
    accounting = decoded.accounting
    assert accounting is not None
    assert accounting.provider == "openrouter"
    assert accounting.request_model == "openrouter/openai/gpt-oss-120b"
    assert accounting.response_model == "openai/gpt-oss-120b"
    assert accounting.provider_latency_ms == 4200
    # WHY beside the latency: the summed latency counts every attempt including
    # failures, so without this a flaky route and a slow model read identically.
    assert accounting.provider_attempts == 1
    # WHY Decimal: cost is money — the SDK's existing Usage already refuses float
    # cost, and the breakdown must sum without binary-float drift.
    assert accounting.usage.cost_usd == Decimal("0.0123450000")
    assert accounting.usage.input_tokens == 1200
    assert accounting.usage.reasoning_tokens == 900
    # INVARIANT: a field the Engine could not observe stays None — NOT 0.
    assert accounting.usage.cache_creation_tokens is None
    assert (accounting.cache.hits, accounting.cache.misses) == (0, 1)


@pytest.mark.parametrize(
    "decode,wire", [(_case_operation, _operation_wire), (_evidence, _evidence_wire)]
)
def test_null_accounting_decodes_to_none_not_a_zeroed_value(decode, wire) -> None:
    # The common case: deterministic Evidence, ambiguous joins, and CorrectiveLoop
    # nested work all carry null. Zeroing it would publish "this was free".
    assert decode(wire(None)).accounting is None


@pytest.mark.parametrize(
    "decode,wire", [(_case_operation, _operation_wire), (_evidence, _evidence_wire)]
)
def test_round_trip_through_to_dict_is_byte_equal(decode, wire) -> None:
    payload = wire(_accounting_wire())
    assert decode(payload).to_dict() == payload


@pytest.mark.parametrize(
    "decode,wire", [(_case_operation, _operation_wire), (_evidence, _evidence_wire)]
)
def test_null_accounting_round_trips_as_an_explicit_null(decode, wire) -> None:
    # Required-nullable on the wire: the key is always present, so a re-serialized
    # record must still carry it rather than dropping it.
    assert decode(wire(None)).to_dict()["accounting"] is None


# -- the version-mismatch guard ------------------------------------------------------


@pytest.mark.parametrize(
    "decode,wire", [(_case_operation, _operation_wire), (_evidence, _evidence_wire)]
)
def test_a_missing_accounting_key_refuses_loudly(decode, wire) -> None:
    # WHY required, not optional: the Engine emits the key unconditionally, so its
    # absence means the Client is talking to an Engine that predates the contract.
    # Defaulting to None would silently publish an empty breakdown for a whole run.
    payload = wire(None)
    del payload["accounting"]
    with pytest.raises(ExecutionError, match="missing 'accounting'"):
        decode(payload)


# -- strictness: every refusal below would otherwise become a false number -----------


@pytest.mark.parametrize(
    "overrides,expected",
    [
        pytest.param(
            {"cache": {"hits": 0, "misses": 0, "bypasses": 0, "unknown": 0}},
            "response",
            id="no-response",
        ),
        pytest.param({"provider_latency_ms": -1}, "provider_latency_ms", id="negative-latency"),
        pytest.param({"provider_attempts": -1}, "provider_attempts", id="negative-attempts"),
        pytest.param({"provider": "   "}, "provider", id="blank-provider"),
        pytest.param(
            {"usage": _usage_wire(input_tokens=-5)},
            "input_tokens",
            id="negative-tokens",
        ),
        pytest.param(
            {"usage": _usage_wire(cost_usd="-1.00")},
            "cost",
            id="negative-cost",
        ),
        pytest.param({"usage": _usage_wire(cost_usd=0.0123)}, "cost", id="float-cost"),
    ],
)
def test_malformed_accounting_refuses_instead_of_degrading(overrides: dict, expected: str) -> None:
    with pytest.raises(ExecutionError, match=expected):
        _case_operation(_operation_wire(_accounting_wire(**overrides)))


@pytest.mark.parametrize(
    "cost",
    [
        pytest.param("1e2", id="positive-exponent"),
        pytest.param("1E-2", id="negative-exponent"),
        pytest.param("01.00", id="leading-zero"),
        pytest.param("+1.00", id="leading-plus"),
        pytest.param(Decimal("1.00"), id="decimal-object"),
    ],
)
def test_noncanonical_wire_cost_refuses_instead_of_being_normalized(cost: object) -> None:
    # INVARIANT: Client decoding preserves the Engine's fixed-point wire bytes.
    # Accepting another Decimal spelling would silently normalize it on export.
    with pytest.raises(ExecutionError, match="cost_usd.*fixed-point"):
        _case_operation(_operation_wire(_accounting_wire(usage=_usage_wire(cost_usd=cost))))


def test_a_cache_hit_keeps_zero_attempts_rather_than_null() -> None:
    # A confirmed hit performs no current provider dispatch, so zero is the exact
    # truth — the same reason its cost and latency are zero. Decoding it to None
    # would turn a known fact into missing evidence.
    decoded = _case_operation(
        _operation_wire(
            _accounting_wire(
                provider_attempts=0,
                provider_latency_ms=0,
                cache={"hits": 1, "misses": 0, "bypasses": 0, "unknown": 0},
            )
        )
    )
    assert decoded.accounting is not None
    assert decoded.accounting.provider_attempts == 0


def test_an_unvalidated_attempt_list_decodes_as_an_unknown_count() -> None:
    # The Engine publishes null when it had to skip an attempt entry: counting a
    # list it could not fully read would tell a retry story that never happened.
    decoded = _case_operation(_operation_wire(_accounting_wire(provider_attempts=None)))
    assert decoded.accounting is not None
    assert decoded.accounting.provider_attempts is None


def test_an_unknown_accounting_field_refuses() -> None:
    # Strict decoder, no compatibility fallback (OME-1031 scope note): an Engine
    # that grew a field the Client cannot interpret must not be half-decoded.
    with pytest.raises(ExecutionError, match="unsupported field"):
        _case_operation(_operation_wire(_accounting_wire(estimated_cost_usd="9.99")))


def test_an_unknown_cache_field_refuses() -> None:
    cache = {"hits": 1, "misses": 0, "bypasses": 0, "unknown": 0, "avoided_cost_usd": "0.10"}
    with pytest.raises(ExecutionError, match="unsupported field"):
        _case_operation(_operation_wire(_accounting_wire(cache=cache)))


def test_a_missing_usage_field_refuses_rather_than_defaulting() -> None:
    # Six independently optional fields — but each must be PRESENT and explicitly
    # null. A dropped key is missing evidence, not a zero.
    usage = _usage_wire()
    del usage["reasoning_tokens"]
    with pytest.raises(ExecutionError, match="reasoning_tokens"):
        _case_operation(_operation_wire(_accounting_wire(usage=usage)))


# -- public surface ------------------------------------------------------------------


def test_the_accounting_values_are_public_and_constructible() -> None:
    accounting = sf.OperationAccounting(
        provider="openrouter",
        request_model="openrouter/openai/gpt-5.4",
        response_model=None,
        usage=sf.Usage(input_tokens=10, cost_usd="0.5"),
        provider_latency_ms=None,
        provider_attempts=None,
        cache=sf.OperationCache(hits=1, misses=0, bypasses=0, unknown=0),
    )
    assert accounting.usage.cost_usd == Decimal("0.5")
    assert accounting.cache.hits == 1
    assert accounting.to_dict()["provider_latency_ms"] is None


def test_a_cache_record_with_no_response_refuses() -> None:
    # The count sum IS the number of consumed responses the record represents;
    # zero of them means the record describes nothing.
    with pytest.raises(ValueError, match="response"):
        sf.OperationCache(hits=0, misses=0, bypasses=0, unknown=0)
