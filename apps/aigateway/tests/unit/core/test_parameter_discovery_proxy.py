from __future__ import annotations

import httpx
import pytest

from aigateway.core.parameter_discovery import HttpxDiscoveryClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://127.0.0.1:1234/v1/models", False),
        ("https://catalog.example/models", True),
    ],
)
async def test_discovery_transport_uses_proxies_only_for_non_loopback_sources(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    expected: bool,
) -> None:
    seen: dict[str, object] = {}
    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        seen.update(kwargs)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"data": []},
            headers={"content-type": "application/json"},
        )
    )

    await HttpxDiscoveryClient(transport=transport).get(
        url,
        timeout_s=3.0,
        max_bytes=1_000_000,
    )

    assert seen["trust_env"] is expected
