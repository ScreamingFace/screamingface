"""Error and boundary paths of the PR #1587 review fixes (findings 1-3), covered on purpose.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; PR #1587 review round,
owner decisions Sergey 2026-11-04).
STORY: as an ensemble author or node operator, the refusals the fixes added behave as specified at
their edges too: a strict field path that execution refuses, a binary blob used as a collection,
a bound inline group, a blob ref hidden in a pre-built graph's row body, and byte limits on the
node's non-streaming relative reads.
"""

from __future__ import annotations

import hashlib
from typing import Any, cast

import pytest

from url4.core.errors import ErrorCode, ResolutionError, Url4Error
from url4.core.nodes import Expression, Text, VarRef
from url4.dag import compile_expression
from url4.dag._collection_shape import UNKNOWN, resolve_collection
from url4.dag._run import run
from url4.dag.node import ExecutionContext
from url4.dag.nodes.blob import BlobRefNode
from url4.io.layer import FetchRequest
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer
from url4.peer.server import Url4Node

IMG = "https://img.example/a.png"
BODY = f"src={IMG};accept=image/png"
PNG = b"\x89PNG\r\n\x1a\n-edges"
PNG_HEX = hashlib.sha256(PNG).hexdigest()


class _Io(StaticIOLayer):
    def __init__(self) -> None:
        super().__init__(
            {IMG: PNG, f"/blob/sha256/{PNG_HEX}": PNG},
            media_types={IMG: "image/png", f"/blob/sha256/{PNG_HEX}": "image/png"},
        )
        self.byte_targets: list[str] = []

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.byte_targets.append(request.target)
        return await super().fetch_bytes(request)


async def _ok(sources: str, intent: str | None, scope: object) -> str:
    return "ok"


# -- finding 2: admission reads a collection exactly as execution will ------------------------


@pytest.mark.asyncio
async def test_a_strict_field_path_execution_refuses_makes_the_picture_unreachable() -> None:
    io = _Io()
    text = f"""(xs='{{"other": 1}}', $xs.rows*({BODY})!'d')!'r'"""
    with pytest.raises(Url4Error) as caught:
        await run(text, io, process=_ok, strict_fields=True)
    assert caught.value.code == ErrorCode.MALFORMED_SOURCE  # execution's strict refusal
    assert IMG not in io.byte_targets


@pytest.mark.asyncio
async def test_a_binary_blob_collection_is_c8_and_its_picture_is_never_fetched() -> None:
    io = _Io()
    with pytest.raises(ResolutionError) as caught:
        await run(f"(/blob/sha256/{PNG_HEX}*({BODY})!'d')!'r'", io, process=_ok)
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    assert IMG not in io.byte_targets


def test_a_bound_inline_group_is_conservatively_unknown() -> None:
    # WHY unknown (reachable): a bound group's text is only known when it runs. The grammar
    # needs an intent on a bound group today, so the AST is built directly.
    group = Expression(sources=(Text("a"), Text("b")), intent=None)
    shape = resolve_collection(VarRef("xs"), {"xs": group})
    assert shape.kind == UNKNOWN


# -- finding 3: a blob ref in text a pre-built graph keeps for later -------------------------


@pytest.mark.asyncio
async def test_a_blob_ref_in_a_prebuilt_row_body_is_refused_with_no_io() -> None:
    graph = compile_expression(f"(('a')*(src=/blob/sha256/{PNG_HEX}, $item)!'d')!'r'")
    io = _Io()
    with pytest.raises(Url4Error) as caught:
        await run(graph, io, process=_ok)
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.MALFORMED_SOURCE, True)
    assert io.byte_targets == []


# -- finding 1: byte limits on the non-streaming paths -----------------------------------------


class _TextOnly:
    async def fetch(self, target: str, *, relative: bool) -> str:
        return "x" * 100


@pytest.mark.asyncio
async def test_the_text_only_fallback_honours_max_bytes() -> None:
    body = ("x" * 100).encode()
    node = BlobRefNode.relative_path(f"/blob/sha256/{hashlib.sha256(body).hexdigest()}")
    with pytest.raises(ResolutionError) as caught:
        await node.verified(ExecutionContext(_TextOnly()), max_bytes=10)
    assert caught.value.code == ErrorCode.SOURCE_TOO_LARGE


class _WholeBytes:
    """A ``[data]`` provider that can only hand over its bytes whole."""

    async def __call__(self) -> str:
        raise AssertionError("the bytes path must not read the text port")

    async def read_bytes(self) -> bytes:
        return PNG


@pytest.mark.asyncio
async def test_a_whole_bytes_data_route_is_charged_and_capped_after_the_read() -> None:
    node = Url4Node()
    node.data("/cat", cast("Any", _WholeBytes()), media_type="image/png")
    drawn: list[int] = []
    request = FetchRequest("/cat", relative=True, max_bytes=4, on_chunk=drawn.append)
    with pytest.raises(ResolutionError) as caught:
        await node.fetch_bytes(request)
    assert caught.value.code == ErrorCode.SOURCE_TOO_LARGE
    assert drawn == [len(PNG)]
