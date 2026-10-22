"""File refs in url4: the bare ``blob:`` token, ``/blob/sha256`` paths and ``url4://…/blob``.

FEATURE: image and PDF inputs for url4 sources (epic ``OME-1529``, unit ``OME-1539``).
STORY: as an ensemble author I name a file by its content address and the node evaluating
that level resolves it through the bytes port into a typed attachment, never as mangled text,
and never on the outer node's behalf for a nested expression.

v1 (#1450 spec §2 F1/F2, owner decisions D1/D2 2026-10-21): every ``url4://…/blob`` ref is
remote and refused before any I/O; a local ref resolves to an :class:`Attachment`, and the
payload stays a plain ``str``.

The conformance cases C1–C9 themselves, by name, are ``tests/spec/test_file_ref_conformance.py``;
this file covers the edges behind them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

import httpx
import pytest

from url4.core.errors import ErrorCode, ParseError, RenderError, ResolutionError
from url4.core.grammar import parse
from url4.core.nodes import Binding, BlobRef, Expression, Source, Text, Url, children, walk
from url4.core.render import render
from url4.dag._lowering import compile_expression
from url4.dag._run import run
from url4.dag.attachment import Attachment
from url4.dag.node import BoundedIOLayer, ExecutionContext
from url4.dag.nodes import RelUrlNode, WebFetchNode
from url4.dag.nodes.blob import BlobRefNode
from url4.io.http import HttpIOLayer
from url4.io.layer import FetchRequest, FetchResult, IOLayer
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer
from url4.peer._http import status_for_code

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR-4827"
HEX = hashlib.sha256(PNG).hexdigest()
TEXT = "ZEBRA-4127"
TEXT_HEX = hashlib.sha256(TEXT.encode()).hexdigest()


class _Store(StaticIOLayer):
    """A fake blob store: a ``StaticIOLayer`` that records every request it serves."""

    def __init__(self, blobs: Mapping[str, bytes | str]) -> None:
        media = {path: "image/png" for path, body in blobs.items() if isinstance(body, bytes)}
        super().__init__(dict(blobs), media_types=media)
        self.byte_requests: list[FetchRequest] = []
        self.text_targets: list[str] = []

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.byte_requests.append(request)
        return await super().fetch_bytes(request)

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.text_targets.append(target)
        return await super().fetch(target, relative=relative)

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.text_targets.append(request.target)
        return await super().fetch_ex(request)


def _store() -> _Store:
    return _Store({f"/blob/sha256/{HEX}": PNG})


async def _resolve(node: BlobRefNode, io: IOLayer) -> Attachment:
    return await node.attachment(ExecutionContext(io))


# -- grammar: a bare token is a BlobRef, distinct from quoted text ------------------------


def test_bare_token_parses_to_blob_ref() -> None:
    tree = parse(f"(img:src=blob:sha256/{HEX})!'Describe'")
    assert isinstance(tree, Expression)
    assert tree.sources == (Binding("img", BlobRef(f"blob:sha256/{HEX}"), ":"),)


def test_quoted_token_stays_text() -> None:
    tree = parse(f"(img:'blob:sha256/{HEX}')!'Describe'")
    assert isinstance(tree, Expression)
    assert tree.sources == (Binding("img", Text(f"blob:sha256/{HEX}"), ":"),)


def test_bare_and_quoted_are_different_trees() -> None:
    assert parse(f"(src=blob:sha256/{HEX})!'D'") != parse(f"('blob:sha256/{HEX}')!'D'")


def test_bare_token_without_src_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        parse(f"(blob:sha256/{HEX})!'Describe'")


@pytest.mark.parametrize(
    "token",
    [
        "blob:sha256/",
        "blob:/abc",
        "blob:SHA256/abc",
        "blob:sha256/a.b",
        "blob:sha256/a/b",
        "blob:-x/abc",
        "blobs:sha256/abc",
    ],
)
def test_a_token_that_is_not_blob_shaped_stays_text(token: str) -> None:
    tree = parse(f"(src={token})!'D'")
    assert isinstance(tree, Expression)
    assert tree.sources == (Text(token),)


def test_identifier_algorithms_other_than_sha256_still_parse() -> None:
    tree = parse("(img=blob:sha3-256/Ab_9-x)!'D'")
    assert isinstance(tree, Expression)
    assert tree.sources == (Binding("img", BlobRef("blob:sha3-256/Ab_9-x"), "="),)


def test_blob_ref_is_a_leaf() -> None:
    ref = BlobRef(f"blob:sha256/{HEX}")
    assert children(ref) == ()
    assert list(walk(ref)) == [ref]


def test_intent_position_token_stays_text() -> None:
    tree = parse(f"('a')!blob:sha256/{HEX}")
    assert isinstance(tree, Expression)
    assert not isinstance(tree.intent, BlobRef)


# -- render: unquoted round trip -----------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        f"(img:src=blob:sha256/{HEX})!'Describe'",
        f"(img=blob:sha256/{HEX})!'Describe'",
        f"(img:0.5:src=blob:sha256/{HEX})!'Describe'",
        f"(src=blob:sha256/{HEX})!'Describe'",
        f"(src=blob:sha256/{HEX};optional)!'Describe'",
        f"(img:'blob:sha256/{HEX}')!'Describe'",
    ],
)
def test_render_round_trips_bare_and_quoted(text: str) -> None:
    assert render(parse(text)) == text
    assert parse(render(parse(text))) == parse(text)


def test_hand_built_bare_source_renders_with_src() -> None:
    tree = Expression((BlobRef(f"blob:sha256/{HEX}"),), intent=Text("D"))
    assert render(tree) == f"(src=blob:sha256/{HEX})!'D'"


def test_hand_built_weighted_source_renders_with_src() -> None:
    tree = Expression(
        (Source(BlobRef(f"blob:sha256/{HEX}"), name="img", weight=0.5),), intent=Text("D")
    )
    assert render(tree) == f"(img:0.5:src=blob:sha256/{HEX})!'D'"


@pytest.mark.parametrize("value", ["blob:sha256/", "sha256/abc", "blob:sha256/a,b", "'x'"])
def test_render_refuses_a_malformed_blob_ref(value: str) -> None:
    with pytest.raises(RenderError):
        render(Expression((BlobRef(value),), intent=Text("D")))


def test_render_refuses_a_blob_ref_intent() -> None:
    # INVARIANT: intent_atom never produces a BlobRef, so rendering one could not reparse.
    with pytest.raises(RenderError):
        render(Expression((Text("a"),), intent=BlobRef(f"blob:sha256/{HEX}")))


# -- lowering: only blob-shaped refs change ----------------------------------------------


def _leaf_types(text: str) -> set[type]:
    return {type(node) for node in compile_expression(text).walk()}


@pytest.mark.parametrize(
    "text",
    [
        f"(img:src=blob:sha256/{HEX})!'D'",
        f"(img:src=/blob/sha256/{HEX})!'D'",
        f"(img:src=url4://n2.example/blob/sha256/{HEX})!'D'",
        f"(img:src=url4://n2.example/blob/sha256/{HEX}?x=1)!'D'",
        "(img:src=url4://n2.example/blob/md5/abc)!'D'",
        "(img:src=url4://n2.example/blob)!'D'",
        f"(img:0.5:src=/blob/sha256/{HEX.upper()})!'D'",
    ],
)
def test_file_refs_lower_to_the_blob_node(text: str) -> None:
    types = _leaf_types(text)
    assert BlobRefNode in types
    assert not types & {RelUrlNode, WebFetchNode}


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("(img:src=/blob/md5/abc)!'D'", RelUrlNode),
        (f"(img:src=/blob/sha256/{HEX[:-1]})!'D'", RelUrlNode),
        (f"(img:src=/blob/sha256/{HEX}/x)!'D'", RelUrlNode),
        ("(img:src=/data/x)!'D'", RelUrlNode),
        (f"(img:src=https://n2.example/blob/sha256/{HEX})!'D'", WebFetchNode),
        ("(img:src=url4://n2.example/data)!'D'", WebFetchNode),
        ("(img:src=url4://n2.example/blobs/x)!'D'", WebFetchNode),
    ],
)
def test_other_uris_lower_exactly_as_before(text: str, kind: type) -> None:
    types = _leaf_types(text)
    assert kind in types
    assert BlobRefNode not in types


# -- resolution at the evaluating node: a typed attachment (D2 / F2) ---------------------


@pytest.mark.asyncio
async def test_relative_path_resolves_to_a_typed_attachment() -> None:
    io = _store()
    got = await _resolve(BlobRefNode.relative_path(f"/blob/sha256/{HEX}"), io)
    assert got == Attachment(digest=f"sha256:{HEX}", media_type="image/png", body=PNG)
    assert (got.filename, got.detail, got.body) == (None, None, PNG)
    assert io.byte_requests == [FetchRequest(f"/blob/sha256/{HEX}", relative=True, kind="relative")]
    assert io.text_targets == []


def test_attachment_repr_never_carries_the_bytes() -> None:
    got = Attachment(digest=f"sha256:{HEX}", media_type="image/png", body=PNG)
    assert "IHDR" not in repr(got)
    # INVARIANT: identity is the verified digest + metadata, not a second copy of the bytes.
    assert got == Attachment(digest=f"sha256:{HEX}", media_type="image/png", body=b"")


@pytest.mark.asyncio
async def test_resolve_yields_the_ref_as_a_plain_str_payload() -> None:
    # INVARIANT (D2): no bytes ride on a str subclass -- the payload is exactly ``str``.
    io = _store()
    ref = f"blob:sha256/{HEX}"
    payload = await BlobRefNode.token(ref).resolve({}, ExecutionContext(io))
    assert type(payload) is str
    assert payload == ref
    assert [r.target for r in io.byte_requests] == [f"/blob/sha256/{HEX}"]


@pytest.mark.asyncio
async def test_bare_token_resolves_from_the_node_own_store() -> None:
    io = _store()
    got = await _resolve(BlobRefNode.token(f"blob:sha256/{HEX}"), io)
    assert (got.digest, got.body) == (f"sha256:{HEX}", PNG)
    assert [r.target for r in io.byte_requests] == [f"/blob/sha256/{HEX}"]


@pytest.mark.asyncio
async def test_upper_case_hex_is_looked_up_lower_case_and_kept_as_written() -> None:
    io = _store()
    node = BlobRefNode.token(f"blob:sha256/{HEX.upper()}")
    got = await _resolve(node, io)
    assert got.digest == f"sha256:{HEX}"
    assert await node.resolve({}, ExecutionContext(io)) == f"blob:sha256/{HEX.upper()}"
    assert {r.target for r in io.byte_requests} == {f"/blob/sha256/{HEX}"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token", ["blob:md5/abc", f"blob:sha256/{HEX[:-1]}", f"blob:sha256/{HEX}0", "blob:sha256/zz"]
)
async def test_a_token_no_store_can_hold_is_source_not_found_without_io(token: str) -> None:
    io = _store()
    with pytest.raises(ResolutionError) as caught:
        await _resolve(BlobRefNode.token(token), io)
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.SOURCE_NOT_FOUND, True)
    assert io.byte_requests == []


@pytest.mark.asyncio
async def test_missing_bytes_are_source_not_found() -> None:
    with pytest.raises(ResolutionError) as caught:
        await _resolve(BlobRefNode.token(f"blob:sha256/{TEXT_HEX}"), _store())
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.SOURCE_NOT_FOUND, True)


@pytest.mark.asyncio
async def test_a_node_endpoint_not_found_reads_as_source_not_found() -> None:
    class _Node:
        async def fetch(self, target: str, *, relative: bool) -> str:
            raise ResolutionError("no route", code=ErrorCode.ENDPOINT_NOT_FOUND, permanent=True)

    with pytest.raises(ResolutionError) as caught:
        await _resolve(BlobRefNode.token(f"blob:sha256/{HEX}"), _Node())
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.SOURCE_NOT_FOUND, True)


@pytest.mark.asyncio
async def test_other_store_failures_pass_through_unchanged() -> None:
    class _Down:
        async def fetch(self, target: str, *, relative: bool) -> str:
            raise ResolutionError("store down")

    with pytest.raises(ResolutionError) as caught:
        await _resolve(BlobRefNode.token(f"blob:sha256/{HEX}"), _Down())
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.RESOLUTION_FAILED, False)


@pytest.mark.asyncio
async def test_an_adapter_without_fetch_bytes_falls_back_to_text() -> None:
    class _TextNode:
        def __init__(self) -> None:
            self.seen: list[str] = []

        async def fetch(self, target: str, *, relative: bool) -> str:
            self.seen.append(target)
            return TEXT

    io = _TextNode()
    got = await _resolve(BlobRefNode.token(f"blob:sha256/{TEXT_HEX}"), io)
    # F2 requires a media type: an adapter that reports none gives the generic octet stream.
    assert (got.body, got.media_type) == (TEXT.encode(), "application/octet-stream")
    assert io.seen == [f"/blob/sha256/{TEXT_HEX}"]


@pytest.mark.asyncio
async def test_digest_mismatch_is_refused() -> None:
    # INVARIANT: a content address that returns other content never resolves.
    io = _Store({f"/blob/sha256/{HEX}": b"not the png"})
    with pytest.raises(ResolutionError) as caught:
        await _resolve(BlobRefNode.relative_path(f"/blob/sha256/{HEX}"), io)
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.BLOB_DIGEST_MISMATCH, True)


@pytest.mark.asyncio
async def test_digest_mismatch_fails_the_run_too() -> None:
    io = _Store({f"/blob/sha256/{HEX}": b"not the png"})
    with pytest.raises(ResolutionError) as caught:
        await run(f"(img:src=blob:sha256/{HEX})!'D'", io=io)
    assert caught.value.code == ErrorCode.BLOB_DIGEST_MISMATCH


# -- url4:// blob refs: remote, unsupported in v1 (D1 / F1) --------------------------------


REMOTE = f"url4://n2.example/blob/sha256/{HEX}"


class _Tripwire:
    """An io on which ANY call is a failure: proves a refusal happens before I/O."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.calls.append(target)
        return ""

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.calls.append(request.target)
        return FetchResult("")

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.calls.append(request.target)
        return FetchedBytes(PNG, "image/png")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ref",
    [
        REMOTE,
        f"url4://N2.Example:8443/blob/sha256/{HEX}",
        f"url4://user@n2.example/blob/sha256/{HEX}",
        f"url4://localhost/blob/sha256/{HEX}",
        f"url4://self/blob/sha256/{HEX}",
        f"url4://127.0.0.1:4761/blob/sha256/{HEX}",
        f"url4://n2.example/blob/sha256/{HEX}?x=1",
        "url4://n2.example/blob/md5/abc",
        "url4://n2.example/blob",
    ],
)
async def test_any_url4_blob_ref_is_remote_blob_unsupported_with_zero_io(ref: str) -> None:
    io = _Tripwire()
    with pytest.raises(ResolutionError) as caught:
        await BlobRefNode.remote(ref).resolve({}, ExecutionContext(io))
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.REMOTE_BLOB_UNSUPPORTED,
        True,
    )
    assert caught.value.code == "x.remote_blob_unsupported"
    assert io.calls == []


