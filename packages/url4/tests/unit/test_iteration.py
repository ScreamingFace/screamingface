"""Golden behavior for collection iteration and reduce-over-iteration.

These pin the observable output of the iteration shapes. They were written
against the pre-DAG engine and carried through the executable-DAG refactor
unchanged (entry point aside), proving it behavior-preserving.

`OME-508`: the grammar's iteration takes a full expression after "*", whose
intent is mandatory — so the map-only and reducer-without-per-row-intent
SURFACE forms are gone. The DAG machinery (MapNode/JoinNode/ReduceNode) still
supports them via hand-built Iteration nodes, and these tests pin that via the
AST path where no legal text exists.
"""

from __future__ import annotations

import json

import pytest
from conftest import RecordingIOLayer

from url4.core.errors import CollectionError
from url4.core.nodes import Expression, Iteration, Text, Url
from url4.core.parser import build
from url4.dag import ExecutionContext, run
from url4.io.static import StaticIOLayer

ROWS = json.dumps([{"q": "2+2"}, {"q": "3+3"}])


def _resolver() -> StaticIOLayer:
    return StaticIOLayer(
        fetch_map={"https://data": ROWS},
        routes={
            "/solve": lambda context, intent: f"A={context}",
            "/reduce": lambda context, intent: f"REDUCED[intent={intent!r}]",
            # the processor tests pass explicitly for the per-row top-intent fan-out
            "/claude": lambda context, intent: f"CLAUDE[intent={intent!r}]",
        },
    )


@pytest.mark.asyncio
async def test_iteration_map_returns_json_array() -> None:
    # Spec §5.3.8 — the protocol-default collection serialization is a JSON array.
    node = Iteration(collection=Url("https://data"), body="/solve($item.q)!'go'")
    result = await run(node, _resolver())
    assert json.loads(result) == ["A=2+2", "A=3+3"]


@pytest.mark.asyncio
async def test_iteration_declared_ndjson_single_row_iterates() -> None:
    # nodes.py MapNode._items(): a fetch producer threads FetchResult.media_type
    # to parse_collection, so a source declared application/x-ndjson holding a
    # single row iterates (spec §5.3.7) instead of being sniffed and rejected as
    # a scalar / JSON object.
    io = StaticIOLayer(
        fetch_map={"https://rows": '{"q": "2+2"}'},
        routes={"/solve": lambda context, intent: f"A={context}"},
        media_types={"https://rows": "application/x-ndjson"},
    )
    node = Iteration(collection=Url("https://rows"), body="/solve($item.q)!'go'")
    result = await run(node, io)
    assert json.loads(result) == ["A=2+2"]


@pytest.mark.asyncio
async def test_reduce_scalar_rows_stay_strings_like_collect() -> None:
    # nodes.py ReduceNode: scalar-looking rows ("1", "2") stay JSON strings in
    # the reducer's row array — matching CollectNode (spec §5.3.8) — rather than
    # being coerced to numbers, so the two consumers of a MapNode agree.
    io = StaticIOLayer(
        routes={
            "/n": lambda context, intent: context,  # echo the row value
            "/reduce": lambda context, intent: intent,  # echo the row array verbatim
        },
    )
    node = Iteration(
        collection=Expression(sources=(Text("1"), Text("2"))),
        body="/n($item)!'go'",
        reducer="/reduce(all)!'agg'",
    )
    result = await run(node, io)
    assert json.loads(result) == ["1", "2"]


@pytest.mark.asyncio
async def test_broadcast_intent_resolves_item_inside_iteration() -> None:
    # nodes.py MergeNode: a broadcast intent nested in an iteration resolves
    # $item (via _substitute, like ProcessNode) — the literal "$item" must not
    # reach the model.
    node = Iteration(
        collection=Expression(sources=(Text("alpha"), Text("beta"))),
        body="('S')!*'row:$item'",
    )
    result = await run(node, StaticIOLayer())
    assert "$item" not in result
    assert "row:alpha" in result
    assert "row:beta" in result


@pytest.mark.asyncio
async def test_iteration_backend_intent_inside_parens() -> None:
    # The '!go' binds to the backend call, not the iteration — /solve ignores it.
    node = Iteration(collection=Url("https://data"), body="/solve($item.q)!go")
    result = await run(node, _resolver())
    assert json.loads(result) == ["A=2+2", "A=3+3"]


