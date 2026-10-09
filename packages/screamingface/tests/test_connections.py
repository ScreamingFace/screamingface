from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

import httpx
import pytest

import screamingface as sf
from screamingface import _default_client

SECRET = "sk-or-v1-client-test-secret"


def _row(
    *,
    status: str = "not_connected",
    auth_method: str | None = None,
    auth_methods: list[str] | None = None,
) -> dict[str, object]:
    return {
        "object": "connection",
        "provider": "openrouter",
        "display_name": "OpenRouter",
        "auth_methods": auth_methods or ["api_key"],
        "status": status,
        "auth_method": auth_method,
        "account_label": None,
    }


def _list(row: dict[str, object] | None = None) -> dict[str, object]:
    return {"object": "list", "data": [row or _row()]}


def _oauth(provider: str = "anthropic") -> dict[str, object]:
    return {
        "object": "oauth_authorization",
        "provider": provider,
        "authorize_url": "https://provider.example/authorize?state=private",
        "expires_in": 600,
    }


def _sync_client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(handler),
    )


def _async_client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.AsyncClient:
    return sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(handler),
    )


def test_explicit_client_lists_gets_connects_and_disconnects() -> None:
    connected = False
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal connected
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json=_list(_row(status="connected", auth_method="api_key"))
                if connected
                else _list(),
            )
        if request.method == "PUT":
            assert request.url.path == "/v1/connections/openrouter"
            assert json.loads(request.content) == {"api_key": SECRET}
            connected = True
            return httpx.Response(200, json=_row(status="connected", auth_method="api_key"))
        if request.method == "DELETE":
            connected = False
            return httpx.Response(200, json=_row())
        raise AssertionError(f"unexpected request {request.method}")

    with _sync_client(handler) as client:
        assert client.connections.list() == (
            sf.Connection(
                provider="openrouter",
                display_name="OpenRouter",
                auth_methods=("api_key",),
                status="not_connected",
                auth_method=None,
                account_label=None,
            ),
        )
        assert client.connections.get("openrouter").status == "not_connected"
        assert client.connect("openrouter", api_key=SECRET).status == "connected"
        assert client.connections.get("openrouter").status == "connected"
        assert client.disconnect("openrouter").status == "not_connected"

    assert SECRET not in repr(client.connections)
    assert all(SECRET not in str(request.url) for request in calls)


@pytest.mark.parametrize("provider", ["../../token", "openrouter/keys", "openrouter?admin=1"])
def test_provider_name_cannot_steer_a_connection_request(provider: str) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        raise AssertionError(f"invalid provider reached {request.url}")

    with _sync_client(handler) as client, pytest.raises(ValueError, match="provider"):
        client.connect(provider, api_key=SECRET)

    assert called is False


def test_engine_cannot_advertise_a_provider_that_is_not_one_path_segment() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_list({**_row(), "provider": "../../token"}))

    with (
        _sync_client(handler) as client,
        pytest.raises(
            sf.ProviderConnectionError,
            match="provider",
        ) as caught,
    ):
        client.connections.list()

    assert caught.value.code == "invalid_connection_response"


def test_sync_oauth_flow_starts_waits_and_cancels_through_the_engine() -> None:
    polls = 0
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal polls
        calls.append(request)
        if request.method == "POST":
            assert request.url.path == "/v1/connections/anthropic/oauth"
            return httpx.Response(201, json=_oauth())
        if request.method == "DELETE":
            return httpx.Response(
                200,
                json={
                    **_row(auth_methods=["api_key", "oauth"]),
                    "provider": "anthropic",
                    "display_name": "Anthropic",
                },
            )
        polls += 1
        status = "pending" if polls == 1 else "connected"
        return httpx.Response(
            200,
            json=_list(
                {
                    **_row(
                        status=status,
                        auth_method="oauth",
                        auth_methods=["api_key", "oauth"],
                    ),
                    "provider": "anthropic",
                    "display_name": "Anthropic",
                    "account_label": "alice@example.com" if status == "connected" else None,
                }
            ),
        )

    with _sync_client(handler) as client:
        flow = client.connect("anthropic", method="oauth")
        assert isinstance(flow, sf.OAuthFlow)
        assert flow.provider == "anthropic"
        assert flow.authorize_url.startswith("https://provider.example/")
        assert flow.wait(poll_interval=0).status == "connected"
        flow.cancel()

    assert [request.method for request in calls] == ["POST", "GET", "GET", "DELETE"]