@pytest.mark.asyncio
async def test_a_remote_ref_is_refused_by_the_run_before_any_io_or_model_call() -> None:
    io, seen = _Tripwire(), []

    async def model(sources: str, intent: str | None, scope: object) -> str:
        seen.append(sources)
        return "ok"

    with pytest.raises(ResolutionError) as caught:
        await run(f"(img:src={REMOTE})!'Describe'", io=io, process=model)
    assert caught.value.code == ErrorCode.REMOTE_BLOB_UNSUPPORTED
    assert (io.calls, seen) == ([], [])


@pytest.mark.asyncio
async def test_a_remote_ref_has_no_attachment_either() -> None:
    io = _Tripwire()
    with pytest.raises(ResolutionError) as caught:
        await _resolve(BlobRefNode.remote(REMOTE), io)
    assert caught.value.code == ErrorCode.REMOTE_BLOB_UNSUPPORTED
    assert io.calls == []


def test_no_adapter_offers_a_blob_peer_allowlist_any_more() -> None:
    # The OME-1599 interim allowlist is gone with the remote fetch (D1).
    for io in (StaticIOLayer(), HttpIOLayer(), BoundedIOLayer(StaticIOLayer(), 2)):
        assert not hasattr(io, "blob_peer_allowed")


# -- adapters ----------------------------------------------------------------------------


