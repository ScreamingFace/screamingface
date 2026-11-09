"""A blob ref is classified on its NORMALIZED path, so no dot-segment alias reaches the wire.

FEATURE: file refs in url4 sources (epic ``OME-1529``, unit ``OME-1539``; #1450 spec §2 F1).
STORY: as a node operator I rely on every ``url4://<authority>/blob/…`` ref being refused
before any DNS, connection or store I/O — however the author spells the path.

WHY (PR #1482 review, 2026-11-02): the classifier matched only a raw path starting with
``/blob``. ``url4://n/x/../blob/sha256/<hex>`` lowered as a plain web fetch, and HTTPX 0.28
removed the dot segments before transport, so ``https://n/blob/sha256/<hex>`` was fetched and
its body reached the model with no ``x.remote_blob_unsupported``.

INVARIANT: these tests drive the REAL :class:`~url4.io.http.HttpIOLayer` over an
``httpx.MockTransport``; for a remote ref the transport fails the test on any request, so
HTTPX's own normalization is covered, not only the pure classifier.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable

import httpx
import pytest

from url4.core.blob_ref import address_of
from url4.core.errors import ErrorCode, ParseError, ResolutionError
from url4.core.grammar import parse
from url4.core.nodes import Binding, Expression, Node, RelUrl, Text, Url
from url4.dag._lowering import compile_expression
from url4.dag._run import run
from url4.dag.nodes import RelUrlNode, WebFetchNode
from url4.dag.nodes.blob import BlobRefNode
from url4.io.http import HttpIOLayer

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR-9031"
HEX = hashlib.sha256(PNG).hexdigest()
BASE = "https://self.local"

# Spellings the url4 grammar accepts and HTTPX 0.28 normalizes to /blob/sha256/<hex>.
DOT_ALIASES = [
    f"/./blob/sha256/{HEX}",
    f"/x/../blob/sha256/{HEX}",
    f"/../blob/sha256/{HEX}",
    f"/blob/./sha256/{HEX}",
    f"/a/b/../../blob/sha256/{HEX}",
]
# Spellings the grammar refuses (``%``, ``//``) but a hand-built tree can still carry.
ENCODED_ALIASES = [
    f"/%2e/blob/sha256/{HEX}",
    f"/%2E/blob/sha256/{HEX}",
    f"/x/%2e%2e/blob/sha256/{HEX}",
    f"/x/%2E%2e/blob/sha256/{HEX}",
    f"/x/.%2E/blob/sha256/{HEX}",
    f"/blob/%2e/sha256/{HEX}",
    f"//blob/sha256/{HEX}",
    f"/x//../blob/sha256/{HEX}",
]


def _tree(value: Node) -> Expression:
    return Expression(sources=(Binding("img", value, ":"),), intent=Text("Describe"))


class _NoRequest:
    """A transport on which ANY request fails the test (and is recorded)."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        pytest.fail(f"no request may be made for a remote blob ref, got {request.url}")


class _Serve:
    """A transport that serves ``body`` and records every request path HTTPX sent."""

    def __init__(self, body: bytes, media_type: str = "image/png") -> None:
        self.body, self.media_type = body, media_type
        self.paths: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.raw_path.decode())
        return httpx.Response(200, content=self.body, headers={"content-type": self.media_type})


def _io(handler: Callable[[httpx.Request], httpx.Response]) -> HttpIOLayer:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HttpIOLayer(BASE, client=client)


async def _refused(target: str | Expression) -> tuple[_NoRequest, list[str]]:
    transport, seen = _NoRequest(), []
    with pytest.raises(ResolutionError) as caught:
        await run(target, io=_io(transport), process=_model(seen))
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.REMOTE_BLOB_UNSUPPORTED, True)
    return transport, seen


# -- the reported alias: url4://<authority>/<dot path to blob> --------------------------


@pytest.mark.parametrize("path", DOT_ALIASES)
def test_a_dot_segment_url4_alias_lowers_to_the_blob_node(path: str) -> None:
    types = {type(node) for node in compile_expression(f"(img:src=url4://n{path})!'D'").walk()}
    assert BlobRefNode in types
    assert WebFetchNode not in types