def test_oauth_flow_wait_has_a_caller_controlled_deadline() -> None:
    pending = sf.Connection(
        provider="anthropic",
        display_name="Anthropic",
        auth_methods=("oauth",),
        status="pending",
        auth_method="oauth",
        account_label=None,
    )
    flow = sf.OAuthFlow(
        provider="anthropic",
        authorize_url="https://provider.example/authorize",
        expires_in=600,
        _get=lambda: pending,
        _expires_at=10**12,
    )

    with pytest.raises(sf.ProviderConnectionError) as caught:
        flow.wait(timeout=0.01, poll_interval=0.001)

    assert caught.value.code == "oauth_authorization_timeout"
    assert caught.value.permanent is False


def test_engine_cannot_advertise_an_unbounded_oauth_lifetime() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={**_oauth(), "expires_in": 1801})

    with _sync_client(handler) as client, pytest.raises(sf.ProviderConnectionError) as caught:
        client.connect("anthropic", method="oauth")

    assert caught.value.code == "invalid_connection_response"
    assert "between 1 and 1800" in str(caught.value)


@pytest.mark.asyncio
async def test_async_oauth_flow_has_async_wait_and_cancel() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json=_oauth())
        if request.method == "DELETE":
            return httpx.Response(
                200,
                json={
                    **_row(auth_methods=["oauth"]),
                    "provider": "anthropic",
                    "display_name": "Anthropic",
                },
            )
        return httpx.Response(
            200,
            json=_list(
                {
                    **_row(status="connected", auth_method="oauth", auth_methods=["oauth"]),
                    "provider": "anthropic",
                    "display_name": "Anthropic",
                }
            ),
        )

    async with _async_client(handler) as client:
        flow = await client.connect("anthropic", method="oauth")
        assert isinstance(flow, sf.AsyncOAuthFlow)
        assert (await flow.wait(poll_interval=0)).status == "connected"
        await flow.cancel()


@pytest.mark.asyncio
async def test_async_client_has_the_same_connection_operations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=_list())
        if request.method == "PUT":
            return httpx.Response(200, json=_row(status="connected", auth_method="api_key"))
        return httpx.Response(200, json=_row())

    async with _async_client(handler) as client:
        assert (await client.connections.list())[0].provider == "openrouter"
        assert (await client.connections.get("openrouter")).status == "not_connected"
        assert (await client.connect("openrouter", api_key=SECRET)).status == "connected"
        assert (await client.disconnect("openrouter")).status == "not_connected"