def _client(status: int) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(status)))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 410])
async def test_http_fetch_bytes_reports_a_missing_source(status: int) -> None:
    io = HttpIOLayer(client=_client(status))
    with pytest.raises(ResolutionError) as caught:
        await io.fetch_bytes(FetchRequest("https://x/blob"))
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.SOURCE_NOT_FOUND, True)


@pytest.mark.asyncio
async def test_http_text_fetch_keeps_its_404_code() -> None:
    # Other URIs behave exactly as today: only the bytes path names a missing source.
    io = HttpIOLayer(client=_client(404))
    with pytest.raises(ResolutionError) as caught:
        await io.fetch_ex(FetchRequest("https://x/page"))
    assert caught.value.code == ErrorCode.RESOLUTION_FAILED


@pytest.mark.asyncio
async def test_http_fetch_bytes_other_errors_keep_their_code() -> None:
    io = HttpIOLayer(client=_client(500))
    with pytest.raises(ResolutionError) as caught:
        await io.fetch_bytes(FetchRequest("https://x/blob"))
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.RESOLUTION_FAILED, False)


@pytest.mark.asyncio
async def test_static_fetch_bytes_miss_is_source_not_found_but_text_miss_is_unchanged() -> None:
    io = StaticIOLayer()
    with pytest.raises(ResolutionError) as caught:
        await io.fetch_bytes(FetchRequest("/none", relative=True))
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.SOURCE_NOT_FOUND, True)
    with pytest.raises(ResolutionError) as text_miss:
        await io.fetch("/none", relative=True)
    assert (text_miss.value.code, text_miss.value.permanent) == (ErrorCode.RESOLUTION_FAILED, False)


