"""The DAG capabilities: scheduling, memoization, laziness, extensibility."""

from __future__ import annotations

import asyncio
import json

import pytest
from conftest import RecordingIOLayer

from url4.core.errors import CollectionError, CycleError, ParseError, ResolutionError
from url4.core.grammar import parse as grammar_parse
from url4.core.grammar import parse_group_root
from url4.core.nodes import ForeachDirectives, Text, Url
from url4.dag import (
    DEFAULT_MAP_CONCURRENCY,
    BindingNode,
    CodePointerNode,
    ExecutionContext,
    ExpandNode,
    FanoutReduceNode,
    GuardNode,
    JoinNode,
    LazyExprNode,
    MapNode,
    ProcessNode,
    RelUrlNode,
    StructNode,
    TextNode,
    WebFetchNode,
    compile_expression,
    default_registry,
    run,
)
from url4.io.static import StaticIOLayer


class BarrierIOLayer:
    """Releases fetches only once ``expected`` of them are in flight at once."""

    def __init__(self, expected: int) -> None:
        self._expected = expected
        self._in_flight: set[str] = set()
        self._all_started = asyncio.Event()

    async def fetch(self, target: str, *, relative: bool) -> str:
        self._in_flight.add(target)
        if len(self._in_flight) >= self._expected:
            self._all_started.set()
        await asyncio.wait_for(self._all_started.wait(), timeout=2)
        return target.rsplit("/", 1)[-1].upper()


@pytest.mark.asyncio
async def test_independent_sources_fetch_in_parallel() -> None:
    # Each fetch blocks until BOTH are in flight — only true parallelism passes.
    resolver = BarrierIOLayer(expected=2)
    result = await run("(https://host/a, https://host/b)!go", resolver)
    assert result == "go\n\nA\nB"


@pytest.mark.asyncio
async def test_global_concurrency_bound_caps_bare_fanout() -> None:
    # C1: run()'s global concurrency bound must cap a bare fan-out group's
    # independent sources, not just MapNode rows (which only have a node-local
    # cap). 8 sources, bound to 2 in flight at once.
    in_flight = 0
    seen_max = 0

    class CountingIOLayer:
        async def fetch(self, target: str, *, relative: bool) -> str:
            nonlocal in_flight, seen_max
            in_flight += 1
            seen_max = max(seen_max, in_flight)
            await asyncio.sleep(0)
            in_flight -= 1
            return target.rsplit("/", 1)[-1].upper()

    sources = ", ".join(f"https://host/{c}" for c in "abcdefgh")
    await run(f"({sources})!go", CountingIOLayer(), concurrency=2)
    assert seen_max <= 2
    assert seen_max > 1  # still parallel, just bounded — not accidentally serial


@pytest.mark.asyncio
async def test_global_concurrency_bound_holds_across_mixed_fanout_and_map() -> None:
    # C1: the global bound must hold across a SINGLE run mixing a bare fan-out
    # of independent sources with a MapNode's rows — both node kinds fetch
    # through the one run-wide BoundedIOLayer wrapper, so combined in-flight
    # fetches never exceed the global bound even though MapNode's own per-row
    # cap (left at its default here, which is looser) would otherwise allow
    # every row to attempt concurrently.
    in_flight = 0
    seen_max = 0

    class CountingIOLayer:
        async def fetch(self, target: str, *, relative: bool) -> str:
            nonlocal in_flight, seen_max
            in_flight += 1
            seen_max = max(seen_max, in_flight)
            await asyncio.sleep(0)
            in_flight -= 1
            return "x"

    collection = TextNode('["1", "2", "3", "4"]')
    map_node = MapNode(body="https://row/item", deps={"collection": collection})
    graph = JoinNode(
        deps={
            "part:0": WebFetchNode("https://a"),
            "part:1": WebFetchNode("https://b"),
            "part:2": map_node,
        }
    )
    await run(graph, CountingIOLayer(), concurrency=2)
    assert seen_max <= 2
    assert seen_max > 1


@pytest.mark.asyncio
async def test_global_concurrency_bound_can_be_disabled() -> None:
    # concurrency=None is the documented escape hatch back to the pre-existing
    # unbounded behavior. BarrierIOLayer requires BOTH fetches in flight at
    # once — a wrongly-applied low bound would deadlock (and time out) here.
    resolver = BarrierIOLayer(expected=2)
    result = await run("(https://host/a, https://host/b)!go", resolver, concurrency=None)
    assert result == "go\n\nA\nB"


@pytest.mark.asyncio
async def test_run_rejects_zero_concurrency_instead_of_deadlocking() -> None:
    # BUG-1 regression: concurrency=0 used to build asyncio.Semaphore(0), which
    # can never be acquired — every fetch hung forever (no error, no timeout, and
    # the finally/aclose never ran, leaking the owned client). It must now raise
    # a clear ValueError at the run() boundary, before any scheduling.
    resolver = StaticIOLayer(fetch_map={"https://a": "A", "https://b": "B"})
    with pytest.raises(ValueError, match="concurrency.*>= 1"):
        await run("(https://a, https://b)!go", resolver, concurrency=0)


