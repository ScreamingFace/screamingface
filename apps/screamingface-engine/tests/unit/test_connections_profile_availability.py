from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from screamingface_engine.config import Settings
from screamingface_engine.connections import build_connections
from screamingface_engine.connections.aigateway import AigatewayConnections
from screamingface_engine.connections.port import Caller, ConnectionBadResponse

pytestmark = pytest.mark.asyncio

ALICE = {"X-User-Email": "alice@example.com"}
BOB = {"X-User-Email": "bob@example.com"}


def _provider(provider: str, display_name: str) -> dict[str, object]:
    return {
        "object": "provider",
        "id": provider,
        "display_name": display_name,
        "auth_methods": ["api_key"],
    }


def _providers() -> dict[str, object]:
    return {
        "object": "list",
        "data": [
            _provider("anthropic", "Anthropic"),
            _provider("openrouter", "OpenRouter"),
        ],
    }


def _profile(provider: str, state: str) -> dict[str, object]:
    return {
        "id": f"private:{provider}:default",
        "account_id": "private-account",
        "provider": provider,
        "name": "default",
        "account_label": "must-not-leak@example.com",
        "state": state,
        "auth_type": "api_key",
        "defaults": {"system_prompt": "must not leak"},
    }


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
    return AigatewayConnections(client, listing_source="profiles"), seen


async def test_profile_availability_is_caller_scoped_and_secret_free() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/providers":
            return httpx.Response(200, json=_providers())
        email = request.headers["X-User-Email"]
        provider = "openrouter" if email == "alice@example.com" else "anthropic"
        return httpx.Response(200, json={"profiles": [_profile(provider, "authenticated")]})

    adapter, seen = _adapter(handler)

    alice = await adapter.list(Caller(ALICE))
    bob = await adapter.list(Caller(BOB))

    assert [(row.provider, row.status) for row in alice] == [
        ("anthropic", "not_connected"),
        ("openrouter", "connected"),
    ]
    assert [(row.provider, row.status) for row in bob] == [
        ("anthropic", "connected"),
        ("openrouter", "not_connected"),
    ]
    assert all(row.auth_method is None and row.account_label is None for row in (*alice, *bob))
    assert "private-account" not in repr((alice, bob))
    assert "must-not-leak" not in repr((alice, bob))
    assert [request.url.path for request in seen] == [
        "/v1/providers",
        "/v1/auth/profiles",
        "/v1/providers",
        "/v1/auth/profiles",
    ]


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        (("error", "pending", "authenticated"), "connected"),
        (("error", "pending"), "pending"),
        (("error",), "error"),
        ((), "not_connected"),
    ],
)
async def test_profile_state_precedence(states: tuple[str, ...], expected: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/providers":
            return httpx.Response(
                200,
                json={"object": "list", "data": [_provider("openrouter", "OpenRouter")]},
            )
        return httpx.Response(
            200,
            json={"profiles": [_profile("openrouter", state) for state in states]},
        )

    adapter, _ = _adapter(handler)

    (connection,) = await adapter.list(Caller(ALICE))

    assert connection.status == expected


async def test_profiles_for_disabled_providers_do_not_create_catalogue_rows() -> None:
    adapter, _ = _adapter(
        lambda request: httpx.Response(
            200,
            json=(
                _providers()
                if request.url.path == "/v1/providers"
                else {"profiles": [_profile("disabled-provider", "authenticated")]}
            ),
        )
    )

    rows = await adapter.list(Caller(ALICE))

    assert tuple(row.provider for row in rows) == ("anthropic", "openrouter")
    assert all(row.status == "not_connected" for row in rows)


@pytest.mark.parametrize(
    "profiles",
    [
        None,
        {},
        ["not-an-object"],
        [{"provider": "OpenRouter", "state": "authenticated"}],
        [{"provider": "openrouter", "state": "unknown"}],
    ],
)
async def test_malformed_profile_availability_is_rejected(profiles: object) -> None:
    adapter, _ = _adapter(
        lambda request: httpx.Response(
            200,
            json=(_providers() if request.url.path == "/v1/providers" else {"profiles": profiles}),
        )
    )

    with pytest.raises(ConnectionBadResponse):
        await adapter.list(Caller(ALICE))


async def test_builder_can_select_profile_availability_without_a_gateway_change() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = (
            _providers()
            if request.url.path == "/v1/providers"
            else {"profiles": [_profile("openrouter", "authenticated")]}
        )
        return httpx.Response(200, json=payload)

    def client_factory(base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=base_url,
            transport=httpx.MockTransport(handler),
        )

    adapter = build_connections(
        Settings(aigateway_base_url="http://aigateway.test"),
        listing_source="profiles",
        client_factory=client_factory,
    )
    assert adapter is not None

    rows = await adapter.list(Caller(ALICE))

    assert [(row.provider, row.status) for row in rows] == [
        ("anthropic", "not_connected"),
        ("openrouter", "connected"),
    ]
    await adapter.aclose()
