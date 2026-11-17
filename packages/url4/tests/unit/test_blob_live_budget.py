"""Local and relative blob reads draw from the run's ONE live byte budget, chunk by chunk.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; PR #1587 review finding 1,
owner decision Sergey 2026-11-04: the same shared live ``CapBudget`` as attachment flights).
STORY: as a node operator, a run naming two valid 7 MB blob refs is refused
``x.attachments_too_large`` once the bytes read so far pass the 8,000,000-byte cap — the node
never reads and holds 14 MB first, whether the blob comes from the engine's io, a text-only io,
or a ``url4 serve`` ``[data]`` file on the node itself.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncGenerator
from typing import Any, cast

import pytest

from url4.cli._files import FileData
from url4.core.errors import ErrorCode, ResolutionError
from url4.dag._caps import MAX_ATTACHMENT_BYTES
from url4.dag._run import run
from url4.dag.attachment import Attachment
from url4.dag.attachments import current_attachments
from url4.io.layer import FetchRequest
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer
from url4.peer.server import Request, Url4Node

CAP = MAX_ATTACHMENT_BYTES
CHUNK = 64 * 1024
SEVEN_MB = 7_000_000


def _blob(fill: bytes, size: int) -> tuple[bytes, str]:
    body = fill * size
    return body, hashlib.sha256(body).hexdigest()


A, A_HEX = _blob(b"a", SEVEN_MB)
B, B_HEX = _blob(b"b", SEVEN_MB)
TWO_BLOBS = f"(src=/blob/sha256/{A_HEX}, src=blob:sha256/{B_HEX})!'d'"


class _Streaming(StaticIOLayer):
    """A store that streams each body to ``on_chunk`` in CHUNK pieces and stops when refused."""

    def __init__(self, bodies: dict[str, bytes]) -> None:
        super().__init__(dict(bodies))
        self.bodies = bodies
        self.media: dict[str, str] = dict.fromkeys(bodies, "image/png")
        self.streamed = 0
        self.requests: list[FetchRequest] = []

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.requests.append(request)
        body = self.bodies[request.target]
        for start in range(0, len(body), CHUNK):
            piece = len(body[start : start + CHUNK])
            self.streamed += piece
            if request.on_chunk is not None:
                request.on_chunk(piece)
        return FetchedBytes(body, self.media.get(request.target))


class _Model:
    def __init__(self) -> None:
        self.seen: list[tuple[Attachment, ...]] = []

    async def __call__(self, sources: str, intent: str | None, scope: object) -> str:
        self.seen.append(current_attachments())
        return "ok"


def _store(*blobs: tuple[bytes, str]) -> _Streaming:
    return _Streaming({f"/blob/sha256/{hex_}": body for body, hex_ in blobs})


@pytest.mark.asyncio
async def test_two_7_mb_blobs_are_refused_without_reading_14_mb() -> None:
    io, model = _store((A, A_HEX), (B, B_HEX)), _Model()
    with pytest.raises(ResolutionError) as caught:
        await run(TWO_BLOBS, io, process=model)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert caught.value.permanent is True
    # INVARIANT: about the cap plus one chunk per read — never 2 x 7 MB.
    assert io.streamed <= CAP + 2 * CHUNK
    assert model.seen == []


@pytest.mark.asyncio
async def test_each_blob_read_carries_the_budget_ceiling_and_the_live_hook() -> None:
    small, small_hex = _blob(b"s", 10)
    io = _store((small, small_hex))
    case = [Attachment("sha256:" + "0" * 64, "application/pdf", b"c" * 3_000_000)]
    await run(f"(src=/blob/sha256/{small_hex})!'d'", io, process=_Model(), attachments=case)
    assert [r.max_bytes for r in io.requests] == [CAP - 3_000_000]
    assert all(r.on_chunk is not None for r in io.requests)


@pytest.mark.asyncio
async def test_blobs_exactly_at_the_cap_pass_and_are_attached() -> None:
    four, four_hex = _blob(b"f", CAP // 2)
    other, other_hex = _blob(b"g", CAP - CAP // 2)
    io, model = _store((four, four_hex), (other, other_hex)), _Model()
    text = f"(src=/blob/sha256/{four_hex}, src=/blob/sha256/{other_hex})!'d'"
    assert await run(text, io, process=model) == "ok"
    assert sum(len(a.body) for a in model.seen[0]) == CAP


@pytest.mark.asyncio
async def test_a_blob_equal_to_a_case_attachment_is_not_counted_twice() -> None:
    # WHY: the final list dedups by digest, so the blob read must not draw the same bytes again.
    five, five_hex = _blob(b"v", 5_000_000)
    io, model = _store((five, five_hex)), _Model()
    case = [Attachment(f"sha256:{five_hex}", "image/png", five)]
    assert await run(f"(src=/blob/sha256/{five_hex})!'d'", io, process=model, attachments=case)
    assert [len(a.body) for a in model.seen[0]] == [5_000_000]


@pytest.mark.asyncio
async def test_a_collection_blob_is_not_charged_to_the_attachment_budget() -> None:
    rows = b'["x"]' + b" " * (CAP + 10)  # a large text collection: never an attachment (D4)
    rows_hex = hashlib.sha256(rows).hexdigest()
    io = _Streaming({f"/blob/sha256/{rows_hex}": rows})
    io.media[f"/blob/sha256/{rows_hex}"] = "application/json"
    model = _Model()
    await run(f"(/blob/sha256/{rows_hex}*($item)!'d')!'r'", io, process=model)
    assert all(r.on_chunk is None for r in io.requests)


class _TextOnly:
    """An io with a text port only: the blob node's UTF-8 fallback path."""

    def __init__(self, bodies: dict[str, str]) -> None:
        self.bodies = bodies

    async def fetch(self, target: str, *, relative: bool) -> str:
        return self.bodies[target]


