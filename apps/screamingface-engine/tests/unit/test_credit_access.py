from datetime import UTC, datetime

import httpx
import pytest

from screamingface_engine.connections.aigateway import AigatewayConnections
from screamingface_engine.connections.port import (
    Caller,
    ConnectionBadResponse,
    ConnectionMethodUnsupported,
)


def payload():
    known = {
        "status": "available",
        "amount_usd": "12.34",
        "as_of": datetime.now(UTC).isoformat(),
        "reason": None,
    }
    unknown = {
        "status": "unavailable",
        "amount_usd": None,
        "as_of": None,
        "reason": "hosted_unavailable",
    }
    return {
        "object": "credit_status",
        "provider": "openrouter",
        "connection_token": "a" * 64,
        "account": known,
        "key": known,
        "hosted": unknown,
        "management_key_configured": True,
    }


@pytest.mark.asyncio
async def test_credit_read_preserves_caller_identity_and_decimal():
    def handler(request):
        assert request.headers["x-user-email"] == "owner@example.com"
        assert request.url.path == "/v1/credits/openrouter"
        return httpx.Response(200, json=payload())

    async with httpx.AsyncClient(
        base_url="https://gateway.example", transport=httpx.MockTransport(handler)
    ) as client:
        service = AigatewayConnections(client)
        result = await service.credits.read(
            Caller({"X-User-Email": "owner@example.com"}, None), "openrouter", refresh=True
        )
    assert str(result.account.amount_usd) == "12.34"


@pytest.mark.asyncio
async def test_hosted_credit_never_reads_shared_provider_funds_or_accepts_keys():
    def handler(request):
        pytest.fail("hosted credit must not contact gateway")

    async with httpx.AsyncClient(
        base_url="https://gateway.example", transport=httpx.MockTransport(handler)
    ) as client:
        service = AigatewayConnections(client, mutable=False)
        caller = Caller({}, None)
        result = await service.credits.read(caller, "openrouter", refresh=True)
        assert result.account.reason == "hosted_unavailable"
        with pytest.raises(ConnectionMethodUnsupported):
            await service.credits.configure(caller, "openrouter", "secret")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"provider": "other"},
        {"extra_secret": "do-not-forward"},
        {"account": {"status": "available", "amount_usd": "NaN"}},
    ],
)
async def test_bad_upstream_credit_shape_is_rejected(bad):
    async with httpx.AsyncClient(
        base_url="https://gateway.example",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={**payload(), **bad})),
    ) as client:
        with pytest.raises(ConnectionBadResponse):
            await AigatewayConnections(client).credits.read(
                Caller({}, None), "openrouter", refresh=True
            )


@pytest.mark.asyncio
async def test_engine_credit_routes_keep_secrets_write_only_and_refuse_selectors():
    from screamingface_engine.app import create_app
    from screamingface_engine.config import Settings
    from screamingface_engine.testing import InMemoryEventStream

    seen = []

    def handler(request):
        seen.append(request)
        return (
            httpx.Response(200, json=payload()) if request.method == "GET" else httpx.Response(204)
        )

    async with httpx.AsyncClient(
        base_url="https://gateway.example", transport=httpx.MockTransport(handler)
    ) as upstream:
        app = create_app(
            Settings(jwt_secret="test-secret"),
            stream=InMemoryEventStream(),
            connections=AigatewayConnections(upstream),
        )
        async with httpx.AsyncClient(
            base_url="http://test", transport=httpx.ASGITransport(app)
        ) as client:
            response = await client.get(
                "/v1/credits/openrouter", headers={"X-User-Email": "owner@example.com"}
            )
            assert response.status_code == 200
            assert response.headers["cache-control"] == "private, no-store"
            assert seen[-1].headers["x-user-email"] == "owner@example.com"
            response = await client.put(
                "/v1/credits/openrouter/management-key", json={"api_key": "private-management"}
            )
            assert response.status_code == 204 and not response.content
            assert b"private-management" in seen[-1].content
            response = await client.delete("/v1/credits/openrouter/management-key")
            assert response.status_code == 204
            count = len(seen)
            response = await client.get("/v1/credits/openrouter", headers={"X-Profile": "retired"})
            assert response.status_code == 400 and len(seen) == count
            response = await client.put(
                "/v1/credits/openrouter/management-key",
                json={"api_key": {"private-management": "secret"}},
            )
            assert response.status_code == 422 and "private-management" not in response.text


