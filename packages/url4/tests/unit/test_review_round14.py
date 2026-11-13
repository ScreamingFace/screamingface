"""PR #1587 review round 14: refusals that are knowable at run start spend nothing first.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``).
STORY: as a node operator, (1) counting a held non-ASCII ``[data]`` string's UTF-8 size before the
live cap draws it never builds a multi-MiB temporary; (2) a text-only run at my node whose
expression or reduce processor names a ``url4://`` node is refused ``x.remote_node_unsupported``
before ANY local endpoint or model runs (F1b); (3) a static Form-3 processor that does not parse
is refused before any member runs.
"""

from __future__ import annotations

import tracemalloc
from collections.abc import Callable

import pytest

from url4.core.errors import ErrorCode, ParseError, ResolutionError, Url4Error
from url4.dag._run import run
from url4.dag.remote_nodes import refuse_remote_nodes
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes
from url4.peer._bytes import _utf8_size
from url4.peer.server import Url4Node

# WHY a four-byte code point: CPython holds it as UCS-4, the widest slice and encode per char.
WIDE = "\U0001d11e" * 2_000_000
PEAK_BOUND = 1 << 20  # 1 MiB: far under the ~8 MiB one 1 MiB-character slice once cost


def _peak(call: Callable[[], object]) -> int:
    tracemalloc.start()
    try:
        call()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


# -- blocker 1: the UTF-8 count holds no large temporary --------------------------------------


def test_counting_a_wide_unicode_string_has_a_bounded_transient_peak() -> None:
    peak = _peak(lambda: _utf8_size(WIDE))
    assert peak < PEAK_BOUND, peak
    assert _utf8_size(WIDE) == len(WIDE.encode("utf-8"))


@pytest.mark.parametrize("text", ["", "a", "é", "☕", "\U0001d11e", "a☕é\U0001d11e" * 70_001])
def test_the_chunked_count_is_exact_across_chunk_boundaries(text: str) -> None:
    assert _utf8_size(text) == len(text.encode("utf-8"))


@pytest.mark.asyncio
async def test_a_refused_wide_held_body_is_refused_with_a_bounded_peak() -> None:
    node = Url4Node()
    node.data("/t", WIDE)

    def refuse(size: int | None) -> None:
        raise ResolutionError("over", code=ErrorCode.ATTACHMENTS_TOO_LARGE)

    request = FetchRequest("/t", relative=True, on_declared=refuse)
    tracemalloc.start()
    try:
        with pytest.raises(ResolutionError):
            await node.fetch_bytes(request)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < PEAK_BOUND, peak


# -- blocker 2: a text-only node run prechecks every remote call ------------------------------


class _Tripwire:
    """An outbound io that records every call on every port."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.calls.append(f"fetch {target}")
        return "remote"

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.calls.append(f"fetch_ex {request.target}")
        return FetchResult("remote")

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.calls.append(f"fetch_bytes {request.target}")
        return FetchedBytes(b"remote", "text/plain")


def _spied_node(*, default_processor: str | None = None) -> tuple[Url4Node, list[str], _Tripwire]:
    outbound = _Tripwire()
    node = Url4Node("n1", outbound=outbound, default_processor=default_processor)
    ran: list[str] = []
    for name in ("a", "b"):
        node.endpoint(f"/{name}")(lambda request, name=name: ran.append(name) or name.upper())
    return node, ran, outbound


def _assert_remote_refused(error: ResolutionError) -> None:
    assert (error.code, error.permanent) == (ErrorCode.REMOTE_NODE_UNSUPPORTED, True)


@pytest.mark.parametrize(
    "text",
    [
        "(/a(x)!'i', url4://n2/v1(x)!go)!'r'",  # the review probe: a mixed ensemble
        "(url4://n2/v1(x)!go, /a(x)!'i')!'r'",  # the remote member first
        "((/a(x)!'i')!'p', (url4://n2/v1(x)!go)!'q')!'r'",  # nested groups
        "(/a(x)!'i', /b(url4://n2/v1(x)!go)!'d')!'r'",  # inside a local call context
    ],
)
@pytest.mark.asyncio
async def test_a_text_only_remote_expression_refuses_before_any_local_endpoint(text: str) -> None:
    node, ran, outbound = _spied_node()
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(text)
    _assert_remote_refused(caught.value)
    assert ran == []
    assert outbound.calls == []


REDUCE = "(/a(x)!'i', /b(y)!'j')!'r'"


@pytest.mark.parametrize(
    "processor",
    [
        "url4://n2.example/v1",  # the review probe: a literal remote processor
        "(url4://n2/v1(x)!go)!'t'",  # a Form-3 processor that calls a node
    ],
)
@pytest.mark.asyncio
async def test_a_remote_default_processor_refuses_before_any_member_runs(processor: str) -> None:
    node, ran, outbound = _spied_node(default_processor=processor)
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(REDUCE)
    _assert_remote_refused(caught.value)
    assert ran == []
    assert outbound.calls == []


@pytest.mark.asyncio
async def test_a_callers_remote_processor_refuses_before_any_member_runs() -> None:
    node, ran, outbound = _spied_node()
    with pytest.raises(ResolutionError) as caught:
        await node.fetch(f"/v1?processor=url4://n2.example/v1&q={REDUCE}", relative=True)
    _assert_remote_refused(caught.value)
    assert ran == []
    assert outbound.calls == []


@pytest.mark.asyncio
async def test_a_remote_processor_under_bare_refusal_refuses_before_the_model() -> None:
    outbound, calls = _Tripwire(), []

    async def model(sources: str, intent: str | None, scope: object) -> str:
        calls.append(intent)
        return "m"

    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(
            run("(/m('a')!'x', /m('b')!'y')!'d'", outbound, processor="url4://n2/v1", process=model)
        )
    _assert_remote_refused(caught.value)
    assert calls == []
    assert outbound.calls == []


@pytest.mark.asyncio
async def test_a_local_text_only_reduce_at_a_node_still_runs() -> None:
    node, ran, outbound = _spied_node()
    result = await node.fetch(f"/v1?processor=/b&q={REDUCE}", relative=True)
    assert getattr(result, "text", result) == "B"
    assert sorted(set(ran)) == ["a", "b"]
    assert outbound.calls == []


# -- blocker 3: a malformed static Form-3 processor refuses before any member -----------------


TARGET = "(/m('a')!'member')!'d'"


@pytest.mark.parametrize(
    ("processor", "code"),
    [
        ("(src=https://f.example/p.png;accept=image/png", ErrorCode.MALFORMED_SOURCE),  # review
        ("('x', 'q'", ErrorCode.MALFORMED_SOURCE),
        ("('x')", ErrorCode.MISSING_INTENT),
    ],
)
@pytest.mark.asyncio
async def test_a_malformed_form3_processor_refuses_before_any_member(
    processor: str, code: ErrorCode
) -> None:
    outbound, calls = _Tripwire(), []

    async def model(sources: str, intent: str | None, scope: object) -> str:
        calls.append(intent)
        return "m"

    with pytest.raises(ParseError) as caught:
        await run(TARGET, outbound, processor=processor, process=model)
    assert (caught.value.code, caught.value.permanent) == (code, True)
    assert outbound.calls == []
    assert calls == []


@pytest.mark.asyncio
async def test_a_well_formed_text_only_form3_processor_still_reaches_the_member() -> None:
    outbound = _Tripwire()
    try:
        await run(TARGET, outbound, processor="('x', 'q')!'t'")
    except Url4Error as error:
        assert not isinstance(error, ParseError)
    assert outbound.calls  # the member ran