def test_source_not_found_is_a_404() -> None:
    assert status_for_code(ErrorCode.SOURCE_NOT_FOUND, permanent=True) == 404


@pytest.mark.asyncio
async def test_https_fetch_bytes_still_follows_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://x/new"})
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    got = await HttpIOLayer(client=client).fetch_bytes(FetchRequest("https://x/old"))
    assert got == FetchedBytes(PNG, "image/png")


# -- collection position: a text blob is text, not an attachment (D4 / C8) ---------------


def _json_blob() -> tuple[str, StaticIOLayer]:
    body = '["a", "b"]'
    path = f"/blob/sha256/{hashlib.sha256(body.encode()).hexdigest()}"
    return path, StaticIOLayer({path: body.encode()}, media_types={path: "application/json"})


@pytest.mark.asyncio
async def test_a_text_blob_still_iterates_as_a_collection() -> None:
    path, io = _json_blob()
    got = await run(f"{path}*('row $item')!'go'", io=io)
    assert "row a" in got and "row b" in got


@pytest.mark.asyncio
async def test_a_text_blob_expands_as_a_collection() -> None:
    path, io = _json_blob()
    seen: list[str] = []

    async def model(sources: str, intent: str | None, scope: object) -> str:
        seen.append(sources)
        return "ok"

    assert await run(f"(*src={path})!'go'", io=io, process=model) == "ok"
    (sources,) = seen
    assert "a" in sources and "b" in sources and path not in sources