def test_module_functions_delegate_to_the_lazy_default_client(monkeypatch: Any) -> None:
    disconnected = sf.Connection(
        provider="openrouter",
        display_name="OpenRouter",
        auth_methods=("api_key",),
        status="not_connected",
        auth_method=None,
        account_label=None,
    )
    calls: list[tuple[str, object]] = []

    class Connections:
        def list(self) -> tuple[sf.Connection, ...]:
            calls.append(("list", None))
            return (disconnected,)

        def get(self, provider: str) -> sf.Connection:
            calls.append(("get", provider))
            return disconnected

    class FakeClient:
        engine_url = "https://engine.example"
        authenticated = True
        connections = Connections()

        def connect(
            self,
            provider: str,
            *,
            api_key: str | None = None,
            method: str | None = None,
        ) -> sf.Connection:
            assert api_key is not None
            assert method is None
            calls.append(("connect", (provider, api_key)))
            return disconnected

        def disconnect(self, provider: str) -> sf.Connection:
            calls.append(("disconnect", provider))
            return disconnected

    monkeypatch.setattr(_default_client, "_client", FakeClient())

    assert sf.connections.list() == (disconnected,)
    assert sf.connections.get("openrouter") == disconnected
    assert sf.connect("openrouter", api_key=SECRET) == disconnected
    assert sf.disconnect("openrouter") == disconnected
    panel = sf.connect()
    assert panel.engine == "https://engine.example"
    assert panel.connections == (disconnected,)
    assert [name for name, _ in calls] == ["list", "get", "connect", "disconnect", "list"]

    monkeypatch.setattr(_default_client, "_client", None)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"object": "wrong", "data": []},
        {"object": "list", "data": "wrong"},
        {"object": "list", "data": [_row(status="unknown")]},
        {"object": "list", "data": [_row(), _row()]},
        {"object": "list", "data": [{**_row(), "private": "must reject"}]},
    ],
)
def test_connection_catalog_rejects_malformed_payloads(payload: object) -> None:
    client = _sync_client(lambda _: httpx.Response(200, json=payload))

    with client, pytest.raises(sf.ProviderConnectionError) as failure:
        client.connections.list()

    assert failure.value.code == "invalid_connection_response"


def test_engine_failures_are_safe_and_typed() -> None:
    client = _sync_client(
        lambda _: httpx.Response(
            401,
            json={
                "type": "about:blank",
                "title": "Unauthorized",
                "status": 401,
                "detail": "upstream body " + SECRET,
            },
        )
    )

    with client, pytest.raises(sf.ProviderConnectionError) as failure:
        client.connect("openrouter", api_key=SECRET)

    assert failure.value.status == 401
    assert failure.value.code == "connection_rejected"
    assert SECRET not in str(failure.value)


@pytest.mark.parametrize(
    ("status", "code", "message", "retryable"),
    [
        (
            400,
            "connection_method_unsupported",
            "The provider does not support API-key connections",
            False,
        ),
        (404, "unknown_provider", "The provider is not available on this SF Engine", False),
        (409, "connection_conflict", "The provider connection is ambiguous in AI Gateway", False),
        (
            429,
            "connection_rate_limited",
            "Provider connection requests are temporarily rate limited",
            True,
        ),
        (502, "connection_gateway_bad_response", "AI Gateway returned an unusable response", True),
        (503, "connection_gateway_unavailable", "AI Gateway is unavailable", True),
        (504, "connection_gateway_timeout", "AI Gateway did not respond in time", True),
        (
            500,
            "connection_engine_error",
            "SF Engine provider connection failed with HTTP 500",
            True,
        ),
    ],
)
def test_engine_failure_statuses_have_stable_retry_semantics(
    status: int,
    code: str,
    message: str,
    retryable: bool,
) -> None:
    client = _sync_client(lambda _: httpx.Response(status))

    with client, pytest.raises(sf.ProviderConnectionError) as failure:
        client.connections.get("openrouter")

    assert failure.value.status == status
    assert failure.value.code == code
    assert str(failure.value) == message
    assert failure.value.retryable is retryable


def test_unreachable_engine_has_a_dedicated_actionable_error() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private socket detail", request=request)

    client = _sync_client(unreachable)

    with client, pytest.raises(sf.EngineUnavailableError) as failure:
        client.connections.list()

    assert failure.value.engine_url == "https://engine.example"
    assert failure.value.code == "engine_unreachable"
    assert "Check that the configured SF Engine is running" in failure.value.user_message
    assert "private socket detail" not in failure.value.user_message


@pytest.mark.asyncio
async def test_async_unreachable_engine_has_the_same_actionable_error() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private socket detail", request=request)

    async with _async_client(unreachable) as client:
        with pytest.raises(sf.EngineUnavailableError) as failure:
            await client.connections.list()

    assert failure.value.engine_url == "https://engine.example"
    assert "Check that the configured SF Engine is running" in failure.value.user_message


