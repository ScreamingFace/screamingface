"""PR #1587 review round 10: the three remaining bypasses, closed (owner decisions 2026-11-05).

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``).
STORY (finding 1b): as a node operator, a ``[data]`` provider that can only hand over its bytes
whole draws its DECLARED size from the run's byte budget before it is read; a provider that
declares no size, or one over the budget, is refused ``x.attachments_too_large`` unread.
STORY (finding 2): as an ensemble author, a picture under ``/rows/$xs*(…)`` whose ``xs`` is a
model's output is refused ``x.source_not_static`` before any I/O; a binding cycle fetches nothing.
STORY (finding 3): as a node operator, a Form-3 processor expression that calls ``url4://…`` is
refused ``x.remote_node_unsupported`` before any run-start I/O.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from typing import Any, cast

import pytest

from url4.core.errors import ErrorCode, ResolutionError, Url4Error
from url4.core.grammar import parse
from url4.core.nodes import Binding, Expression, Iteration, Node
from url4.dag._caps import MAX_ATTACHMENT_BYTES, CapBudget
from url4.dag._collection_shape import MODEL, resolve_collection
from url4.dag._run import run
from url4.dag.remote_nodes import refuse_remote_nodes
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes
from url4.peer.server import Url4Node

CAP = MAX_ATTACHMENT_BYTES
IMG = "https://img.example/t.png"
PNG = b"\x89PNG\r\n\x1a\n-round10"


class _Tripwire:
    """An io that records every call on every port."""

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
        return FetchedBytes(PNG, "image/png")

    def has_code(self, pointer: str) -> bool:
        return True  # the repro's bare ``!d`` / ``!r`` are code pointers

    async def invoke_code(self, call: object) -> object:
        self.calls.append("invoke_code")
        return "ok"


async def _ok(sources: str, intent: str | None, scope: object) -> str:
    return "ok"


# -- finding 1b: a whole-body provider draws its declared size BEFORE the read ----------------


class _Resident:
    """The bytes the providers hold at once, and the most they ever held together."""

    def __init__(self) -> None:
        self.now = 0
        self.peak = 0
        self.reads: list[int] = []
        self.all_in = asyncio.Event()  # set once two reads are resident together


class _Whole:
    """A ``[data]`` provider that can hand over its bytes only whole (no ``read_chunks``)."""

    def __init__(self, body: bytes, resident: _Resident, declared: int | None) -> None:
        self._body = body
        self._resident = resident
        self._declared = declared

    async def __call__(self) -> str:
        raise AssertionError("the bytes path must not read the text port")

    async def read_bytes(self) -> bytes:
        held = len(self._body)
        self._resident.reads.append(held)
        self._resident.now += held
        self._resident.peak = max(self._resident.peak, self._resident.now)
        if len(self._resident.reads) >= 2:
            self._resident.all_in.set()
        try:
            # Synchronized: a read waits for its sibling, so without the fix both are resident.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._resident.all_in.wait(), 0.2)
            return self._body
        finally:
            self._resident.now -= held


class _Declared(_Whole):
    def declared_size(self) -> int | None:
        return self._declared


def _blob(fill: bytes, size: int) -> tuple[bytes, str]:
    body = fill * size
    return body, hashlib.sha256(body).hexdigest()


def _node(providers: dict[str, object]) -> Url4Node:
    node = Url4Node("n1", default_processor="/reduce")
    for hex_, provider in providers.items():
        node.data(f"/blob/sha256/{hex_}", cast("Any", provider), media_type="image/png")
    return node


@pytest.mark.asyncio
async def test_two_synchronized_whole_body_providers_peak_at_no_more_than_the_cap() -> None:
    resident = _Resident()
    a, a_hex = _blob(b"a", 7_000_000)
    b, b_hex = _blob(b"b", 7_000_000)
    node = _node({a_hex: _Declared(a, resident, len(a)), b_hex: _Declared(b, resident, len(b))})
    text = f"(src=/blob/sha256/{a_hex}, src=/blob/sha256/{b_hex})!'d'"
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(text)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    # INVARIANT: the second body is refused before it is read, so at most one is resident.
    assert resident.peak <= CAP
    assert len(resident.reads) <= 1


@pytest.mark.asyncio
async def test_a_whole_body_provider_with_no_declared_size_is_refused_unread() -> None:
    resident = _Resident()
    body, hex_ = _blob(b"u", 10)
    node = _node({hex_: _Whole(body, resident, None)})
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(f"(src=/blob/sha256/{hex_}, 'q')!'d'")
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert resident.reads == []


@pytest.mark.asyncio
async def test_a_declared_size_over_the_budget_is_refused_unread() -> None:
    resident = _Resident()
    body, hex_ = _blob(b"o", 10)
    node = _node({hex_: _Declared(body, resident, CAP + 1)})
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(f"(src=/blob/sha256/{hex_}, 'q')!'d'")
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    assert resident.reads == []


def test_a_reserve_of_unknown_size_is_refused_and_sticky() -> None:
    budget = CapBudget()
    with pytest.raises(ResolutionError) as caught:
        budget.reserve("k", None)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE
    with pytest.raises(ResolutionError):
        budget.raise_if_refused()  # an ;optional guard cannot swallow it


def test_a_reserve_draws_the_declared_size_from_the_live_budget() -> None:
    budget = CapBudget()
    budget.reserve("a", 5_000_000)
    with pytest.raises(ResolutionError) as caught:
        budget.reserve("b", 3_000_001)
    assert caught.value.code == ErrorCode.ATTACHMENTS_TOO_LARGE


@pytest.mark.asyncio
async def test_bytes_beyond_the_declared_size_are_drawn_after_the_read() -> None:
    node = Url4Node()
    resident = _Resident()
    node.data("/cat", cast("Any", _Declared(PNG, resident, 4)), media_type="image/png")
    declared: list[int | None] = []
    drawn: list[int] = []
    request = FetchRequest(
        "/cat", relative=True, on_chunk=drawn.append, on_declared=declared.append
    )
    got = await node.fetch_bytes(request)
    assert got.body == PNG
    assert (declared, drawn) == ([4], [len(PNG) - 4])  # each byte drawn once


@pytest.mark.asyncio
async def test_a_declared_size_over_max_bytes_is_too_large_before_the_read() -> None:
    node = Url4Node()
    resident = _Resident()
    node.data("/cat", cast("Any", _Declared(PNG, resident, len(PNG))), media_type="image/png")
    request = FetchRequest("/cat", relative=True, max_bytes=4, on_declared=lambda _: None)
    with pytest.raises(ResolutionError) as caught:
        await node.fetch_bytes(request)
    assert caught.value.code == ErrorCode.SOURCE_TOO_LARGE
    assert resident.reads == []


@pytest.mark.asyncio
async def test_an_honest_declared_body_is_attached() -> None:
    resident = _Resident()
    body, hex_ = _blob(b"h", 1000)
    node = Url4Node("n1")
    node.data(f"/blob/sha256/{hex_}", cast("Any", _Declared(body, resident, 1000)))
    seen: list[int] = []

    async def model(sources: str, intent: str | None, scope: object) -> str:
        from url4.dag.attachments import current_attachments

        seen.extend(len(x.body) for x in current_attachments())
        return "ok"

    assert await run(f"(src=/blob/sha256/{hex_}, 'q')!'d'", node, process=model)
    assert seen == [1000]


# -- finding 2: a templated collection over a model's output ----------------------------------


@pytest.mark.parametrize(
    "text",
    [
        f"(xs=/m(q)!list, /rows/$xs*(src={IMG};accept=image/png)!d)!r",
        f"(ys=/m(q)!list, xs=$ys, /rows/$xs*(src={IMG};accept=image/png)!d)!r",
        f"(xs=/m(q)!list, ys=/rows/$xs, $ys*(src={IMG};accept=image/png)!d)!r",
    ],
)
@pytest.mark.asyncio
async def test_a_model_derived_templated_collection_is_not_static_with_zero_io(text: str) -> None:
    io = _Tripwire()
    with pytest.raises(ResolutionError) as caught:
        await run(text, io, process=_ok)
    assert (caught.value.code, caught.value.permanent) == (ErrorCode.SOURCE_NOT_STATIC, True)
    assert io.calls == []


def _bound(text: str) -> tuple[Node, dict[str, Node]]:
    ast = parse(text)
    assert isinstance(ast, Expression)
    *bindings, iteration = ast.sources
    assert isinstance(iteration, Iteration)
    return iteration.collection, {b.name: b.value for b in bindings if isinstance(b, Binding)}


def test_a_self_referencing_template_terminates() -> None:
    items, bound = _bound("(xs=/rows/$xs, $xs*($item)!'d')!'r'")
    assert resolve_collection(items, bound).kind != MODEL  # terminates; no model on the chain


@pytest.mark.asyncio
async def test_a_binding_cycle_fetches_nothing() -> None:
    io = _Tripwire()
    with pytest.raises(Url4Error):
        await run(f"(xs=$ys, ys=$xs, $xs*(src={IMG};accept=image/png)!'d')!'r'", io, process=_ok)
    assert not any(IMG in call for call in io.calls)


# -- finding 3: a remote call inside a Form-3 processor expression ----------------------------

FORM3 = "(url4://n2/v1(x)!go)!url4://n3/reduce"
WITH_IMAGE = f"(src={IMG};accept=image/png, 'q')!'d'"


@pytest.mark.asyncio
async def test_a_form3_default_processor_with_a_remote_call_refuses_before_any_io() -> None:
    outbound = _Tripwire()
    node = Url4Node("n1", outbound=outbound, default_processor=FORM3)
    with pytest.raises(ResolutionError) as caught:
        await node.evaluate(WITH_IMAGE)
    assert caught.value.code == ErrorCode.REMOTE_NODE_UNSUPPORTED
    assert outbound.calls == []


@pytest.mark.asyncio
async def test_a_form3_processor_run_option_with_a_remote_call_refuses_before_any_io() -> None:
    io = _Tripwire()
    with pytest.raises(ResolutionError) as caught:
        await refuse_remote_nodes(run(WITH_IMAGE, io, processor="(url4://n2/v1(x)!go)!'pick'"))
    assert caught.value.code == ErrorCode.REMOTE_NODE_UNSUPPORTED
    assert io.calls == []


# -- finding 1a: a Case attachment's digest reuses the verified Case bytes --------------------


class _Store:
    """A store that would serve the same digest again; records every read."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.reads: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.reads.append(f"fetch {target}")
        return ""

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.reads.append(f"fetch_bytes {request.target}")
        if request.on_chunk is not None:
            request.on_chunk(len(self.body))
        return FetchedBytes(bytes(self.body), "image/png")  # a distinct second copy