@pytest.mark.asyncio
@pytest.mark.parametrize("path", DOT_ALIASES)
async def test_a_dot_segment_url4_alias_is_refused_with_zero_requests(path: str) -> None:
    transport, seen = await _refused(f"(img:src=url4://n{path})!'Describe'")
    assert (transport.urls, seen) == ([], [])


@pytest.mark.parametrize("path", ENCODED_ALIASES)
def test_the_grammar_already_refuses_the_encoded_and_double_slash_spellings(path: str) -> None:
    with pytest.raises(ParseError):
        parse(f"(img:src=url4://n{path})!'D'")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ENCODED_ALIASES)
async def test_a_hand_built_encoded_url4_alias_is_refused_with_zero_requests(path: str) -> None:
    # WHY: the grammar is not the only producer of trees; the classifier must not rely on it.
    transport, seen = await _refused(_tree(Url(f"url4://n{path}")))
    assert (transport.urls, seen) == ([], [])


@pytest.mark.parametrize("path", [f"/blob/sha256/{HEX}/..", "/blob/x/../..", "/blob/.."])
def test_a_raw_blob_prefix_that_normalizes_away_is_still_remote(path: str) -> None:
    # INVARIANT: normalization only ADDS refusals; every previously refused spelling stays so.
    address = address_of(Url(f"url4://n{path}"))
    assert address is not None
    assert (address.form, address.authority) == ("remote", "n")


# -- the local form: an alias of /blob/sha256/<hex> resolves as the verified file ref ----


@pytest.mark.parametrize("path", DOT_ALIASES + ENCODED_ALIASES)
def test_a_local_alias_is_the_canonical_path_ref(path: str) -> None:
    address = address_of(RelUrl(path))
    assert address is not None
    assert (address.form, address.digest, address.ref) == ("path", HEX, path)
    assert address.target == f"/blob/sha256/{HEX}"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", DOT_ALIASES)
async def test_a_local_alias_fetches_only_the_canonical_target_and_verifies_it(path: str) -> None:
    served = _Serve(PNG)
    with pytest.raises(ResolutionError) as caught:
        # A body that is not the digest's bytes: only the blob node verifies, so this proves
        # the alias went through it and not through a plain relative fetch.
        await run(f"(img:src={path})!'D'", io=_io(_Serve(b"other")), process=_model([]))
    assert caught.value.code == ErrorCode.BLOB_DIGEST_MISMATCH
    seen: list[str] = []
    await run(f"(img:src={path})!'D'", io=_io(served), process=_model(seen))
    assert served.paths == [f"/blob/sha256/{HEX}"]
    assert seen and path in seen[0]


@pytest.mark.parametrize(
    "path",
    [
        "/./blob/md5/abc",
        f"/x/../blob/sha256/{HEX}/x",
        f"/blob/sha256/{HEX}/.",
        f"/blob/sha256/{HEX}//..",
        "/data/../x",
    ],
)
def test_a_local_path_that_does_not_normalize_to_the_blob_shape_is_not_a_ref(path: str) -> None:
    assert address_of(RelUrl(path)) is None


def _model(seen: list[str]) -> Callable[[str, str | None, object], Awaitable[str]]:
    async def model(sources: str, intent: str | None, scope: object) -> str:
        seen.append(sources)
        return "ok"

    return model


# -- controls: ordinary paths still fetch -------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "sent"),
    [
        ("url4://n/data/x", "https://n/data/x"),
        ("url4://n/x/../data", "https://n/data"),
        ("url4://n/blobs/x", "https://n/blobs/x"),
        ("/data/x", f"{BASE}/data/x"),
    ],
)
async def test_a_non_blob_path_still_fetches(source: str, sent: str) -> None:
    served, seen = _Serve(b"ZEBRA-5512", "text/plain"), []
    sent_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_urls.append(str(request.url))
        return served(request)

    graph = compile_expression(f"(img:src={source})!'D'")
    assert {type(node) for node in graph.walk()} & {WebFetchNode, RelUrlNode}
    await run(graph, io=_io(handler), process=_model(seen))
    assert sent_urls == [sent]
    assert "ZEBRA-5512" in seen[0]
