"""Conformance: generic content identifiers ``<namespace>:<algorithm>/<digest>`` (Part B §5.4.4).

FEATURE: file refs in url4 sources (epic ``OME-1529``, unit ``OME-1539``).
STORY: as an ensemble author I can write any content identifier; a node that does not support
its namespace or algorithm refuses it as ``unsupported_mode`` (permanent) before any I/O, so it
never reaches an executor as text and is never confused with missing bytes.

Owner decision (Sergey, 2026-10-27, on HupBaHa's review of design PR 31): the parser recognises
every syntactically valid content identifier (Part B §8 ``content-id``). v1 supports exactly
``blob:sha256/<64 lowercase hex>``; namespace and algorithm compare case-sensitively; the
digest is an opaque key (never case-folded); ``.`` and ``..`` are not digests.
"""

from __future__ import annotations

import hashlib

import pytest

from url4.core.blob_ref import address_of
from url4.core.errors import ErrorCode, ResolutionError
from url4.core.grammar import parse
from url4.core.nodes import Binding, BlobRef, Expression, Text
from url4.core.render import render
from url4.dag._run import run
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer

PNG = b"\x89PNG\r\n\x1a\n-content-id-4827"
HEX = hashlib.sha256(PNG).hexdigest()
LOCAL = f"/blob/sha256/{HEX}"

UNSUPPORTED = [
    f"ipfs:sha256/{HEX}",  # another namespace
    "blob:md5/0123456789abcdef0123456789abcdef",  # another algorithm
    f"blob:sha3-256/{HEX}",
    f"BLOB:sha256/{HEX}",  # case-sensitive namespace
    f"blob:SHA256/{HEX}",  # case-sensitive algorithm
    "x:y/a.b_c-1",
]


class _Node(StaticIOLayer):
    """The evaluating node, holding the PNG under every address a lookup could try."""

    def __init__(self) -> None:
        blobs = {LOCAL: PNG, f"/blob/sha256/{HEX.upper()}": PNG}
        super().__init__(blobs, media_types=dict.fromkeys(blobs, "image/png"))
        self.requests: list[str] = []

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.requests.append(request.target)
        return await super().fetch_bytes(request)

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.requests.append(target)
        return await super().fetch(target, relative=relative)

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.requests.append(request.target)
        return await super().fetch_ex(request)


async def _process(sources: str, intent: str | None, scope: object) -> str:
    return f"model saw {sources}"


async def _refusal(token: str) -> tuple[ResolutionError, _Node]:
    node = _Node()
    with pytest.raises(ResolutionError) as caught:
        await run(f"(img:src={token})!'Describe'", io=node, process=_process)
    return caught.value, node


@pytest.mark.parametrize("token", [*UNSUPPORTED, f"blob:sha256/{HEX}"])
def test_every_syntactically_valid_content_id_parses_as_one(token: str) -> None:
    text = f"(img:src={token})!'Describe'"
    tree = parse(text)
    assert isinstance(tree, Expression)
    assert tree.sources == (Binding("img", BlobRef(token), ":"),)
    assert render(tree) == text  # round-trips unquoted


@pytest.mark.asyncio
@pytest.mark.parametrize("token", UNSUPPORTED)
async def test_an_unsupported_namespace_or_algorithm_is_unsupported_mode_before_any_io(
    token: str,
) -> None:
    # INVARIANT: never Text (it would reach the executor) and never source_not_found (it
    # would read as missing bytes); refused before the store is asked anything.
    error, node = await _refusal(token)
    assert (error.code, error.permanent) == (ErrorCode.UNSUPPORTED_MODE, True)
    assert node.requests == []


@pytest.mark.asyncio
async def test_upper_case_hex_is_an_opaque_key_no_store_holds() -> None:
    # WHY: v1 supports only lower-case hex; the digest is never case-folded into another key.
    error, node = await _refusal(f"blob:sha256/{HEX.upper()}")
    assert (error.code, error.permanent) == (ErrorCode.SOURCE_NOT_FOUND, True)
    assert node.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("digest", [HEX[:-1], f"{HEX}0", "a.b", "zz"])
async def test_a_supported_id_with_a_non_sha256_digest_is_source_not_found_without_io(
    digest: str,
) -> None:
    error, node = await _refusal(f"blob:sha256/{digest}")
    assert (error.code, error.permanent) == (ErrorCode.SOURCE_NOT_FOUND, True)
    assert node.requests == []


@pytest.mark.parametrize("token", ["blob:sha256/.", "blob:sha256/..", "ipfs:sha256/..", "x:y/."])
def test_dot_segment_digests_are_not_content_ids(token: str) -> None:
    # INVARIANT: the digest is an opaque key; ``.``/``..`` could address outside the store.
    tree = parse(f"(src={token})!'D'")
    assert isinstance(tree, Expression)
    assert tree.sources == (Text(token),)
    assert address_of(tree.sources[0]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [*UNSUPPORTED, f"blob:sha256/{HEX}"])
async def test_a_quoted_content_id_is_literal_text_and_never_resolved(token: str) -> None:
    text = f"(img:'{token}')!'Describe'"
    tree = parse(text)
    assert isinstance(tree, Expression)
    assert tree.sources == (Binding("img", Text(token), ":"),)
    node = _Node()
    assert await run(text, io=node, process=_process) == f"model saw img: {token}"
    assert node.requests == []


@pytest.mark.parametrize(
    "token", ["blob:sha256", "blob:/abc", "blob:-x/abc", "1x:sha256/abc", "blob:sha256/a/b"]
)
def test_tokens_outside_the_content_id_production_stay_text(token: str) -> None:
    tree = parse(f"(src={token})!'D'")
    assert isinstance(tree, Expression)
    assert tree.sources == (Text(token),)
