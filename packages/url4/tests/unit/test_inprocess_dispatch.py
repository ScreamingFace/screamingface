"""In-process endpoint calls skip the wire round trip (memory fix 1, MMLU-Pro aggregate).

FEATURE: url4 in-process dispatch — spec ``docs/spec/2026-11-05-url4-inprocess-dispatch.md``.
STORY: as an operator running a 12k-Case benchmark, the aggregate call that carries every
Case row as its context does not percent-encode ~150 MB into a URL only for the same process
to parse it back, so the run stays inside its memory budget.

Three contracts are pinned here:

- INVARIANT (memory): an in-process endpoint call holds well under 3x its context at peak
  (the wire round trip held ~15x).
- INVARIANT (equivalence): an endpoint receives byte-identical ``context``, ``intent`` and
  ``params`` on the fast path and on the wire path — or the same refusal.
- INVARIANT (wire compatibility): the encoded bytes, the request's ``target``, equality and
  hash are unchanged, so every other adapter (static, HTTP, remote ``url4://``) sees exactly
  today's request.
"""

from __future__ import annotations

import gc
import json
import tracemalloc

import pytest

from url4.core.errors import ParseError, ResolutionError
from url4.dag import run
from url4.dag.nodes._subrequest_fetch import SubrequestFetch
from url4.io.layer import FetchRequest, FetchResult
from url4.io.static import StaticIOLayer
from url4.peer.server import Request, Url4Node
from url4.wire.subrequest import SubrequestCall, encode_subrequest

_MB = 1_000_000


def _recording_node() -> tuple[Url4Node, list[Request]]:
    node = Url4Node("eq")
    seen: list[Request] = []

    @node.endpoint("/sink")
    def sink(request: Request) -> str:
        seen.append(request)
        return "ok"

    return node, seen


