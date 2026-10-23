"""Review round 2 of the bytes port (``OME-1538``, PR #1478): the three regressions.

FEATURE: image and PDF inputs for url4 sources (epic OME-1529).
STORY: as an engine author I rely on the text path refusing anything that is not text, on the
bounded wrapper honouring the ports' keyword signatures, and on ``;accept=`` reaching the wire
for every source form, including a remote expression.
"""

from __future__ import annotations

import httpx
import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag import compile_expression
from url4.dag._context import BoundedIOLayer
from url4.dag._run import run
from url4.dag.nodes import RemoteFetchNode
from url4.io.http import HttpIOLayer
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes, bare_media_type, is_text_media_type, require_text
from url4.io.static import StaticIOLayer

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xff\xfe\x00\x01"

# The reviewer's adversarial values: none of them may reach response.text.
ADVERSARIAL = [
    "image/png; charset=utf-8",
    "application/octet-stream; charset=utf-8",
    'application/pdf; name="x;charset=utf-8"',
    "text/plain, image/png",  # HTTPX comma-joins duplicate Content-Type fields
    "text/",
]


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _serving(headers: list[tuple[str, str]], body: bytes = PNG, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, content=body, headers=headers)

    return handler


# -- finding 1: the text/binary guard fails closed ----------------------------------------


@pytest.mark.parametrize(
    "content_type",
    [
        *ADVERSARIAL,
        "IMAGE/PNG; CHARSET=utf-8",
        "audio/wav; charset=utf-8",
        "video/mp4; charset=utf-8",
        "font/woff2; charset=utf-8",
        "multipart/mixed; charset=utf-8",
        "application/zip; charset=utf-8",
        "text/plain, text/plain",
        "text",
        "/plain",
        "text/plain/x",
        "text/pl ain",
        "text/plain; charset",
        'text/plain; charset="utf-8',
        "teéxt/plain",
    ],
)
def test_binary_duplicate_or_invalid_types_are_not_text(content_type: str) -> None:
    # INVARIANT: a charset never turns an intrinsically binary type into text, and a value that
    # is not exactly one RFC 9110 media type is never text.
    assert is_text_media_type(content_type) is False
    with pytest.raises(ResolutionError) as caught:
        require_text("https://x/f", content_type)
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert caught.value.permanent is True


@pytest.mark.parametrize(
    "content_type",
    [
        'text/plain; name="a,b"',  # a comma inside a quoted-string is not a second value
        'application/vnd.x; title="semi;colon"; charset=utf-8',
        'text/plain ; charset="utf-8"',
        "text/plain;",
        "application/vnd.custom; CHARSET=utf-8",
    ],
)
def test_quoted_and_spaced_parameters_still_parse_as_text(content_type: str) -> None:
    assert is_text_media_type(content_type) is True


def test_a_quoted_parameter_cannot_invent_a_charset() -> None:
    # Only a real `charset` parameter counts; one hidden inside a quoted value does not.
    assert is_text_media_type('application/vnd.x; name="x;charset=utf-8"') is False
    assert is_text_media_type('application/vnd.x; name="x"; charset=utf-8') is True


@pytest.mark.parametrize(
    ("content_type", "bare"),
    [
        (None, None),
        ("", None),
        ("IMAGE/PNG; charset=utf-8", "image/png"),
        ('application/pdf; name="x;charset=utf-8"', "application/pdf"),
        ('text/plain; name="a,b"', "text/plain"),
    ],
)
def test_bare_media_type_is_one_validated_type(content_type: str | None, bare: str | None) -> None:
    assert bare_media_type("https://x/f", content_type) == bare