@pytest.mark.asyncio
async def test_iteration_row_with_unbalanced_parens_does_not_crash() -> None:
    # A row value carrying a stray ')' or '(' must not corrupt the per-row
    # re-parse: $item is bound into scope as data, never injected into the grammar.
    io = StaticIOLayer(fetch_map={"https://data": "task done)\nsmile :("})
    result = await run(Iteration(collection=Url("https://data"), body="answer $item"), io)
    assert json.loads(result) == ["answer task done)", "answer smile :("]


@pytest.mark.asyncio
async def test_iteration_top_level_intent_reduces_each_row() -> None:
    # A top-level intent AFTER the iteration reduces each 1-element row-group
    # through the explicit processor (/claude — the resolver declares /solve
    # first, so relying on the first-declared-route default would mis-dispatch).
    result = await run(
        "https://data*(/solve($item.q)!'go')!topintent", _resolver(), processor="/claude"
    )
    # The reducer input is repr'd by the fake /claude, so its real newlines show
    # as literal \n; the per-row results assemble into the JSON-array result.
    assert json.loads(result) == [
        r"CLAUDE[intent='[Response 1]\nA=2+2\n\n[Instruction]\ntopintent']",
        r"CLAUDE[intent='[Response 1]\nA=3+3\n\n[Instruction]\ntopintent']",
    ]


@pytest.mark.asyncio
async def test_reduce_over_iteration_via_backend_call() -> None:
    node = Iteration(
        collection=Url("https://data"), body="/solve($item.q)!'go'", reducer="/reduce(all)!'agg'"
    )
    result = await run(node, _resolver())
    assert result == 'REDUCED[intent=\'["A=2+2", "A=3+3"]\']'


@pytest.mark.asyncio
async def test_reduce_passes_row_data_verbatim_without_substitution() -> None:
    # The row array is data, not a template: a literal "$$" a row produces must
    # reach the reducer intact, not be collapsed to "$" by env-var substitution
    # running over the payload.
    seen: dict[str, str] = {}
    io = StaticIOLayer(
        fetch_map={"https://data": json.dumps([{"q": "x"}])},
        routes={
            "/solve": lambda context, intent: "cost: $$5",
            "/reduce": lambda context, intent: seen.setdefault("intent", intent) or "ok",
        },
    )
    node = Iteration(
        collection=Url("https://data"), body="/solve($item.q)!'go'", reducer="/reduce(all)!'agg'"
    )
    await run(node, io)
    assert seen["intent"] == '["cost: $$5"]'


@pytest.mark.asyncio
async def test_reduce_over_iteration_via_text_reducer() -> None:
    node = Iteration(
        collection=Url("https://data"), body="/solve($item.q)!'go'", reducer="combine these"
    )
    result = await run(node, _resolver())
    assert result == 'combine these\n\n["A=2+2", "A=3+3"]'


@pytest.mark.asyncio
async def test_reduce_over_iteration_with_per_row_intent() -> None:
    node = Iteration(
        collection=Url("https://data"), body="/solve($item.q)!go", reducer="/reduce(all)!'agg'"
    )
    result = await run(node, _resolver())
    assert result == 'REDUCED[intent=\'["A=2+2", "A=3+3"]\']'


@pytest.mark.asyncio
async def test_reduce_over_iteration_with_inner_directive() -> None:
    from url4.core.nodes import IterationDirectives

    node = Iteration(
        collection=Url("https://data"),
        body="/solve($item.q)!'go'",
        reducer="/reduce(all)!'agg'",
        directives=IterationDirectives(concurrency=1),
    )
    result = await run(node, _resolver())
    assert result == 'REDUCED[intent=\'["A=2+2", "A=3+3"]\']'


@pytest.mark.asyncio
async def test_iteration_with_concurrency_directive() -> None:
    from url4.core.nodes import IterationDirectives

    node = Iteration(
        collection=Url("https://data"),
        body="/solve($item.q)!'go'",
        directives=IterationDirectives(concurrency=1),
    )
    result = await run(node, _resolver())
    assert json.loads(result) == ["A=2+2", "A=3+3"]


@pytest.mark.asyncio
async def test_iteration_on_error_collect_captures_failures() -> None:
    # `collect` is the default policy (spec §5.3.6). The bad row fails only in
    # strict field mode (RDS, §5.3.4.1) — lenient mode substitutes "".
    rows = json.dumps([{"q": "ok"}, {"other": "bad"}])
    resolver = StaticIOLayer(
        fetch_map={"https://data": rows},
        routes={"/solve": lambda context, intent: f"OK:{context}"},
    )
    ctx = ExecutionContext(resolver, strict_fields=True)
    node = Iteration(collection=Url("https://data"), body="/solve($item.q)!go")
    result = await run(node, ctx=ctx)
    assert "OK:ok" in result
    assert ctx.collected_errors == 1
    assert '"error"' in result