def _escaped_json(size: int) -> str:
    """JSON rows dense in every character the wire escapes — the worst case for encoding."""
    row = {
        "id": 0,
        "text": "a (b) + c & d % e 'f' {g} #h\tq=1, !x",
        "nested": {"k": "( ) { } ' % + & # ="},
    }
    unit = json.dumps(row) + ",\n"
    return "[" + unit * (size // len(unit)) + "{}]"


# --- memory ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_process_endpoint_call_peaks_under_three_times_its_context() -> None:
    # WHY a data route as the context source: the context reaches RelUrlNode as resolved
    # data, exactly like the MMLU-Pro aggregate's gathered Case rows.
    context = _escaped_json(50 * _MB)
    node = Url4Node("mem")
    node.data("/api/big", context)
    lengths: list[int] = []

    @node.endpoint("/sink")
    def sink(request: Request) -> str:
        lengths.append(len(request.context))
        return "ok"

    gc.collect()
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        result = await node.evaluate("/sink(/api/big)!'go'")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result.text == "ok"
    assert lengths == [len(context)]
    assert peak < 3 * len(context), (
        f"peak {peak / _MB:.0f} MB for a {len(context) / _MB:.0f} MB context"
    )


# --- equivalence ----------------------------------------------------------------------

_EDGE = "% + & = ( ) ! ' ,"
_CASES: list[tuple[str, str | None, tuple[tuple[str, str], ...], bool]] = [
    (_EDGE, _EDGE, (), True),
    (_EDGE, _EDGE, (), False),
    ("%41%2B+%%", "%41 + %", (), True),
    ("unicodé — 日本語 🙂", "ünï 🙂", (("tone", "formal"),), True),
    ("", "", (), True),
    ("", None, (), True),
    ("ctx", None, (("broadcast", ""),), False),
    ("", "'already quoted'", (), False),
    ("", "'already quoted'", (), True),
    ("line\nbreak\ttab\r", "line\nbreak", (("note", "'a&b (c) %'"),), True),
    ("x", "go", (("processor", "/claude(a b)!'%+'"),), True),
    ("x", "go", (("a", "1"), ("b.c", "x,y:z/w"), ("flag", "")), True),
    ("trailing space ", " leading", (), True),
    ("x", "go", (("bad key", "v"),), True),
    ("x", "go", (("tone", "has space"),), True),
    ("x", "go", (("resume", "r1"), ("rid", "7"), ("tone", "warm")), True),
]


async def _received(node: Url4Node, seen: list[Request], request: FetchRequest) -> object:
    """What the endpoint was handed — or the refusal, as (type, message)."""
    seen.clear()
    try:
        await node.fetch_ex(request)
    except (ParseError, ResolutionError) as exc:
        return (type(exc), str(exc))
    assert len(seen) == 1
    got = seen[0]
    return (got.path, got.context, got.intent, dict(got.params))


@pytest.mark.asyncio
@pytest.mark.parametrize(("context", "intent", "params", "quote"), _CASES)
async def test_fast_path_and_wire_path_hand_the_endpoint_identical_values(
    context: str, intent: str | None, params: tuple[tuple[str, str], ...], quote: bool
) -> None:
    node, seen = _recording_node()
    call = SubrequestCall("/sink", context, intent, params, quote=quote)
    wire = FetchRequest(
        encode_subrequest("/sink", context, intent, params, quote=quote),
        relative=True,
        kind="relative",
    )
    via_wire = await _received(node, seen, wire)
    via_fast = await _received(node, seen, SubrequestFetch(call))
    assert via_fast == via_wire
    if isinstance(via_fast, tuple) and via_fast[0] == "/sink":
        # INVARIANT: the fast path passes the context through — the very same object.
        assert seen[0].context is context


@pytest.mark.asyncio
async def test_a_full_run_reaches_the_endpoint_with_the_same_values_as_before() -> None:
    node, seen = _recording_node()
    node.data("/api/edge", _EDGE)
    result = await node.evaluate("/sink(/api/edge)!'% + & = ( ) ! , ünï'")
    assert result.text == "ok"
    assert [(r.context, r.intent) for r in seen] == [(_EDGE, "% + & = ( ) ! , ünï")]


# --- wire compatibility ---------------------------------------------------------------


@pytest.mark.parametrize(("context", "intent", "params", "quote"), _CASES)
def test_the_call_encodes_to_exactly_todays_bytes(
    context: str, intent: str | None, params: tuple[tuple[str, str], ...], quote: bool
) -> None:
    expected = encode_subrequest("/sink", context, intent, params, quote=quote)
    call = SubrequestCall("/sink", context, intent, params, quote=quote)
    assert call.encode() == expected
    request = SubrequestFetch(call, accept="application/json")
    plain = FetchRequest(expected, relative=True, kind="relative", accept="application/json")
    assert request.target == expected
    assert request == plain
    assert plain == request
    assert hash(request) == hash(plain)
    assert (request.relative, request.kind, request.accept) == (
        True,
        "relative",
        "application/json",
    )


def test_the_target_is_encoded_only_when_read_and_only_once() -> None:
    call = SubrequestCall("/sink", "a b", "go", (), quote=True)
    request = SubrequestFetch(call)
    assert "target" not in vars(request)
    first = request.target
    assert vars(request)["target"] == first
    assert request.target is first


def test_a_missing_attribute_still_raises_attribute_error() -> None:
    request = SubrequestFetch(SubrequestCall("/sink", "", None))
    name = "not_a_field"
    with pytest.raises(AttributeError):
        getattr(request, name)


class _Recorder:
    """An io layer that records every request it is handed and answers ``"r"``."""

    def __init__(self) -> None:
        self.requests: list[FetchRequest] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        raise AssertionError("fetch_ex is the port this test drives")

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.requests.append(request)
        return FetchResult("r")


@pytest.mark.asyncio
async def test_a_remote_call_keeps_todays_wire_bytes() -> None:
    # RemoteFetchNode is untouched: its target is today's codec output, url4://-prefixed,
    # pinned here as literal bytes measured on origin/main before this change.
    io = _Recorder()
    await run("url4://peer.example/claude(% + & = ( ) ! , ünï)!'go now'", io)
    assert [(r.target, type(r)) for r in io.requests] == [
        (
            "url4://peer.example/claude?q=(%25%20%2B%20%26%20=%20%28%20%29%20!%20,%20ünï)!%27go%20now%27",
            FetchRequest,
        )
    ]
    rel = encode_subrequest("/claude", _EDGE, _EDGE, (("tone", "formal"),), quote=True)
    assert rel == (
        "/claude?tone=formal&q=(%25%20%2B%20%26%20=%20%28%20%29%20!%20%27%20,)!"
        "%27%25%20%2B%20%26%20=%20%28%20%29%20!%20\\%27%20,%27"
    )


@pytest.mark.asyncio
async def test_a_relative_call_to_another_adapter_carries_todays_target() -> None:
    io = _Recorder()
    await run("/claude(% + & = ( ) ! , ünï)!'go now'", io)
    assert [r.target for r in io.requests] == [
        "/claude?q=(%25%20%2B%20%26%20=%20%28%20%29%20!%20,%20ünï)!%27go%20now%27"
    ]
    assert io.requests == [FetchRequest(io.requests[0].target, relative=True, kind="relative")]


@pytest.mark.asyncio
async def test_another_adapter_decodes_the_lazy_target_like_todays() -> None:
    io = StaticIOLayer(routes={"/sink": lambda context, intent: f"{context}|{intent}"})
    call = SubrequestCall("/sink", _EDGE, _EDGE, (), quote=True)
    plain = FetchRequest(call.encode(), relative=True, kind="relative")
    got = await io.fetch_ex(SubrequestFetch(call))
    assert got == await io.fetch_ex(plain)
    assert got.body == f"{_EDGE}|{_EDGE}"


# --- fallbacks: only a registered endpoint takes the fast path ------------------------


@pytest.mark.asyncio
async def test_the_eval_path_still_takes_the_wire_path() -> None:
    node = Url4Node("ev")

    @node.endpoint("/echo")
    def echo(request: Request) -> str:
        return f"[{request.context}|{request.intent}]"

    request = SubrequestFetch(SubrequestCall("/v1", "a b", "hi", (), quote=True))
    wire = FetchRequest(request.target, relative=True, kind="relative")
    got = await node.fetch_ex(request)
    # The eval path evaluates `(a b)!'hi'` — whatever it yields, it yields it either way.
    assert got == await node.fetch_ex(wire)


@pytest.mark.asyncio
async def test_a_data_route_and_an_unknown_path_still_take_the_wire_path() -> None:
    node = Url4Node("dr")
    node.data("/api/rows", '["a"]', media_type="application/json")
    got = await node.fetch_ex(SubrequestFetch(SubrequestCall("/api/rows", "x", "y")))
    assert (got.body, got.media_type) == ('["a"]', "application/json")
    with pytest.raises(ResolutionError) as exc:
        await node.fetch_ex(SubrequestFetch(SubrequestCall("/nowhere", "x", "y")))
    assert exc.value.code == "endpoint_not_found"


@pytest.mark.asyncio
async def test_a_path_carrying_its_own_query_takes_the_wire_path() -> None:
    # The wire path splits at the FIRST "?", so the call's own `q=` lands inside `tone`'s
    # value and is refused; the fast path must not quietly accept what the wire refuses.
    node, seen = _recording_node()
    call = SubrequestCall("/sink?tone=formal", "ctx", "go", (), quote=True)
    wire = FetchRequest(call.encode(), relative=True, kind="relative")
    via_wire = await _received(node, seen, wire)
    assert via_wire == await _received(node, seen, SubrequestFetch(call))
    assert isinstance(via_wire, tuple) and via_wire[0] is ParseError


def test_a_request_never_equals_a_non_request() -> None:
    request = SubrequestFetch(SubrequestCall("/sink", "a", "b"))
    target = request.target
    assert request != target
    assert request != object()
