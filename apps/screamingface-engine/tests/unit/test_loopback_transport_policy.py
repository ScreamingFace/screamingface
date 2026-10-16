from __future__ import annotations

import httpx
import pytest

from screamingface_engine.catalog import _default_client
from screamingface_engine.network_policy import is_numeric_loopback_url
from screamingface_engine.world import connector
from screamingface_engine.world.config import ModelSpec


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:9105", "http://127.42.0.9:9105", "http://[::1]:9105"],
)
def test_numeric_loopback_url_is_recognized(url: str) -> None:
    assert is_numeric_loopback_url(url) is True


@pytest.mark.parametrize(
    "url",
    ["http://localhost:9105", "https://gateway.example", "not-a-url"],
)
def test_hostname_remote_or_malformed_url_is_not_numeric_loopback(url: str) -> None:
    assert is_numeric_loopback_url(url) is False


@pytest.mark.asyncio
async def test_catalog_client_ignores_proxy_environment_only_for_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, object]] = []
    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        seen.append(kwargs)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    loopback = _default_client("http://127.0.0.1:9105")
    remote = _default_client("https://gateway.example")

    assert seen[0]["trust_env"] is False
    assert seen[1]["trust_env"] is True
    await loopback.aclose()
    await remote.aclose()


@pytest.mark.asyncio
async def test_model_execution_client_ignores_proxy_environment_for_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        seen.update(kwargs)
        transport = httpx.MockTransport(lambda _request: httpx.Response(200))
        return real_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(connector.httpx, "AsyncClient", client)
    world = await connector.build_aigateway_world(
        connector.AigatewayConfig(
            base_url="http://127.0.0.1:9105",
            default_model="local/fixture",
            models=(ModelSpec(id="local/fixture"),),
        )
    )

    assert seen["trust_env"] is False
    await world.aclose()
