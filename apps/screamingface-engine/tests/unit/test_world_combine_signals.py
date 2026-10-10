"""The combine route next to member model calls (OME-1289 E4a gap-closure, unit 1).

FEATURE: a combine step runs after its member calls; a member that fails still fails the case,
and the route reads each member's accounting by exact call fingerprint.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

import pytest
from combine_support import FAKE_REGISTRY, context_text, request, run, spec_text, vote_spec

from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.combine.spec import canonical_params
from screamingface_engine.operation_accounting import SignalAccounting
from screamingface_engine.operation_calls import (
    OperationCall,
    capture_operation_calls,
    current_operation_calls,
    operation_call_identity,
    record_combine_call,
    record_operation_call,
)
from screamingface_engine.world.combine import CombineRoute, install_combine_runtime
from url4 import RelExpr, Text, expr, render, src, struct, text
from url4.core.errors import ResolutionError
from url4.io.static import StaticIOLayer
from url4.peer.server import Request, Url4Node

# --- AB#6 -------------------------------------------------------------------------------------


def _member_down(request: Request) -> str:
    raise ResolutionError("down", code="upstream_error", permanent=True)


def _failing_member_expression() -> str:
    context = render(struct({"input": "$input", "outputs": {"member_1": "$model_1"}}))
    return render(
        expr(
            src(
                RelExpr(path="/provider/down", context="$input", intent=text("Answer plainly.")),
                name="model_1",
                weight=0.0,
            ),
            src(
                RelExpr(
                    path=COMBINE_ROUTE,
                    context=context,
                    intent=Text(spec_text(vote_spec(1))),
                    params=(("binding", "synthesis_1"),),
                ),
                name="synthesis_1",
                weight=0.0,
            ),
            intent=text("$synthesis_1"),
        )
    )


@pytest.mark.asyncio
async def test_member_transport_error_still_fails_the_case() -> None:
    node = Url4Node("t", outbound=StaticIOLayer())
    node.endpoint("/provider/down")(_member_down)
    install_combine_runtime(node, FAKE_REGISTRY)
    with capture_operation_calls() as calls:
        with pytest.raises(ResolutionError) as caught:
            await node.evaluate(_failing_member_expression(), env={"input": "q"})
    assert caught.value.code == "upstream_error"
    assert all(call.combine is None for call in calls)


# --- the adapter reads member accounting by exact call fingerprint ----------------------------

_LOGGER = "screamingface_engine.world.combine"
_ALPHA = ("/provider/alpha", {"temperature": "0.0"})
_BETA = ("/provider/beta", {})
_GAMMA = ("/provider/gamma", {})
_GHOST = ("/provider/ghost-SECRET", {})

type _Call = tuple[str, dict[str, str]]


def _record(call: _Call, **numbers: float | None) -> None:
    """Record one model call as the connector does: identity first, then the terminal record."""
    path, params = call
    with operation_call_identity(path, params):
        record_operation_call("out", "stop", None, SignalAccounting(**numbers))


def _sources(*per_member: list[_Call]) -> dict[str, Any]:
    """The ``sources`` of a context: the fingerprints each member's calls are known by."""
    return {
        f"member_{index}": {
            f"call_{number}": {"path": path, "params": canonical_params(params.items())}
            for number, (path, params) in enumerate(calls, start=1)
        }
        for index, calls in enumerate(per_member, start=1)
    }


def _route_signals(
    calls: list[OperationCall], sources: dict[str, Any], key: str = "cost_usd"
) -> list[dict[str, Any]]:
    """Run the route on two members; return each row's signals from the call it recorded."""
    spec = vote_spec(
        2,
        reduce={"op": "fake_signal_score@1", "args": {"key": key, "order": "max"}},
        select={"op": "fake_best@1", "args": {}},
    )
    CombineRoute(FAKE_REGISTRY)(
        request(spec_text(spec), context_text(["a x", "b y"], sources=sources))
    )
    evidence = calls[-1].combine
    assert evidence is not None
    return [dict(row.signals) for row in evidence.members]


def _decoy_combine_call() -> None:
    evidence = run(spec_text(vote_spec(2)), context_text(["a x", "b y"])).evidence
    record_combine_call(COMBINE_ROUTE, {"binding": "synthesis_9"}, "", evidence)


def test_adapter_sums_member_signal_accounting_by_fingerprint() -> None:
    with capture_operation_calls() as calls:
        _record(_ALPHA, cost_usd=0.001, tokens_in=10.0)
        _record(_BETA, cost_usd=0.002, tokens_in=20.0)
        _record(_GAMMA, cost_usd=0.004, tokens_in=40.0)
        _decoy_combine_call()
        sources = _sources([_ALPHA, _BETA], [_GAMMA])
        costs = _route_signals(calls, sources)
        tokens = _route_signals(calls, sources, "tokens_in")
    assert costs == [{"cost_usd": math.fsum([0.001, 0.002])}, {"cost_usd": 0.004}]
    assert tokens == [{"tokens_in": 30.0}, {"tokens_in": 40.0}]