@pytest.mark.asyncio
async def test_the_text_only_fallback_is_charged_and_refused_too() -> None:
    text_a = "a" * SEVEN_MB
    text_b = "b" * SEVEN_MB
    hex_a = hashlib.sha256(text_a.encode()).hexdigest()
    hex_b = hashlib.sha256(text_b.encode()).hexdigest()
    io = _TextOnly({f"/blob/sha256/{hex_a}": text_a, f"/blob/sha256/{hex_b}": text_b})
    with pytest.raises(ResolutionError) as caught:
        await run(f"(src=/blob/sha256/{hex_a}, src=/blob/sha256/{hex_b})!'d'", io, process=_Model())
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE


# -- the node's relative bytes path ---------------------------------------------------------


class _Chunked:
    """A ``[data]`` provider read in pieces; counts the bytes it actually produced."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.produced = 0

    async def __call__(self) -> str:
        raise AssertionError("the bytes path must not read the text port")

    async def read_chunks(self) -> AsyncGenerator[bytes]:
        for start in range(0, len(self.body), CHUNK):
            piece = self.body[start : start + CHUNK]
            self.produced += len(piece)
            yield piece


def _node_with(*blobs: tuple[bytes, str]) -> tuple[Url4Node, list[_Chunked]]:
    node, providers = Url4Node(), []
    for body, hex_ in blobs:
        provider = _Chunked(body)
        providers.append(provider)
        node.data(f"/blob/sha256/{hex_}", cast("Any", provider), media_type="image/png")
    return node, providers


@pytest.mark.asyncio
async def test_a_node_refuses_two_7_mb_data_blobs_without_reading_14_mb() -> None:
    node, providers = _node_with((A, A_HEX), (B, B_HEX))
    seen: list[tuple[Attachment, ...]] = []

    @node.endpoint("/model")
    def model(request: Request) -> str:
        seen.append(request.attachments)
        return "described"

    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(f"/model(a:src=/blob/sha256/{A_HEX}, b:src=/blob/sha256/{B_HEX})!'d'")
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert sum(p.produced for p in providers) <= CAP + 2 * CHUNK
    assert seen == []


@pytest.mark.asyncio
async def test_node_relative_bytes_honour_max_bytes_and_on_chunk() -> None:
    node, (provider,) = _node_with((A, A_HEX))
    drawn: list[int] = []
    request = FetchRequest(
        f"/blob/sha256/{A_HEX}",
        relative=True,
        kind="relative",
        max_bytes=1_000_000,
        on_chunk=drawn.append,
    )
    with pytest.raises(ResolutionError) as caught:
        await node.fetch_bytes(request)
    assert caught.value.code == ErrorCode.SOURCE_TOO_LARGE
    assert provider.produced <= 1_000_000 + CHUNK
    assert drawn and all(n <= CHUNK for n in drawn)  # charged per piece, not once at the end


@pytest.mark.asyncio
async def test_node_relative_bytes_without_limits_read_the_whole_body() -> None:
    node, _ = _node_with((A, A_HEX))
    got = await node.fetch_bytes(FetchRequest(f"/blob/sha256/{A_HEX}", relative=True))
    assert got == FetchedBytes(A, "image/png")


@pytest.mark.asyncio
async def test_a_node_text_route_read_as_bytes_is_still_charged() -> None:
    node = Url4Node()
    node.data("/notes", "x" * 100, media_type="text/plain")
    drawn: list[int] = []
    request = FetchRequest("/notes", relative=True, max_bytes=10, on_chunk=drawn.append)
    with pytest.raises(ResolutionError) as caught:
        await node.fetch_bytes(request)
    assert caught.value.code == ErrorCode.SOURCE_TOO_LARGE
    assert drawn == [100]


@pytest.mark.asyncio
async def test_a_file_data_route_reads_its_file_in_pieces(tmp_path) -> None:
    path = tmp_path / "big.bin"
    body = bytes(range(256)) * 1000  # 256,000 bytes: several pieces
    path.write_bytes(body)
    pieces = [piece async for piece in FileData(str(path)).read_chunks()]
    assert b"".join(pieces) == body
    assert len(pieces) > 1 and all(len(piece) <= CHUNK for piece in pieces)


@pytest.mark.asyncio
async def test_a_missing_file_data_route_is_the_sources_failure(tmp_path) -> None:
    with pytest.raises(ResolutionError):
        [piece async for piece in FileData(str(tmp_path / "nope")).read_chunks()]


# -- finding 6 on the blob path: the cap refusal wins over a concurrent read's failure ------


class _RacingStore(StaticIOLayer):
    """``A`` breaches the budget, then waits for ``B``'s read to fail before it re-raises."""

    def __init__(self) -> None:
        super().__init__({})
        self.breached = asyncio.Event()
        self.b_failed = asyncio.Event()

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        if request.target == f"/blob/sha256/{A_HEX}":
            try:
                assert request.on_chunk is not None
                request.on_chunk(CAP + 1)
            except ResolutionError:
                self.breached.set()
                await self.b_failed.wait()
                raise
            raise AssertionError("the budget did not refuse")
        await self.breached.wait()
        try:
            raise ResolutionError("gone", code=ErrorCode.SOURCE_NOT_FOUND, permanent=True)
        finally:
            self.b_failed.set()


@pytest.mark.asyncio
async def test_a_blob_read_failing_after_the_breach_does_not_mask_the_cap_refusal() -> None:
    with pytest.raises(ResolutionError) as caught:
        await asyncio.wait_for(run(TWO_BLOBS, _RacingStore(), process=_Model()), 10)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