@pytest.mark.parametrize("collection", [False, True])
@pytest.mark.asyncio
async def test_an_8_mb_case_attachment_and_its_store_body_leave_one_copy(collection: bool) -> None:
    from url4.dag.attachment import Attachment
    from url4.dag.attachments import current_attachments

    body, hex_ = _blob(b"c", CAP)  # exactly 8,000,000 bytes
    case = Attachment(f"sha256:{hex_}", "image/png", body)
    store = _Store(body)
    seen: list[tuple[Attachment, ...]] = []

    async def model(sources: str, intent: str | None, scope: object) -> str:
        seen.append(current_attachments())
        return "ok"

    if collection:  # a collection read of the same digest reuses the Case bytes too (C8 here)
        with pytest.raises(ResolutionError) as caught:
            await run(
                f"(/blob/sha256/{hex_}*($item)!'d')!'r'", store, process=model, attachments=[case]
            )
        assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE
    else:
        assert await run(
            f"(src=/blob/sha256/{hex_}, 'q')!'d'", store, process=model, attachments=[case]
        )
        (attached,) = seen
        assert [x.body is body for x in attached] == [True]  # the one resident copy
    assert store.reads == []  # the store copy is never read


# -- security review: the template walk is bounded --------------------------------------------


def _timed(items: Node, bound: dict[str, Node]) -> tuple[str, float]:
    import time

    start = time.perf_counter()
    kind = resolve_collection(items, bound).kind
    return kind, time.perf_counter() - start


