"""File refs in url4: the bare ``blob:`` token, ``/blob/sha256`` paths and ``url4://…/blob``.

FEATURE: image and PDF inputs for url4 sources (epic ``OME-1529``, unit ``OME-1539``).
STORY: as an ensemble author I name a file by its content address and the node evaluating
that level resolves it through the bytes port, never as mangled text, and never on the
outer node's behalf for a nested expression.

The conformance cases C1–C9 themselves, by name, are ``tests/spec/test_file_ref_conformance.py``;
this file covers the edges behind them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

import httpx
import pytest

from url4.core.errors import ErrorCode, ParseError, RenderError, ResolutionError
from url4.core.grammar import parse
from url4.core.nodes import Binding, BlobRef, Expression, Source, Text, Url, children, walk
from url4.core.render import render
from url4.dag._lowering import compile_expression
from url4.dag._run import run
from url4.dag.node import BoundedIOLayer, ExecutionContext
from url4.dag.nodes import RelUrlNode, WebFetchNode
from url4.dag.nodes.blob import BlobRefNode, ResolvedBlob
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

    def __init__(self, blobs: Mapping[str, bytes | str], *, blob_peers: Sequence[str] = ()) -> None:
        media = {path: "image/png" for path, body in blobs.items() if isinstance(body, bytes)}
        super().__init__(dict(blobs), media_types=media, blob_peers=blob_peers)
        self.byte_requests: list[FetchRequest] = []
        self.text_targets: list[str] = []

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.byte_requests.append(request)
        return await super().fetch_bytes(request)

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.text_targets.append(target)
        return await super().fetch(target, relative=relative)


def _store(*, blob_peers: Sequence[str] = ()) -> _Store:
    return _Store({f"/blob/sha256/{HEX}": PNG}, blob_peers=blob_peers)


async def _resolve(node: BlobRefNode, io: IOLayer) -> ResolvedBlob:
    payload = await node.resolve({}, ExecutionContext(io))
    assert isinstance(payload, ResolvedBlob)
    return payload


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
        (f"(img:src=url4://n2.example/blob/sha256/{HEX}?x=1)!'D'", WebFetchNode),
        ("(img:src=url4://n2.example/data)!'D'", WebFetchNode),
    ],
)
def test_other_uris_lower_exactly_as_before(text: str, kind: type) -> None:
    types = _leaf_types(text)
    assert kind in types
    assert BlobRefNode not in types


# -- resolution through the bytes port ----------------------------------------------------


@pytest.mark.asyncio
async def test_relative_path_resolves_to_bytes_with_the_ref_as_text() -> None:
    io = _store()
    got = await _resolve(BlobRefNode.relative_path(f"/blob/sha256/{HEX}"), io)
    assert got == f"/blob/sha256/{HEX}"
    assert (got.body, got.media_type, got.digest) == (PNG, "image/png", HEX)
    assert io.byte_requests == [FetchRequest(f"/blob/sha256/{HEX}", relative=True, kind="relative")]
    assert io.text_targets == []


@pytest.mark.asyncio
async def test_bare_token_resolves_from_the_node_own_store() -> None:
    io = _store()
    got = await _resolve(BlobRefNode.token(f"blob:sha256/{HEX}"), io)
    assert got == f"blob:sha256/{HEX}"
    assert got.body == PNG
    assert [r.target for r in io.byte_requests] == [f"/blob/sha256/{HEX}"]


@pytest.mark.asyncio
async def test_upper_case_hex_is_looked_up_lower_case_and_kept_as_written() -> None:
    io = _store()
    got = await _resolve(BlobRefNode.token(f"blob:sha256/{HEX.upper()}"), io)
    assert got == f"blob:sha256/{HEX.upper()}"
    assert [r.target for r in io.byte_requests] == [f"/blob/sha256/{HEX}"]


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
    assert (got.body, got.media_type) == (TEXT.encode(), None)
    assert io.seen == [f"/blob/sha256/{TEXT_HEX}"]


@pytest.mark.asyncio
async def test_digest_mismatch_is_refused() -> None:
    # INVARIANT: a content address that returns other content never resolves.
    io = _Store({f"/blob/sha256/{HEX}": b"not the png"})
    with pytest.raises(ResolutionError) as caught:
        await _resolve(BlobRefNode.relative_path(f"/blob/sha256/{HEX}"), io)
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.BLOB_DIGEST_MISMATCH, True)


# -- url4:// across nodes: the OME-1599 interim allowlist ---------------------------------


REMOTE = f"url4://n2.example/blob/sha256/{HEX}"


@pytest.mark.asyncio
async def test_remote_ref_fetches_from_an_allowlisted_node() -> None:
    io = _Store({REMOTE: PNG}, blob_peers=["n2.example"])
    got = await _resolve(BlobRefNode.remote(REMOTE), io)
    assert (got, got.body) == (REMOTE, PNG)
    assert io.byte_requests == [FetchRequest(REMOTE, relative=False, kind="url4")]


@pytest.mark.asyncio
async def test_allowlist_compares_authorities_case_insensitively() -> None:
    io = _Store({REMOTE: PNG}, blob_peers=["N2.Example"])
    assert (await _resolve(BlobRefNode.remote(REMOTE), io)).body == PNG


@pytest.mark.asyncio
@pytest.mark.parametrize("peers", [[], ["n3.example"], ["n2.example:8443"]])
async def test_remote_ref_to_a_node_off_the_allowlist_is_refused_without_io(
    peers: list[str],
) -> None:
    io = _Store({REMOTE: PNG}, blob_peers=peers)
    with pytest.raises(ResolutionError) as caught:
        await _resolve(BlobRefNode.remote(REMOTE), io)
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.BLOB_PEER_NOT_ALLOWED, True)
    assert io.byte_requests == []


@pytest.mark.asyncio
async def test_an_adapter_with_no_allowlist_capability_allows_no_peer() -> None:
    # INVARIANT (fail closed): no declared allowlist means no cross-node blob fetch at all.
    class _Bare:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch(self, target: str, *, relative: bool) -> str:
            self.calls += 1
            return ""

    io = _Bare()
    with pytest.raises(ResolutionError) as caught:
        await _resolve(BlobRefNode.remote(REMOTE), io)
    assert caught.value.code == ErrorCode.BLOB_PEER_NOT_ALLOWED
    assert io.calls == 0


@pytest.mark.asyncio
async def test_remote_missing_bytes_are_source_not_found() -> None:
    io = _Store({}, blob_peers=["n2.example"])
    with pytest.raises(ResolutionError) as caught:
        await _resolve(BlobRefNode.remote(REMOTE), io)
    assert caught.value.code == ErrorCode.SOURCE_NOT_FOUND


@pytest.mark.asyncio
async def test_run_wide_bounded_wrapper_forwards_the_allowlist() -> None:
    io = _Store({REMOTE: PNG}, blob_peers=["n2.example"])
    seen: list[str] = []

    async def model(sources: str, intent: str | None, scope: object) -> str:
        seen.append(sources)
        return "ok"

    assert await run(f"(img:src={REMOTE})!'Describe'", io=io, process=model) == "ok"
    assert seen == [f"img: {REMOTE}"]
    assert len(io.byte_requests) == 1


def test_bounded_wrapper_hides_the_allowlist_when_inner_lacks_it() -> None:
    class _Bare:
        async def fetch(self, target: str, *, relative: bool) -> str:
            return ""

    assert not hasattr(BoundedIOLayer(_Bare(), 2), "blob_peer_allowed")
    assert getattr(BoundedIOLayer(_store(blob_peers=["a"]), 2), "blob_peer_allowed")("a") is True


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


def test_http_blob_peers_allowlist() -> None:
    io = HttpIOLayer(blob_peers=["N2.example", "n3.example:8443"])
    assert io.blob_peer_allowed("n2.example") is True
    assert io.blob_peer_allowed("n3.example:8443") is True
    assert io.blob_peer_allowed("n3.example") is False
    assert HttpIOLayer().blob_peer_allowed("n2.example") is False


@pytest.mark.asyncio
async def test_static_fetch_bytes_miss_is_source_not_found_but_text_miss_is_unchanged() -> None:
    io = StaticIOLayer()
    with pytest.raises(ResolutionError) as caught:
        await io.fetch_bytes(FetchRequest("/none", relative=True))
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.SOURCE_NOT_FOUND, True)
    with pytest.raises(ResolutionError) as text_miss:
        await io.fetch("/none", relative=True)
    assert (text_miss.value.code, text_miss.value.permanent) == (ErrorCode.RESOLUTION_FAILED, False)


def test_static_blob_peers_default_to_none() -> None:
    assert StaticIOLayer().blob_peer_allowed("n2.example") is False


def test_source_not_found_is_a_404() -> None:
    assert status_for_code(ErrorCode.SOURCE_NOT_FOUND, permanent=True) == 404


# -- collection position (C8 edge) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_text_blob_still_iterates_as_a_collection() -> None:
    body = '["a", "b"]'
    digest = hashlib.sha256(body.encode()).hexdigest()
    io = StaticIOLayer(
        {f"/blob/sha256/{digest}": body.encode()},
        media_types={f"/blob/sha256/{digest}": "application/json"},
    )
    got = await run(f"/blob/sha256/{digest}*('row $item')!'go'", io=io)
    assert "row a" in got and "row b" in got


@pytest.mark.asyncio
async def test_resolved_blob_is_plain_text_to_a_text_consumer() -> None:
    blob = ResolvedBlob("blob:sha256/x", body=b"\x00", media_type="image/png", digest="x")
    assert isinstance(blob, str)
    assert blob + "!" == "blob:sha256/x!"
    assert FetchResult(blob).body == "blob:sha256/x"


# -- the interim allowlist cannot be bypassed by a redirect ---------------------------------


@pytest.mark.asyncio
async def test_url4_fetch_bytes_never_follows_a_redirect_off_the_named_node() -> None:
    # SECURITY (OME-1599 interim rule): an allowlisted node must not redirect the fetch to
    # a host the allowlist never named, so a url4:// bytes fetch refuses any 3xx.
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://evil.example/x"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    io = HttpIOLayer(client=client, blob_peers=["n2.example"])
    with pytest.raises(ResolutionError) as caught:
        await io.fetch_bytes(FetchRequest(REMOTE, kind="url4"))
    assert caught.value.permanent is True
    assert seen == [f"https://n2.example/blob/sha256/{HEX}"]


@pytest.mark.asyncio
async def test_https_fetch_bytes_still_follows_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://x/new"})
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    got = await HttpIOLayer(client=client).fetch_bytes(FetchRequest("https://x/old"))
    assert got == FetchedBytes(PNG, "image/png")


@pytest.mark.asyncio
async def test_url4_fetch_bytes_server_errors_stay_transient() -> None:
    io = HttpIOLayer(client=_client(503), blob_peers=["n2.example"])
    with pytest.raises(ResolutionError) as caught:
        await io.fetch_bytes(FetchRequest(REMOTE, kind="url4"))
    assert caught.value.permanent is False


# -- addressing and the collection boundary ------------------------------------------------


def test_address_of_a_token_and_of_a_non_ref() -> None:
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
    assert remote is not None and remote.target == REMOTE


def test_blob_lowering_refuses_another_node_type() -> None:
    from url4.dag._lowering import _lower_blob_ref, default_registry

    with pytest.raises(TypeError):
        _lower_blob_ref(Text("x"), {}, default_registry())


@pytest.mark.parametrize("ref", ["/data/x", "url4://n2.example/data"])
def test_named_constructors_refuse_a_non_ref(ref: str) -> None:
    make = BlobRefNode.remote if ref.startswith("url4") else BlobRefNode.relative_path
    with pytest.raises(ValueError):
        make(ref)


def test_a_text_typed_blob_that_is_not_utf8_cannot_be_a_collection() -> None:
    from url4.dag.nodes.blob import collection_body

    blob = ResolvedBlob("blob:sha256/x", body=b"\xff\xfe", media_type="text/plain", digest="x")
    with pytest.raises(ResolutionError) as caught:
        collection_body(blob)
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert collection_body("plain") == "plain"


# -- the public surface ----------------------------------------------------------------------


def test_the_builder_classifies_the_token() -> None:
    # BlobRef stays in url4.core.nodes: the top-level export count is pinned (hygiene ratchet).
    import url4

    built = url4.expr(url4.src(f"blob:sha256/{HEX}", name="img"), intent="Describe")
    assert url4.render(built).startswith(f"(img=blob:sha256/{HEX})!")
    assert url4.build(url4.render(built)) == built
