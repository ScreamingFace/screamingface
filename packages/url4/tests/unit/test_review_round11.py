"""PR #1587 review round 11: admission reads a collection in the scope execution wires.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``).
STORY (finding 2): as an ensemble author, a picture under ``/rows/$1*(…)`` or ``$1.rows*(…)``
whose first source is a model's output is refused ``x.source_not_static`` before any I/O,
exactly as under ``/rows/$ys*(…)``.
STORY (finding 3): as an ensemble author, ``(xs=$ys, ys=/m(…), /rows/$xs*(…))`` is not refused:
``xs`` is defined before ``ys``, so execution never binds ``ys`` into it and fetches the literal
``/rows/$ys``.
INVARIANT (mirror ``_wiring._build_slots`` / ``_lowering._build_ctx_nodes``): ``$N`` names the
N-th source when that source is named; a named source sees only EARLIER named siblings; an
unnamed source sees every named sibling; a call context registers no positions.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncGenerator
from typing import Any, cast

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag._run import run
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes
from url4.peer.server import Url4Node

IMG = "https://img.example/t.png"
ATT = f"src={IMG};accept=image/png"


class _Tripwire:
    """An io that records every call on every port (each fetch yields one row)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.calls.append(f"fetch {target}")
        return '["r"]'

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.calls.append(f"fetch_ex {request.target}")
        return FetchResult('["r"]')

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.calls.append(f"fetch_bytes {request.target}")
        return FetchedBytes(b"\x89PNG\r\n\x1a\n-round11", "image/png")

    def has_code(self, pointer: str) -> bool:
        return True  # the repro's bare ``!d`` / ``!r`` are code pointers

    async def invoke_code(self, call: object) -> object:
        self.calls.append("invoke_code")
        return "ok"


async def _ok(sources: str, intent: str | None, scope: object) -> str:
    return "ok"


async def _refused_with_zero_io(text: str) -> None:
    io = _Tripwire()
    with pytest.raises(ResolutionError) as caught:
        await run(text, io, process=_ok)
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.SOURCE_NOT_STATIC, True)
    assert io.calls == []


@pytest.mark.parametrize(
    "text",
    [
        f"(ys=/m(q)!list, /rows/$1*({ATT})!d)!r",  # the reviewer's repro
        f"(ys=/m(q)!list, $1.rows*({ATT})!d)!r",
        f"(ys=/m(q)!list, $1*({ATT})!d)!r",
        f"(ys=/m(q)!list, xs=$1, $xs*({ATT})!d)!r",  # an alias through a position
        f"(ys=/m(q)!list, xs=/rows/$1, $xs*({ATT})!d)!r",
        f"(/a, ys=/m(q)!list, /rows/$2*({ATT})!d)!r",  # positions count unnamed sources
        f"(/rows/$ys*({ATT})!d, ys=/m(q)!list)!r",  # an unnamed source sees a LATER binding
        f"(ys=/m(q)!list, (/rows/$1*({ATT})!d, 'k')!'g')!r",  # a nested group sees outer $1
    ],
)
@pytest.mark.asyncio
async def test_a_positional_or_sibling_model_collection_is_not_static_with_zero_io(
    text: str,
) -> None:
    await _refused_with_zero_io(text)


@pytest.mark.asyncio
async def test_a_call_context_sibling_model_collection_is_not_static_with_zero_io() -> None:
    await _refused_with_zero_io(f"(/p(ys=/m(q)!list, /rows/$ys*({ATT})!d)!r, 'z')!'w'")


@pytest.mark.asyncio
async def test_a_forward_alias_is_not_model_derived_and_fetches_the_literal_template() -> None:
    io = _Tripwire()
    text = f"(xs=$ys, ys=/m(q)!list, /rows/$xs*({ATT})!'d')!'r'"
    assert await run(text, io, process=_ok)
    assert "fetch_ex /rows/$ys" in io.calls  # execution never bound the later ys into xs


@pytest.mark.asyncio
async def test_a_forward_positional_ref_is_not_model_derived() -> None:
    io = _Tripwire()
    text = f"(xs=$2, ys=/m(q)!list, /rows/$xs*({ATT})!'d')!'r'"
    assert await run(text, io, process=_ok)
    assert "fetch_ex /rows/$2" in io.calls


