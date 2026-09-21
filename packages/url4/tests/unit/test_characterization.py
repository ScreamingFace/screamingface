"""Characterization tests for behaviors the original suite left unpinned.

Written against the pre-DAG engine (and verified green there) before the
executable-DAG rewrite, these pin the subtle semantics it must reproduce.
"""

from __future__ import annotations

import json
import random

import pytest
from conftest import RecordingIOLayer

from url4 import StaticIOLayer
from url4.core.grammar import parse as grammar_parse
from url4.core.parser import build
from url4.core.render import render
from url4.core.subrequest import decode_subrequest
from url4.dag import compile_expression, run


@pytest.mark.asyncio
async def test_pure_binding_group_falls_back_to_binding_values() -> None:
    # `OME-534`: a name-only source contributes to the packed context as a
    # labeled line AND interpolates into the intent — the intent resolves
    # without a processor, over the interpolated binding values.
    resolver = StaticIOLayer(fetch_map={"https://x": "VALUE"})
    result = await run("(a=https://x)!'$a'", resolver)
    assert result == "VALUE\n\na: VALUE"


@pytest.mark.asyncio
async def test_non_binding_source_sees_later_binding() -> None:
    # Bindings resolve in a first phase regardless of position, so a
    # non-binding source may reference a binding declared AFTER it.
    resolver = StaticIOLayer(fetch_map={"https://x": "X"})
    result = await run("(use $a, a=https://x)!go", resolver)
    assert result == "go\n\nuse X\na: X"  # `OME-534`: the named source packs too


@pytest.mark.asyncio
async def test_relative_expression_encodes_context_and_intent_in_query() -> None:
    # A relative expression /solve()!intent is fetched as /solve?q=()!intent —
    # a localhost fetch, with $$ collapsing to a literal $ once (no double pass).
    resolver = RecordingIOLayer()
    await run("/solve()!it costs $$9", resolver)
    # Spaces wire-escape as %20 (spec §7.3); $ stays raw, $$ collapsed once.
    assert resolver.fetches == ["/solve?q=()!it%20costs%20$9"]


@pytest.mark.asyncio
async def test_broadcast_intent_resolved_exactly_once() -> None:
    # The !* intent (here a URL) is resolved a single time and shared across
    # every per-source application — not re-fetched per source.
    resolver = RecordingIOLayer(
        fetch_map={"https://a": "A", "https://b": "B", "https://instr": "TAG"}
    )
    result = await run("(https://a, https://b)!*https://instr", resolver)
    assert [row["result"] for row in json.loads(result)] == ["TAG\n\nA", "TAG\n\nB"]
    assert resolver.fetches.count("https://instr") == 1


@pytest.mark.asyncio
async def test_single_relative_expression_group_takes_fanout_path() -> None:
    # A group whose only source is a relative expression still goes through the
    # fan-out reducer (the reducer fetch runs even for one response).
    resolver = RecordingIOLayer()
    await run("(/solve(x)!go)!merge", resolver, processor="/claude")
    paths = [target.split("?q=")[0] for target in resolver.fetches]
    assert paths == ["/solve", "/claude"]
    # Decode the wire-escaped reducer sub-request back to its readable input.
    _, reducer_input = decode_subrequest(resolver.fetches[-1].split("?q=", 1)[1])
    assert "[Response 1]" in reducer_input
    assert "[Instruction]\nmerge" in reducer_input


@pytest.mark.asyncio
async def test_bare_relative_expression_is_a_single_call_intent_folded() -> None:
    # A BARE relative expression with a top-level intent is one dispatch with the
    # intent folded into that call — NOT a fan-out + reducer. This mirrors the
    # reference engine (a lone backend call is not a list, so it never reduces)
    # and the eager AST path, which parses the whole thing as one RelExpr.
    resolver = RecordingIOLayer()
    await run("/claude(https://n)!'sum'", resolver)
    # `OME-535`: the context URL is a SOURCE — fetched first, its content
    # dispatched — still one folded call, never a fan-out reducer.
    assert resolver.fetches == ["https://n", "/claude?q=(<https://n>)!sum"]


