"""The internal bytes fetch port: ``(bytes, media_type)`` beside the text fetch.

FEATURE: image and PDF inputs for url4 sources (epic OME-1529).
STORY: as an engine author I fetch a PNG or a PDF source and get its exact bytes and media
type, so it can reach the model as a file instead of as mangled text.
"""

from __future__ import annotations

import hashlib

import httpx
import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag._context import BoundedIOLayer
from url4.io.http import HttpIOLayer
from url4.io.layer import (
    FetchedBytes,
    FetchRequest,
    FetchResult,
    SupportsFetchBytes,
    fetch_bytes,
    is_text_media_type,
)
from url4.io.static import StaticIOLayer

# Not decodable as UTF-8 (0x89, 0xff), so a .text decode would visibly mangle them.
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xff\xfe\x00\x01"
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n\xff\xd8"


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _serving(body: bytes, content_type: str | None, seen: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        response = httpx.Response(200, content=body)
        if content_type is None:
            response.headers.pop("content-type", None)
        else:
            response.headers["content-type"] = content_type
        return response

    return handler


# -- the text/binary classifier ------------------------------------------------------------


@pytest.mark.parametrize(
    "content_type",
    [
        None,
        "",
        "text/plain",
        "text/csv",
        "TEXT/HTML; charset=ISO-8859-1",
        "application/json",
        "application/json; charset=utf-8",
        "application/ld+json",
        "application/atom+xml",
        "application/xml",
        "application/x-ndjson",
        "application/jsonl",
        "application/yaml",
        "application/javascript",
        "application/x-www-form-urlencoded",
        "application/vnd.custom; charset=utf-8",
    ],
)
def test_text_media_types(content_type: str | None) -> None:
    assert is_text_media_type(content_type) is True


@pytest.mark.parametrize(
    "content_type",
    [
        "image/png",
        "IMAGE/JPEG",
        "application/pdf",
        "application/pdf; name=x.pdf",
        "application/octet-stream",
        "audio/wav",
        "video/mp4",
        "application/zip",
    ],
)
def test_binary_media_types(content_type: str) -> None:
    assert is_text_media_type(content_type) is False


# -- the port bridge -----------------------------------------------------------------------


class _TextOnlyIO:
    """An old-style adapter: text ``fetch`` and ``fetch_ex`` only."""

    async def fetch(self, target: str, *, relative: bool) -> str:
        return f"text:{target}"

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        return FetchResult("héllo", media_type="text/plain")


class _BareIO:
    async def fetch(self, target: str, *, relative: bool) -> str:
        return "bare"


@pytest.mark.asyncio
async def test_bridge_prefers_fetch_bytes() -> None:
    io = StaticIOLayer({"https://x/a.png": PNG}, media_types={"https://x/a.png": "image/png"})
    assert isinstance(io, SupportsFetchBytes)
    got = await fetch_bytes(io, FetchRequest("https://x/a.png"))
    assert got == FetchedBytes(PNG, media_type="image/png")


@pytest.mark.asyncio
async def test_bridge_falls_back_to_utf8_text_with_media_type() -> None:
    # INVARIANT: an adapter without the capability could only ever give text, so the
    # bridge encodes that text as UTF-8 and keeps the media type it reported.
    got = await fetch_bytes(_TextOnlyIO(), FetchRequest("https://x"))
    assert got == FetchedBytes("héllo".encode(), media_type="text/plain")


@pytest.mark.asyncio
async def test_bridge_falls_back_to_bare_fetch() -> None:
    got = await fetch_bytes(_BareIO(), FetchRequest("/p", relative=True))
    assert got == FetchedBytes(b"bare", media_type=None)


# -- HttpIOLayer ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "content_type", "media_type"),
    [
        (PNG, "image/png", "image/png"),
        (PDF, "application/pdf; name=doc.pdf", "application/pdf"),
        (b"plain \xc3\xa9", "text/plain; charset=utf-8", "text/plain"),
        (b"raw", None, None),
    ],
)
async def test_http_fetch_bytes_is_byte_identical(
    body: bytes, content_type: str | None, media_type: str | None
) -> None:
    io = HttpIOLayer(client=_mock_client(_serving(body, content_type)))
    got = await io.fetch_bytes(FetchRequest("https://x/f"))
    assert got.body == body
    assert hashlib.sha256(got.body).digest() == hashlib.sha256(body).digest()
    assert got.media_type == media_type


@pytest.mark.asyncio
async def test_http_fetch_bytes_sends_accept_from_the_annotation() -> None:
    seen: list[httpx.Request] = []
    io = HttpIOLayer(client=_mock_client(_serving(PNG, "image/png", seen)))
    await io.fetch_bytes(FetchRequest("https://x/f", accept="image/png"))
    assert seen[0].headers["accept"] == "image/png"


@pytest.mark.asyncio
async def test_http_fetch_ex_sends_accept_from_the_annotation() -> None:
    seen: list[httpx.Request] = []
    io = HttpIOLayer(client=_mock_client(_serving(b"[1]", "application/json", seen)))
    got = await io.fetch_ex(FetchRequest("https://x/d", accept="application/json"))
    assert seen[0].headers["accept"] == "application/json"
    assert got == FetchResult("[1]", media_type="application/json")