@pytest.mark.asyncio
async def test_iteration_collect_preserves_code_and_retryable() -> None:
    # OME-924: a collected row must keep the exception's own diagnostics (code +
    # retryable), so a collect-boundary consumer can render the ORIGINAL upstream
    # failure instead of falling back to a default code. ``permanent`` travels as
    # ``retryable`` (its inverse) — permanent errors must not be retried.
    from url4.core.errors import ResolutionError

    def rate_limited(_context: str, _intent: str) -> str:
        raise ResolutionError("rate limit reached", code="rate_limited", permanent=False)

    rows = json.dumps([{"q": "x"}])
    resolver = StaticIOLayer(
        fetch_map={"https://data": rows},
        routes={"/solve": rate_limited},
    )
    ctx = ExecutionContext(resolver, strict_fields=True)
    node = Iteration(collection=Url("https://data"), body="/solve($q)!go")
    result = await run(node, ctx=ctx)
    (row,) = json.loads(result)
    assert row == {
        "error": {
            "kind": "ResolutionError",
            "code": "rate_limited",
            "message": "rate limit reached",
            "retryable": True,
        }
    }


@pytest.mark.asyncio
async def test_iteration_collect_leaves_retryable_unset_without_permanent() -> None:
    # A non-URL4 exception carries no ``code``/``permanent``: the payload keeps the
    # legacy kind/message pair so older readers stay byte-compatible.
    def broken(_context: str, _intent: str) -> str:
        raise RuntimeError("boom")

    rows = json.dumps([{"q": "x"}])
    resolver = StaticIOLayer(
        fetch_map={"https://data": rows},
        routes={"/solve": broken},
    )
    ctx = ExecutionContext(resolver, strict_fields=True)
    node = Iteration(collection=Url("https://data"), body="/solve($q)!go")
    result = await run(node, ctx=ctx)
    (row,) = json.loads(result)
    assert row == {"error": {"kind": "RuntimeError", "message": "boom"}}


@pytest.mark.asyncio
async def test_empty_collection_resolves_to_empty_array() -> None:
    # Spec §5.3.9 — zero elements is a SUCCESS with an empty result collection.
    resolver = StaticIOLayer(fetch_map={"https://data": "[]"})
    node = Iteration(collection=Url("https://data"), body="/solve($item.q)!'go'")
    assert await run(node, resolver) == "[]"


@pytest.mark.asyncio
async def test_scalar_collection_raises_malformed_source() -> None:
    # Spec §5.3.9 — a non-iterable collection reference is malformed_source.
    resolver = StaticIOLayer(fetch_map={"https://data": "one scalar value"})
    node = Iteration(collection=Url("https://data"), body="/solve($item.q)!'go'")
    with pytest.raises(CollectionError) as exc_info:
        await run(node, resolver)
    assert exc_info.value.code == "malformed_source"


@pytest.mark.asyncio
async def test_directive_after_top_level_intent_is_parsed_not_swallowed() -> None:
    # Pre-0.2 QUIRK, now fixed per spec §5.3.6: a trailing ';iteration.*' after
    # the intent is an execution annotation on the iteration, never intent text.
    result = await run(
        "https://data*(/solve($item.q)!'go')!topintent;iteration.concurrency=1",
        _resolver(),
        processor="/claude",
    )
    assert json.loads(result) == [
        r"CLAUDE[intent='[Response 1]\nA=2+2\n\n[Instruction]\ntopintent']",
        r"CLAUDE[intent='[Response 1]\nA=3+3\n\n[Instruction]\ntopintent']",
    ]