@pytest.mark.asyncio
async def test_run_rejects_negative_concurrency() -> None:
    # Negative concurrency previously surfaced as a raw asyncio ValueError from
    # Semaphore deep in the executor at first-fetch time; it must raise the
    # url4-level guard at the call site instead.
    resolver = StaticIOLayer(fetch_map={"https://a": "A"})
    with pytest.raises(ValueError, match="concurrency.*>= 1"):
        await run("https://a!go", resolver, concurrency=-5)


@pytest.mark.asyncio
async def test_run_rejects_non_int_concurrency() -> None:
    # A non-int (e.g. a str from upstream config) would otherwise reach
    # asyncio.Semaphore and raise a confusing TypeError; guard it at run().
    resolver = StaticIOLayer(fetch_map={"https://a": "A"})
    with pytest.raises(TypeError, match="concurrency.*int"):
        await run("https://a!go", resolver, concurrency="2")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_run_zero_concurrency_does_not_hang() -> None:
    # The guard fires before BoundedIOLayer is built, so run() returns promptly
    # instead of hanging on a Semaphore(0) that can never be acquired.
    import time

    started = time.monotonic()
    with pytest.raises(ValueError):
        await run("(https://a, https://b)!go", None, concurrency=0)
    assert time.monotonic() - started < 5  # never hangs


@pytest.mark.asyncio
async def test_diamond_binding_resolved_once() -> None:
    # One binding read by two consumers and the intent → a single fetch.
    resolver = RecordingIOLayer(fetch_map={"https://x": "V"})
    result = await run("(a=https://x, use $a, also $a)!both: $a", resolver)
    assert result == "both: V\n\na: V\nuse V\nalso V"  # `OME-534`: a packs too
    assert resolver.fetches.count("https://x") == 1