@pytest.mark.asyncio
async def test_bare_relexpr_text_path_matches_ast_path() -> None:
    # The lazy text path and the eager AST path must not diverge: both compile a
    # bare relative expression to the same single folded call.
    expr = "/claude(https://n)!'sum'"
    text_io, ast_io = RecordingIOLayer(), RecordingIOLayer()
    await run(expr, text_io)  # text path (string target)
    await run(grammar_parse(expr), ast_io)  # AST path (parsed node)
    # `OME-535`: both paths fetch the context source, then dispatch its content
    assert text_io.fetches == ast_io.fetches == ["https://n", "/claude?q=(<https://n>)!sum"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expr",
    [
        # a nested group beside a plain source — the shape the compiler's own
        # parity note names: text path defers it to a LazyExprNode thunk, AST
        # path expands it eagerly
        "(https://a, (/solve(https://n)!'go')!merge)!'top'",
        # a nested group beside an expression source
        "(/proc('x')!'p1', (/solve(https://n)!'go')!merge)!'top'",
        # nesting two deep
        "(https://a, (/proc('x')!'p1', (/solve(https://n)!'go')!merge)!'mid')!'top'",
        # broadcast and outer params ride the same envelope
        "(https://a, (/solve(https://n)!'go')!merge)!*'top'",
        "(https://a, (/solve(https://n)!'go')!merge)!'top';quorum=1",
    ],
)
async def test_nested_group_text_path_matches_ast_path(expr: str) -> None:
    # Result parity for the NESTED-GROUP shapes, extending the bare-relexpr
    # test above as the parity note in dag/_lowering.py prescribes. The two
    # paths build legitimately different graphs (a lazy thunk vs eager
    # expansion), so parity is asserted on the RESOLVED STRING — never on
    # graph structure — which is the observable contract a caller holds.
    def io() -> StaticIOLayer:
        return StaticIOLayer(
            fetch_map={"https://a": "A", "https://n": "N"},
            routes={
                "/solve": lambda context, intent: f"SOLVE[{context}]/{intent}",
                "/proc": lambda context, intent: f"PROC[{context}]/{intent}",
            },
        )

    text_result = await run(expr, io())  # text path (string)
    ast_result = await run(grammar_parse(expr), io())  # AST path (parsed node)
    assert text_result == ast_result


# --- generated lowering-path parity corpus (second review, F3) ----------------------


# The two hand-picked parity tests above cover only the shapes their authors
# thought of. The lowering's wiring decisions live in twin functions
# (``_slot_from_text``/``_slot_from_ast``, ``_compile_group_text``/
# ``_lower_expression``, ``_map_from_text``/``_lower_iteration``), so every
# path-specific bug is a twin-fix hazard — the iteration-body reference bug
# (CHANGELOG 1.3.0) had to be fixed once per path. This corpus composes
# grammar-shaped expressions from a seeded part list (sources × name/weight
# descriptors × nesting × iteration × broadcast × references) and asserts
# RESULT parity for each: the lazy text path (``compile_expression(str)``) and
# the eager AST path (``compile_expression(build(str))``) must resolve to the
# same string. Per the AIDEV-NOTE on ``_compile_text``, parity is asserted on
# the resolved string only — never on graph structure (the two paths
# legitimately build different graphs). The seed is pinned, so any failure
# reproduces exactly.
_PARITY_SEED = 0x5EED_2026  # pinned — a new seed is a new corpus and needs review
_PARITY_SAMPLES = 150
_PARITY_ROWS = json.dumps([{"q": "r0", "answer": "a0"}, {"q": "r1", "answer": "a1"}])

_INTENTS = ("'top'", "'go'", "go", "'sum'", "'mid'")
_ROW_INTENTS = ("'row'", "row", "'R $item'")


def _parity_io() -> StaticIOLayer:
    """The deterministic world every corpus shape resolves against."""
    return StaticIOLayer(
        fetch_map={"https://a": "A", "https://n": "N", "https://rows": _PARITY_ROWS},
        routes={
            "/solve": lambda context, intent: f"SOLVE[{context}]/{intent}",
            "/proc": lambda context, intent: f"PROC[{context}]/{intent}",
            "/reduce": lambda context, intent: f"REDUCE[{context}]/{intent}",
        },
    )


def _relexpr(rng: random.Random) -> str:
    """A relative-expression source — with its own mandatory ``!intent``."""
    call = rng.choice(("/solve", "/proc"))
    context = rng.choice(("'ctx'", "https://n", "'x'"))
    return f"{call}({context})!{rng.choice(_INTENTS)}"


def _source(rng: random.Random, depth: int) -> str:
    """One group member: a URI, a binding, a name:weight descriptor, a
    relative expression, or (nested) a plain group."""
    if depth > 0 and rng.random() < 0.3:
        return _group(rng, depth - 1)
    return rng.choice(("https://a", "https://n", "a=https://a", "w:0.5:https://a", _relexpr(rng)))


def _group(rng: random.Random, depth: int) -> str:
    """A plain ``(src, …)!intent`` group — safe at any nesting depth.

    Envelope extras (``!*`` broadcast, ``;quorum``) are composed only at the
    top level (see ``_parity_expression``): this generator composes proven
    grammar shapes, it does not explore the error surface.
    """
    members = ", ".join(_source(rng, depth) for _ in range(rng.randint(1, 3)))
    return f"({members})!{rng.choice(_INTENTS)}"


