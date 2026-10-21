"""The bounded discovery adapter can carry provider-owned request headers (OME-1634).

FEATURE: live Codex model list — the Codex catalog answers per account, so its fetch must
carry the caller's own bearer token through the SAME bounded adapter (size cap, deadline,
no redirects) the public catalogs use.

INVARIANT: the default adapter (the app-lifetime runtime client) sends no extra header —
the shared injected discovery client stays credential-free.
"""

from __future__ import annotations

import httpx
import pytest

from aigateway.core.parameter_discovery import HttpxDiscoveryClient


def _recording_transport(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_constructor_headers_are_sent() -> None:
    seen: list[httpx.Request] = []
    client = HttpxDiscoveryClient(
        transport=_recording_transport(seen),
        headers={"Authorization": "Bearer t", "ChatGPT-Account-Id": "acct"},
    )
    response = await client.get("https://example.test/x", timeout_s=1.0, max_bytes=1000)
    assert response.status == 200
    assert seen[0].headers["authorization"] == "Bearer t"
    assert seen[0].headers["chatgpt-account-id"] == "acct"
    # INVARIANT: the identity-encoding bound still applies with extra headers.
    assert seen[0].headers["accept-encoding"] == "identity"


@pytest.mark.asyncio
async def test_extra_headers_cannot_reopen_compressed_transfer() -> None:
    seen: list[httpx.Request] = []
    client = HttpxDiscoveryClient(
        transport=_recording_transport(seen), headers={"Accept-Encoding": "gzip"}
    )
    await client.get("https://example.test/x", timeout_s=1.0, max_bytes=1000)
    assert seen[0].headers["accept-encoding"] == "identity"


@pytest.mark.asyncio
async def test_default_adapter_sends_no_credential() -> None:
    seen: list[httpx.Request] = []
    client = HttpxDiscoveryClient(transport=_recording_transport(seen))
    await client.get("https://example.test/x", timeout_s=1.0, max_bytes=1000)
    assert "authorization" not in seen[0].headers
