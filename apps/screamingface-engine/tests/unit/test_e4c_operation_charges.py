"""Each operation carries what its provider calls charge the Budget (E4c, OME-1291, ans:Q32).

FEATURE: the report's overspend line (report RP-34) must show the spend the Budget saw, also on
a replay. A cache hit costs $0 now (``OperationAccounting`` stays exact), but the Budget charges
the ORIGINAL cost (``cache.reference``, budget BU-27). So the Engine writes the ``charge`` rule's
numbers per provider call on the operation, and the SDK adds them.
STORY: as a researcher who replays a run, I see the same overspend as the live run.
"""

from __future__ import annotations

from test_operation_output_capture import _accounting, _call, _fusion_expression

from screamingface_engine.benchmarks.contract import (
    OperationOutput,
    decode_candidate_invocation_record,
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.operation_outputs import attribute_operation_outputs
from screamingface_engine.budget import CallCharge
from screamingface_engine.operation_accounting import SignalAccounting
from screamingface_engine.operation_calls import OperationCall

_MEMBER_1 = ("/provider/alpha", (("temperature", "0.0"),))
_MEMBER_2 = ("/provider/beta", ())
_WRITER = ("/provider/alpha", (("temperature", "0.5"),))


def _priced(
    key: tuple[str, tuple[tuple[str, str], ...]], *, cost: str, signals: SignalAccounting
) -> OperationCall:
    call = _call(*key, "answer", accounting=_accounting(cost=cost))
    return OperationCall(
        path=call.path,
        params=call.params,
        output=call.output,
        finish_reason=call.finish_reason,
        accounting=call.accounting,
        signal_accounting=signals,
    )


def _operations(calls: list[OperationCall], *, charged: bool) -> list[OperationOutput]:
    operations = attribute_operation_outputs(_fusion_expression(), calls, charged=charged)
    assert operations is not None
    return operations


def test_a_cache_hit_charges_its_original_cost() -> None:
    # A replayed hit: $0 now in accounting, the live run's numbers in signal_accounting.
    original = SignalAccounting(cost_usd=0.002, tokens_in=120.0, tokens_out=30.0)
    calls = [
        _priced(_MEMBER_1, cost="0", signals=original),
        _priced(_MEMBER_2, cost="0", signals=original),
        _priced(_WRITER, cost="0", signals=original),
    ]

    operations = _operations(calls, charged=True)

    assert [op.charges for op in operations] == [[CallCharge(usd=0.002, tokens=150.0)]] * 3
    assert {op.accounting.usage.cost_usd for op in operations if op.accounting} == {"0"}


def test_each_round_charges_once_and_an_unpriced_call_has_no_number() -> None:
    priced = SignalAccounting(cost_usd=0.001, tokens_in=10.0, tokens_out=2.0)
    calls = [
        _priced(_MEMBER_1, cost="0.001", signals=priced),
        _priced(_MEMBER_1, cost="0.001", signals=SignalAccounting(tokens_in=8.0, tokens_out=1.0)),
        _priced(_MEMBER_2, cost="0.001", signals=priced),
    ]

    member_1 = _operations(calls, charged=True)[0]

    assert member_1.charges == [
        CallCharge(usd=0.001, tokens=12.0),
        CallCharge(usd=None, tokens=9.0),
    ]


def test_no_budget_keeps_the_wire_bytes() -> None:
    signals = SignalAccounting(cost_usd=0.002, tokens_in=1.0, tokens_out=1.0)
    calls = [_priced(_MEMBER_1, cost="0.002", signals=signals)]

    operations = _operations(calls, charged=False)

    assert all(op.charges is None for op in operations)
    assert all("charges" not in op.model_dump(by_alias=True) for op in operations)


def test_an_operation_with_no_provider_call_has_no_charges() -> None:
    # The writer never ran: nothing to charge, and no invented zero.
    signals = SignalAccounting(cost_usd=0.002, tokens_in=1.0, tokens_out=1.0)
    calls = [_priced(_MEMBER_1, cost="0.002", signals=signals)]

    operations = _operations(calls, charged=True)

    assert operations[0].charges == [CallCharge(usd=0.002, tokens=2.0)]
    assert operations[1].charges is None
    assert operations[2].charges is None
    assert "charges" in operations[0].model_dump(by_alias=True)


def test_charges_survive_the_invocation_envelope() -> None:
    signals = SignalAccounting(cost_usd=0.002, tokens_in=1.0, tokens_out=1.0)
    operations = _operations([_priced(_MEMBER_1, cost="0", signals=signals)], charged=True)

    envelope = encode_candidate_invocation("answer", "stop", None, operations=operations)

    assert decode_candidate_invocation_record(envelope).operations == operations
    assert '"charges":[{"usd":0.002,"tokens":2.0}]' in envelope
