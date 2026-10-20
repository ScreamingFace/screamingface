"""Conformance cases C1–C9 for file refs (``OME-1534``, signed off by Kevin on 2026-10-13).

FEATURE: image and PDF inputs for url4 sources (epic ``OME-1529``, unit ``OME-1539``).

Each test is one row of the signed-off table, on resolution behaviour. The §5.4.2 trust
steps of C1/C2 (policy, identity, attribution, ``URL4-Auth-Token``) are ``OME-1599``; until
then its interim rule applies to C2: a cross-node fetch only to an allowlisted node. The
``data:`` attachment of C1 and the model refusal of C9 are the engine connector's
(``OME-1545`` / ``OME-1548``); here C9 is the url4 half — the error is the intent's.
"""

from __future__ import annotations

import hashlib

import pytest

from url4.core.context import Context
from url4.core.errors import ErrorCode, ParseError, ResolutionError
from url4.core.grammar import parse
from url4.core.nodes import Binding, BlobRef, Expression, RelUrl, RemoteExpr, Source, Text, Url
from url4.core.render import render
from url4.dag._run import run
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer
from url4.wire.subrequest import decode_subrequest, extract_expression_params

PNG = b"\x89PNG\r\n\x1a\n-conformance-4827"
HEX = hashlib.sha256(PNG).hexdigest()
LOCAL = f"/blob/sha256/{HEX}"
REMOTE = f"url4://n2.example/blob/sha256/{HEX}"
TOKEN = f"blob:sha256/{HEX}"


class _Node(StaticIOLayer):
    """The evaluating node: its own blob store, plus a record of every request it makes."""

    def __init__(self, blobs: dict[str, bytes], *, blob_peers: tuple[str, ...] = ()) -> None:
        super().__init__(
            dict(blobs), media_types=dict.fromkeys(blobs, "image/png"), blob_peers=blob_peers
        )
        self.byte_targets: list[str] = []
        self.text_targets: list[str] = []

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.byte_targets.append(request.target)
        return await super().fetch_bytes(request)

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.text_targets.append(target)
        if target.startswith("url4://n2.example/v1?"):
            return "n2 summary"
        return await super().fetch(target, relative=relative)

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        return FetchResult(await self.fetch(request.target, relative=request.relative))


class _Model:
    """The ``process`` hook standing in for the model: records what it was given."""

    def __init__(self, error: ResolutionError | None = None) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self._error = error

    async def __call__(self, sources: str, intent: str | None, scope: Context) -> str:
        self.calls.append((sources, intent))
        if self._error is not None:
            raise self._error
        return "described"


@pytest.mark.asyncio
async def test_c1_relative_blob_path_resolves_on_the_current_node() -> None:
    text = f"(img:0.5:src={LOCAL})!'Describe'"
    tree = parse(text)
    assert isinstance(tree, Expression)
    assert tree.sources == (Source(RelUrl(LOCAL), name="img", weight=0.5),)
    node, model = _Node({LOCAL: PNG}), _Model()
    assert await run(text, io=node, process=model) == "described"
    assert node.byte_targets == [LOCAL]
    assert node.text_targets == []  # never through the text path, so a PNG cannot be mangled
    assert model.calls == [(f"img: {LOCAL}", "Describe")]


@pytest.mark.asyncio
async def test_c2_remote_ref_is_fetched_from_the_named_node() -> None:
    text = f"(img:src={REMOTE})!'Describe'"
    tree = parse(text)
    assert isinstance(tree, Expression)
    assert tree.sources == (Binding("img", Url(REMOTE), ":"),)
    node = _Node({REMOTE: PNG}, blob_peers=("n2.example",))
    assert await run(text, io=node, process=_Model()) == "described"
    assert node.byte_targets == [REMOTE]


