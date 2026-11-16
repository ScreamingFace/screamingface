"""The two disclosed gaps of the PR #1587 review round, closed (owner decision 2026-11-04).

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``).
STORY (gap 1): as a node operator, a run whose reduce processor is ``url4://…`` (a run option or
the node's default) is refused ``x.remote_node_unsupported`` in the same pre-I/O remote-node
precheck as a remote expression — before any attachment fetch.
STORY (gap 2): as a node operator, the store read of a blob whose digest matches a Case attachment
draws from the run's live byte budget too: an honest read adds nothing (the list dedups it), but
bytes beyond the Case attachment's size count, so an oversized body is refused once the run passes
the cap, never read up to the io's own cap.
"""

from __future__ import annotations

import hashlib

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag._caps import MAX_ATTACHMENT_BYTES, CapBudget
from url4.dag._run import run
from url4.dag.attachment import Attachment
from url4.dag.attachments import current_attachments
from url4.dag.remote_nodes import allow_one_remote_hop, refuse_remote_nodes
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer
from url4.peer.server import Url4Node

CAP = MAX_ATTACHMENT_BYTES
CHUNK = 64 * 1024
IMG = "https://img.example/a.png"
PNG = b"\x89PNG\r\n\x1a\n-gaps"
WITH_IMAGE = f"(src={IMG};accept=image/png, 'q')!'d'"


class _Tripwire:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.calls.append(f"fetch {target}")
        return "reduced"

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.calls.append(f"fetch_ex {request.target}")
        return FetchResult("reduced")

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.calls.append(f"fetch_bytes {request.target}")
        return FetchedBytes(PNG, "image/png")


# -- gap 1: a url4:// reduce processor --------------------------------------------------------


@pytest.mark.parametrize("processor", ["url4://n2/reduce", "URL4://n2", "url4://n2/v1?x=1"])
@pytest.mark.asyncio
async def test_a_url4_processor_run_option_refuses_before_the_attachment_flight(
    processor: str,
) -> None:
    io = _Tripwire()
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(WITH_IMAGE, io, processor=processor))
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.REMOTE_NODE_UNSUPPORTED, True)
    assert io.calls == []


@pytest.mark.asyncio
async def test_a_nodes_url4_default_processor_refuses_before_any_io() -> None:
    outbound = _Tripwire()
    node = Url4Node("n1", outbound=outbound, default_processor="url4://n2/reduce")
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(WITH_IMAGE)
    assert caught.value.code == ErrorCode.REMOTE_NODE_UNSUPPORTED
    assert outbound.calls == []


@pytest.mark.asyncio
async def test_an_https_or_route_processor_is_not_a_remote_node_call() -> None:
    io = _Tripwire()
    for processor in ["https://p.example/reduce", "/reduce"]:
        await refuse_remote_nodes(run(WITH_IMAGE, io, processor=processor))
    assert f"fetch_bytes {IMG}" in io.calls


@pytest.mark.asyncio
async def test_the_clients_hop_as_processor_is_checked_not_spent() -> None:
    io = _Tripwire()
    ran = run(WITH_IMAGE, io, processor="url4://n2/v1")
    await allow_one_remote_hop(ran, ("n2", "/v1"))  # not refused: the hop is still free
    assert io.calls[0] == f"fetch_bytes {IMG}"


# -- gap 2: a blob equal to a Case attachment draws from the live budget ----------------------


class _Oversized(StaticIOLayer):
    """Serves each requested blob as ``sizes[target]`` bytes in CHUNK pieces (none verify)."""

    def __init__(self, sizes: dict[str, int]) -> None:
        super().__init__({})
        self.sizes = sizes
        self.streamed = 0
        self.requests: list[FetchRequest] = []

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.requests.append(request)
        size = self.sizes[request.target]
        for start in range(0, size, CHUNK):
            piece = min(CHUNK, size - start)
            self.streamed += piece
            if request.on_chunk is not None:
                request.on_chunk(piece)
        return FetchedBytes(b"\0" * size, "image/png")


def _case(fill: bytes, size: int) -> tuple[Attachment, str]:
    body = fill * size
    hex_ = hashlib.sha256(body).hexdigest()
    return Attachment(f"sha256:{hex_}", "image/png", body), hex_


@pytest.mark.asyncio
async def test_case_attachment_blobs_served_past_the_cap_are_refused_within_a_chunk() -> None:
    a, a_hex = _case(b"a", CAP // 2)
    b, b_hex = _case(b"b", CAP - CAP // 2)
    # The store serves 9/8 of the cap for each digest: the Case already holds the whole cap, so
    # every byte the reads add beyond the Case sizes is over it.
    over = CAP * 9 // 8
    io = _Oversized({f"/blob/sha256/{a_hex}": over, f"/blob/sha256/{b_hex}": over})
    seen: list[tuple[Attachment, ...]] = []

    async def model(sources: str, intent: str | None, scope: object) -> str:
        seen.append(current_attachments())
        return "ok"

    text = f"(src=/blob/sha256/{a_hex}, src=/blob/sha256/{b_hex})!'d'"
    assert await run(text, io, process=model, attachments=[a, b])
    # INVARIANT (round 10 1(a), owner 2026-11-05 — amended with approval): the store copy of a
    # Case digest is never read, so the oversized store bodies never reach the run; the Case
    # bytes are the one resident copy, and nothing goes past the cap.
    assert (io.requests, io.streamed) == ([], 0)
    (attached,) = seen
    assert [x.body for x in attached] == [a.body, b.body]
    assert all(x.body is case.body for x, case in zip(attached, (a, b), strict=True))
    assert sum(len(x.body) for x in attached) <= CAP


@pytest.mark.asyncio
async def test_an_honest_read_of_a_case_digest_still_fits() -> None:
    a, a_hex = _case(b"a", 5_000_000)

    class _Honest(StaticIOLayer):
        async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
            assert request.on_chunk is not None and request.max_bytes is not None
            for start in range(0, len(a.body), CHUNK):
                request.on_chunk(len(a.body[start : start + CHUNK]))
            return FetchedBytes(a.body, "image/png")

    seen: list[tuple[Attachment, ...]] = []

    async def model(sources: str, intent: str | None, scope: object) -> str:
        seen.append(current_attachments())
        return "ok"

    io = _Honest({})
    assert await run(f"(src=/blob/sha256/{a_hex})!'d'", io, process=model, attachments=[a])
    assert [len(x.body) for x in seen[0]] == [5_000_000]


def test_a_counted_keys_read_draws_only_its_bytes_beyond_the_counted_size() -> None:
    budget = CapBudget()
    counted = CAP * 5 // 8
    budget.charge("k", counted)
    budget.charge_bytes("k", counted)  # an honest re-read: nothing beyond the counted size
    budget.charge_bytes("other", CAP - counted)  # exactly at the cap
    with pytest.raises(ResolutionError) as caught:
        budget.charge_bytes("k", 1)  # one byte past the counted size
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE


def test_settling_a_counted_key_again_gives_its_read_back() -> None:
    budget = CapBudget()
    counted = CAP * 5 // 8
    budget.charge("k", counted)
    budget.charge_bytes("k", counted + CAP // 8)  # an eighth of the cap beyond: counted live
    budget.charge("k", counted)  # the read landed: counted once, its live bytes released
    budget.charge_bytes("other", CAP - counted)  # exactly the cap in all: fits
    budget.raise_if_refused()