@pytest.mark.parametrize("content_type", ["text/plain, image/png", "text/", "image/png,"])
def test_bare_media_type_refuses_a_joined_or_invalid_value(content_type: str) -> None:
    with pytest.raises(ResolutionError) as caught:
        bare_media_type("https://x/f", content_type)
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert caught.value.permanent is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        [("content-type", "image/png; charset=utf-8")],
        [("content-type", "application/octet-stream; charset=utf-8")],
        [("content-type", 'application/pdf; name="x;charset=utf-8"')],
        [("content-type", "text/plain"), ("content-type", "image/png")],
        [("content-type", "text/")],
    ],
)
async def test_http_text_paths_refuse_adversarial_content_types(
    headers: list[tuple[str, str]],
) -> None:
    io = HttpIOLayer(client=_client(_serving(headers)))
    for call in (io.fetch("https://x/f", relative=False), io.fetch_ex(FetchRequest("https://x/f"))):
        with pytest.raises(ResolutionError) as caught:
            await call
        assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE


@pytest.mark.asyncio
async def test_http_fetch_bytes_reports_the_bare_type_of_a_binary_with_charset() -> None:
    io = HttpIOLayer(client=_client(_serving([("content-type", "image/png; charset=utf-8")])))
    assert await io.fetch_bytes(FetchRequest("https://x/f")) == FetchedBytes(PNG, "image/png")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        [("content-type", "text/plain"), ("content-type", "image/png")],
        [("content-type", "text/")],
    ],
)
async def test_http_fetch_bytes_never_exposes_a_joined_or_invalid_type(
    headers: list[tuple[str, str]],
) -> None:
    io = HttpIOLayer(client=_client(_serving(headers)))
    with pytest.raises(ResolutionError) as caught:
        await io.fetch_bytes(FetchRequest("https://x/f"))
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert caught.value.permanent is True


# -- finding 2: BoundedIOLayer honours the ports' keyword signatures ----------------------


@pytest.mark.asyncio
async def test_bounded_wrapper_forwards_keyword_calls_to_every_optional_port() -> None:
    inner = StaticIOLayer(
        {"/t": "text", "/a.png": PNG},
        holdings={"me/docs": "HELD"},
        media_types={"/t": "text/plain", "/a.png": "image/png"},
    )
    # getattr: the ports are bound per instance, so the class declares them loosely.
    io = BoundedIOLayer(inner, 1)
    fetch_ex = getattr(io, "fetch_ex")
    fetch_bytes = getattr(io, "fetch_bytes")
    fetch_holdings = getattr(io, "fetch_holdings")
    got_ex = await fetch_ex(request=FetchRequest("/t", relative=True))
    assert got_ex == FetchResult("text", media_type="text/plain")
    got_bytes = await fetch_bytes(request=FetchRequest("/a.png", relative=True))
    assert got_bytes == FetchedBytes(PNG, "image/png")
    assert await fetch_holdings(identity="me", collection="docs") == "HELD"


# -- finding 3: ;accept= on a remote-expression source reaches the wire -------------------

REMOTE = "url4://n2.example/solve?q=(ctx)!go;accept=application/json"


def test_remote_expression_lowering_keeps_the_accept_annotation() -> None:
    node = compile_expression(REMOTE).sink.deps["src:0"]
    assert isinstance(node, RemoteFetchNode)
    assert node.accept == "application/json"


@pytest.mark.asyncio
async def test_remote_expression_accept_reaches_the_http_request() -> None:
    seen: list[httpx.Request] = []
    handler = _serving([("content-type", "application/json")], b'{"a":1}', seen)
    io = HttpIOLayer(client=_client(handler))
    assert await run(REMOTE, io=io) == '{"a":1}'
    assert [(str(r.url), r.headers["accept"]) for r in seen] == [
        ("https://n2.example/solve?q=(ctx)!go", "application/json")
    ]


@pytest.mark.asyncio
async def test_remote_expression_without_accept_keeps_the_client_default() -> None:
    seen: list[httpx.Request] = []
    handler = _serving([("content-type", "application/json")], b"{}", seen)
    await run("url4://n2.example/solve?q=(ctx)!go", io=HttpIOLayer(client=_client(handler)))
    assert [r.headers["accept"] for r in seen] == ["*/*"]