@pytest.mark.asyncio
async def test_a_text_typed_blob_that_is_not_utf8_cannot_be_a_collection() -> None:
    body = b"\xff\xfe"
    path = f"/blob/sha256/{hashlib.sha256(body).hexdigest()}"
    io = StaticIOLayer({path: body}, media_types={path: "text/plain"})
    with pytest.raises(ResolutionError) as caught:
        await run(f"{path}*('row $item')!'go'", io=io)
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE


@pytest.mark.asyncio
async def test_an_untyped_blob_in_collection_position_is_read_as_text() -> None:
    body = "x\ny"
    path = f"/blob/sha256/{hashlib.sha256(body.encode()).hexdigest()}"
    got = await run(f"{path}*('row $item')!'go'", io=StaticIOLayer({path: body.encode()}))
    assert "row x" in got and "row y" in got


# -- addressing ------------------------------------------------------------------------------


def test_address_of_a_token_a_remote_ref_and_a_non_ref() -> None:
    from url4.core.blob_ref import address_of

    address = address_of(BlobRef(f"blob:sha256/{HEX.upper()}"))
    assert address is not None
    assert (address.form, address.digest, address.target) == (
        "token",
        HEX,
        f"/blob/sha256/{HEX}",
    )
    assert address_of(Text(f"blob:sha256/{HEX}")) is None
    remote = address_of(Url(REMOTE))
    assert remote is not None
    assert (remote.form, remote.authority, remote.digest) == ("remote", "n2.example", None)


def test_blob_lowering_refuses_another_node_type() -> None:
    from url4.dag._lowering import _lower_blob_ref, default_registry

    with pytest.raises(TypeError):
        _lower_blob_ref(Text("x"), {}, default_registry())


@pytest.mark.parametrize("ref", ["/data/x", "url4://n2.example/data"])
def test_named_constructors_refuse_a_non_ref(ref: str) -> None:
    make = BlobRefNode.remote if ref.startswith("url4") else BlobRefNode.relative_path
    with pytest.raises(ValueError):
        make(ref)


# -- the public surface ----------------------------------------------------------------------


def test_the_builder_classifies_the_token() -> None:
    # BlobRef stays in url4.core.nodes: the top-level export count is pinned (hygiene ratchet).
    import url4

    built = url4.expr(url4.src(f"blob:sha256/{HEX}", name="img"), intent="Describe")
    assert url4.render(built).startswith(f"(img=blob:sha256/{HEX})!")
    assert url4.build(url4.render(built)) == built
