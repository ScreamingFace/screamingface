"""A run's files are encoded once and streamed into every model call (PR #1588 review, blocker 1).

STORY: as a node operator, one legal 8 MB picture fanned out to eight members, a synthesizer and a
reducer costs about one encoded copy of memory, not one per concurrent call. The review probe held
eight distinct 10,666,690-byte ``data:`` URIs (85 MB current, 96 MB peak) before any JSON copy.

INVARIANT (the bound these tests pin): ``E`` is the encoded ``data:`` URI of the file and ``R`` the
per-request overhead. While ``N`` calls are in flight the engine retains at most ``E + N * R``; the
peak adds one transient ``E`` (the base64 bytes and their ``str`` exist together once, while the
shared URI is built). ``R`` = 256 KiB: one 64 KiB streaming buffer, one 64 Ki-character slice of
the URI and its encoded bytes, plus the envelope and httpx/asyncio objects of the call — far below
``E``, so any per-call copy of the URI (or of the JSON body) breaks the bound.
"""

from __future__ import annotations

import asyncio
import gc
import hashlib
import json
import tracemalloc
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from test_aigateway_connector import _MODEL

import screamingface_engine.world.attachment_parts as attachment_parts_module
from screamingface_engine.world.attachment_parts import (
    attachment_parts,
    bound_blob_reader,
    canonical_data_uri,
)
from screamingface_engine.world.config import ModelSpec, routes_for
from screamingface_engine.world.connector import AigatewayConfig, _ModelEndpoint
from screamingface_engine.world.streamed_json import streamed_json_body
from url4 import Attachment
from url4.core.errors import ResolutionError
from url4.peer.server import Request

pytestmark = pytest.mark.asyncio

_FAN_OUT = 8
_PER_REQUEST = 256 * 1024
_SIZE = 8_000_000  # the reviewer's probe: one legal attachment at today's url4 cap


def _digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _picture(size: int = _SIZE) -> Attachment:
    body = bytes(range(256)) * (size // 256) + b"\x00" * (size % 256)
    return Attachment(digest=_digest(body), media_type="image/png", body=body)


class _StreamingGateway(httpx.AsyncBaseTransport):
    """Reads each request body chunk by chunk, keeps only its length and hash, answers ``42``.

    WHY not ``httpx.MockTransport``: it ``aread()``s every body into memory, which is the very
    per-call copy under test. ``in_flight`` holds every call at a barrier until all have arrived,
    so the probe sees ``_FAN_OUT`` requests alive together.
    """

    def __init__(self, fan_out: int, *, keep: bool = False) -> None:
        self.bodies: list[tuple[int, str]] = []
        self.kept: list[bytes] = []
        self._keep = keep
        self.headers: list[httpx.Headers] = []
        self.in_flight_current: list[int] = []
        self._arrived = asyncio.Barrier(fan_out)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        self.headers.append(request.headers)
        size, hasher, kept = 0, hashlib.sha256(), bytearray()
        assert isinstance(request.stream, httpx.AsyncByteStream)
        async for chunk in request.stream:
            size += len(chunk)
            hasher.update(chunk)
            if self._keep:
                kept += chunk
        if self._keep:
            self.kept.append(bytes(kept))
        self.bodies.append((size, hasher.hexdigest()))
        await self._arrived.wait()
        gc.collect()
        self.in_flight_current.append(tracemalloc.get_traced_memory()[0])
        await self._arrived.wait()
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "42"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
        )


def _handler(client: httpx.AsyncClient) -> _ModelEndpoint:
    models = (ModelSpec(id=_MODEL, web_search=False),)
    return _ModelEndpoint(
        http_client=client,
        cfg=AigatewayConfig(models=models, default_model=_MODEL),
        routes=routes_for(models),
        tavily_http=None,
        tavily_api_key=None,
    )


def _request(attachments: tuple[Attachment, ...], prompt: str = "Describe.") -> Request:
    return Request(
        path=f"/{_MODEL}", context=prompt, intent="Answer.", params={}, attachments=attachments
    )


async def test_a_wide_fan_out_holds_about_one_encoded_copy() -> None:
    picture = _picture()
    encoded = len(canonical_data_uri(picture.media_type, picture.body))
    assert encoded == 10_666_690  # the reviewer's measured URI size, so the probe is the same
    gateway = _StreamingGateway(_FAN_OUT)
    async with httpx.AsyncClient(transport=gateway, base_url="http://aigateway.test") as client:
        handler = _handler(client)
        gc.collect()
        tracemalloc.start()
        try:
            results = await asyncio.gather(
                *(handler(_request((picture,), f"Member {i}.")) for i in range(_FAN_OUT))
            )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

    assert results == ["42"] * _FAN_OUT
    assert len(gateway.bodies) == _FAN_OUT
    assert all(size > encoded for size, _ in gateway.bodies)
    assert max(gateway.in_flight_current) <= encoded + _FAN_OUT * _PER_REQUEST
    assert peak <= 2 * encoded + _FAN_OUT * _PER_REQUEST


