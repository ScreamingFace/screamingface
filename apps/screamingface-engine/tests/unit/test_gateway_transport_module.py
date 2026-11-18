"""The gateway round trip as its own module: the public entry and the import rule.

FEATURE: shared gateway round trip (PRD `gateway-transport.md`, GT-S4 and the delta of §2.2).
The round trip moved out of `world/connector.py` into `world/gateway_transport.py`. The chat
final-step endpoint calls it with no model endpoint and no tool loop.

INVARIANT: `connector.py` imports the MODULE, never a moved name. A test that still patches a
moved name on `connector` must fail with an AttributeError. With a name import, the patch would
succeed and reach no code.
"""

from __future__ import annotations

import ast
import inspect

import httpx
import pytest
from frozen_copy_support import CHAT, MODEL, Gateway, chat

from screamingface_engine.operation_accounting import OperationAccounting
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world import classification, connector, gateway_transport
from url4.streaming.protocol import CachePolicy

# The names a test patched on `connector` before the move: functions, constants, and the sinks
# and helpers that only the moved code reads. Written by hand, so a later edit of either module
# cannot shrink the list without a change here.
_MOVED_NAMES = (
    "_logged_round_trip",
    "_observed_round_trip",
    "_in_flight_heartbeat",
    "_recorded_completion",
    "_fetch_completion",
    "_fetch_replay",
    "_post_answered",
    "_post_completion",
    "_post_attempt",
    "_CaptureProbe",
    "_capture_target",
    "_report_response",
    "_report_usage",
    "_report_unpriced_call",
    "_report_served_from_cache",
    "_headers",
    "_json_or_raise",
    "_raise_for_status",
    "_GatewayRefusal",
    "_transport_backoff",
    "_wait_to_retry",
    "_queue_retry_delay",
    "_deadline_exceeded",
    "_NEVER_SENT",
    "_TRANSPORT_RETRIES",
    "_TRANSPORT_BACKOFF_BASE_S",
    "_TRANSPORT_BACKOFF_MAX_S",
    "_TRANSPORT_BACKOFF_JITTER_S",
    "_IN_FLIGHT_HEARTBEAT_S",
    "_IN_FLIGHT_HEARTBEAT_MAX_S",
    "_GATEWAY_RESPONSE_MARGIN_S",
    "ModelCall",
    "current_log_sink",
    "current_response_sink",
    "current_usage_sink",
    "retained_operation_accounting",
    "signal_accounting_from_aigw",
    "reply_logprobs",
    "time",
)


def _top_level_names(module: object) -> set[str]:
    """The functions, classes and assigned names that a module DEFINES (imports left out)."""
    names: set[str] = set()
    for node in ast.parse(inspect.getsource(module)).body:  # type: ignore[arg-type]
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _names_imported_from_gateway_transport(module: object) -> list[str]:
    return [
        alias.name
        for node in ast.walk(ast.parse(inspect.getsource(module)))  # type: ignore[arg-type]
        if isinstance(node, ast.ImportFrom)
        and node.module == "screamingface_engine.world.gateway_transport"
        for alias in node.names
    ]


@pytest.mark.asyncio
async def test_round_trip_works_without_model_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """GT-5: one call through the public entry, with no `_ModelEndpoint` and no tool loop.

    The cache policy, the transport retry and the accounting are applied by the round trip itself.
    """

    async def no_wait(_attempt: int, _delay: float) -> None:
        return None

    monkeypatch.setattr(gateway_transport, "_wait_to_retry", no_wait)
    gateway = Gateway([httpx.ReadError("the first send breaks"), chat("the final answer")])
    scope = RequestScope(
        origin="run",
        identity_headers={"X-User-Email": "caller@x.test"},
        cache=CachePolicy(participate=False),
    )
    accounting: list[OperationAccounting | None] = []

    async with gateway.client() as client:
        with request_scope(scope):
            choice = await gateway_transport.round_trip(
                client,
                real_model_id=MODEL,
                headers={
                    **gateway_transport._headers(scope),
                    **gateway_transport.timeout_headers(45.0, 15.0),
                },
                body={"model": MODEL, "messages": [{"role": "user", "content": "hello"}]},
                cache=scope.cache,
                max_tokens=None,
                operation_accounting=accounting,
            )

    assert choice.content == "the final answer"
    assert choice.tool_calls is None
    calls = gateway.calls(CHAT)
    # The transport retry sent the same request twice.
    assert len(calls) == 2
    headers, body = calls[-1]
    assert headers["x-user-email"] == "caller@x.test"
    assert headers["x-aigw-execution-timeout-s"] == "45.0"
    assert headers["x-aigw-queue-timeout-s"] == "15.0"
    # The round trip added the cache policy of the scope to the body it was given.
    assert body == {
        "model": MODEL,
        "messages": [{"role": "user", "content": "hello"}],
        "cache": {"use-cache": False},
    }
    assert len(accounting) == 1


def test_timeout_headers_take_plain_numbers() -> None:
    """GT-1 delta: the two time-out headers come from one function of two plain values."""
    assert gateway_transport.timeout_headers(60.0, 12.5) == {
        "x-aigw-execution-timeout-s": "60.0",
        "x-aigw-queue-timeout-s": "12.5",
    }


def test_connector_has_no_private_copy_of_moved_functions() -> None:
    """GT-6: each moved name has ONE definition, and no module imports a moved name by name."""
    moved = _top_level_names(gateway_transport) - {"logger"}

    assert moved >= set(_MOVED_NAMES) - {
        "ModelCall",
        "current_log_sink",
        "current_response_sink",
        "current_usage_sink",
        "retained_operation_accounting",
        "signal_accounting_from_aigw",
        "reply_logprobs",
        "time",
    }
    assert _top_level_names(connector) & moved == set()
    assert _top_level_names(classification) & moved == set()
    assert _names_imported_from_gateway_transport(connector) == []
    assert _names_imported_from_gateway_transport(classification) == []
    # WHY the same object: operators filter the runtime log by this one logger name.
    assert connector.logger is gateway_transport.logger


@pytest.mark.parametrize("name", _MOVED_NAMES)
def test_moved_names_are_not_attributes_of_connector(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GT-8: a stale patch target raises. It must not pass and reach no code."""
    assert hasattr(gateway_transport, name)
    assert not hasattr(connector, name)
    with pytest.raises(AttributeError):
        monkeypatch.setattr(connector, name, object())


def test_gateway_transport_does_not_import_connector() -> None:
    """GT-S5: the new module is below the connector. It imports neither the connector nor a half."""
    imported = {
        node.module
        for node in ast.walk(ast.parse(inspect.getsource(gateway_transport)))
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "screamingface_engine.world.connector" not in imported
    assert not any(
        module.startswith(("screamingface_engine.runner", "screamingface_engine.rest"))
        for module in imported
    )
