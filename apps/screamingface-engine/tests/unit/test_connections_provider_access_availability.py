"""Hosted provider availability read from the gateway's provider-access successor.

# FEATURE: OME-1138 Stage A4, Engine half (OME-1245). The Hosted Engine reads
# `GET /v1/provider-access` after the provider catalogue instead of aggregating the legacy
# `GET /v1/auth/profiles` body locally, and the `listing_source` switch gives way to the D15
# explicit mutability rule (Hosted `mutable=False`, Local `mutable=True`).
# AIDEV-NOTE: this suite re-expresses `test_connections_profile_availability.py` at the successor
# seam (owner decision F-A4-1, 2026-09-21). Every expectation of that suite is carried over —
# caller scoping, secret-freedom, per-fixture status equality, rows outside the catalogue,
# malformed bodies, builder selection, additive fields, mutation refusal, the required keyword at
# the composition seam — and the legacy listing is asserted to be never requested.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields
from inspect import Parameter, signature

import httpx
import pytest

from screamingface_engine.config import Settings
from screamingface_engine.connections import build_connections
from screamingface_engine.connections.aigateway import AigatewayConnections
from screamingface_engine.connections.port import (
    Caller,
    Connection,
    ConnectionBadResponse,
    ConnectionMethodUnsupported,
    ConnectionUnavailable,
)
from screamingface_engine.rest.connections import ConnectionResponse

pytestmark = pytest.mark.asyncio

ALICE = {"X-User-Email": "alice@example.com"}
BOB = {"X-User-Email": "bob@example.com"}
TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
PROVIDERS_PATH = "/v1/providers"
AVAILABILITY_PATH = "/v1/provider-access"
LEGACY_PROFILES_PATH = "/v1/auth/profiles"
LOCAL_ROWS_PATH = "/v1/oauth/connections"


def _provider(provider: str, display_name: str) -> dict[str, object]:
    return {
        "object": "provider",
        "id": provider,
        "display_name": display_name,
        "auth_methods": ["api_key"],
    }


def _providers(*rows: dict[str, object]) -> dict[str, object]:
    return {
        "object": "list",
        "data": list(rows)
        or [_provider("anthropic", "Anthropic"), _provider("openrouter", "OpenRouter")],
    }


def _availability(*rows: tuple[str, str]) -> dict[str, object]:
    return {"providers": [{"provider": provider, "status": status} for provider, status in rows]}


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    mutable: bool = False,
) -> tuple[AigatewayConnections, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        # INVARIANT: the legacy Profile listing is no longer an Engine dependency on any path.
        assert request.url.path != LEGACY_PROFILES_PATH, "the Engine reached the legacy listing"
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(
        base_url="http://aigateway.test",
        transport=httpx.MockTransport(capture),
    )
    return AigatewayConnections(client, mutable=mutable), seen


def _gateway(availability: object) -> Callable[[httpx.Request], httpx.Response]:
    """A gateway serving the two-provider catalogue and one availability answer."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == PROVIDERS_PATH:
            return httpx.Response(200, json=_providers())
        assert request.url.path == AVAILABILITY_PATH, request.url.path
        if isinstance(availability, httpx.Response):
            return availability
        return httpx.Response(200, json=availability)

    return handler


async def test_hosted_availability_is_caller_scoped_and_secret_free() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == PROVIDERS_PATH:
            return httpx.Response(200, json=_providers())
        email = request.headers["X-User-Email"]
        provider = "openrouter" if email == "alice@example.com" else "anthropic"
        return httpx.Response(200, json=_availability((provider, "connected")))

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
    assert [request.url.path for request in seen] == [
        PROVIDERS_PATH,
        AVAILABILITY_PATH,
        PROVIDERS_PATH,
        AVAILABILITY_PATH,
    ]


