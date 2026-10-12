"""Regression gates for the error paths (audit B6 and E7).

B6: a malformed attribution chain must raise ParseError, not IndexError.
E7: an unexpected handler exception must reach the client as the JSON
    ``internal_error`` body with status 500, and must not leak its message.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from url4 import ParseError, build
from url4.peer.server import Request, Url4Node


@pytest.mark.parametrize(
    "text", ["a:", "0:", "(x, a:)!go", "a:0.5:", "a:(w: 1):", "a:max_tokens=5:"]
)
def test_empty_attribution_chain_raises_parse_error(text: str) -> None:
    with pytest.raises(ParseError):
        build(text)


@pytest.mark.asyncio
async def test_malformed_chain_over_http_is_400_malformed_source() -> None:
    node = Url4Node(name="errnode")
    transport = httpx.ASGITransport(app=node.asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://errnode") as http:
        response = await http.get("/v1", params={"q": "(x, a:)!go"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "malformed_source"


@pytest.mark.asyncio
async def test_unexpected_handler_error_is_json_500_without_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    node = Url4Node(name="boomnode")

    @node.endpoint("/boom")
    async def boom(request: Request) -> str:
        raise RuntimeError("secret detail")

    transport = httpx.ASGITransport(app=node.asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://boomnode") as http:
        response = await http.get("/boom", params={"q": "go"})
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert response.json()["error"]["code"] == "internal_error"
    assert response.json()["error"]["message"] == "internal error"
    assert "secret detail" not in response.text
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None
