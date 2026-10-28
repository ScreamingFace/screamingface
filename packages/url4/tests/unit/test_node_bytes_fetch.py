"""A url4 node is a binary-safe io layer: https attachments and binary ``[data]`` files work on it.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; local end-to-end run
2026-10-28).
STORY: as an operator running ``url4 serve`` I put a PNG behind an ``https`` attachment source
(``;accept=image/png``) or in a ``[data]`` file served at ``/blob/sha256/<hex>``, and the node
fetches it as bytes, through the destination guard, and attaches it, instead of refusing it with a
misleading ``unsupported_content_type`` or failing with a 500.

No network: the guarded transport's inner transport is a mock and DNS is a fake resolver.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
import url4.io.http as http_mod
from url4.cli._serve import ProviderSpec, ServeConfig, build_node
from url4.core.errors import ErrorCode, ResolutionError
from url4.dag._run import run
from url4.dag.attachment import Attachment
from url4.io.layer import FetchRequest
from url4.io.media import FetchedBytes, SupportsFetchBytes
from url4.peer.server import Request, Url4Node

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xff\xfe-node"
PNG_HEX = hashlib.sha256(PNG).hexdigest()
IMG_URL = "https://images.example/cat.png"
PUBLIC = "93.184.215.14"
METADATA = "169.254.169.254"


class _Web:
    """The fake network: DNS answers and the mock transport's recorded requests."""

    def __init__(self, answer: str = PUBLIC) -> None:
        self.answer = answer
        self.lookups: list[str] = []
        self.sent: list[httpx.Request] = []

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        self.lookups.append(host)
        return [self.answer]

    def transport(self) -> httpx.AsyncBaseTransport:
        def record(request: httpx.Request) -> httpx.Response:
            self.sent.append(request)
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

        return httpx.MockTransport(record)


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> _Web:
    fake = _Web()
    monkeypatch.setattr(guarded_mod, "_inner_transport", fake.transport)
    # WHY the http module's name: HttpIOLayer() reads its default resolver from there.
    monkeypatch.setattr(http_mod, "system_resolver", fake.resolve)
    return fake


def _serve_node(data: dict[str, ProviderSpec] | None = None) -> Url4Node:
    """A ``url4 serve`` node (``build_node``, owned guarded httpx outbound).

    WHY a ``/model`` Python endpoint (``_model``) besides the command: a command route cannot
    observe attachments, so the expressions call ``/model(…)!…`` explicitly.
    """
    return build_node(ServeConfig(commands={"/echo": ("cat",)}, data=data or {}))


def _model(node: Url4Node) -> list[tuple[Attachment, ...]]:
    seen: list[tuple[Attachment, ...]] = []

    @node.endpoint("/model")
    def model(request: Request) -> str:
        seen.append(request.attachments)
        return "described"

    return seen


# -- bug 1: Url4Node has a binary-safe fetch_bytes ---------------------------------------


def test_a_node_is_a_binary_safe_io_layer() -> None:
    # INVARIANT: the engine reaches fetch_bytes duck-typed on ctx.io; a node must offer it.
    assert isinstance(Url4Node(), SupportsFetchBytes)


@pytest.mark.asyncio
async def test_https_attachment_source_on_a_serve_node_reaches_the_guard_and_is_attached(
    web: _Web,
) -> None:
    node = _serve_node()
    seen = _model(node)
    try:
        result = await node.evaluate(f"/model(src={IMG_URL};accept=image/png)!'describe'")
    finally:
        await node.aclose()
    assert result.text == "described"
    assert web.lookups == ["images.example"]  # the destination guard vetted the host
    assert [str(request.url.host) for request in web.sent] == [PUBLIC]
    assert seen == [(Attachment(f"sha256:{PNG_HEX}", "image/png", PNG),)]


@pytest.mark.asyncio
async def test_https_attachment_source_to_a_refused_address_fails_with_the_guard_code(
    web: _Web,
) -> None:
    web.answer = METADATA
    node = _serve_node()
    seen = _model(node)
    try:
        with pytest.raises(ResolutionError) as caught:
            await node.evaluate(f"/model(src={IMG_URL};accept=image/png)!'describe'")
    finally:
        await node.aclose()
    assert caught.value.code == ErrorCode.SOURCE_DESTINATION_BLOCKED
    assert web.sent == [] and seen == []