@pytest.mark.asyncio
async def test_map_concurrency_bound_respected() -> None:
    in_flight = 0
    seen_max = 0

    async def solve(context: str, intent: str) -> str:
        nonlocal in_flight, seen_max
        in_flight += 1
        seen_max = max(seen_max, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        return context

    resolver = StaticIOLayer(
        fetch_map={"https://data": '[{"q": "1"}, {"q": "2"}, {"q": "3"}, {"q": "4"}]'},
        routes={"/solve": solve},
    )
    await run("https://data*(r=/solve($item.q)!'go')!'$r';iteration.concurrency=2", resolver)
    assert seen_max <= 2


@pytest.mark.asyncio
async def test_map_default_concurrency_is_bounded() -> None:
    # C2: no `;foreach.concurrency` directive must NOT mean "all rows at once".
    # A collection larger than DEFAULT_MAP_CONCURRENCY must still respect it.
    in_flight = 0
    seen_max = 0

    async def solve(context: str, intent: str) -> str:
        nonlocal in_flight, seen_max
        in_flight += 1
        seen_max = max(seen_max, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        return context

    rows = [{"q": str(i)} for i in range(DEFAULT_MAP_CONCURRENCY * 3)]
    resolver = StaticIOLayer(
        fetch_map={"https://data": json.dumps(rows)},
        routes={"/solve": solve},
    )
    await run("https://data*(r=/solve($item.q)!'go')!'$r'", resolver)
    assert seen_max <= DEFAULT_MAP_CONCURRENCY
    assert seen_max > 1  # still parallel, just bounded — not accidentally serial


@pytest.mark.asyncio
async def test_map_non_positive_concurrency_falls_back_to_default() -> None:
    # A falsy/non-positive concurrency (only reachable by constructing
    # IterationDirectives directly — the surface `;iteration.concurrency`
    # syntax rejects n < 1) must mean "use the default bound", never "unbounded".
    resolver = StaticIOLayer(fetch_map={"https://data": '["1", "2"]'})
    graph = compile_expression("https://data*(r:0:$item)!'$r'")
    map_node = graph.sink.deps["rows"]
    assert isinstance(map_node, MapNode)
    map_node.directives = ForeachDirectives(concurrency=0)
    result = await run(graph, resolver)
    assert json.loads(result) == ["1", "2"]


@pytest.mark.asyncio
async def test_abort_cancels_sibling_rows() -> None:
    slow_started = asyncio.Event()
    slow_cancelled = asyncio.Event()

    async def solve(context: str, intent: str) -> str:
        if context == "bad":
            await asyncio.wait_for(slow_started.wait(), timeout=2)
            raise RuntimeError("boom")
        slow_started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            slow_cancelled.set()
            raise
        return context

    resolver = StaticIOLayer(
        fetch_map={"https://data": '[{"q": "slow"}, {"q": "bad"}]'},
        routes={"/solve": solve},
    )
    with pytest.raises(RuntimeError, match="boom"):
        await run("https://data*(r=/solve($item.q)!'go')!'$r';iteration.on_error=fail", resolver)
    assert slow_cancelled.is_set()


class ShoutNode:
    """A custom node: satisfies the DagNode protocol with no inheritance."""

    def __init__(self, inner) -> None:
        self._deps: dict = {"inner": inner}

    @property
    def deps(self):
        return self._deps

    async def resolve(self, inputs, ctx) -> str:
        value = inputs["inner"]
        return (value if isinstance(value, str) else "\n".join(value)).upper()


@pytest.mark.asyncio
async def test_custom_node_in_hand_built_graph() -> None:
    node = ShoutNode(TextNode("hello world"))
    assert await run(node, RecordingIOLayer()) == "HELLO WORLD"


@pytest.mark.asyncio
async def test_cycle_detected_before_any_resolve() -> None:
    a = ShoutNode(TextNode("x"))
    b = ShoutNode(a)
    a._deps["back"] = b  # forge a cycle
    with pytest.raises(CycleError):
        await run(b, RecordingIOLayer())


@pytest.mark.asyncio
async def test_lowering_registry_override() -> None:
    class CachedNode:
        deps: dict = {}

        async def resolve(self, inputs, ctx) -> str:
            return "CACHED"

    registry = default_registry()
    registry.register(Url, lambda node, edges, reg: CachedNode())
    result = await run("https://x!go", RecordingIOLayer(), registry=registry)
    assert result == "go\n\nCACHED"


def test_collect_captures_errors_but_propagates_cancellation() -> None:
    node = MapNode(body="x")
    ctx = ExecutionContext(StaticIOLayer())
    # A regular error is captured as a per-row data result...
    out = node._collect([ResolutionError("boom"), "ok"], ctx)
    assert ctx.collected_errors == 1
    assert '"error"' in out[0] and out[1] == "ok"
    # ...but a CancelledError is a control-flow signal, never a row: it propagates.
    with pytest.raises(asyncio.CancelledError):
        node._collect([asyncio.CancelledError()], ctx)


def test_skip_omits_errors_but_propagates_cancellation() -> None:
    # nodes.py MapNode._skip(): the ;iteration.on_error=skip twin of
    # _collect() above — a regular error is omitted from the results...
    node = MapNode(body="x")
    out = node._skip(["ok", ResolutionError("boom")])
    assert out == ["ok"]
    # ...but a CancelledError is a control-flow signal, never a row: it propagates.
    with pytest.raises(asyncio.CancelledError):
        node._skip([asyncio.CancelledError()])


@pytest.mark.asyncio
async def test_validate_uses_graph_registry_for_lazy_fragments() -> None:
    class Marker(Exception):
        pass

    def boom(node, edges, reg):
        raise Marker()

    registry = default_registry()
    registry.register(Url, boom)
    # The nested group defers to a LazyExprNode, so the custom (raising) Url
    # lowering isn't reached at outer compile...
    graph = compile_expression("(a, (https://x, https://z)!y)!go", registry=registry)
    # ...but validate() must expand it with the graph's own registry, not the
    # default — reaching boom. (Old behavior compiled with default_registry and
    # silently validated an expression using the custom form.)
    with pytest.raises(Marker):
        graph.validate()


def test_nested_group_compiles_to_lazy_thunk() -> None:
    graph = compile_expression("(a, (nested, stuff)!x)!go")
    lazies = [node for node in graph.walk() if isinstance(node, LazyExprNode)]
    assert [lazy.text for lazy in lazies] == ["(nested, stuff)!x"]


@pytest.mark.asyncio
async def test_malformed_nested_fragment_errors_only_at_execution() -> None:
    # The nested group's inner text is invalid url4 — compile defers it...
    graph = compile_expression("(a, ((b)(c))!x)!go")
    # ...validate() forces expansion and fails fast...
    with pytest.raises(ParseError):
        graph.validate()
    # ...and executing reaches the thunk and raises the same error.
    with pytest.raises(ParseError):
        await run(graph, RecordingIOLayer())


def test_graph_shape_for_mixed_group() -> None:
    graph = compile_expression("(a=x, /c()!go)!m")
    sink = graph.sink
    assert isinstance(sink, ProcessNode)
    assert list(sink.deps) == ["src:0", "src:1"]
    assert isinstance(sink.deps["src:0"], BindingNode)
    # A text intent is ProcessNode's template, substituted against the
    # populated post-gather scope (expansion renumbers $N there — §5.3.12.4).
    assert sink.intent_template == "m"
    # `OME-534`: the SlotSpec bool means INSTRUMENTAL (weight 0.0), and a
    # name-only binding contributes — so it is False here.
    assert sink.slots == (("a", False), (None, False))


@pytest.mark.asyncio
async def test_explicit_context_reports_collected_errors() -> None:
    resolver = StaticIOLayer(
        fetch_map={"https://data": '[{"q": "ok"}, {"other": "bad"}]'},
        routes={"/solve": lambda context, intent: context},
    )
    ctx = ExecutionContext(resolver, strict_fields=True)
    await run("https://data*(r=/solve($item.q)!'go')!'$r'", ctx=ctx)
    assert ctx.collected_errors == 1


@pytest.mark.asyncio
async def test_shared_ctx_across_concurrent_runs_gets_independent_spawn_wiring() -> None:
    # C4: run() must not mutate a caller-supplied ctx's spawn wiring in place —
    # two overlapping run() calls sharing one ctx, each with its own registry,
    # must each spawn MapNode rows through their OWN registry, not whichever one
    # wired last. This is the regression test for the ctx.spawn logical race.
    resolver = StaticIOLayer(fetch_map={"https://data": '["1"]'})
    ctx = ExecutionContext(resolver)

    def _make_registry(prefix: str):
        registry = default_registry()

        def _lower_text_prefixed(node, edges, _registry):
            assert isinstance(node, Text)
            return TextNode(f"{prefix}{node.value}", deps=dict(edges))

        registry.register(Text, _lower_text_prefixed)
        return registry

    # "row $item" parses as a Text atom (a standalone "$item" is a VarRef and
    # would bypass the custom Text lowering this test observes).
    result_a, result_b = await asyncio.gather(
        run("https://data*(r:0:'row $item')!'$r'", ctx=ctx, registry=_make_registry("A:")),
        run("https://data*(r:0:'row $item')!'$r'", ctx=ctx, registry=_make_registry("B:")),
    )
    assert json.loads(result_a) == ["A:row 1"]
    assert json.loads(result_b) == ["B:row 1"]


@pytest.mark.asyncio
async def test_run_rejects_ctx_combined_with_io_or_processor_or_process() -> None:
    # F3: ctx already carries io/processor/process; combining silently ignored
    # the other kwargs before this fix. Now it's a hard error.
    resolver = StaticIOLayer(fetch_map={"https://x": "V"})
    ctx = ExecutionContext(resolver)
    with pytest.raises(ValueError, match="ctx.*io.*processor.*process"):
        await run("https://x!go", resolver, ctx=ctx)
    with pytest.raises(ValueError, match="ctx.*io.*processor.*process"):
        await run("https://x!go", ctx=ctx, processor="/other")
    with pytest.raises(ValueError, match="ctx.*io.*processor.*process"):
        await run("https://x!go", ctx=ctx, process=lambda s, i, sc: None)  # type: ignore[arg-type]


def test_a_non_url4_intent_over_a_base_group_is_unsupported_mode() -> None:
    # WHY: url4 2.0 — an https:// intent is not a code pointer, so it is refused at compile
    # before any source resolves (PRD row 3, E7). The 1.5.1 barrier-and-merge is gone.
    with pytest.raises(ParseError) as err:
        compile_expression("(https://a, https://b)!https://instr")
    assert err.value.code == "unsupported_mode"
    assert err.value.permanent is True


@pytest.mark.asyncio
async def test_relative_url_intent_lowers_to_a_code_pointer_node() -> None:
    # WHY: url4 2.0 — a /path intent is a code pointer, so the group is one CodePointerNode
    # over its sources (PRD row 9, CH9 flips).
    graph = compile_expression("(https://a)!/doc")
    assert isinstance(graph.sink, CodePointerNode)
    assert graph.sink.pointer.path == "/doc"


# --- coverage: nodes.py private helpers, reached through node/graph shapes ------


class BoomNode:
    """A hand-built node that always fails — for exercising guard/failure paths."""

    deps: dict = {}

    async def resolve(self, inputs, ctx) -> str:
        raise ResolutionError("boom")


@pytest.mark.asyncio
async def test_as_text_treats_source_failure_as_empty_string() -> None:
    # nodes.py _as_text(): a SourceFailure input renders as "", not str(failure)
    # — reached here via a RelUrlNode whose optional "intent" dep failed.
    node = RelUrlNode("/path", is_expr=True, deps={"intent": GuardNode(BoomNode(), optional=True)})
    io = StaticIOLayer(fetch_map={"/path?q=()!": "RESULT"})
    assert await run(node, io) == "RESULT"


@pytest.mark.asyncio
async def test_frame_skips_failed_optional_binding() -> None:
    # nodes.py _frame(): a SourceFailure reference-edge input contributes no
    # binding — the sibling's $name stays unbound and substitutes verbatim.
    # Also exercises GuardNode.resolve()'s optional catch (a failing inner
    # node becomes a SourceFailure value instead of propagating).
    io = StaticIOLayer()  # no fetch mapping for https://x: the fetch fails
    result = await run("(a=https://x;optional, use $a)!go", io)
    assert result == "go\n\nuse $a"


@pytest.mark.asyncio
async def test_frame_binds_positional_pos_role() -> None:
    # nodes.py _frame(): a "pos:N" role binds as $N, mirroring "bind:name" as
    # $name — reached when a later unnamed source references an earlier named
    # slot positionally.
    io = StaticIOLayer(fetch_map={"https://x": "V"})
    result = await run("(a=https://x, use $1)!go", io)
    assert result == "go\n\na: V\nuse V"  # `OME-534`: a packs too


@pytest.mark.asyncio
async def test_kind_of_classifies_url4_and_other_schemes() -> None:
    # nodes.py _kind_of(): "url4://" classifies as kind "url4"; any other
    # non-http(s) scheme ("s3://", …) classifies as "other".
    io = StaticIOLayer(fetch_map={"url4://host/path": "U4", "s3://bucket/key": "S3"})
    assert await run(WebFetchNode("url4://host/path"), io) == "U4"
    assert await run(WebFetchNode("s3://bucket/key"), io) == "S3"


@pytest.mark.asyncio
async def test_decode_struct_rejects_field_without_colon() -> None:
    # nodes.py _decode_struct(): a struct field missing a ":" separator raises
    # CollectionError(code="malformed_source").
    with pytest.raises(CollectionError) as exc_info:
        await run(StructNode("{foo}"), RecordingIOLayer())
    assert exc_info.value.code == "malformed_source"


@pytest.mark.asyncio
async def test_struct_bare_literals_keep_json_scalar_types() -> None:
    # nodes.py _decode_struct_value(): an inline {k: v} object is canonical JSON
    # (spec §5.3.11.3) — a bare number/float/bool/null literal keeps its JSON
    # type, while a bare word and a quoted value stay strings.
    result = await run(
        StructNode("{age: 30, ratio: 1.5, active: true, missing: null, tag: hi, name: 'Bob'}"),
        StaticIOLayer(),
    )
    assert json.loads(result) == {
        "age": 30,
        "ratio": 1.5,
        "active": True,
        "missing": None,
        "tag": "hi",
        "name": "Bob",
    }


@pytest.mark.asyncio
async def test_struct_reference_value_is_never_numerically_coerced() -> None:
    # nodes.py _decode_struct_value(): a $-referenced value is substituted as
    # text and never coerced — {id: $uid} with uid bound to "30" stays the
    # string "30", so a resolved id is not silently renumbered.
    # `OME-508`: the intent-less group is an internal carrier — built via
    # parse_group_root (the envelope entry that holds no intent) for this pin.
    result = await run(
        compile_expression(parse_group_root("(uid:0:'30', {id: $uid})")), StaticIOLayer()
    )
    assert json.loads(result) == {"id": "30"}


def test_refs_of_ast_extracts_relurl_path_reference() -> None:
    # compiler.py _refs_of_ast(): on the AST compile path a bare relative URI
    # /data/$topic contributes its embedded $topic reference, so the edge
    # _lower_relurl attaches actually gets wired.
    graph = compile_expression(parse_group_root("(topic=hello, /data/$topic)"))
    relurl = graph.sink.deps["src:1"]
    assert isinstance(relurl, RelUrlNode)
    assert "bind:topic" in relurl.deps


@pytest.mark.asyncio
async def test_relurl_bare_path_resolves_sibling_reference_text_path() -> None:
    # compiler.py _lower_relurl(): a bare relative URI embedding $name gets its
    # sibling-binding scope frame, so /data/$topic fetches /data/hello, not the
    # literal /data/$topic (which would raise "no fetch mapping").
    io = RecordingIOLayer(fetch_map={"/data/hello": "OK"})
    assert await run("(topic:0:'hello', r:0:/data/$topic)!'$r'", io) == "OK"
    assert "/data/hello" in io.fetches


@pytest.mark.asyncio
async def test_relurl_bare_path_resolves_sibling_reference_ast_path() -> None:
    # The AST twin of the text path — the same edge wired via _refs_of_ast.
    io = RecordingIOLayer(fetch_map={"/data/hello": "OK"})
    ast = parse_group_root("(topic=hello, /data/$topic)")
    # `OME-534`: the named source packs as a labeled line before the fetch value
    assert await run(compile_expression(ast), io) == "topic: hello\nOK"
    assert "/data/hello" in io.fetches


@pytest.mark.asyncio
async def test_guard_retries_transient_error_then_raises_last() -> None:
    # nodes.py GuardNode._attempt(): a transient Url4Error (permanent=False)
    # retries up to `retries` extra attempts, then raises the last one.
    class CountingBoom:
        deps: dict = {}

        def __init__(self) -> None:
            self.attempts = 0

        async def resolve(self, inputs, ctx) -> str:
            self.attempts += 1
            raise ResolutionError("transient boom")

    inner = CountingBoom()
    with pytest.raises(ResolutionError, match="transient boom"):
        await run(GuardNode(inner, retries=2), RecordingIOLayer())
    assert inner.attempts == 3


@pytest.mark.asyncio
async def test_guard_does_not_retry_permanent_error() -> None:
    # nodes.py GuardNode._attempt(): a permanent error raises immediately, on
    # the first attempt, even though retries is configured.
    class CountingBoom:
        deps: dict = {}

        def __init__(self) -> None:
            self.attempts = 0

        async def resolve(self, inputs, ctx) -> str:
            self.attempts += 1
            raise ResolutionError("permanent boom", permanent=True)

    inner = CountingBoom()
    with pytest.raises(ResolutionError, match="permanent boom"):
        await run(GuardNode(inner, retries=5), RecordingIOLayer())
    assert inner.attempts == 1


@pytest.mark.asyncio
async def test_guard_timeout_raises_resolution_error() -> None:
    # nodes.py GuardNode._once(): a ";t=" timeout wrapping a slow inner node
    # raises ResolutionError(code="timeout") once the timeout elapses.
    class SlowNode:
        deps: dict = {}

        async def resolve(self, inputs, ctx) -> str:
            await asyncio.sleep(10)
            return "never"

    with pytest.raises(ResolutionError) as exc_info:
        await run(GuardNode(SlowNode(), timeout=0.05), RecordingIOLayer())
    assert exc_info.value.code == "timeout"


@pytest.mark.asyncio
async def test_gather_expanded_json_stringifies_named_binding() -> None:
    # nodes.py _gather_expanded(): a named expanded source's elements are
    # JSON-stringified into g.named[name] (so a $name[i] field path can select
    # one element, spec §5.3.12.5).
    io = StaticIOLayer(fetch_map={"https://list": '["x", "y"]'})
    result = await run("(a=https://list;expand, use $a)!go", io)
    assert result == "go\n\nx\ny\nuse x\ny"


@pytest.mark.asyncio
async def test_quorum_not_met_raises_resolution_error() -> None:
    # nodes.py _check_quorum(): fewer resolved sources than the configured
    # quorum raises ResolutionError(code="quorum_not_met").
    io = StaticIOLayer(fetch_map={"https://a": "A"})
    with pytest.raises(ResolutionError) as exc_info:
        await run("(https://a, https://missing;optional)!'go';quorum=2", io)
    assert exc_info.value.code == "quorum_not_met"


@pytest.mark.asyncio
async def test_join_node_skips_source_failure_part() -> None:
    # nodes.py JoinNode.resolve(): a SourceFailure dependency contributes no
    # part to the join.
    graph = JoinNode(
        deps={
            "part:0": TextNode("A"),
            "part:1": GuardNode(BoomNode(), optional=True),
            "part:2": TextNode("B"),
        }
    )
    assert await run(graph, RecordingIOLayer()) == "A\nB"


@pytest.mark.asyncio
async def test_run_all_success_path_returns_row_results() -> None:
    # nodes.py MapNode._run_all(): the success path (no row errors,
    # ;iteration.on_error=fail) returns every row's result, in order.
    io = StaticIOLayer(fetch_map={"https://data": '["1", "2", "3"]'})
    result = await run("https://data*(r:0:$item)!'$r';iteration.on_error=fail", io)
    assert json.loads(result) == ["1", "2", "3"]


class NoHoldingsIOLayer:
    """An IOLayer that does not even implement fetch_holdings (unlike
    StaticIOLayer(), which always duck-types as SupportsHoldings and raises
    its OWN self_ref_on_non_url4/identity_ref_on_non_url4 error internally —
    never reaching HoldingsNode.resolve()'s own port-support check)."""

    async def fetch(self, target: str, *, relative: bool) -> str:
        raise ResolutionError(f"no fetch mapping for {target!r}")


@pytest.mark.asyncio
async def test_holdings_node_without_port_support_fails() -> None:
    # nodes.py HoldingsNode.resolve(): an adapter that lacks fetch_holdings
    # entirely fails the isinstance(ctx.io, SupportsHoldings) check here,
    # raising self_ref_on_non_url4 / identity_ref_on_non_url4 permanently.
    io = NoHoldingsIOLayer()
    with pytest.raises(ResolutionError) as exc_info:
        await run("(@)!'q'", io)
    assert exc_info.value.code == "self_ref_on_non_url4"
    assert exc_info.value.permanent is True

    with pytest.raises(ResolutionError) as exc_info:
        await run("(@emily)!'q'", io)
    assert exc_info.value.code == "identity_ref_on_non_url4"


# --- coverage: compiler.py private helpers, reached through compile_expression --


@pytest.mark.asyncio
async def test_lowering_registry_copy_is_independent() -> None:
    # compiler.py LoweringRegistry.copy(): mutating the copy's lowerers must
    # not affect the original registry's.
    original = default_registry()
    copy = original.copy()
    copy.register(Url, lambda node, edges, reg: TextNode("OVERRIDDEN"))
    io = RecordingIOLayer(fetch_map={"https://x": "V"})
    result = await run("https://x!go", io, registry=original)
    assert result == "go\n\nV"


def test_expand_annotation_wraps_in_expand_node() -> None:
    # compiler.py _lower_source(): the ";expand" annotation wraps the value in
    # an ExpandNode.
    graph = compile_expression("(https://list;expand)!go")
    assert isinstance(graph.sink.deps["src:0"], ExpandNode)


def test_guard_options_produce_guard_node_for_each_annotation() -> None:
    # compiler.py _guard_options(): ";optional" / ";t=" / ";retry=" each
    # produce a non-default guard, so the source lowers through a GuardNode.
    for source in ("https://x;optional", "https://x;t=5", "https://x;retry=2"):
        graph = compile_expression(f"({source})!go")
        assert isinstance(graph.sink.deps["src:0"], GuardNode)


def test_annotation_number_uncastable_raises_parse_error() -> None:
    # compiler.py _annotation_number(): an uncastable ";t=" / ";retry=" value
    # raises ParseError at compile time, not at execution.
    with pytest.raises(ParseError):
        compile_expression("(https://x;t=notanumber)!go")
    with pytest.raises(ParseError):
        compile_expression("(https://x;retry=abc)!go")


def test_accept_annotation_sets_node_accept() -> None:
    # compiler.py _push_label(): ";accept=" on a fetch-like source sets the
    # node's `accept` attribute.
    graph = compile_expression("(https://x;accept=application/json)!go")
    node = graph.sink.deps["src:0"]
    assert isinstance(node, WebFetchNode)
    assert node.accept == "application/json"


def test_scalar_weight_extracts_default_from_structured_weight() -> None:
    # compiler.py _scalar_weight(): a structured weight dict's fan-out label
    # scalar comes from its "_default" key.
    ast = grammar_parse("claude:(_default:0.4):/solve(ctx)!go")
    graph = compile_expression(ast)
    assert isinstance(graph.sink, RelUrlNode)
    assert graph.sink.weight == 0.4


def test_quorum_of_skips_non_quorum_params() -> None:
    # compiler.py _quorum_of(): a non-quorum param is skipped via `continue`,
    # falling through to the unbounded (None) default.
    graph = compile_expression("(https://x)!go;t=60")
    assert isinstance(graph.sink, ProcessNode)
    assert graph.sink.quorum is None


def test_quorum_of_all_is_explicitly_unbounded() -> None:
    # compiler.py _quorum_of(): "quorum=all" is the explicit spelling of "no
    # cap", same as omitting quorum entirely.
    graph = compile_expression("(https://x)!go;quorum=all")
    assert isinstance(graph.sink, ProcessNode)
    assert graph.sink.quorum is None


def test_quorum_of_uncastable_raises_parse_error() -> None:
    # compiler.py _quorum_of(): a non-integer, non-"all" quorum value raises
    # ParseError at compile time.
    with pytest.raises(ParseError, match="invalid quorum"):
        compile_expression("(https://x)!go;quorum=notanumber")


@pytest.mark.asyncio
async def test_fanout_call_unwraps_guarded_relative_expression() -> None:
    # compiler.py _fanout_call(): a guarded relative-expression call
    # (";optional" etc.) is still recognized as a fan-out element through the
    # GuardNode wrapper, so the group still compiles to fan-out+reduce.
    io = StaticIOLayer(
        fetch_map={},
        routes={"/a": lambda c, i: "A", "/b": lambda c, i: "B", "/claude": lambda c, i: i},
    )
    graph = compile_expression("(/a()!x;optional, /b()!y)!combine")
    assert isinstance(graph.sink, FanoutReduceNode)
    result = await run(graph, io, processor="/claude")
    assert "A" in result and "B" in result


def test_is_lazy_group_detects_bare_paren_group_without_tail() -> None:
    # compiler.py _is_lazy_group() + _reject_bare_group(): a bare "(...)"
    # segment with no "!tail" is rejected EAGERLY (`OME-508` — deferring it
    # would let a user's bare group slip past the permissive spawn boundary),
    # while the "(...)!tail" shape still defers to a LazyExprNode thunk.
    with pytest.raises(ParseError, match="intent"):
        compile_expression("(a, (nested, stuff))!go")
    graph = compile_expression("(a, (nested, stuff)!x)!go")
    lazies = [node for node in graph.walk() if isinstance(node, LazyExprNode)]
    assert [lazy.text for lazy in lazies] == ["(nested, stuff)!x"]


@pytest.mark.asyncio
async def test_group_binding_rhs_lowers_to_lazy_binding_thunk() -> None:
    # compiler.py _slot_from_text() / _make_binding_thunk(): a binding whose
    # RHS is a lazy group ("name=(...)!x") produces a BindingNode wrapping a
    # LazyExprNode thunk, compiled and executed only when the binding resolves.
    io = StaticIOLayer(fetch_map={"https://x": "X"})
    graph = compile_expression("(g=(https://x)!'label', use $g)!combine")
    binding = graph.sink.deps["src:0"]
    assert isinstance(binding, BindingNode)
    assert isinstance(binding.deps["value"], LazyExprNode)
    result = await run(graph, io)
    # `OME-534`: the deferred g binding contributes a labeled line too
    assert result == "combine\n\ng: label\n\nX\nuse label\n\nX"


@pytest.mark.asyncio
async def test_empty_collection_text_lowers_to_empty_text_node() -> None:
    # compiler.py _collection_dag(): an empty-string collection (e.g. "*(x)"
    # with no source before the "*") lowers to TextNode(""), so iteration sees
    # zero rows (spec §5.3.9).
    graph = compile_expression("*(r=x)!'$r'")
    map_node = graph.sink.deps["rows"]
    collection = map_node.deps["collection"]
    assert isinstance(collection, TextNode)
    assert collection.template == ""
    result = await run(graph, StaticIOLayer())
    assert json.loads(result) == []


def test_refs_of_ast_extracts_relexpr_context_and_struct_references() -> None:
    # compiler.py _refs_of_ast(): on the parse-tree (AST) compile path, a
    # RelExpr's context (a relative/remote call) and a StructObject's raw text
    # are both scanned for $ references — the text-compile path never reaches
    # this function (it uses find_references directly per segment).
    ast = grammar_parse("(data=https://d, /path($data)!go, {key: $data})!combine")
    graph = compile_expression(ast)
    call = graph.sink.deps["src:1"]
    struct = graph.sink.deps["src:2"]
    assert isinstance(call, RelUrlNode)
    assert "bind:data" in call.deps
    assert isinstance(struct, StructNode)
    assert "bind:data" in struct.deps


def test_refs_of_ast_extracts_standalone_var_ref() -> None:
    # compiler.py _refs_of_ast(): a standalone $name (a VarRef source, not
    # embedded in Text/context/struct) is itself scanned for its reference —
    # the AST-path twin of find_references picking up a bare "$name" segment.
    ast = grammar_parse("(data=https://d, $data)!combine")
    graph = compile_expression(ast)
    ref = graph.sink.deps["src:1"]
    assert isinstance(ref, TextNode)
    assert "bind:data" in ref.deps


def test_graph_walk_deduplicates_diamond_dependency() -> None:
    # compiler.py Graph.walk(): a node reached via multiple paths (a diamond
    # dependency) is yielded exactly once.
    graph = compile_expression("(a=https://x, use $a, also $a)!both: $a")
    binding = graph.sink.deps["src:0"]
    assert list(graph.walk()).count(binding) == 1


def test_graph_walk_traverses_guard_node_inner() -> None:
    # compiler.py Graph.walk(): a GuardNode's `.inner` is walked too (it's an
    # attribute, not a `deps` edge), so a guarded subtree's nodes are reachable.
    graph = compile_expression("(https://x;optional)!go")
    guard = graph.sink.deps["src:0"]
    assert isinstance(guard, GuardNode)
    assert guard.inner in list(graph.walk())


def test_validate_parses_reducer_instruction() -> None:
    # compiler.py Graph.validate(): a ReduceNode's reducer template is parsed
    # by validate() too, not just LazyExprNode fragments — a malformed reducer
    # fails fast at validate() instead of only surfacing at execution.
    good = compile_expression("(https://data*(x)!p)!/reduce(all)!'agg'")
    good.validate()  # does not raise
    bad = compile_expression("(https://data*(x)!p)!/reduce((bad")
    with pytest.raises(ParseError):
        bad.validate()


# --- processor resolution: declared routes replace the hardcoded default --------


def test_execution_context_resolves_processor_from_io_declared_routes() -> None:
    # WHY: the processor default is the io world's first declared route
    # (SupportsDefaultRoute) — never a hardcoded path name.
    io = StaticIOLayer(routes={"/r": lambda c, i: i, "/other": lambda c, i: i})
    assert ExecutionContext(io).processor == "/r"
    assert ExecutionContext(io, processor="/explicit").processor == "/explicit"
    assert ExecutionContext(StaticIOLayer()).processor is None


def test_execution_context_child_inherits_resolved_processor() -> None:
    io = StaticIOLayer(routes={"/r": lambda c, i: i})
    ctx = ExecutionContext(io)
    assert ctx.child(ctx.scope).processor == "/r"