@pytest.mark.asyncio
async def test_a_position_naming_an_unnamed_source_stays_unbound() -> None:
    io = _Tripwire()
    # Slot 1 is unnamed: execution wires no ``pos:1`` and fetches the literal template.
    text = f"(/m(q)!list, /rows/$1*({ATT})!'d')!'r'"
    assert await run(text, io, process=_ok)
    assert "fetch_ex /rows/$1" in io.calls


def test_a_scan_keys_a_position_only_for_a_named_source() -> None:
    from url4.core.grammar import parse
    from url4.dag._collection_shape import MODEL, resolve_collection
    from url4.dag.source_scan import scan_sources

    (_, guards), *_ = scan_sources(parse(f"(ys=/m(q)!list, /rows/$1*({ATT})!d)!r")).occurrences
    assert resolve_collection(guards[0].items, guards[0].bound).kind == MODEL
    (_, guards), *_ = scan_sources(parse(f"(/m(q)!list, /rows/$1*({ATT})!d)!r")).occurrences
    assert resolve_collection(guards[0].items, guards[0].bound).kind != MODEL


# -- finding 1: under a live cap only a chunked or a held (str) provider is read ---------------
# STORY: as a node operator, a ``[data]`` provider that can only hand over its bytes whole is
# refused before its read inside a run, whatever size it declares: a stale or underestimated
# declaration can never put two whole bodies past the 8 MB live cap at once.


class _Resident:
    def __init__(self) -> None:
        self.now = 0
        self.peak = 0
        self.reads: list[int] = []


class _UnderDeclared:
    """A whole-body provider that declares 1 byte and hands over far more."""

    def __init__(self, body: bytes, resident: _Resident) -> None:
        self._body = body
        self._resident = resident

    async def __call__(self) -> str:
        raise AssertionError("the bytes path must not read the text port")

    def declared_size(self) -> int:
        return 1

    async def read_bytes(self) -> bytes:
        self._resident.reads.append(len(self._body))
        self._resident.now += len(self._body)
        self._resident.peak = max(self._resident.peak, self._resident.now)
        self._resident.now -= len(self._body)
        return self._body