@pytest.mark.asyncio
async def test_c2_interim_rule_refuses_a_node_off_the_allowlist() -> None:
    node = _Node({REMOTE: PNG})
    with pytest.raises(ResolutionError) as caught:
        await run(f"(img:src={REMOTE})!'Describe'", io=node, process=_Model())
    assert caught.value.code == ErrorCode.BLOB_PEER_NOT_ALLOWED
    assert node.byte_targets == []


@pytest.mark.asyncio
async def test_c3_bare_token_resolves_from_the_evaluating_node_own_store() -> None:
    text = f"(img:src={TOKEN})!'Describe'"
    tree = parse(text)
    assert isinstance(tree, Expression)
    assert tree.sources == (Binding("img", BlobRef(TOKEN), ":"),)
    assert render(tree) == text  # round-trips unquoted
    node, model = _Node({LOCAL: PNG}), _Model()
    assert await run(text, io=node, process=model) == "described"
    assert node.byte_targets == [LOCAL]
    assert model.calls == [(f"img: {TOKEN}", "Describe")]


@pytest.mark.asyncio
async def test_c4_quoted_token_is_the_literal_string() -> None:
    text = f"(img:'{TOKEN}')!'Describe'"
    tree = parse(text)
    assert isinstance(tree, Expression)
    assert tree.sources == (Binding("img", Text(TOKEN), ":"),)
    assert render(tree) == text
    node, model = _Node({}), _Model()
    assert await run(text, io=node, process=model) == "described"
    assert node.byte_targets == node.text_targets == []
    assert model.calls == [(f"img: {TOKEN}", "Describe")]


@pytest.mark.asyncio
async def test_c5_token_the_node_does_not_hold_is_source_not_found() -> None:
    with pytest.raises(ResolutionError) as caught:
        await run(f"(img:src={TOKEN})!'Describe'", io=_Node({}), process=_Model())
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.SOURCE_NOT_FOUND, True)


@pytest.mark.asyncio
async def test_c6_nested_remote_expression_forwards_its_sources_unchanged() -> None:
    inner = f"img:src={TOKEN}"
    text = f"(url4://n2.example/v1({inner})!'Describe')!'Summarize'"
    tree = parse(text)
    assert isinstance(tree, Expression)
    assert tree.sources == (RemoteExpr("n2.example", "/v1", inner, Text("Describe")),)
    node, model = _Node({LOCAL: PNG}), _Model()
    assert await run(text, io=node, process=model) == "described"
    # INVARIANT: the outer node resolves nothing inside the nested expression...
    assert node.byte_targets == []
    # ...and forwards its source list byte for byte, for n2 to resolve against its own store.
    (target,) = node.text_targets
    _params, q = extract_expression_params(target.partition("?")[2])
    assert q is not None
    assert decode_subrequest(q) == (inner, "Describe")


def test_c7_bare_token_without_src_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        parse(f"({TOKEN})!'Describe'")


@pytest.mark.asyncio
async def test_c8_bytes_the_node_cannot_handle_are_unsupported_content_type() -> None:
    # A collection must be text: a PNG blob in collection position cannot be iterated.
    with pytest.raises(ResolutionError) as caught:
        await run(f"{LOCAL}*('row $item')!'go'", io=_Node({LOCAL: PNG}))
    assert (caught.value.code, caught.value.permanent) == (
        ErrorCode.UNSUPPORTED_CONTENT_TYPE,
        True,
    )


@pytest.mark.asyncio
async def test_c9_a_model_that_cannot_take_the_image_is_an_intent_error() -> None:
    refusal = ResolutionError("model takes no images", code=ErrorCode.INTENT_ERROR, permanent=True)
    node, model = _Node({LOCAL: PNG}), _Model(refusal)
    with pytest.raises(ResolutionError) as caught:
        await run(f"(img:src={TOKEN})!'Describe'", io=node, process=model)
    assert caught.value.code == ErrorCode.INTENT_ERROR
    # The source itself resolved: the model was reached with it.
    assert node.byte_targets == [LOCAL]
    assert model.calls == [(f"img: {TOKEN}", "Describe")]
