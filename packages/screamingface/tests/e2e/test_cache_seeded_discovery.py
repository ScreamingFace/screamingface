"""The keyless replay adapter changes only optional live-access metadata."""

import json

import httpx
import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,status,access,removed",
    [
        ("/v1/model-parameters", 200, "missing", True),
        ("/v1/model-parameters", 200, "configured", True),
        ("/v1/model-parameters", 200, None, True),
        ("/v1/model-parameters", 404, "missing", False),
        ("/v1/chat/completions", 200, "missing", False),
    ],
)
async def test_replay_discovery_preserves_everything_except_optional_live_access(
    path, status, access, removed
):
    from harness.cache_discovery import ReplayDiscovery

    document = {"context": {"revision": "stable"}, "parameters": [{"name": "temperature"}]}
    if access is not None:
        document["context"]["execution_access"] = access
    body = json.dumps(document).encode()

    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"x-fixture", b"preserved"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body[:10], "more_body": True})
        await send({"type": "http.response.body", "body": body[10:]})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ReplayDiscovery(app)), base_url="http://replay"
    ) as client:
        response = await client.get(path)
    expected = json.loads(body)
    if removed:
        expected["context"].pop("execution_access", None)
    assert response.status_code == status
    assert response.json() == expected
    assert response.headers["x-fixture"] == "preserved"
    assert int(response.headers["content-length"]) == len(response.content)