class _Chunked:
    """A provider that hands over its bytes in pieces (the ``url4 serve`` ``[data]`` file)."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def __call__(self) -> str:
        raise AssertionError("the bytes path must not read the text port")

    async def read_chunks(self) -> AsyncGenerator[bytes]:
        for start in range(0, len(self._body), 65536):
            yield self._body[start : start + 65536]


def _blob(fill: bytes, size: int) -> tuple[bytes, str]:
    body = fill * size
    return body, hashlib.sha256(body).hexdigest()


@pytest.mark.asyncio
async def test_two_under_declared_whole_body_providers_are_refused_unread() -> None:
    resident = _Resident()
    a, a_hex = _blob(b"a", 7_000_000)
    b, b_hex = _blob(b"b", 7_000_000)
    node = Url4Node("n1", default_processor="/reduce")
    for hex_, body in ((a_hex, a), (b_hex, b)):
        provider = _UnderDeclared(body, resident)
        node.data(f"/blob/sha256/{hex_}", cast("Any", provider), media_type="image/png")
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(f"(src=/blob/sha256/{a_hex}, src=/blob/sha256/{b_hex})!'d'")
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert resident.reads == []  # INVARIANT: refused BEFORE the read, never after it
    assert resident.peak == 0


@pytest.mark.asyncio
async def test_a_whole_body_provider_is_refused_under_a_live_cap_even_when_exact() -> None:
    node = Url4Node()
    resident = _Resident()
    body = b"\x89PNG\r\n\x1a\n-exact"
    provider = _UnderDeclared(body, resident)
    node.data("/cat", cast("Any", provider), media_type="image/png")
    request = FetchRequest("/cat", relative=True, on_declared=lambda _: None)
    with pytest.raises(ResolutionError) as caught:
        await node.fetch_bytes(request)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert resident.reads == []


@pytest.mark.parametrize("held", [False, True])
@pytest.mark.asyncio
async def test_a_chunked_or_held_provider_is_still_attached(held: bool) -> None:
    body = b"h" * 1000
    hex_ = hashlib.sha256(body).hexdigest()
    node = Url4Node("n1")
    provider: object = body.decode() if held else _Chunked(body)
    node.data(f"/blob/sha256/{hex_}", cast("Any", provider))
    seen: list[int] = []

    async def model(sources: str, intent: str | None, scope: object) -> str:
        from url4.dag.attachments import current_attachments

        seen.extend(len(x.body) for x in current_attachments())
        return "ok"

    assert await run(f"(src=/blob/sha256/{hex_}, 'q')!'d'", node, process=model)
    assert seen == [1000]


@pytest.mark.asyncio
async def test_a_chunked_provider_past_the_cap_is_refused_within_a_piece() -> None:
    body, hex_ = _blob(b"c", 9_000_000)
    node = Url4Node("n1", default_processor="/reduce")
    node.data(f"/blob/sha256/{hex_}", cast("Any", _Chunked(body)), media_type="image/png")
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(f"(src=/blob/sha256/{hex_}, 'q')!'d'")
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE


def test_outside_a_run_a_whole_body_provider_is_still_read() -> None:
    node = Url4Node()
    resident = _Resident()
    node.data("/cat", cast("Any", _UnderDeclared(b"abc", resident)), media_type="image/png")
    got = asyncio.run(node.fetch_bytes(FetchRequest("/cat", relative=True)))
    assert (got.body, resident.reads) == (b"abc", [3])  # no live cap: the bounded read stands


# -- round 11 e2e follow-up (owner 2026-11-06): a ``value`` blob is held text, not whole-body ----
# STORY: as an operator, a ``[data]`` ``value`` blob (``url4 serve`` / the engine) is attached
# inside a run: the provider hands url4 its str (in memory, exact size), so the str exemption
# covers it; a whole-body refusal names the remedy, not the budget.


@pytest.mark.asyncio
async def test_a_value_backed_blob_ref_is_attached_inside_a_run() -> None:
    from url4.cli._config import ProviderSpec
    from url4.cli._serve import make_data_provider

    value = "a 31-byte value-backed blob ok!"
    assert len(value.encode()) == 31
    hex_ = hashlib.sha256(value.encode()).hexdigest()
    node = Url4Node("n1")
    spec = ProviderSpec(value=value, media_type="text/plain")
    node.data(f"/blob/sha256/{hex_}", make_data_provider(spec, 5.0), media_type="text/plain")
    seen: list[bytes] = []

    async def model(sources: str, intent: str | None, scope: object) -> str:
        from url4.dag.attachments import current_attachments

        seen.extend(x.body for x in current_attachments())
        return "ok"

    assert await run(f"(src=/blob/sha256/{hex_}, 'q')!'d'", node, process=model)
    assert seen == [value.encode()]


def test_a_file_provider_stays_chunked(tmp_path: Any) -> None:
    from url4.cli._config import ProviderSpec
    from url4.cli._serve import make_data_provider
    from url4.peer._bytes import SupportsReadChunks

    path = tmp_path / "f.bin"
    path.write_bytes(b"x")
    assert isinstance(make_data_provider(ProviderSpec(file=str(path)), 5.0), SupportsReadChunks)


@pytest.mark.asyncio
async def test_a_whole_body_refusal_names_the_chunked_remedy_and_stays_sticky() -> None:
    from url4.dag._caps import CapBudget
    from url4.peer._bytes import whole_body_refused

    node = Url4Node()
    resident = _Resident()
    node.data("/cat", cast("Any", _UnderDeclared(b"abc", resident)), media_type="image/png")
    budget = CapBudget()
    request = FetchRequest(
        "/cat", relative=True, on_declared=lambda size: budget.reserve("k", size)
    )
    with pytest.raises(ResolutionError) as caught:
        await node.fetch_bytes(request)
    assert str(caught.value) == str(whole_body_refused())
    assert "read_chunks" in str(caught.value)
    assert resident.reads == []
    with pytest.raises(ResolutionError):
        budget.raise_if_refused()  # INVARIANT: still sticky — an ;optional guard cannot swallow it


@pytest.mark.asyncio
async def test_a_run_reports_the_whole_body_remedy() -> None:
    body = b"w" * 40
    hex_ = hashlib.sha256(body).hexdigest()
    node = Url4Node("n1", default_processor="/reduce")
    node.data(f"/blob/sha256/{hex_}", cast("Any", _UnderDeclared(body, _Resident())))
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(f"(src=/blob/sha256/{hex_}, 'q')!'d'")
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert "read_chunks" in str(caught.value)