def test_a_param_set_is_part_of_the_fingerprint() -> None:
    with capture_operation_calls() as calls:
        _record(_ALPHA, cost_usd=0.001)
        _record(("/provider/alpha", {"temperature": "0.5"}), cost_usd=0.5)
        other = ("/provider/alpha", {"temperature": "0.5"})
        rows = _route_signals(calls, _sources([_ALPHA], [other]))
    assert rows == [{"cost_usd": 0.001}, {"cost_usd": 0.5}]


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == _LOGGER and record.levelname == "WARNING"
    ]


def test_unmatched_or_unrecorded_source_gives_none_not_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger=_LOGGER), capture_operation_calls() as calls:
        _record(_ALPHA, cost_usd=0.001)
        _record(_ALPHA, cost_usd=0.002)  # recorded twice: several matches
        rows = _route_signals(calls, _sources([_GHOST], [_ALPHA]))  # no match; several matches
    assert rows == [{"cost_usd": None}, {"cost_usd": None}]
    (message,) = _warnings(caplog)
    assert "2 source call(s)" in message
    assert "/provider" not in message and "SECRET" not in message and "temperature" not in message


def test_no_capture_scope_gives_none_with_one_warning(caplog: pytest.LogCaptureFixture) -> None:
    spec = vote_spec(
        2,
        reduce={"op": "fake_signal_score@1", "args": {"key": "cost_usd", "order": "max"}},
        select={"op": "fake_best@1", "args": {}},
    )
    context = context_text(["a x", "b y"], sources=_sources([_ALPHA], [_BETA]))
    with caplog.at_level("WARNING", logger=_LOGGER):
        CombineRoute(FAKE_REGISTRY)(request(spec_text(spec), context))
    (message,) = _warnings(caplog)
    assert "no operation-call recorder" in message


def test_a_member_without_source_calls_gets_none_and_no_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger=_LOGGER), capture_operation_calls() as calls:
        _record(_ALPHA, cost_usd=0.001)
        rows = _route_signals(calls, _sources([_ALPHA], []))
    assert rows == [{"cost_usd": 0.001}, {"cost_usd": None}]
    assert _warnings(caplog) == []


def test_a_matched_call_without_signal_accounting_is_incomplete_and_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger=_LOGGER), capture_operation_calls() as calls:
        with operation_call_identity(*_ALPHA):
            record_operation_call("out", "stop")  # a call recorded without signal accounting
        _record(_BETA, cost_usd=0.002)
        rows = _route_signals(calls, _sources([_ALPHA], [_BETA]))
    assert rows == [{"cost_usd": None}, {"cost_usd": 0.002}]
    assert _warnings(caplog) == []


@pytest.mark.asyncio
async def test_parallel_cases_see_only_their_own_calls() -> None:
    both_recorded = asyncio.Event()
    recorded: list[float] = []

    async def case(cost: float) -> list[dict[str, Any]]:
        with capture_operation_calls() as calls:
            _record(_ALPHA, cost_usd=cost)
            recorded.append(cost)
            if len(recorded) == 2:
                both_recorded.set()
            await both_recorded.wait()
            return _route_signals(calls, _sources([_ALPHA], [_ALPHA]))

    first, second = await asyncio.gather(case(0.1), case(0.2))
    # The same fingerprint in two cases is no cross-talk: each scope holds exactly one match.
    assert first == [{"cost_usd": 0.1}, {"cost_usd": 0.1}]
    assert second == [{"cost_usd": 0.2}, {"cost_usd": 0.2}]


def test_current_operation_calls_is_the_innermost_snapshot() -> None:
    assert current_operation_calls() is None
    with capture_operation_calls() as outer:
        _record(_ALPHA, cost_usd=0.1)
        outer_snapshot = current_operation_calls()
        assert outer_snapshot is not None and len(outer_snapshot) == 1
        with capture_operation_calls() as inner:
            _record(_BETA, cost_usd=0.2)
            snapshot = current_operation_calls()
            assert isinstance(snapshot, tuple)
            assert snapshot == tuple(inner)
            assert [call.path for call in snapshot] == ["/provider/beta"]
            _record(_GAMMA, cost_usd=0.3)
            assert len(snapshot) == 1  # a snapshot, not a live view
        assert current_operation_calls() == tuple(outer)
    assert [call.path for call in outer] == ["/provider/alpha", "/provider/beta", "/provider/gamma"]
    assert current_operation_calls() is None