@pytest.mark.asyncio
async def test_http_without_accept_keeps_the_client_default() -> None:
    seen: list[httpx.Request] = []
    io = HttpIOLayer(client=_mock_client(_serving(b"x", "text/plain", seen)))
    await io.fetch_ex(FetchRequest("https://x/d"))
    await io.fetch_bytes(FetchRequest("https://x/d"))
    assert [r.headers["accept"] for r in seen] == ["*/*", "*/*"]


@pytest.mark.asyncio
async def test_http_relative_fetch_bytes_uses_base_url_and_url4_rides_https() -> None:
    seen: list[httpx.Request] = []
    io = HttpIOLayer(base_url="https://host", client=_mock_client(_serving(PNG, "image/png", seen)))
    await io.fetch_bytes(FetchRequest("/blob/a", relative=True))
    await io.fetch_bytes(FetchRequest("url4://n2.example/blob/b"))
    assert [str(r.url) for r in seen] == ["https://host/blob/a", "https://n2.example/blob/b"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content_type", ["image/png", "application/pdf", "application/octet-stream"]
)
async def test_http_text_paths_refuse_a_binary_type(content_type: str) -> None:
    # INVARIANT: a binary media type never goes through response.text (spec C8).
    io = HttpIOLayer(client=_mock_client(_serving(PNG, content_type)))
    for call in (
        io.fetch("https://x/f", relative=False),
        io.fetch_ex(FetchRequest("https://x/f")),
    ):
        with pytest.raises(ResolutionError) as caught:
            await call
        assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
        assert caught.value.permanent is True
        assert content_type in str(caught.value)


@pytest.mark.asyncio
async def test_http_text_path_decodes_text_exactly_as_httpx_does() -> None:
    # Latin-1 declared: .text honours the charset, byte-identical to today's behaviour.
    body = "café".encode("latin-1")
    response = httpx.Response(
        200, content=body, headers={"content-type": "text/plain; charset=latin-1"}
    )
    io = HttpIOLayer(client=_mock_client(_serving(body, "text/plain; charset=latin-1")))
    assert await io.fetch("https://x/t", relative=False) == response.text == "café"


@pytest.mark.asyncio
async def test_http_fetch_bytes_maps_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    io = HttpIOLayer(client=_mock_client(handler))
    with pytest.raises(ResolutionError) as caught:
        await io.fetch_bytes(FetchRequest("https://x/missing"))
    assert caught.value.permanent is True


# -- StaticIOLayer -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_static_fetch_bytes_returns_bytes_as_is_and_encodes_strings() -> None:
    io = StaticIOLayer(
        {"/a.pdf": PDF, "/t": "héllo"},
        media_types={"/a.pdf": "application/pdf"},
    )
    assert await io.fetch_bytes(FetchRequest("/a.pdf", relative=True)) == FetchedBytes(
        PDF, "application/pdf"
    )
    assert await io.fetch_bytes(FetchRequest("/t", relative=True)) == FetchedBytes(
        "héllo".encode(), None
    )


@pytest.mark.asyncio
async def test_static_fetch_bytes_serves_routes() -> None:
    io = StaticIOLayer(routes={"/m": lambda ctx, intent: f"{ctx}|{intent}"})
    got = await io.fetch_bytes(FetchRequest("/m?q=(a)!b", relative=True))
    assert got == FetchedBytes(b"a|b", None)


@pytest.mark.asyncio
async def test_static_text_path_refuses_binary_bytes() -> None:
    io = StaticIOLayer({"/a.png": PNG}, media_types={"/a.png": "image/png"})
    with pytest.raises(ResolutionError) as caught:
        await io.fetch_ex(FetchRequest("/a.png", relative=True))
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    with pytest.raises(ResolutionError):
        await io.fetch("/a.png", relative=True)


@pytest.mark.asyncio
async def test_static_text_path_decodes_text_bytes() -> None:
    io = StaticIOLayer({"/t": "é".encode()}, media_types={"/t": "text/plain"})
    assert await io.fetch_ex(FetchRequest("/t", relative=True)) == FetchResult("é", "text/plain")
    untyped = StaticIOLayer({"/u": b"raw"})
    assert await untyped.fetch("/u", relative=True) == "raw"


@pytest.mark.asyncio
async def test_static_fetch_bytes_miss_raises() -> None:
    with pytest.raises(ResolutionError):
        await StaticIOLayer().fetch_bytes(FetchRequest("/none", relative=True))


# -- the run-wide bounded wrapper ----------------------------------------------------------


@pytest.mark.asyncio
async def test_bounded_wrapper_forwards_fetch_bytes() -> None:
    inner = StaticIOLayer({"/a.png": PNG}, media_types={"/a.png": "image/png"})
    wrapped = BoundedIOLayer(inner, 2)
    assert isinstance(wrapped, SupportsFetchBytes)
    got = await wrapped.fetch_bytes(FetchRequest("/a.png", relative=True))
    assert got == FetchedBytes(PNG, "image/png")


def test_bounded_wrapper_hides_fetch_bytes_when_inner_lacks_it() -> None:
    assert not isinstance(BoundedIOLayer(_BareIO(), 2), SupportsFetchBytes)


# -- end to end: the annotation in an expression reaches the wire ---------------------------


@pytest.mark.asyncio
async def test_expression_accept_annotation_reaches_the_request_header() -> None:
    from url4.dag._run import run

    seen: list[httpx.Request] = []
    io = HttpIOLayer(client=_mock_client(_serving(b"DATA", "text/plain", seen)))
    assert await run("https://x/d;accept=text/plain", io=io) == "DATA"
    assert [r.headers["accept"] for r in seen] == ["text/plain"]