async def test_the_streamed_request_is_the_json_body_httpx_would_send() -> None:
    # WHY byte parity: the gateway cache hashes the request (F3), so streaming changes no byte.
    picture = _picture(300_000)
    gateway = _StreamingGateway(1, keep=True)
    async with httpx.AsyncClient(transport=gateway, base_url="http://aigateway.test") as client:
        assert await _handler(client)(_request((picture,), "Décris ✓ 🖼")) == "42"

    (raw,), (headers,) = gateway.kept, gateway.headers
    assert headers["content-length"] == str(len(raw))
    assert headers["content-type"] == "application/json"
    assert "transfer-encoding" not in headers
    assert httpx.Request("POST", "http://x", json=json.loads(raw)).read() == raw


@pytest.mark.parametrize(
    "body",
    [
        {"model": "m", "messages": [{"role": "user", "content": "x" * 300_000}]},
        {"a": ["é" * 200_000, {"b": ' \n"\\' * 70_000}], "n": [1, 2.5, None, True, False]},
        {"u": "🖼" * 300_000, "k": {}, "l": [], "t": "small"},
        {"model": "m", "messages": [{"role": "user", "content": "short"}]},
    ],
    ids=["ascii", "escapes", "astral", "small"],
)
async def test_streamed_json_is_byte_identical_to_httpx_encode_json(body: dict[str, Any]) -> None:
    expected = httpx.Request("POST", "http://x", json=body)
    expected_bytes = expected.read()
    streamed = streamed_json_body(body)
    if streamed is None:
        # A body with no large string keeps httpx's own ``json=`` path (text-only parity).
        assert len(expected_bytes) < 256 * 1024
        return
    headers, content = streamed
    got = b"".join([chunk async for chunk in _iterate(content)])
    assert got == expected_bytes
    assert headers == {
        "Content-Length": str(len(expected_bytes)),
        "Content-Type": "application/json",
    }
    again = b"".join([chunk async for chunk in _iterate(content)])
    assert again == expected_bytes  # re-iterable: a transport retry re-sends the same bytes


async def _iterate(content: Any) -> AsyncIterator[bytes]:
    async for chunk in content:
        assert len(chunk) <= 64 * 1024
        yield chunk


async def test_a_frozen_attachment_is_verified_and_encoded_once_per_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hashed: list[str] = []
    real = attachment_parts_module._hashes_to

    def counting(body: bytes, digest: str) -> bool:
        hashed.append(digest)
        return real(body, digest)

    monkeypatch.setattr(attachment_parts_module, "_hashes_to", counting)
    picture = _picture(30_000)

    first = await attachment_parts([picture])
    second = await attachment_parts([picture])

    assert hashed == [picture.digest]
    assert first[0]["image_url"]["url"] is second[0]["image_url"]["url"]  # type: ignore[typeddict-item]


async def test_a_ref_is_read_and_verified_per_call_but_encoded_once() -> None:
    body = _picture(30_000).body
    ref = Attachment(digest=_digest(body), media_type="image/png")
    reads: list[str] = []

    class _Reader:
        async def read(self, digest: str) -> bytes | None:
            reads.append(digest)
            return body

    with bound_blob_reader(_Reader()):
        first = await attachment_parts([ref])
        second = await attachment_parts([ref])

    assert reads == [ref.digest, ref.digest]  # the run-scoped reader answers every call (F3)
    assert first[0]["image_url"]["url"] is second[0]["image_url"]["url"]  # type: ignore[typeddict-item]


async def test_a_ref_encoded_for_one_reader_is_not_served_to_an_out_of_scope_reader() -> None:
    # INVARIANT (F3 authorization): the shared encoding never stands in for a read. A ref whose
    # bytes one run read stays unreadable for a reader that cannot see the digest.
    body = _picture(30_000).body
    ref = Attachment(digest=_digest(body), media_type="image/png")

    class _Reader:
        def __init__(self, blobs: dict[str, bytes]) -> None:
            self.blobs = blobs

        async def read(self, digest: str) -> bytes | None:
            return self.blobs.get(digest)

    with bound_blob_reader(_Reader({ref.digest: body})):
        await attachment_parts([ref])
    with bound_blob_reader(_Reader({})), pytest.raises(Exception) as caught:
        await attachment_parts([ref])
    assert getattr(caught.value, "code", None) == "source_not_found"


async def test_a_forged_body_is_still_refused_after_an_honest_one_was_encoded() -> None:
    picture = _picture(30_000)
    forged = Attachment(digest=picture.digest, media_type="image/png", body=b"forged")
    await attachment_parts([picture])

    gateway = _StreamingGateway(1)
    async with httpx.AsyncClient(transport=gateway, base_url="http://aigateway.test") as client:
        with pytest.raises(ResolutionError) as caught:
            await _handler(client)(_request((forged,)))
    assert caught.value.code == "x.blob_digest_mismatch"
    assert gateway.bodies == []
