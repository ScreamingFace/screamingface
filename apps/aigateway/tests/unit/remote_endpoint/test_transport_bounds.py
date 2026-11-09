"""Dispatch bounds what it holds and forwards from an endpoint, as readiness does.

# FEATURE: hosted BYOM — the response size bound must hold for the bytes kept in memory, and an
# upstream retry hint crosses the boundary only within the gateway's one Retry-After bound.
# INVARIANT: dispatch asks for an identity-encoded answer and never reads an encoded one, so a
# small compressed body cannot expand past the bound inside the gateway.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from aigateway.plugins.remote_endpoint.definitions import parse_remote_endpoint_config
from aigateway.plugins.remote_endpoint.plugin import RemoteEndpointPlugin

from .fixtures import ALIAS, ENDPOINT_A, FINISHED_COMPLETION, JSON_TYPE, two_endpoint_document

KEY = "sk-byom-transport-0001"
REQUEST = {
    "model": f"{ENDPOINT_A}/{ALIAS}",
    "messages": [{"role": "user", "content": "ping"}],
    "api_key": KEY,
}


class _Body(httpx.AsyncByteStream):
    """A response body that records whether anyone read it."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.was_read = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.was_read = True
        yield self.data


def _plugin(respond: Callable[[httpx.Request], httpx.Response]) -> RemoteEndpointPlugin:
    definition = parse_remote_endpoint_config(two_endpoint_document()).endpoints[0]
    return RemoteEndpointPlugin(definition, transport=httpx.MockTransport(respond))


def _code(exc: HTTPException) -> str:
    detail: Any = exc.detail
    return detail["code"]


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "gzip, identity"])
async def test_an_encoded_answer_is_refused_without_being_read(encoding: str) -> None:
    expanded = json.dumps({**FINISHED_COMPLETION, "pad": "x" * 2_000_000}).encode()
    body = _Body(gzip.compress(expanded))
    asked: list[str | None] = []

    def respond(request: httpx.Request) -> httpx.Response:
        asked.append(request.headers.get("accept-encoding"))
        headers = {"content-type": JSON_TYPE, "content-encoding": encoding}
        return httpx.Response(200, headers=headers, stream=body)

    with pytest.raises(HTTPException) as caught:
        await _plugin(respond).chat_completion(dict(REQUEST))

    assert (caught.value.status_code, _code(caught.value)) == (502, "provider_error")
    assert (asked, body.was_read) == (["identity"], False)


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", [None, "identity", "IDENTITY"])
async def test_an_identity_answer_still_serves(encoding: str | None) -> None:
    body = _Body(json.dumps(FINISHED_COMPLETION).encode())

    def respond(_request: httpx.Request) -> httpx.Response:
        headers = {"content-type": JSON_TYPE}
        if encoding is not None:
            headers["content-encoding"] = encoding
        return httpx.Response(200, headers=headers, stream=body)

    assert await _plugin(respond).chat_completion(dict(REQUEST)) == FINISHED_COMPLETION


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize(
    "hint, forwarded",
    [
        ("30", "30"),
        ("2147483647", "2147483647"),
        ("2147483648", None),
        ("0", None),
        ("9" * 1000, None),
        ("1.5", None),
        ("Wed, 21 Oct 2026 07:28:00 GMT", None),
    ],
    ids=["seconds", "largest", "too-large", "zero", "thousand-digits", "fraction", "http-date"],
)
async def test_only_a_bounded_retry_hint_is_forwarded(
    status: int, hint: str, forwarded: str | None
) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"retry-after": hint})

    with pytest.raises(HTTPException) as caught:
        await _plugin(respond).chat_completion(dict(REQUEST))

    assert caught.value.status_code == status
    assert (caught.value.headers or {}).get("Retry-After") == forwarded
