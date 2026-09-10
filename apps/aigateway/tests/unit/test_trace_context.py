"""The caller's trace id joins aigateway's log context (OME-1120) — rung 4b, the payoff rung.

`OME-1119` put the client's trace id on the wire to this gateway; `OME-938` gave it a
per-request log context and a render slot. This joins them, so one id is greppable across the
engine's namespace and `sf-aigw` — which IS Phase 1's acceptance.

The property that matters most here is not the happy path. **The header is caller-controlled.**
Adopting a malformed or attacker-chosen value would hand a caller the correlation key for other
people's requests, so the nine-case rejection table below is the real subject of this file.
"""

from __future__ import annotations

import logging

import pytest

from aigateway import logs
from aigateway.call_context import (
    call_scope,
    current_trace_id,
    install_call_context_injection,
    record_trace_id,
)
from aigateway.w3c_trace import TRACE_ID_LEN, adopt_or_mint_trace_id, parse_trace_id

CALL_ID = "call_" + "a" * 32
INBOUND_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
INBOUND = f"00-{INBOUND_TRACE}-00f067aa0ba902b7-01"


@pytest.fixture(autouse=True)
def _restore_log_record_factory():
    original = logging.getLogRecordFactory()
    try:
        yield
    finally:
        logging.setLogRecordFactory(original)


def _record() -> logging.LogRecord:
    return logging.getLogRecordFactory()(
        "aigateway.test", logging.INFO, __file__, 1, "a message", (), None
    )


# --- the rejection table — the security surface ---------------------------------------------

REJECTED = [
    pytest.param("00-" + "0" * 32 + "-00f067aa0ba902b7-01", id="all-zero-trace"),
    pytest.param(f"00-{INBOUND_TRACE}-" + "0" * 16 + "-01", id="all-zero-span"),
    pytest.param(f"01-{INBOUND_TRACE}-00f067aa0ba902b7-01", id="version-01"),
    pytest.param(f"00-{INBOUND_TRACE.upper()}-00f067aa0ba902b7-01", id="uppercase-hex"),
    pytest.param("", id="empty"),
    pytest.param("not-a-traceparent", id="garbage"),
    pytest.param(f"00-{INBOUND_TRACE}-00f067aa0ba902b7", id="missing-flags"),
    pytest.param("00-abc-00f067aa0ba902b7-01", id="short-trace-id"),
    pytest.param(f"00-{INBOUND_TRACE}-00f067-01", id="short-span-id"),
]
"""The nine shapes the engine rejects, restated rather than imported.

`apps/aigateway` does not depend on `url4`, so this table IS the contract between the two
services. Restating it means a change to url4's rule that widened what counts as valid would
surface here as a failure rather than be adopted silently.
"""


@pytest.mark.parametrize("value", REJECTED)
def test_a_malformed_traceparent_is_never_adopted(value: str) -> None:
    assert parse_trace_id(value) is None


@pytest.mark.parametrize("value", REJECTED)
def test_a_malformed_traceparent_yields_a_fresh_id_not_the_input(value: str) -> None:
    """Rejecting is half of it. The request still needs an id, and it must not be the caller's.

    Returning None here would leave the request anonymous; returning the input would let a
    caller pick the correlation key. Neither is acceptable, so the rule is adopt-or-MINT.
    """
    minted = adopt_or_mint_trace_id(value)

    assert len(minted) == TRACE_ID_LEN
    assert set(minted) <= set("0123456789abcdef")
    assert minted != "0" * TRACE_ID_LEN
    assert minted not in value


def test_a_valid_traceparent_is_adopted_verbatim() -> None:
    """The whole point: the gateway must join the CALLER's trace, not start its own."""
    assert parse_trace_id(INBOUND) == INBOUND_TRACE
    assert adopt_or_mint_trace_id(INBOUND) == INBOUND_TRACE


def test_an_absent_header_yields_a_minted_id() -> None:
    minted = adopt_or_mint_trace_id(None)

    assert len(minted) == TRACE_ID_LEN
    assert minted != "0" * TRACE_ID_LEN


def test_two_mints_never_collide() -> None:
    assert adopt_or_mint_trace_id(None) != adopt_or_mint_trace_id(None)


# --- the scope and the record ----------------------------------------------------------------


def test_outside_a_request_there_is_no_trace_id() -> None:
    assert current_trace_id() is None