async def test_the_availability_request_carries_identity_and_trace_but_no_selector() -> None:
    adapter, seen = _adapter(_gateway(_availability(("openrouter", "connected"))))

    await adapter.list(Caller(ALICE, traceparent=TRACEPARENT, profile="team"))

    catalogue, availability = seen
    # WHY: `X-Profile` is non-selecting on the successor (D17), so it is not forwarded on that
    # one request. The catalogue call is outside this unit and keeps today's carrier behaviour.
    assert catalogue.headers["X-Profile"] == "team"
    assert "X-Profile" not in availability.headers
    assert availability.headers["X-User-Email"] == "alice@example.com"
    assert availability.headers["traceparent"] == TRACEPARENT


@pytest.mark.parametrize(
    ("published", "expected"),
    [
        ("connected", "connected"),
        ("pending", "pending"),
        ("error", "error"),
        ("needs_reauth", "needs_reauth"),
        ("not_connected", "not_connected"),
    ],
)
async def test_published_statuses_reach_the_catalogue_row_unchanged(
    published: str,
    expected: str,
) -> None:
    # INVARIANT (per-fixture equality, A4 acceptance): the prior suite's fixtures — Profiles in
    # states error+pending+authenticated → connected, error+pending → pending, error → error,
    # none → not_connected — are folded by the gateway now (A3 golden equivalence) and arrive as
    # one published status per provider. The Engine passes that status through unchanged.
    adapter, _ = _adapter(_gateway(_availability(("openrouter", published))))

    rows = await adapter.list(Caller(ALICE))

    assert [(row.provider, row.status) for row in rows] == [
        ("anthropic", "not_connected"),
        ("openrouter", expected),
    ]


async def test_rows_outside_the_catalogue_create_no_connection() -> None:
    adapter, _ = _adapter(_gateway(_availability(("disabled-provider", "connected"))))

    rows = await adapter.list(Caller(ALICE))

    assert tuple(row.provider for row in rows) == ("anthropic", "openrouter")
    assert all(row.status == "not_connected" for row in rows)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"providers": None},
        {"providers": {}},
        {"providers": ["not-an-object"]},
        {"providers": [{"provider": "OpenRouter", "status": "connected"}]},
        {"providers": [{"provider": "openrouter", "status": "authenticated"}]},
        {"providers": [{"provider": "openrouter"}]},
        {
            "providers": [
                {"provider": "openrouter", "status": "connected"},
                {"provider": "openrouter", "status": "error"},
            ]
        },
    ],
    ids=[
        "no-providers-key",
        "providers-null",
        "providers-not-a-list",
        "row-not-an-object",
        "invalid-provider-id",
        "legacy-profile-state-vocabulary",
        "missing-status",
        "duplicate-provider-rows",
    ],
)
async def test_a_malformed_availability_body_is_a_bad_gateway_response(body: object) -> None:
    # INVARIANT: a malformed body is refused, never guessed (design: "a bad response, 502").
    adapter, _ = _adapter(_gateway(body))

    with pytest.raises(ConnectionBadResponse) as failure:
        await adapter.list(Caller(ALICE))

    assert failure.value.status == 502


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(200, content=b"<html>not json</html>"), ConnectionBadResponse),
        (httpx.Response(200, json=["not", "an", "object"]), ConnectionBadResponse),
        (httpx.Response(500, json={"detail": "boom"}), ConnectionBadResponse),
        (httpx.Response(503, json={"detail": "down"}), ConnectionUnavailable),
    ],
    ids=["not-json", "not-an-object", "upstream-500", "upstream-503"],
)
async def test_availability_failures_follow_the_existing_gateway_failure_semantics(
    response: httpx.Response,
    expected: type[Exception],
) -> None:
    adapter, _ = _adapter(_gateway(response))

    with pytest.raises(expected):
        await adapter.list(Caller(ALICE))


async def test_builder_selects_the_hosted_listing_for_an_immutable_adapter() -> None:
    def client_factory(base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=base_url,
            transport=httpx.MockTransport(_gateway(_availability(("openrouter", "connected")))),
        )

    adapter = build_connections(
        Settings(aigateway_base_url="http://aigateway.test"),
        mutable=False,
        client_factory=client_factory,
    )
    assert adapter is not None

    rows = await adapter.list(Caller(ALICE))

    assert [(row.provider, row.status) for row in rows] == [
        ("anthropic", "not_connected"),
        ("openrouter", "connected"),
    ]
    await adapter.aclose()