@pytest.mark.asyncio
async def test_node_fetch_bytes_delegates_an_absolute_target_to_its_outbound_bytes_port() -> None:
    class _Outbound:
        def __init__(self) -> None:
            self.requests: list[FetchRequest] = []

        async def fetch(self, target: str, *, relative: bool) -> str:
            raise AssertionError("the text port must not be used for bytes")

        async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
            self.requests.append(request)
            return FetchedBytes(PNG, "image/png")

    outbound = _Outbound()
    request = FetchRequest(IMG_URL, accept="image/png")
    got = await Url4Node(outbound=outbound).fetch_bytes(request)
    assert got == FetchedBytes(PNG, "image/png")
    assert outbound.requests == [request]  # passed through unchanged, accept included


class _TextOnly:
    """An io layer with a text port only."""

    async def fetch(self, target: str, *, relative: bool) -> str:
        return "text"


@pytest.mark.asyncio
async def test_node_with_a_text_only_outbound_refuses_bytes_with_unsupported_mode() -> None:
    with pytest.raises(ResolutionError) as caught:
        await Url4Node(outbound=_TextOnly()).fetch_bytes(FetchRequest(IMG_URL))
    assert caught.value.code == ErrorCode.UNSUPPORTED_MODE
    assert caught.value.permanent is True


@pytest.mark.asyncio
async def test_attachment_source_on_an_io_without_a_bytes_port_is_unsupported_mode() -> None:
    # WHY unsupported_mode: the io lacks a capability (like a code pointer on an io without
    # SupportsCode), the body's type was never seen, so it is not unsupported_content_type.
    with pytest.raises(ResolutionError) as caught:
        await run(f"(src={IMG_URL};accept=image/png)!'d'", _TextOnly(), process=_never)
    assert caught.value.code == ErrorCode.UNSUPPORTED_MODE
    assert caught.value.permanent is True


async def _never(sources: str, intent: str | None, scope: object) -> str:
    raise AssertionError("no model call before the attachment is materialized")


# -- bug 2: binary [data] files are served as bytes --------------------------------------


@pytest.mark.asyncio
async def test_binary_data_file_serves_a_verified_blob_ref_on_the_node(tmp_path) -> None:
    blob = tmp_path / "cat.png"
    blob.write_bytes(PNG)
    node = _serve_node(
        {f"/blob/sha256/{PNG_HEX}": ProviderSpec(file=str(blob), media_type="image/png")},
    )
    seen = _model(node)
    result = await node.evaluate(f"/model(img:src=/blob/sha256/{PNG_HEX})!'describe'")
    assert result.text == "described"
    assert seen == [(Attachment(f"sha256:{PNG_HEX}", "image/png", PNG),)]


@pytest.mark.asyncio
async def test_node_fetch_bytes_reads_a_data_file_exactly(tmp_path) -> None:
    blob = tmp_path / "cat.png"
    blob.write_bytes(PNG)
    node = _serve_node({"/cat": ProviderSpec(file=str(blob), media_type="image/png")})
    got = await node.fetch_bytes(FetchRequest("/cat", relative=True, kind="relative"))
    assert got == FetchedBytes(PNG, "image/png")


@pytest.mark.asyncio
async def test_node_fetch_bytes_of_a_text_route_is_its_utf8_text(tmp_path) -> None:
    node = _serve_node({"/notes": ProviderSpec(value="héllo", media_type="text/plain")})
    got = await node.fetch_bytes(FetchRequest("/notes", relative=True, kind="relative"))
    assert got == FetchedBytes("héllo".encode(), "text/plain")


@pytest.mark.asyncio
async def test_node_fetch_bytes_of_an_unknown_path_is_endpoint_not_found(tmp_path) -> None:
    node = _serve_node()
    with pytest.raises(ResolutionError) as caught:
        await node.fetch_bytes(FetchRequest("/nope", relative=True, kind="relative"))
    assert caught.value.code == ErrorCode.ENDPOINT_NOT_FOUND


@pytest.mark.asyncio
async def test_text_read_of_a_binary_data_file_is_a_typed_permanent_error(tmp_path) -> None:
    blob = tmp_path / "cat.png"
    blob.write_bytes(PNG)
    node = _serve_node({"/cat": ProviderSpec(file=str(blob))})
    with pytest.raises(ResolutionError) as caught:
        await node.fetch("/cat", relative=True)
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert caught.value.permanent is True


@pytest.mark.asyncio
async def test_text_data_file_still_reads_as_text(tmp_path) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("# héllo", encoding="utf-8")
    node = _serve_node({"/notes": ProviderSpec(file=str(notes))})
    assert await node.fetch("/notes", relative=True) == "# héllo"