def test_a_deep_doubling_template_chain_resolves_in_bounded_time() -> None:
    from url4.core.nodes import RelUrl, Text

    # Each level substitutes the next twice: 2**60 paths for a per-path walk.
    bound: dict[str, Node] = {f"x{i}": RelUrl(f"/r/$x{i + 1}/$x{i + 1}") for i in range(60)}
    bound["x60"] = Text("a")
    kind, took = _timed(RelUrl("/r/$x0"), bound)
    assert kind != MODEL and took < 1.0


def test_a_dense_fan_out_of_templates_and_aliases_resolves_in_bounded_time() -> None:
    from url4.core.nodes import RelUrl, VarRef

    # Every binding's template names every other binding, and each has an alias: k! orders.
    k = 300
    every = "/".join(f"$t{j}" for j in range(k))
    bound: dict[str, Node] = {f"t{i}": RelUrl(f"/r/{every}") for i in range(k)}
    bound.update({f"a{i}": VarRef(f"t{i}") for i in range(k)})
    kind, took = _timed(RelUrl("/r/" + "/".join(f"$a{i}" for i in range(k))), bound)
    assert kind != MODEL and took < 1.0


def test_a_long_template_with_a_model_at_its_end_resolves_in_bounded_time() -> None:
    from url4.core.nodes import RelExpr, RelUrl

    bound: dict[str, Node] = {"m": RelExpr(path="/m", context="q", intent=None, params=())}
    kind, took = _timed(RelUrl("/r/" + "$$x" * 200_000 + "$m"), bound)
    assert kind == MODEL and took < 1.0


@pytest.mark.asyncio
async def test_a_template_walk_past_its_step_budget_fails_closed_with_zero_io() -> None:
    from url4.dag._collection_shape import MAX_TEMPLATE_STEPS

    n = MAX_TEMPLATE_STEPS + 1
    chain = ", ".join(f"x{i}=/r/$x{i + 1}" for i in range(n))
    io = _Tripwire()
    with pytest.raises(ResolutionError) as caught:
        await run(
            f"(x{n}='a', {chain}, /rows/$x0*(src={IMG};accept=image/png)!'d')!'r'", io, process=_ok
        )
    assert caught.value.code == ErrorCode.SOURCE_NOT_STATIC
    assert io.calls == []