def _iteration(rng: random.Random, *, inline_collection: bool) -> str:
    """The §5.3 iteration production ``collection*(body)!per-row-intent``.

    A call body (``/solve(…)``) must carry its own ``!intent`` — the per-row
    intent wraps *outside* the body; an empty body leaves ``$item`` to the
    per-row intent; a binding body packs it into the row context. The inline
    paren collection (``('r0', 'r1')``) is composed only where it is a proven
    shape — at the top level; nested under a wrapper the collection's parens
    sit below depth 0 and the ``*(`` scan no longer sees the iteration
    (``inline_collection=False`` under the reduce/named-source wrappers).
    """
    json_rows = not (inline_collection and rng.random() < 0.4)
    collection = "https://rows" if json_rows else "('r0', 'r1')"
    item = "$item.q" if json_rows else "$item"
    body = rng.choice(("", f"/solve({item})!'go'", f"t={item}"))
    directives = rng.choice(
        (
            "",
            ";iteration.concurrency=1",
            ";iteration.on_error=collect",
            ";iteration.concurrency=2;iteration.on_error=collect",
        )
    )
    return f"{collection}*({body})!{rng.choice(_ROW_INTENTS)}{directives}"


def _parity_expression(rng: random.Random) -> str:
    """Compose one corpus shape from the proven part families."""
    roll = rng.random()
    if roll < 0.08:  # broadcast: the intent resolves once, is shared per source
        members = ", ".join(rng.sample(("https://a", "https://n"), 2))
        expr = f"({members})!*{rng.choice(_INTENTS)}"
    elif roll < 0.14:  # quorum rides the trailing ; chain
        expr = f"{_group(rng, 2)};quorum=1"
    elif roll < 0.52:
        expr = _group(rng, 2)
    elif roll < 0.74:
        expr = _iteration(rng, inline_collection=True)
    elif roll < 0.86:  # cross-row reduce over an iteration (§5.3)
        expr = f"({_iteration(rng, inline_collection=False)})!/reduce()!'agg'"
    else:  # an iteration as a name:weight source of an outer expression (§5.3.1)
        expr = f"(scores:0.0:{_iteration(rng, inline_collection=False)})!'Agg $scores'"
    return expr


@pytest.mark.asyncio
async def test_generated_parity_corpus_text_path_matches_ast_path() -> None:
    # Every raw shape is canonicalized through build → render first, so both
    # paths start from identical surface text (and the canonicalization itself
    # is checked: the canonical text must build the same AST as the raw text).
    # `processor="/reduce"` keeps reduce-shaped compositions (a lone relative-
    # expression group) resolvable; it applies to both sides alike.
    rng = random.Random(_PARITY_SEED)
    for i in range(_PARITY_SAMPLES):
        raw = _parity_expression(rng)
        canonical = render(build(raw))
        assert build(canonical) == build(raw), (i, raw, canonical)
        text_graph = compile_expression(canonical)
        ast_graph = compile_expression(build(canonical))
        text_result = await run(text_graph, _parity_io(), processor="/reduce")
        ast_result = await run(ast_graph, _parity_io(), processor="/reduce")
        assert text_result == ast_result, (i, raw, canonical, text_result, ast_result)


@pytest.mark.asyncio
async def test_intent_quotes_are_delimiters_everywhere() -> None:
    # Quotes are delimiters (spec §5.1): stripped uniformly — on a top-level
    # intent AND on a relative expression's own inside-the-parens intent. The
    # pre-0.2 Url4Text quote-keeping asymmetry is gone.
    seen: dict[str, str] = {}

    def route(context: str, intent: str) -> str:
        seen[context] = intent
        return "R"

    io = StaticIOLayer(routes={"/claude": route})
    await run("/claude(top)!'sum'", io)  # top-level intent
    await run("(/claude(nested)!'sum')!'outer'", io)  # the call's own intent
    assert seen["top"] == "sum"
    assert seen["nested"] == "sum"


@pytest.mark.asyncio
async def test_parenthesized_single_relexpr_still_reduces() -> None:
    # Parenthesising the lone source makes it a LIST; a top-level intent over a
    # list is a genuine fan-out + reduce (two calls), even for one member —
    # matching the reference engine's ``_is_fanout and raw_intent`` gate.
    resolver = RecordingIOLayer()
    await run("(/claude(https://n)!'go')!'sum'", resolver, processor="/claude")
    paths = [target.split("?q=")[0] for target in resolver.fetches]
    # `OME-535`: the context fetch precedes the call and the reducer dispatch
    assert paths == ["https://n", "/claude", "/claude"]