@pytest.mark.asyncio
async def test_engine_credit_error_does_not_invent_an_ambiguous_connection():
    from screamingface_engine.app import create_app
    from screamingface_engine.config import Settings
    from screamingface_engine.testing import InMemoryEventStream

    async with httpx.AsyncClient(
        base_url="https://gateway.example",
        transport=httpx.MockTransport(lambda r: httpx.Response(409, text="private-secret")),
    ) as upstream:
        app = create_app(
            Settings(jwt_secret="test-secret"),
            stream=InMemoryEventStream(),
            connections=AigatewayConnections(upstream),
        )
        async with httpx.AsyncClient(
            base_url="http://test", transport=httpx.ASGITransport(app)
        ) as client:
            response = await client.put(
                "/v1/credits/openrouter/management-key", json={"api_key": "private-management"}
            )
    assert response.status_code == 409
    assert response.json() == {
        "type": "about:blank",
        "title": "Conflict",
        "status": 409,
        "detail": "Credit request could not be completed",
    }


@pytest.mark.asyncio
async def test_hosted_allowance_reads_only_the_callers_limited_key():
    def handler(request):
        assert request.headers["x-user-email"] == "owner@example.com"
        assert request.url.path == "/v1/credits/openrouter/key"
        return httpx.Response(200, json=payload())

    async with httpx.AsyncClient(
        base_url="https://gateway.example", transport=httpx.MockTransport(handler)
    ) as client:
        service = AigatewayConnections(client, mutable=False)
        result = await service.credits.read(
            Caller({"X-User-Email": "owner@example.com"}, None), "openrouter", refresh=True
        )
    assert str(result.hosted.amount_usd) == "12.34"
    assert result.hosted == result.key
    assert result.account.amount_usd is None
    assert not result.management_key_configured


@pytest.mark.asyncio
async def test_hosted_unlimited_key_does_not_invent_a_hosted_budget():
    body = payload()
    body["key"] = {
        "status": "unlimited",
        "amount_usd": None,
        "as_of": datetime.now(UTC).isoformat(),
        "reason": None,
    }
    async with httpx.AsyncClient(
        base_url="https://gateway.example",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
    ) as client:
        result = await AigatewayConnections(client, mutable=False).credits.read(
            Caller({"X-User-Email": "owner@example.com"}, None), "openrouter", refresh=True
        )
    assert result.hosted.status == "unavailable"
    assert result.hosted.amount_usd is None
    assert result.account.amount_usd is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,amount", [("available", "0"), ("stale", "4.50"), ("unavailable", None)]
)
async def test_hosted_allowance_preserves_zero_stale_and_unknown(status, amount):
    body = payload()
    body["key"] = {
        "status": status,
        "amount_usd": amount,
        "as_of": None if status == "unavailable" else "2026-11-11T12:00:00Z",
        "reason": None if status == "available" else "lookup_failed",
    }
    async with httpx.AsyncClient(
        base_url="https://gateway.example",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
    ) as client:
        result = await AigatewayConnections(client, mutable=False).credits.read(
            Caller({"X-User-Email": "owner@example.com"}, None), "openrouter", refresh=False
        )
    assert result.hosted.status == status
    assert result.hosted.as_of == result.key.as_of
    assert result.hosted.amount_usd == result.key.amount_usd
    assert result.account.amount_usd is None
