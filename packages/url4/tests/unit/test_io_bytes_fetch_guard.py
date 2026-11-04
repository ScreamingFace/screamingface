"""The bytes fetch inherits the destination guard (spec F1b) of the text fetch.

FEATURE: image and PDF inputs for url4 sources (epic OME-1529).
STORY: as an operator I expose a node that fetches binary sources, and a PNG/PDF expression
cannot reach the cloud metadata endpoint any more than a text one can.
No network: the guarded transport's inner transport is a recording mock.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
from url4.core.errors import ErrorCode, ResolutionError
from url4.io.http import HttpIOLayer
from url4.io.layer import FetchRequest

METADATA = "169.254.169.254"


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def transport() -> httpx.AsyncBaseTransport:
        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"})

        return httpx.MockTransport(record)

    monkeypatch.setattr(guarded_mod, "_inner_transport", transport)
    return seen


async def _metadata_resolver(host: str, port: int) -> Sequence[str]:
    return [METADATA]


async def _refused(io: HttpIOLayer, target: str) -> ResolutionError:
    try:
        with pytest.raises(ResolutionError) as caught:
            await io.fetch_bytes(FetchRequest(target, relative=False))
    finally:
        await io.aclose()
    return caught.value


@pytest.mark.asyncio
async def test_fetch_bytes_refuses_the_metadata_address_literal(sent: list[httpx.Request]) -> None:
    lookups: list[str] = []

    async def resolver(host: str, port: int) -> Sequence[str]:
        lookups.append(host)
        return [METADATA]

    error = await _refused(HttpIOLayer(resolver=resolver), f"https://{METADATA}/latest/meta-data/")
    assert error.code == ErrorCode.SOURCE_DESTINATION_BLOCKED
    assert error.permanent is True
    assert sent == [] and lookups == []


@pytest.mark.asyncio
async def test_fetch_bytes_refuses_a_name_resolving_to_the_metadata_address(
    sent: list[httpx.Request],
) -> None:
    error = await _refused(
        HttpIOLayer(resolver=_metadata_resolver), "https://images.example/cat.png"
    )
    assert error.code == ErrorCode.SOURCE_DESTINATION_BLOCKED
    assert sent == []