async def test_additive_envelope_and_row_fields_are_tolerated_and_never_surface() -> None:
    body = {
        "object": "list",
        "providers": [
            {
                "provider": "openrouter",
                "status": "connected",
                "account_label": "must-not-leak@example.com",
            }
        ],
        "has_more": False,
    }
    adapter, _ = _adapter(_gateway(body))

    rows = await adapter.list(Caller(ALICE))

    assert [(row.provider, row.status) for row in rows] == [
        ("anthropic", "not_connected"),
        ("openrouter", "connected"),
    ]
    assert all(row.auth_method is None and row.account_label is None for row in rows)
    assert "must-not-leak" not in repr(rows)


@pytest.mark.parametrize("operation", ["connect", "start_oauth", "disconnect"])
async def test_hosted_mutations_are_rejected_before_gateway_io(operation: str) -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"hosted mutation reached AI Gateway: {request.method} {request.url}")

    adapter, seen = _adapter(unexpected)

    with pytest.raises(ConnectionMethodUnsupported) as failure:
        if operation == "connect":
            await adapter.connect(Caller(ALICE), "openrouter", "must-not-be-sent")
        elif operation == "start_oauth":
            await adapter.start_oauth(Caller(ALICE), "openrouter")
        else:
            await adapter.disconnect(Caller(ALICE), "openrouter")

    assert failure.value.status == 400
    assert seen == []
    assert "must-not-be-sent" not in str(failure.value)


async def test_an_explicitly_mutable_adapter_keeps_the_local_listing_and_its_mutations() -> None:
    # INVARIANT (A4 acceptance): Local Engine behaviour is unchanged — it lists and manages the
    # caller's rows under `/v1/oauth/connections*` and never reads the availability successor.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == PROVIDERS_PATH:
            return httpx.Response(200, json=_providers(_provider("openrouter", "OpenRouter")))
        assert request.url.path.startswith(LOCAL_ROWS_PATH), request.url.path
        if request.method == "GET":
            return httpx.Response(200, json={"connections": []})
        return httpx.Response(
            201,
            json={
                "id": "00000000-0000-0000-0000-000000000001",
                "provider": "openrouter",
                "label": "screamingface",
                "status": "active",
                "auth_type": "api_key",
                "account": None,
            },
        )

    adapter, seen = _adapter(handler, mutable=True)

    rows = await adapter.list(Caller(ALICE))
    connected = await adapter.connect(Caller(ALICE), "openrouter", "sk-local-test")

    assert rows == (Connection("openrouter", "OpenRouter", ("api_key",), "not_connected"),)
    assert connected.status == "connected" and connected.auth_method == "api_key"
    assert [request.url.path for request in seen] == [
        PROVIDERS_PATH,
        LOCAL_ROWS_PATH,
        PROVIDERS_PATH,
        LOCAL_ROWS_PATH,
        f"{LOCAL_ROWS_PATH}/api-key",
    ]


async def test_mutability_is_required_at_the_composition_seam() -> None:
    parameters = signature(build_connections).parameters

    assert parameters["mutable"].default is Parameter.empty
    assert parameters["mutable"].kind is Parameter.KEYWORD_ONLY
    # F-A4-1: the retired `listing_source` switch is not kept alive beside the mutability rule.
    assert "listing_source" not in parameters
    assert "listing_source" not in signature(AigatewayConnections).parameters


async def test_the_connections_dto_field_set_is_unchanged() -> None:
    # INVARIANT (A4 acceptance): the Engine `/v1/connections` field set is frozen so the SDK's
    # strict decoder needs no change.
    public = {"provider", "display_name", "auth_methods", "status", "auth_method", "account_label"}

    assert set(ConnectionResponse.model_fields) == {"object", *public}
    assert {field.name for field in fields(Connection)} == public