def test_the_scope_carries_both_ids_together() -> None:
    with call_scope(CALL_ID, trace_id=INBOUND_TRACE):
        assert current_trace_id() == INBOUND_TRACE
    assert current_trace_id() is None


def test_a_record_created_in_scope_carries_the_trace_id() -> None:
    install_call_context_injection()

    with call_scope(CALL_ID, trace_id=INBOUND_TRACE):
        record = _record()

    assert record_trace_id(record) == INBOUND_TRACE


def test_a_record_outside_any_request_carries_no_trace_id() -> None:
    install_call_context_injection()

    assert record_trace_id(_record()) is None


# --- rendering --------------------------------------------------------------------------------


def test_the_line_carries_both_ids() -> None:
    install_call_context_injection()
    formatter = logging.Formatter(logs._FORMAT, defaults={"call_context": ""})
    filt = logs.CallContextFilter()

    with call_scope(CALL_ID, trace_id=INBOUND_TRACE):
        record = _record()
    filt.filter(record)
    rendered = formatter.format(record)

    assert f"gateway_call_id={CALL_ID}" in rendered
    assert f"trace_id={INBOUND_TRACE}" in rendered


def test_a_call_without_a_trace_renders_only_the_call_id() -> None:
    """A request that somehow has no trace must not render `trace_id=` empty or zero.

    An empty field parses as a value downstream; an all-zero id correlates nothing while
    looking correct in every log it reaches.
    """
    install_call_context_injection()
    filt = logs.CallContextFilter()

    with call_scope(CALL_ID):
        record = _record()
    filt.filter(record)

    assert "gateway_call_id=" in logs.rendered_context(record)
    assert "trace_id=" not in logs.rendered_context(record)


def test_a_line_outside_a_request_is_unchanged() -> None:
    install_call_context_injection()
    formatter = logging.Formatter(logs._FORMAT, defaults={"call_context": ""})
    filt = logs.CallContextFilter()

    record = _record()
    filt.filter(record)

    assert formatter.format(record) == "INFO:     aigateway.test a message"


# --- through the real app: the wire, not the unit ---------------------------------------------


def _app_client():
    """A minimal real app, so the middleware is exercised where it actually runs."""
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    from aigateway.call_context import current_call_id, current_trace_id
    from aigateway.middleware import CallIdMiddleware

    app = FastAPI()
    app.add_middleware(CallIdMiddleware)

    @app.get("/probe")
    def probe() -> dict[str, str | None]:
        return {"trace_id": current_trace_id(), "gateway_call_id": current_call_id()}

    return TestClient(app)


def test_a_wellformed_inbound_trace_is_joined_end_to_end() -> None:
    body = _app_client().get("/probe", headers={"traceparent": INBOUND}).json()

    assert body["trace_id"] == INBOUND_TRACE, "the gateway started its own trace instead of joining"


@pytest.mark.parametrize("value", REJECTED)
def test_a_malformed_inbound_trace_never_reaches_the_request(value: str) -> None:
    """The security property, asserted on the wire rather than on the helper."""
    body = _app_client().get("/probe", headers={"traceparent": value}).json()

    assert body["trace_id"] != value
    assert len(body["trace_id"]) == TRACE_ID_LEN


def test_every_response_echoes_the_trace_id_as_a_header() -> None:
    """A STREAMING caller never sees a response body object — the header is its only channel."""
    from aigateway.middleware.call_id import TRACE_RESPONSE_HEADER

    response = _app_client().get("/probe", headers={"traceparent": INBOUND})

    header = TRACE_RESPONSE_HEADER.decode()
    assert response.headers[header] == INBOUND_TRACE
    assert response.json()["trace_id"] == response.headers[header]


def test_the_echo_does_not_drop_the_responses_own_headers() -> None:
    """The header list is APPENDED to, never replaced — content-type must survive."""
    response = _app_client().get("/probe", headers={"traceparent": INBOUND})

    assert response.headers["content-type"].startswith("application/json")


def test_two_requests_do_not_share_a_trace() -> None:
    client = _app_client()

    first = client.get("/probe", headers={"traceparent": INBOUND}).json()
    second = client.get("/probe").json()

    assert first["trace_id"] == INBOUND_TRACE
    assert second["trace_id"] != first["trace_id"], "one caller's trace leaked into another's"
