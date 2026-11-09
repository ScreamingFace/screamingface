from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from screamingface_engine.connections.aigateway import AigatewayConnections
from screamingface_engine.connections.port import (
    Caller,
    Connection,
    ConnectionAlreadyConnected,
    ConnectionBadResponse,
    ConnectionConflict,
    ConnectionMethodUnsupported,
    ConnectionRejected,
    Connections,
    ConnectionTimeout,
    ConnectionUnavailable,
    OAuthAuthorization,
)

pytestmark = pytest.mark.asyncio

IDENTITY = {"X-User-Email": "alice@example.com"}
SECRET = "sk-or-v1-unit-secret"


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[AigatewayConnections, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(
        base_url="http://aigateway.test",
        transport=httpx.MockTransport(capture),
    )
    return AigatewayConnections(client), seen


def _list(*rows: dict[str, object]) -> dict[str, object]:
    return {"connections": list(rows)}


def _providers(*rows: dict[str, object]) -> dict[str, object]:
    return {"object": "list", "data": list(rows) if rows else [_provider()]}


def _provider(
    provider: str = "openrouter",
    display_name: str = "OpenRouter",
    auth_methods: tuple[str, ...] = ("api_key",),
) -> dict[str, object]:
    return {
        "object": "provider",
        "id": provider,
        "display_name": display_name,
        "auth_methods": list(auth_methods),
    }


def _access(**statuses: str) -> dict[str, object]:
    """`GET /v1/provider-access`: the status the gateway lists per provider (OME-1138 L7b)."""
    return {"providers": [{"provider": key, "status": value} for key, value in statuses.items()]}


def _get(
    request: httpx.Request, *rows: dict[str, object], access: dict[str, str] | None = None
) -> httpx.Response:
    if request.url.path == "/v1/providers":
        payload = _providers()
    elif request.url.path == "/v1/provider-access":
        payload = _access(**(access or {}))
    else:
        payload = _list(*rows)
    return httpx.Response(200, json=payload)


def _disconnected(provider: str = "openrouter", display_name: str = "OpenRouter") -> Connection:
    return Connection(provider, display_name, ("api_key",), "not_connected")


def _row(
    *,
    connection_id: str = "00000000-0000-0000-0000-000000000001",
    status: str = "active",
    auth_type: str = "api_key",
    label: str = "screamingface",
    provider: str = "openrouter",
    account: object = None,
) -> dict[str, object]:
    return {
        "id": connection_id,
        "account_id": "00000000-0000-0000-0000-000000000099",
        "provider": provider,
        "label": label,
        "status": status,
        "auth_type": auth_type,
        "account": account,
        "credential_locator": {"service": "must-not-leak", "account": "default"},
        "created_at": "2026-07-31T00:00:00Z",
        "last_used_at": None,
        "last_refreshed_at": None,
        "error_message": None,
        "is_duplicate": False,
    }


async def test_adapter_satisfies_the_connection_port_and_advertises_openrouter() -> None:
    adapter, _ = _adapter(_get)

    assert isinstance(adapter, Connections)
    assert await adapter.list(Caller(IDENTITY)) == (_disconnected(),)


@pytest.mark.parametrize("provider", ["../../token", "openrouter/keys", "OpenRouter"])
async def test_provider_catalog_rejects_ids_that_are_not_one_path_segment(
    provider: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/providers":
            return httpx.Response(200, json=_providers(_provider(provider)))
        raise AssertionError("invalid provider catalogue reached the connection store")

    adapter, _ = _adapter(handler)

    with pytest.raises(ConnectionBadResponse):
        await adapter.list(Caller())


async def test_connected_state_is_sanitized_and_identity_is_forwarded() -> None:
    adapter, seen = _adapter(
        lambda request: _get(request, _row(), access={"openrouter": "connected"})
    )

    (connection,) = await adapter.list(Caller(IDENTITY))

    assert connection.provider == "openrouter"
    assert connection.status == "connected"
    assert connection.auth_method == "api_key"
    assert connection.account_label is None
    assert seen[0].headers["X-User-Email"] == "alice@example.com"
    assert "authorization" not in seen[0].headers
    assert "credential_locator" not in repr(connection)


async def test_oauth_account_exposes_only_the_safe_display_label() -> None:
    provider = _provider("anthropic", "Anthropic", ("oauth",))
    row = _row(
        provider="anthropic",
        auth_type="oauth",
        account={
            "sub": "provider-account-id",
            "email": " alice@example.com ",
            "name": "Alice",
            "raw": {"access_token": "must-not-leak"},
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/providers":
            return httpx.Response(200, json=_providers(provider))
        if request.url.path == "/v1/provider-access":
            return httpx.Response(200, json=_access(anthropic="connected"))
        return httpx.Response(200, json=_list(row))

    adapter, _ = _adapter(handler)

    (connection,) = await adapter.list(Caller(IDENTITY))

    assert connection.account_label == "alice@example.com"
    assert "provider-account-id" not in repr(connection)
    assert "must-not-leak" not in repr(connection)


@pytest.mark.parametrize("account", ["alice@example.com", {"email": 7}, {"name": " "}])
async def test_malformed_oauth_account_is_rejected(account: object) -> None:
    provider = _provider("anthropic", "Anthropic", ("oauth",))
    row = _row(provider="anthropic", auth_type="oauth", account=account)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _providers(provider) if request.url.path == "/v1/providers" else _list(row)
        return httpx.Response(200, json=payload)

    adapter, _ = _adapter(handler)

    with pytest.raises(ConnectionBadResponse):
        await adapter.list(Caller())


async def test_connect_creates_a_validated_connection_without_leaking_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: PLR0911
        if request.method == "GET":
            return _get(request, access={"openrouter": "connected"})
        assert request.url.path == "/v1/oauth/connections/api-key"
        assert json.loads(request.content) == {
            "provider": "openrouter",
            "label": "screamingface",
            "api_key": SECRET,
        }
        return httpx.Response(201, json=_row())

    adapter, seen = _adapter(handler)

    connection = await adapter.connect(Caller(IDENTITY), "openrouter", SECRET)

    assert connection.status == "connected"
    assert SECRET not in repr(connection)
    assert SECRET not in str(seen[-1].url)


async def test_start_oauth_creates_a_sanitized_authorization() -> None:
    provider = _provider("anthropic", "Anthropic", ("api_key", "oauth"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/providers":
            return httpx.Response(200, json=_providers(provider))
        if request.method == "GET":
            return httpx.Response(200, json=_list())
        assert request.method == "POST"
        assert request.url.path == "/v1/oauth/connections"
        assert json.loads(request.content) == {
            "provider": "anthropic",
            "label": "screamingface",
        }
        return httpx.Response(
            201,
            json={
                "connection_id": "00000000-0000-0000-0000-000000000001",
                "authorize_url": "https://claude.example/authorize?state=private",
                "state": "must-not-leak",
                "expires_in": 600,
            },
        )

    adapter, _ = _adapter(handler)

    authorization = await adapter.start_oauth(Caller(IDENTITY), "anthropic")

    assert authorization == OAuthAuthorization(
        provider="anthropic",
        authorize_url="https://claude.example/authorize?state=private",
        expires_in=600,
    )
    assert "must-not-leak" not in repr(authorization)


async def test_start_oauth_rejects_an_unbounded_authorization_lifetime() -> None:
    provider = _provider("anthropic", "Anthropic", ("oauth",))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/providers":
            return httpx.Response(200, json=_providers(provider))
        if request.method == "GET":
            return httpx.Response(200, json=_list())
        return httpx.Response(
            201,
            json={
                "connection_id": "00000000-0000-0000-0000-000000000001",
                "authorize_url": "https://claude.example/authorize",
                "state": "private",
                "expires_in": 1801,
            },
        )

    adapter, _ = _adapter(handler)

    with pytest.raises(ConnectionBadResponse):
        await adapter.start_oauth(Caller(), "anthropic")


async def test_start_oauth_rejects_a_malformed_authorization_url() -> None:
    provider = _provider("anthropic", "Anthropic", ("oauth",))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/providers":
            return httpx.Response(200, json=_providers(provider))
        if request.method == "GET":
            return httpx.Response(200, json=_list())
        return httpx.Response(
            201,
            json={
                "connection_id": "00000000-0000-0000-0000-000000000001",
                "authorize_url": "https://[malformed",
                "state": "private",
                "expires_in": 600,
            },
        )

    adapter, _ = _adapter(handler)

    with pytest.raises(ConnectionBadResponse):
        await adapter.start_oauth(Caller(), "anthropic")


@pytest.mark.parametrize(
    "authorize_url",
    ["https://provider.example:bad/authorize", "https://provider.example:99999/authorize"],
)
async def test_start_oauth_rejects_an_invalid_authorization_port(
    authorize_url: str,
) -> None:
    provider = _provider("anthropic", "Anthropic", ("oauth",))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/providers":
            return httpx.Response(200, json=_providers(provider))
        if request.method == "GET":
            return httpx.Response(200, json=_list())
        return httpx.Response(
            201,
            json={
                "connection_id": "00000000-0000-0000-0000-000000000001",
                "authorize_url": authorize_url,
                "state": "private",
                "expires_in": 600,
            },
        )

    adapter, _ = _adapter(handler)

    with pytest.raises(ConnectionBadResponse):
        await adapter.start_oauth(Caller(), "anthropic")


async def test_start_oauth_requires_explicit_disconnect_of_a_managed_connection() -> None:
    provider = _provider("anthropic", "Anthropic", ("oauth",))
    existing = _row(provider="anthropic", auth_type="oauth")
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/providers":
            return httpx.Response(200, json=_providers(provider))
        if request.method == "GET":
            return httpx.Response(200, json=_list(existing))
        methods.append(request.method)
        raise AssertionError("OAuth replacement must not mutate a connected provider")

    adapter, _ = _adapter(handler)

    with pytest.raises(ConnectionAlreadyConnected):
        await adapter.start_oauth(Caller(), "anthropic")

    assert methods == []


async def test_connect_does_not_adopt_a_single_unmanaged_api_key_connection() -> None:
    existing = _row(label="research")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _get(request, existing, access={"openrouter": "connected"})
        assert request.method == "POST"
        assert request.url.path == "/v1/oauth/connections/api-key"
        assert json.loads(request.content) == {
            "provider": "openrouter",
            "label": "screamingface",
            "api_key": SECRET,
        }
        return httpx.Response(201, json=_row())

    adapter, _ = _adapter(handler)

    assert (await adapter.connect(Caller(), "openrouter", SECRET)).status == "connected"


async def test_connect_replaces_only_the_existing_managed_api_key_connection() -> None:
    existing = _row()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _get(request, existing, access={"openrouter": "connected"})
        assert request.method == "PUT"
        assert request.url.path.endswith("/00000000-0000-0000-0000-000000000001/api-key")
        assert json.loads(request.content) == {"api_key": SECRET}
        return httpx.Response(200, json=existing)

    adapter, _ = _adapter(handler)

    assert (await adapter.connect(Caller(), "openrouter", SECRET)).status == "connected"


async def test_connect_requires_disconnect_before_replacing_oauth_with_an_api_key() -> None:
    provider = _provider("openrouter", "OpenRouter", ("api_key", "oauth"))
    existing = _row(auth_type="oauth")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/providers":
            return httpx.Response(200, json=_providers(provider))
        if request.method == "GET":
            return httpx.Response(200, json=_list(existing))
        raise AssertionError("the API key must not leave the Engine before explicit disconnect")

    adapter, seen = _adapter(handler)

    with pytest.raises(ConnectionAlreadyConnected):
        await adapter.connect(Caller(), "openrouter", SECRET)

    assert all(SECRET not in request.content.decode(errors="ignore") for request in seen)


@pytest.mark.parametrize(
    ("status_code", "status", "auth_type"),
    [(202, "active", "api_key"), (201, "pending", "api_key"), (201, "active", "oauth")],
)
async def test_connect_rejects_an_incorrect_success_response(
    status_code: int,
    status: str,
    auth_type: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _get(request)
        return httpx.Response(
            status_code,
            json=_row(status=status, auth_type=auth_type),
        )

    adapter, _ = _adapter(handler)

    with pytest.raises(ConnectionBadResponse):
        await adapter.connect(Caller(), "openrouter", SECRET)


async def test_multiple_unmanaged_rows_leave_the_automatic_row_disconnected() -> None:
    rows = [
        _row(connection_id="00000000-0000-0000-0000-000000000001", label="one"),
        _row(connection_id="00000000-0000-0000-0000-000000000002", label="two"),
    ]

    adapter, _ = _adapter(lambda request: _get(request, *rows))

    assert await adapter.list(Caller()) == (_disconnected(),)


async def test_managed_row_is_selected_without_mutating_unmanaged_rows() -> None:
    rows = [
        _row(connection_id="00000000-0000-0000-0000-000000000001", label="research"),
        _row(connection_id="00000000-0000-0000-0000-000000000002"),
    ]

    adapter, _ = _adapter(lambda request: _get(request, *rows, access={"openrouter": "connected"}))

    (connection,) = await adapter.list(Caller())
    assert connection.status == "connected"


async def test_multiple_managed_rows_are_a_conflict() -> None:
    rows = [
        _row(connection_id="00000000-0000-0000-0000-000000000001"),
        _row(connection_id="00000000-0000-0000-0000-000000000002"),
    ]
    adapter, _ = _adapter(lambda request: _get(request, *rows))

    with pytest.raises(ConnectionConflict):
        await adapter.list(Caller())


async def test_disconnect_never_deletes_an_unmanaged_connection() -> None:
    existing = _row(label="research")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            raise AssertionError("disconnect must not mutate an unmanaged Gateway row")
        return _get(request, existing)

    adapter, seen = _adapter(handler)

    assert (await adapter.disconnect(Caller(), "openrouter")).status == "not_connected"
    assert all(request.method == "GET" for request in seen)


async def test_disconnect_is_idempotent_and_removes_the_selected_connection() -> None:
    rows = [_row()]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _get(request, *rows)
        assert request.method == "DELETE"
        rows.clear()
        return httpx.Response(204)

    adapter, seen = _adapter(handler)

    assert (await adapter.disconnect(Caller(), "openrouter")).status == "not_connected"
    assert (await adapter.disconnect(Caller(), "openrouter")).status == "not_connected"
    assert [request.method for request in seen].count("DELETE") == 1


async def test_disconnect_is_idempotent_when_a_concurrent_delete_wins() -> None:
    existing = _row()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _get(request, existing)
        return httpx.Response(404, json={"detail": {"code": "connection_not_found"}})

    adapter, _ = _adapter(handler)

    connection = await adapter.disconnect(Caller(), "openrouter")
    assert connection.status == "not_connected"


@pytest.mark.parametrize("status", [401, 403])
async def test_caller_authentication_rejection_is_typed(status: int) -> None:
    adapter, _ = _adapter(lambda _: httpx.Response(status, json={"detail": "private"}))

    with pytest.raises(ConnectionRejected):
        await adapter.list(Caller(IDENTITY))


@pytest.mark.parametrize("status", [400, 422])
async def test_invalid_key_failure_is_sanitized(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _get(request)
        return httpx.Response(
            status,
            json={"detail": {"code": "invalid_api_key", "message": SECRET}},
        )

    adapter, _ = _adapter(handler)

    with pytest.raises(ConnectionRejected) as failure:
        await adapter.connect(Caller(), "openrouter", SECRET)

    assert SECRET not in str(failure.value)


async def test_malformed_upstream_response_is_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/providers":
            return httpx.Response(200, json=_providers())
        return httpx.Response(200, json={"connections": [_row(status="x")]})

    adapter, _ = _adapter(handler)

    with pytest.raises(ConnectionBadResponse):
        await adapter.list(Caller())


async def test_non_string_provider_auth_method_is_typed() -> None:
    malformed = _provider()
    malformed["auth_methods"] = [{}]
    adapter, _ = _adapter(lambda request: httpx.Response(200, json=_providers(malformed)))

    with pytest.raises(ConnectionBadResponse):
        await adapter.list(Caller())


async def test_unhashable_connection_status_is_typed() -> None:
    adapter, _ = _adapter(lambda request: _get(request, _row(status=[])))  # type: ignore[arg-type]

    with pytest.raises(ConnectionBadResponse):
        await adapter.list(Caller())


async def test_non_uuid_connection_id_is_rejected_before_it_can_enter_a_request_path() -> None:
    adapter, _ = _adapter(lambda request: _get(request, _row(connection_id="../token")))

    with pytest.raises(ConnectionBadResponse):
        await adapter.disconnect(Caller(), "openrouter")


async def test_timeout_is_typed_and_secret_safe() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(SECRET, request=request)

    adapter, _ = _adapter(timeout)

    with pytest.raises(ConnectionTimeout) as failure:
        await adapter.connect(Caller(), "openrouter", SECRET)

    assert SECRET not in str(failure.value)


async def test_lists_every_provider_and_keeps_credentials_provider_scoped() -> None:
    providers = _providers(
        _provider(),
        _provider("anthropic", "Anthropic", ("api_key", "oauth")),
        _provider("codex", "Codex", ("oauth",)),
    )
    rows = [_row(provider="anthropic", auth_type="oauth")]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/providers":
            return httpx.Response(200, json=providers)
        if request.url.path == "/v1/provider-access":
            return httpx.Response(200, json=_access(anthropic="connected"))
        return httpx.Response(200, json=_list(*rows))

    adapter, _ = _adapter(handler)
    connections = await adapter.list(Caller())

    assert [(item.provider, item.status) for item in connections] == [
        ("openrouter", "not_connected"),
        ("anthropic", "connected"),
        ("codex", "not_connected"),
    ]
    assert connections[1].auth_methods == ("api_key", "oauth")


async def test_api_key_connect_rejects_an_oauth_only_provider_before_sending_a_secret() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_providers(_provider("codex", "Codex", ("oauth",))))

    adapter, _ = _adapter(handler)
    with pytest.raises(ConnectionMethodUnsupported):
        await adapter.connect(Caller(), "codex", SECRET)

    assert [request.url.path for request in seen] == ["/v1/providers"]


async def test_connection_refusal_is_reported_as_gateway_unavailable() -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(SECRET, request=request)

    adapter, _ = _adapter(refused)

    with pytest.raises(ConnectionUnavailable) as failure:
        await adapter.list(Caller())

    assert failure.value.status == 503
    assert failure.value.detail == "AI Gateway is unavailable"
    assert SECRET not in str(failure.value)
