"""Credits are an independently injectable port, not a concrete connection adapter."""

import httpx
import pytest

from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.connections.credits import CreditAmount, CreditStatus


@pytest.mark.asyncio
async def test_credit_route_accepts_a_port_without_gateway_or_connections():
    unknown = CreditAmount(status="unavailable", reason="not_connected")
    seen = []

    class FakeCredits:
        async def read(self, caller, provider, *, refresh):
            seen.append((provider, refresh))
            return CreditStatus(
                object="credit_status",
                provider=provider,
                account=unknown,
                key=unknown,
                hosted=unknown,
                management_key_configured=False,
            )

        async def configure(self, caller, provider, api_key):
            seen.append((provider, "configure"))

        async def remove(self, caller, provider):
            seen.append((provider, "remove"))

    app = create_app(Settings(jwt_secret="test-secret"), credits=FakeCredits())
    async with httpx.AsyncClient(base_url="http://test", transport=httpx.ASGITransport(app)) as c:
        response = await c.get("/v1/credits/openrouter?refresh=false")
        assert response.status_code == 200
        assert response.json()["key"]["reason"] == "not_connected"
        assert (
            await c.put("/v1/credits/openrouter/management-key", json={"api_key": "test"})
        ).status_code == 204
        assert (await c.delete("/v1/credits/openrouter/management-key")).status_code == 204
    assert seen == [("openrouter", False), ("openrouter", "configure"), ("openrouter", "remove")]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("openrouter", True),
        ("a_0-b", True),
        ("0" * 10000, True),
        ("0" * 10000 + "!", False),
        ("", False),
        ("_a", False),
        ("A", False),
        ("é", False),
        ("a\n", False),
        (None, False),
    ],
)
def test_provider_identifier_grammar(value, expected):
    from screamingface_engine.connections.provider_id import is_provider_id

    assert is_provider_id(value) is expected
