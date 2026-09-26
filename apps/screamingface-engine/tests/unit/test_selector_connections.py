"""OME-1381 — the connection routes refuse a nonblank `X-Profile` at their router boundary.

# FEATURE: selector-less provider access — design `component/provider-access` v6, "Stage D
# target", rollout step 2 (Engine producer-off). Connection management is the one REST ingress
# with a request body and a service that may be unconfigured, so it is the one where "refuse
# before anything else" has competitors.
# INVARIANT: the refusal wins over every other answer these routes can give — FastAPI's body
# parsing and validation (422) and the unconfigured-service answer (503) included — so a caller
# fixing a request learns about the retired header first, and no connection is listed, written,
# authorized or removed for a request that named a selector.
"""

from __future__ import annotations

import httpx
import pytest
from test_rest_connections import SECRET as _API_KEY
from test_rest_connections import FakeConnections
from test_rest_connections import _app as _connections_app
from test_rest_models import client_for
from test_selector_refusal import (
    _IDENTITY,
    _SELECTOR_LESS,
    _SELECTORS,
    Headers,
    _assert_problem_refusal,
)

pytestmark = pytest.mark.asyncio

_CONNECTION_CALLS = [
    pytest.param("GET", "/v1/connections", None, id="list"),
    pytest.param("PUT", "/v1/connections/openrouter", {"api_key": _API_KEY}, id="connect"),
    pytest.param("POST", "/v1/connections/openrouter/oauth", None, id="start-oauth"),
    pytest.param("DELETE", "/v1/connections/openrouter", None, id="disconnect"),
]

# Bodies FastAPI itself would refuse with 422 — parsing (malformed, empty) and validation (wrong
# type, forbidden extra field) — each a different point inside FastAPI's request handling.
_INVALID_BODIES = [
    pytest.param(b"{not json", id="malformed-json"),
    pytest.param(b"", id="missing"),
    pytest.param(b'{"api_key": ["' + _API_KEY.encode() + b'"]}', id="wrong-type"),
    pytest.param(b'{"api_key": "k", "profile": "team-a"}', id="extra-field"),
]

_ONE_SELECTOR: Headers = [("X-Profile", "team-a")]


@pytest.fixture(autouse=True)
def logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Every log line at DEBUG, so "never logged" is asserted rather than assumed."""
    caplog.set_level("DEBUG")
    return caplog


async def _call(
    service: FakeConnections | None,
    method: str,
    path: str,
    sent: Headers,
    *,
    body: object = None,
    raw: bytes | None = None,
) -> httpx.Response:
    headers = [*_IDENTITY.items(), *sent]
    if raw is not None:
        headers.append(("Content-Type", "application/json"))
    async with client_for(_connections_app(service)) as client:
        return await client.request(method, path, json=body, content=raw, headers=headers)


@pytest.mark.parametrize("sent", _SELECTORS)
@pytest.mark.parametrize(("method", "path", "body"), _CONNECTION_CALLS)
async def test_connection_routes_refuse_a_selector_before_calling_the_gateway(
    method: str, path: str, body: object, sent: Headers, logs: pytest.LogCaptureFixture
) -> None:
    service = FakeConnections()

    response = await _call(service, method, path, sent, body=body)

    _assert_problem_refusal(response, sent, logs)
    assert _API_KEY not in response.text
    assert service.calls == []


@pytest.mark.parametrize("sent", _SELECTOR_LESS)
@pytest.mark.parametrize(("method", "path", "body"), _CONNECTION_CALLS)
async def test_connection_routes_treat_a_blank_selector_as_absent(
    method: str, path: str, body: object, sent: Headers
) -> None:
    service = FakeConnections()

    response = await _call(service, method, path, sent, body=body)

    assert response.status_code in {200, 201}, response.text
    ((_verb, caller, _arg),) = service.calls
    assert caller.profile is None
    assert caller.identity == _IDENTITY


# --- precedence: the refusal comes before FastAPI's body handling and the service lookup --------


@pytest.mark.parametrize("raw", _INVALID_BODIES)
async def test_the_refusal_wins_over_an_invalid_body(
    raw: bytes, logs: pytest.LogCaptureFixture
) -> None:
    service = FakeConnections()

    response = await _call(service, "PUT", "/v1/connections/openrouter", _ONE_SELECTOR, raw=raw)

    _assert_problem_refusal(response, _ONE_SELECTOR, logs)
    assert _API_KEY not in response.text
    assert service.calls == []


@pytest.mark.parametrize("sent", _SELECTOR_LESS)
@pytest.mark.parametrize("raw", _INVALID_BODIES)
async def test_without_a_selector_an_invalid_body_is_still_a_422(raw: bytes, sent: Headers) -> None:
    """The precedence test's control: the same body is refused by validation when no selector
    is stated, so the refusal above is not a 422 that happens to be spelled differently."""
    service = FakeConnections()

    response = await _call(service, "PUT", "/v1/connections/openrouter", sent, raw=raw)

    assert response.status_code == 422, response.text
    assert "code" not in response.json()
    assert _API_KEY not in response.text
    assert service.calls == []


@pytest.mark.parametrize(("method", "path", "body"), _CONNECTION_CALLS)
async def test_the_refusal_wins_over_an_unconfigured_service(
    method: str, path: str, body: object, logs: pytest.LogCaptureFixture
) -> None:
    response = await _call(None, method, path, _ONE_SELECTOR, body=body)

    _assert_problem_refusal(response, _ONE_SELECTOR, logs)


@pytest.mark.parametrize("sent", _SELECTOR_LESS)
@pytest.mark.parametrize(("method", "path", "body"), _CONNECTION_CALLS)
async def test_without_a_selector_an_unconfigured_service_is_still_a_503(
    method: str, path: str, body: object, sent: Headers
) -> None:
    response = await _call(None, method, path, sent, body=body)

    assert response.status_code == 503, response.text
