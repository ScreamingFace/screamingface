"""Local mode's fair-share wrapper keeps a run's live attachment byte budget (push security review).

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1545``; push security review
"resource-cap-defeat", owner decision 2026-11-03: shared live budget).
STORY: as a local-mode operator, a run naming many large ``https://`` attachments through
``serve --local`` (which wraps every run's io in ``FairShareIOLayer``) is refused once its bytes
pass the 8,000,000-byte per-run cap, without first downloading every body.

INVARIANT: ``FairShareIOLayer.fetch_bytes`` passes the request through unchanged, so its
``max_bytes`` / ``on_chunk`` reach the transport that reads the body.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest

from screamingface_engine.runner.fair_share import FairShareGate, FairShareIOLayer
from url4.core.errors import ErrorCode, ResolutionError
from url4.dag import run
from url4.io.http import HttpIOLayer
from url4.io.layer import FetchRequest
from url4.io.media import FetchedBytes

MIB = 1024 * 1024
CHUNK = 64 * 1024
CAP = 8_000_000


class _Recording:
    def __init__(self) -> None:
        self.requests: list[FetchRequest] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        return target

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.requests.append(request)
        return FetchedBytes(b"x", "image/png")


@pytest.mark.asyncio
async def test_fetch_bytes_passes_the_byte_hook_through_unchanged() -> None:
    inner = _Recording()
    layer = FairShareIOLayer(inner, FairShareGate(2), "run-a")  # type: ignore[arg-type]
    request = FetchRequest("https://img.example/a.png", max_bytes=123, on_chunk=lambda n: None)
    await layer.fetch_bytes(request)
    assert inner.requests[0] is request


class _Body(httpx.AsyncByteStream):
    def __init__(self, size: int) -> None:
        self.size = size
        self.read = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while self.read < self.size:
            piece = min(CHUNK, self.size - self.read)
            self.read += piece
            yield b"\0" * piece


@pytest.mark.asyncio
async def test_twenty_1_mib_attachments_through_the_share_stop_near_the_cap() -> None:
    bodies: list[_Body] = []

    def answer(request: httpx.Request) -> httpx.Response:
        body = _Body(MIB)
        bodies.append(body)
        return httpx.Response(200, stream=body, headers={"content-type": "image/png"})

    calls: list[str] = []

    async def model(sources: str, intent: str | None, scope: object) -> str:
        calls.append(sources)
        return "ok"

    urls = [f"https://files.example/f{i}.png" for i in range(20)]
    text = "(" + ", ".join(f"src={u};accept=image/png" for u in urls) + ")!'d'"
    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    layer = FairShareIOLayer(HttpIOLayer(client=client), FairShareGate(32), "run-a")
    try:
        with pytest.raises(ResolutionError) as caught:
            await asyncio.wait_for(run(text, layer, process=model), 30)
    finally:
        await client.aclose()
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert sum(body.read for body in bodies) <= CAP + 20 * CHUNK
    assert calls == []