def test_connection_values_are_immutable_and_strict() -> None:
    value = sf.Connection(
        provider="openrouter",
        display_name="OpenRouter",
        auth_methods=("api_key",),
        status="connected",
        auth_method="api_key",
        account_label=None,
    )

    with pytest.raises(AttributeError):
        setattr(value, "status", "error")
    with pytest.raises(ValueError, match="not advertised"):
        sf.Connection("openrouter", "OpenRouter", ("api_key",), "connected", "oauth", None)
    with pytest.raises(ValueError, match="non-empty"):
        _sync_client(lambda _: httpx.Response(200, json=_row())).connect(
            "openrouter",
            api_key=" ",
        )
    with pytest.raises(ValueError, match="provider and display_name"):
        sf.Connection(" ", "OpenRouter", ("api_key",), "connected", "api_key", None)
    with pytest.raises(ValueError, match="unsupported method"):
        sf.Connection(
            "openrouter",
            "OpenRouter",
            cast(Any, ("oauth2",)),
            "connected",
            None,
            None,
        )
    with pytest.raises(ValueError, match="account_label"):
        sf.Connection("openrouter", "OpenRouter", ("api_key",), "connected", None, " ")


def test_connection_response_must_be_json() -> None:
    client = _sync_client(lambda _: httpx.Response(200, content=b"not-json"))

    with client, pytest.raises(sf.ProviderConnectionError) as failure:
        client.connections.list()

    assert failure.value.code == "invalid_connection_response"


@pytest.mark.parametrize(
    "row",
    [
        {**_row(), "auth_methods": []},
        {**_row(), "provider": " "},
        {**_row(), "account_label": " "},
    ],
)
def test_connection_values_reject_invalid_identity_fields(row: dict[str, object]) -> None:
    client = _sync_client(lambda _: httpx.Response(200, json=_list(row)))

    with client, pytest.raises(sf.ProviderConnectionError) as failure:
        client.connections.list()

    assert failure.value.code == "invalid_connection_response"


def test_connection_lookup_and_mutation_validate_provider_identity() -> None:
    client = _sync_client(lambda _: httpx.Response(200, json=_list()))

    with client:
        with pytest.raises(sf.ProviderConnectionError, match="does not advertise"):
            client.connections.get("anthropic")
        with pytest.raises(ValueError, match="provider must be"):
            client.connections.get(" ")


def test_connection_response_must_match_the_requested_provider() -> None:
    client = _sync_client(lambda _: httpx.Response(200, json=_row()))

    with client, pytest.raises(sf.ProviderConnectionError) as failure:
        client.connections.connect("anthropic", SECRET)

    assert failure.value.code == "invalid_connection_response"


def test_provider_keys_require_https_outside_loopback() -> None:
    client = sf.Client(engine_url="http://engine.example")

    with client, pytest.raises(sf.ProviderConnectionError) as failure:
        client.connect("openrouter", api_key=SECRET)

    assert failure.value.code == "secure_transport_required"


def test_connection_catalog_decodes_unavailable_distinct_from_error() -> None:
    # FEATURE (OME-1250, step 1 of 2): `unavailable` = the credential authenticates but cannot
    # be served right now (402 / quota); `error` = the credential was rejected. The SDK must
    # accept the new value before the gateway emits it, and keep the two apart.
    rows = [
        _row(status="unavailable"),
        {**_row(status="error"), "provider": "anthropic", "display_name": "Anthropic"},
    ]
    client = _sync_client(lambda _: httpx.Response(200, json={"object": "list", "data": rows}))

    with client:
        listed = client.connections.list()

    assert [(row.provider, row.status) for row in listed] == [
        ("openrouter", "unavailable"),
        ("anthropic", "error"),
    ]


def test_an_unknown_status_beyond_unavailable_is_still_refused() -> None:
    # INVARIANT (owner decision 2026-10-02, STRICT): one new value, no lenient decoder.
    client = _sync_client(lambda _: httpx.Response(200, json=_list(_row(status="degraded"))))

    with client, pytest.raises(sf.ProviderConnectionError) as failure:
        client.connections.list()

    assert failure.value.code == "invalid_connection_response"