@pytest.mark.asyncio
async def test_map_rows_share_one_compile_per_unique_body(monkeypatch) -> None:
    # Every row of a MapNode spawns the SAME body text (body/intent are node
    # attributes, constant across rows), so the per-row lowering must compile
    # it once and reuse the graph for every row — not re-parse per row. A spy on
    # compile_expression should see the outer expression once and the shared
    # row body exactly once, regardless of row count.
    import url4.dag.executor as executor

    calls: list[str] = []
    real = executor.compile_expression

    def spy(text: str, *, registry=None, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(text)
        return real(text, registry=registry, **kwargs)

    monkeypatch.setattr(executor, "compile_expression", spy)

    rows = json.dumps([{"q": f"r{i}"} for i in range(5)])
    io = StaticIOLayer(
        fetch_map={"https://data": rows},
        routes={"/solve": lambda context, intent: f"A={context}"},
    )
    node = Iteration(collection=Url("https://data"), body="/solve($item.q)!'go'")
    result = await run(node, io)

    assert json.loads(result) == [f"A=r{i}" for i in range(5)]  # correctness preserved
    # One compile for the outer node + exactly one for the shared row body
    # (5 rows, but the body text is identical, so it lowers once).
    assert len(calls) == 2
    assert calls[0] is node
    assert calls[1] == "(/solve($item.q)!'go')"


@pytest.mark.asyncio
async def test_distinct_spawned_bodies_each_compile_once(monkeypatch) -> None:
    # One run, TWO distinct spawned texts: each row's body (a group) and the
    # lazy fragment inside it. The compile cache is keyed by text, so each
    # distinct text lowers exactly once even though 3 rows each spawn both —
    # proving the memo is text-keyed, not "compile once per run". Without the
    # cache this would be 1 (outer) + 3 (row body) + 3 (lazy fragment) = 7 calls.
    import url4.dag.executor as executor

    calls: list[str] = []
    real = executor.compile_expression

    def spy(text: str, *, registry=None, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(text)
        return real(text, registry=registry, **kwargs)

    monkeypatch.setattr(executor, "compile_expression", spy)

    rows = json.dumps([{"k": i} for i in range(3)])
    io = StaticIOLayer(
        fetch_map={"https://data": rows, "https://inner": "PAYLOAD"},
    )
    node = Iteration(collection=Url("https://data"), body="(https://inner)!p")
    result = await run(node, io)

    # Correctness: each row resolves the lazy fragment (fetch + intent "p").
    assert json.loads(result) == ["p\n\nPAYLOAD"] * 3
    # Outer once + the two distinct spawn texts once each, despite 3 rows.
    assert len(calls) == 3
    assert calls[0] is node
    assert sorted(calls[1:]) == ["((https://inner)!p)", "(https://inner)!p"]


@pytest.mark.asyncio
async def test_acyclic_check_runs_once_per_unique_fragment_not_per_row(monkeypatch) -> None:
    # Acyclicity is a property of the *graph*, so a compiled fragment is
    # validated once (on first compile in the spawn closure) and the N rows that
    # re-execute it skip the redundant O(V+E) DFS in execute. A 5-row map should
    # call check_acyclic exactly twice: once for the outer graph (top-level
    # execute, the default non-prevalidated path) + once for the shared row-body
    # fragment — not 1 + 5 = 6. (The hand-built cycle guard still fires via that
    # default path — pinned by test_cycle_detected_before_any_resolve.)
    import url4.dag.executor as executor

    calls: list = []
    real = executor.check_acyclic

    def spy(root):  # type: ignore[no-untyped-def]
        calls.append(root)
        return real(root)

    monkeypatch.setattr(executor, "check_acyclic", spy)

    rows = json.dumps([{"q": f"r{i}"} for i in range(5)])
    io = StaticIOLayer(
        fetch_map={"https://data": rows},
        routes={"/solve": lambda context, intent: f"A={context}"},
    )
    node = Iteration(collection=Url("https://data"), body="/solve($item.q)!'go'")
    result = await run(node, io)

    assert json.loads(result) == [f"A=r{i}" for i in range(5)]  # correctness preserved
    assert len(calls) == 2  # 1 outer graph + 1 shared row body; was 6 pre-fix


@pytest.mark.asyncio
async def test_iteration_ast_path_matches_text_path() -> None:
    # F3: the eager parse-tree path (compile_expression → _lower_iteration) and
    # the lazy text path (_compile_text) must produce identical observable
    # execution for every src*(body) surface form. test_bare_relexpr_text_path
    # _matches_ast_path pins parity only for a bare relative expression; this
    # extends it to the iteration shapes the AST path lowers via _lower_iteration
    # (otherwise uncovered). Assert on both the resolved string AND the fetch
    # sequence so a divergence in graph shape that still resolves the same is
    # still caught (the compiler's own F2 note warns result parity is not
    # evidence of identical graphs — so check dispatch too).
    routes = {
        "/solve": lambda context, intent: f"A={context}",
        "/reduce": lambda context, intent: f"REDUCED[intent={intent!r}]",
        "/claude": lambda context, intent: f"CLAUDE[intent={intent!r}]",
    }
    # `OME-508`: only intent-bearing iteration texts remain grammar-legal, so
    # parity is asserted over those; the intent-less shapes are AST-only now
    # (pinned by the AST-path tests above).
    cases = [
        "https://data*(/solve($item.q)!'go')!topintent",
        "(https://data*(/solve($item.q)!'go')!go)!/reduce(all)!'agg'",
        "https://data*(/solve($item.q)!'go')!topintent;iteration.concurrency=1",
    ]
    for expr in cases:
        text_io = RecordingIOLayer(fetch_map={"https://data": ROWS}, routes=routes)
        ast_io = RecordingIOLayer(fetch_map={"https://data": ROWS}, routes=routes)
        text_result = await run(expr, text_io)  # text path (string)
        ast_result = await run(build(expr), ast_io)  # AST path (Iteration node)
        assert text_result == ast_result, f"result diverged for {expr!r}"
        assert text_io.fetches == ast_io.fetches, f"fetches diverged for {expr!r}"


@pytest.mark.asyncio
async def test_iteration_ast_path_matches_text_path_for_map_only() -> None:
    # F3: a map-only iteration (no reduce tail) exercises the _lower_iteration
    # branch that emits a JoinNode wrapping the MapNode — distinct from the
    # reduce-over-iteration shape (ReduceNode). `OME-508` removed the map-only
    # TEXT form, so the JoinNode branch is pinned via the AST path alone.
    rows = json.dumps([{"q": "1"}, {"q": "2"}, {"q": "3"}])
    io = RecordingIOLayer(
        fetch_map={"https://data": rows},
        routes={"/solve": lambda context, intent: f"A={context}"},
    )
    node = Iteration(collection=Url("https://data"), body="/solve($item.q)!'go'")
    assert json.loads(await run(node, io)) == ["A=1", "A=2", "A=3"]


# --- inline parenthesized collections (spec §5.3.11) --------------------------


@pytest.mark.asyncio
async def test_inline_collection_single_scalar_element_iterates() -> None:
    # Spec §5.3.11 — a ONE-element inline collection is a genuine 1-element
    # collection, not a scalar. It must NOT be joined-to-text and re-sniffed by
    # the §5.3.7 body parser (which would reject a lone line as a non-iterable
    # scalar, §5.3.9). Regression: this used to 422 with "resolved to a scalar
    # value, not an iterable collection".
    result = await run("('only-one')*()!'Item is $item'", StaticIOLayer())
    assert json.loads(result) == ["Item is only-one"]


@pytest.mark.asyncio
async def test_inline_collection_single_struct_element_field_access() -> None:
    # Spec §5.3.11.3 — a lone ``{}`` element keeps its JSON shape, so a per-row
    # ``$item.field`` path resolves. Joined-to-text this used to be rejected as a
    # "JSON object is malformed" collection (§5.3.7).
    result = await run("({outer:{inner:'val'}})*()!'$item.outer.inner'", StaticIOLayer())
    assert json.loads(result) == ["val"]


@pytest.mark.asyncio
async def test_inline_collection_multi_element_still_iterates() -> None:
    # Regression guard: the 2+-element inline collection that already worked
    # (accidentally, via multi-line-plaintext sniffing) still yields one row per
    # authored element after the fix routes it through InlineCollectionNode.
    result = await run("('a','b')*()!'Item is $item'", StaticIOLayer())
    assert json.loads(result) == ["Item is a", "Item is b"]


@pytest.mark.asyncio
async def test_inline_collection_empty_is_zero_rows() -> None:
    # Spec §5.3.11.4 / §5.3.9 — an empty inline collection iterates to zero rows
    # (success), not an error. The fix must not disturb this edge.
    result = await run("()*()!'Item is $item'", StaticIOLayer())
    assert json.loads(result) == []


@pytest.mark.asyncio
async def test_inline_collection_text_path_matches_ast_path() -> None:
    # Both compile paths must lower an inline collection identically: the text
    # path (_collection_dag) and the AST path (_lower_collection) each build an
    # InlineCollectionNode from the bare group's authored elements.
    for expr in (
        "('only-one')*()!'Item is $item'",
        "({outer:{inner:'val'}})*()!'$item.outer.inner'",
        "('a','b')*()!'Item is $item'",
    ):
        assert await run(expr, StaticIOLayer()) == await run(build(expr), StaticIOLayer())
