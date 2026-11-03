"""A run's attachment flights draw from ONE live 8,000,000-byte budget as bytes arrive.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; push security review
"resource-cap-defeat", owner decision Sergey 2026-11-03: shared live budget).
STORY: as a node operator, a run naming many large ``https://`` attachment sources is refused
(``attachments_too_large``, permanent) as soon as the bytes received so far pass the per-run
cap, and its other flights are cancelled — the node never downloads and holds about
20 × 20 MiB first. Peak memory is about the cap plus one read chunk per in-flight request.

The transport is a recording mock: every response body is a counting stream, so the tests
measure the bytes ACTUALLY read off the (fake) wire, not the bytes a fetch returned.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
from url4.core.errors import ErrorCode, ResolutionError
from url4.dag._caps import MAX_ATTACHMENT_BYTES, CapBudget
from url4.dag._run import run
from url4.dag.attachment import Attachment
from url4.dag.attachments import current_attachments
from url4.io.http import HttpIOLayer
from url4.io.layer import FetchRequest
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer

MIB = 1024 * 1024
CHUNK = 64 * 1024
CAP = MAX_ATTACHMENT_BYTES


class _Body(httpx.AsyncByteStream):
    """``size`` bytes in ``CHUNK`` pieces; counts reads (the guarded transport yields to the
    loop after each piece, so concurrent flights interleave as on a real network)."""

    def __init__(self, size: int, fail_after: int | None = None) -> None:
        self.size = size
        self.fail_after = fail_after
        self.read = 0
        self.finished = False
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while self.read < self.size:
            if self.fail_after is not None and self.read >= self.fail_after:
                raise httpx.ReadError("connection reset mid-body")
            piece = min(CHUNK, self.size - self.read)
            self.read += piece
            yield b"\0" * piece
        self.finished = True

    async def aclose(self) -> None:
        self.closed = True


class _Wire:
    """The fake wire: ``sizes`` maps a path to its body size; every body is kept for inspection."""

    def __init__(self, sizes: dict[str, int], fail_after: dict[str, int] | None = None) -> None:
        self.sizes = sizes
        self.fail_after = dict(fail_after or {})
        self.bodies: dict[str, list[_Body]] = {}

    def answer(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = _Body(self.sizes[path], self.fail_after.pop(path, None))
        self.bodies.setdefault(path, []).append(body)
        return httpx.Response(200, stream=body, headers={"content-type": "image/png"})

    @property
    def all(self) -> list[_Body]:
        return [body for bodies in self.bodies.values() for body in bodies]

    @property
    def total_read(self) -> int:
        return sum(body.read for body in self.all)


async def _public(host: str, port: int) -> Sequence[str]:
    return ["93.184.216.34"]


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> list[_Wire]:
    holder: list[_Wire] = []

    def transport() -> httpx.AsyncBaseTransport:
        return httpx.MockTransport(lambda request: holder[0].answer(request))

    monkeypatch.setattr(guarded_mod, "_inner_transport", transport)
    return holder


class _Model:
    def __init__(self) -> None:
        self.seen: list[tuple[Attachment, ...]] = []

    async def __call__(self, sources: str, intent: str | None, scope: object) -> str:
        self.seen.append(current_attachments())
        return "ok"


def _url(name: str) -> str:
    return f"https://files.example/{name}.png"


def _expr(names: Sequence[str], suffix: str = "") -> str:
    return "(" + ", ".join(f"src={_url(n)};accept=image/png{suffix}" for n in names) + ")!'d'"


async def _run(text: str, model: _Model) -> str:
    io = HttpIOLayer(resolver=_public)
    try:
        return await asyncio.wait_for(run(text, io, process=model), 30)
    finally:
        await io.aclose()


@pytest.mark.asyncio
async def test_twenty_concurrent_1_mib_flights_are_refused_once_the_total_passes_the_cap(
    wire: list[_Wire],
) -> None:
    names = [f"f{i}" for i in range(20)]
    wire.append(_Wire({f"/{n}.png": MIB for n in names}))
    model = _Model()
    with pytest.raises(ResolutionError) as caught:
        await _run(_expr(names), model)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert caught.value.permanent is True
    # INVARIANT: bytes read off the wire stay within the cap plus one chunk per flight.
    assert wire[0].total_read <= CAP + 20 * CHUNK
    # The remaining flights were cancelled, not read to the end (20 MiB would be 20,971,520).
    assert sum(body.finished for body in wire[0].all) < 20
    assert all(body.closed for body in wire[0].all)
    assert model.seen == []


@pytest.mark.asyncio
async def test_a_single_20_mib_body_is_refused_after_about_the_cap_not_20_mib(
    wire: list[_Wire],
) -> None:
    wire.append(_Wire({"/big.png": 20 * MIB}))
    with pytest.raises(ResolutionError) as caught:
        await _run(_expr(["big"]), _Model())
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert CAP < wire[0].total_read <= CAP + CHUNK


@pytest.mark.asyncio
async def test_exactly_the_cap_passes(wire: list[_Wire]) -> None:
    wire.append(_Wire({"/a.png": 4_000_000, "/b.png": 4_000_000}))
    model = _Model()
    assert await _run(_expr(["a", "b"]), model) == "ok"
    assert sum(len(a.body) for a in model.seen[0]) == 8_000_000


@pytest.mark.asyncio
async def test_one_byte_over_the_cap_fails(wire: list[_Wire]) -> None:
    wire.append(_Wire({"/a.png": 4_000_000, "/b.png": 4_000_001}))
    model = _Model()
    with pytest.raises(ResolutionError) as caught:
        await _run(_expr(["a", "b"]), model)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert model.seen == []


@pytest.mark.asyncio
async def test_a_breach_inside_an_optional_flight_still_refuses_the_run(
    wire: list[_Wire],
) -> None:
    # INVARIANT: the cap is the run's refusal — an ;optional guard never swallows it.
    wire.append(_Wire({"/big.png": 9_000_000}))
    model = _Model()
    with pytest.raises(ResolutionError) as caught:
        await _run(_expr(["big"], ";optional"), model)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert wire[0].total_read <= CAP + CHUNK
    assert model.seen == []


@pytest.mark.asyncio
async def test_a_failed_attempt_gives_its_bytes_back_before_a_retry(wire: list[_Wire]) -> None:
    # 6 MB read, then the connection resets (transient); the retry reads 6 MB again. Without the
    # give-back the two attempts would count 12 MB against the 8 MB cap.
    wire.append(_Wire({"/r.png": 6_000_000}, fail_after={"/r.png": 6_000_000 - CHUNK}))
    model = _Model()
    assert await _run(_expr(["r"], ";retry=1"), model) == "ok"
    assert [len(a.body) for a in model.seen[0]] == [6_000_000]
    assert len(wire[0].bodies["/r.png"]) == 2


# -- an optional source that fails consumes no budget (deterministic, no transport) -------


class _Streaming(StaticIOLayer):
    """Streams each body to ``on_chunk`` in CHUNK pieces; ``fail`` raises after streaming.

    ``order`` makes a target wait until another target's fetch has ENDED, so the test fixes
    which flight runs first without relying on scheduling.
    """

    def __init__(
        self,
        bodies: dict[str, bytes],
        *,
        fail: frozenset[str] = frozenset(),
        order: dict[str, str] | None = None,
    ) -> None:
        super().__init__(dict(bodies), media_types=dict.fromkeys(bodies, "image/png"))
        self.bodies = bodies
        self.fail = fail
        self.order = dict(order or {})
        self.ended: dict[str, asyncio.Event] = {url: asyncio.Event() for url in bodies}
        self.requests: list[FetchRequest] = []

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.requests.append(request)
        target = request.target
        try:
            after = self.order.get(target)
            if after is not None:
                await self.ended[after].wait()
            body = self.bodies[target]
            for start in range(0, len(body), CHUNK):
                if request.on_chunk is not None:
                    request.on_chunk(len(body[start : start + CHUNK]))
            if target in self.fail:
                raise ResolutionError("upstream went away", code=ErrorCode.RESOLUTION_FAILED)
            return FetchedBytes(body, "image/png")
        finally:
            self.ended[target].set()


@pytest.mark.asyncio
async def test_an_optional_source_that_fails_does_not_consume_budget() -> None:
    gone, kept = _url("gone"), _url("kept")
    io = _Streaming(
        {gone: b"g" * 7_000_000, kept: b"k" * 5_000_000},
        fail=frozenset({gone}),
        order={kept: gone},
    )
    model = _Model()
    text = f"(src={gone};accept=image/png;optional, src={kept};accept=image/png)!'d'"
    assert await run(text, io, process=model) == "ok"
    # 7 MB streamed by the failed optional flight + 5 MB kept would be 12 MB without the refund.
    assert [len(a.body) for a in model.seen[0]] == [5_000_000]


@pytest.mark.asyncio
async def test_each_flight_reads_at_most_the_budget_left_by_settled_entries() -> None:
    img = _url("img")
    io = _Streaming({img: b"i" * 10})
    case = [Attachment("sha256:" + "0" * 64, "application/pdf", b"c" * 3_000_000)]
    await run(f"(src={img};accept=image/png)!'d'", io, process=_Model(), attachments=case)
    assert [r.max_bytes for r in io.requests] == [CAP - 3_000_000]
    assert all(r.on_chunk is not None for r in io.requests)


# -- the budget itself -----------------------------------------------------------------------


def test_live_charges_are_settled_once_per_key_by_the_final_charge() -> None:
    budget = CapBudget()
    budget.charge_bytes("a", 3_000_000)
    budget.charge_bytes("a", 1_000_000)
    assert budget.remaining() == CAP  # in-flight bytes do not lower a new flight's ceiling
    budget.charge("a", 4_000_000)  # settles: the live 4 MB become the counted 4 MB
    budget.charge("a", 4_000_000)  # once per key
    assert budget.remaining() == CAP - 4_000_000
    budget.charge_bytes("b", 4_000_000)  # exactly at the cap: allowed
    with pytest.raises(ResolutionError) as caught:
        budget.charge_bytes("b", 1)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    with pytest.raises(ResolutionError):
        budget.raise_if_refused()


def test_release_gives_a_keys_live_bytes_back() -> None:
    budget = CapBudget()
    budget.charge_bytes("opt", 7_000_000)
    budget.release("opt")
    budget.release("never-charged")
    budget.charge_bytes("req", 8_000_000)
    budget.raise_if_refused()  # nothing was refused


def test_once_refused_every_later_draw_is_refused_even_after_a_give_back() -> None:
    budget = CapBudget()
    with pytest.raises(ResolutionError):
        budget.charge_bytes("big", CAP + 1)
    budget.release("big")  # the breaching flight's attempt ends and gives its bytes back
    with pytest.raises(ResolutionError) as caught:
        budget.charge_bytes("sibling", 1)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
