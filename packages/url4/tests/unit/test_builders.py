"""Builder facade tests — Python constructors lowering to the url4 AST.

INVARIANT: every node a builder returns renders via ``render(node)`` (whose
``check=True`` certifies the round-trip) — builders can never construct a tree
the grammar cannot carry. Coercions mirror the grammar exactly: a string
source goes through the full descriptor grammar (``parse``), a string *value*
through §5.2 value detection (``parse_value``), so Python-side construction
and text-side parsing can never disagree about meaning.
"""

from __future__ import annotations

import pytest

from url4 import build
from url4.core.builders import (
    broadcast,
    expand,
    expr,
    identity,
    iterate,
    reduce,
    ref,
    self_,
    src,
    struct,
    text,
)
from url4.core.nodes import (
    Binding,
    Expression,
    IdentityRef,
    Iteration,
    IterationDirectives,
    NamedJob,
    RelExpr,
    RelUrl,
    SelfRef,
    Source,
    StructObject,
    Text,
    Url,
    VarRef,
)
from url4.core.render import render

# --- leaf constructors --------------------------------------------------------------


def test_leaf_constructors():
    assert text("formal") == Text("formal")
    assert ref("article") == VarRef("article")
    assert ref(1) == VarRef("1")
    assert ref("item", "tags", 0) == VarRef("item", ("tags", 0))
    assert self_() == SelfRef()
    assert identity("emily") == IdentityRef("emily")
    assert identity("andrew", "published") == IdentityRef("andrew", "published")


def test_struct_builder():
    node = struct({"name": "Emily", "style": "optimistic"})
    assert node == StructObject("{name: 'Emily', style: 'optimistic'}")
    # numbers stay bare tokens; nested mappings nest
    nested = struct({"a": 1, "b": {"c": "deep"}, "w": 0.5})
    assert nested == StructObject("{a: 1, b: {c: 'deep'}, w: 0.5}")
    # struct output is grammar-carriable
    assert render(nested) == "{a: 1, b: {c: 'deep'}, w: 0.5}"


@pytest.mark.parametrize(
    "mapping",
    # "café" is str.isalnum()-true but outside the grammar's [A-Za-z0-9_] class
    [{"bad key": 1}, {"café": 1}, {"k": None}, {"k": [1, 2]}, {"k": True}],
)
def test_struct_rejects_uncarriable(mapping):
    with pytest.raises((ValueError, TypeError)):
        struct(mapping)


# --- src(): coercion and the two-axis descriptor ---------------------------------------


def test_src_value_coercion_follows_value_detection():
    assert src("https://news.com/story") == Url("https://news.com/story")
    assert src("/api/patient/42") == RelUrl("/api/patient/42")
    # a bare word is value-detected as Text — same node text() builds
    assert src("formal") == text("formal")
    # $-initial strings become variable references
    assert src("$item.tags[0]") == VarRef("item", ("tags", 0))
    # '@' forms
    assert src("@") == SelfRef()
    assert src("@emily/notes") == IdentityRef("emily", "notes")
    # a mapping becomes a struct object
    assert src({"k": "v"}) == StructObject("{k: 'v'}")
    # AIDEV-NOTE: value position does NOT run the descriptor grammar —
    # "name=https://x" is one bare value (Text), not a binding.
    assert isinstance(src("article=https://x"), Text)


def test_src_normalization_mirrors_grammar():
    # nothing but a value → the bare node
    assert src("https://x") == Url("https://x")
    # name only → Binding, exactly what the parser yields for name=value
    assert src("https://x", name="a") == Binding("a", Url("https://x"), "=")
    # any descriptor content → Source
    node = src("https://x", name="a", weight=0.9)
    assert node == Source(value=Url("https://x"), name="a", weight=0.9)


def test_src_full_descriptor_golden():
    node = src(
        "https://hospital.org/api/patient/42",
        name="medical",
        weight=0.5,
        budgets={"tokens": 8000, "influence": 0.6},
        mode="agent",
        t=120,
        retry=2,
        required=True,
    )
    assert render(expr(node, intent=text("go"))) == (
        "(medical:0.5:tokens=8000:influence=0.6:https://hospital.org/api/patient/42"
        ";mode=agent;t=120;retry=2;required)!'go'"
    )


def test_src_spec_examples():
    # spec §4.5: unnamed, weighted, with execution annotations (builders emit
    # typed annotations before flags; order is semantically irrelevant, §4.2)
    node = src(text("Supplementary AMA guidelines"), weight=0.2, required=False, retry=3)
    assert render(expr(node, intent=text("go"))) == (
        "(0.2:'Supplementary AMA guidelines';retry=3;optional)!'go'"
    )
    # structured weight requires a name (token-initial '(' is value-shaped)
    weighted = src(
        "https://x", name="claude", weight={"science": 0.85, "math": 0.64, "_default": 0.4}
    )
    assert render(expr(weighted, intent=text("go"))) == (
        "(claude:(science:0.85,math:0.64,_default:0.4):https://x)!'go'"
    )
    # scoped budget (§24.4)
    budgeted = src(
        "https://x",
        name="claude",
        weight=0.6,
        budgets={"tokens": {"_each": 4000, "_total": 5000000}},
    )
    assert render(expr(budgeted, intent=text("go"))) == (
        "(claude:0.6:tokens=(_each:4000,_total:5000000):https://x)!'go'"
    )


def test_src_accepts_expression_values():
    inner = expr(src("https://allrecipes.com"), intent="Find recipes")
    node = src(inner, name="chef", weight=0.4, mode="agent", t=120)
    assert render(expr(node, intent=text("go"))) == (
        "(chef:0.4:(https://allrecipes.com)!'Find recipes';mode=agent;t=120)!'go'"
    )


def test_src_required_is_tristate():
    # §10.1 — True marks ;required, False marks ;optional, None marks nothing
    assert (
        render(expr(src("https://x", required=True), intent=text("go")))
        == "(https://x;required)!'go'"
    )
    assert (
        render(expr(src("https://x", required=False), intent=text("go")))
        == "(https://x;optional)!'go'"
    )
    assert render(expr(src("https://x"), intent=text("go"))) == "(https://x)!'go'"


def test_src_validation():
    with pytest.raises(ValueError):
        src("https://x", name="src")  # reserved
    with pytest.raises(ValueError):
        src("https://x", name="9bad")
    with pytest.raises(ValueError):
        src("https://x", weight=-0.1)
    with pytest.raises(ValueError):
        src("https://x", budgets={"weight": 1})  # reserved budget key
    with pytest.raises(TypeError):
        src(src("https://x", name="a", weight=1.0))  # Source is not a value
    with pytest.raises(TypeError):
        src(123)  # type: ignore[arg-type]


# --- expr() ----------------------------------------------------------------------------


def test_expr_string_sources_use_full_descriptor_grammar():
    e = expr(
        "article:0.9:https://news.com/story",
        "style:0.1:'formal'",
        intent="Summarize $article in $style",
    )
    assert render(e) == (
        "(article:0.9:https://news.com/story, style:0.1:'formal')!'Summarize $article in $style'"
    )


def test_expr_intent_forms():
    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert expr("https://x", intent="Summarize").intent == NamedJob(value="Summarize")
    assert expr("https://x", intent="https://code.com/s.py").intent == Url("https://code.com/s.py")
    assert expr("https://x", intent="/score.py").intent is not None
    assert render(expr("https://x", intent=text("go"))) == "(https://x)!'go'"
    with pytest.raises(TypeError):
        expr("https://x", intent=SelfRef())  # type: ignore[arg-type]


def test_expr_params():
    e = expr("https://x", intent=text("go"), params={"quorum": 2, "t": 60})
    assert render(e) == "(https://x)!'go';quorum=2;t=60"
    flags = expr("https://x", intent=text("go"), params=[("meta", "full"), ("stream", None)])
    assert render(flags) == "(https://x)!'go';meta=full;stream"


def test_expr_empty_and_broadcast():
    assert render(expr(intent="Generate a haiku")) == "()!'Generate a haiku'"
    e = broadcast("https://a.com", "https://b.com", intent="Extract key claims")
    assert e.broadcast is True
    assert render(e) == "(https://a.com, https://b.com)!*'Extract key claims'"
    with pytest.raises(ValueError):
        expr("https://x", broadcast=True)  # broadcast needs an intent


def test_reduce_is_query_sugar():
    e = reduce(
        "/claude(https://u.com)!'Go'", "/llama(https://u.com)!'Go'", intent="Merge $1 and $2"
    )
    assert render(e) == (
        "(/claude(https://u.com)!'Go', /llama(https://u.com)!'Go')!'Merge $1 and $2'"
    )
    assert isinstance(e.sources[0], RelExpr)
    with pytest.raises(ValueError):
        reduce(intent="Merge")


# --- iterate() ---------------------------------------------------------------------------


def test_iterate_minimal():
    it = iterate("https://data.com/paragraphs", intent="Translate: $item.text")
    assert it == Iteration(
        collection=Url("https://data.com/paragraphs"),
        body="",
        intent="'Translate: $item.text'",
    )
    assert render(it) == "https://data.com/paragraphs*()!'Translate: $item.text'"


def test_iterate_body_forms():
    # raw string body is taken verbatim
    it = iterate(
        "https://d/rows",
        "model:/claude($item.q)!'A', truth=$item.answer",
        intent="https://code.com/score.py",
    )
    assert render(it) == (
        "https://d/rows*(model:/claude($item.q)!'A', truth=$item.answer)!https://code.com/score.py"
    )
    # a sequence of sources builds the body via the source grammar
    it2 = iterate("https://d/rows", [src("$item.q", name="q")], intent="Answer")
    assert it2.body == "q=$item.q"


def test_iterate_python_list_collection():
    it = iterate(["sci", "tech", "econ"], intent="List $item stories")
    assert isinstance(it.collection, Expression)
    assert render(it) == "('sci', 'tech', 'econ')*()!'List $item stories'"
    structs = iterate([{"name": "Emily"}, {"name": "Max"}], intent="Mimic $item.name")
    assert render(structs) == "({name: 'Emily'}, {name: 'Max'})*()!'Mimic $item.name'"


def test_iterate_directives_and_reduce():
    it = iterate(
        "https://d/rows",
        "x=$item",
        intent="per row",
        reduce="across rows",
        concurrency=10,
        on_error="skip",
        slice=(2, 5),
        fmt_result="csv",
    )
    assert it.reducer == "'across rows'"
    assert it.directives == IterationDirectives(
        concurrency=10, on_error="skip", slice=(2, 5), fmt_result="csv"
    )
    assert build(render(it)) == it


def test_iterate_validation():
    with pytest.raises(ValueError):
        iterate("https://d/rows", on_error="explode")
    with pytest.raises(ValueError):
        iterate("https://d/rows", concurrency=0)
    with pytest.raises(ValueError):
        iterate("https://d/rows", slice=(5, 2))


# --- iteration sources inside expressions (hazard shielding) ------------------------------


def test_expr_keeps_bare_iteration_sources():
    # `OME-508`: the old shield wrapped the iteration in an intent-less group,
    # which has no surface form — the source stays as authored. The envelope's
    # source-list check (`parser._is_source_list`) keeps a sibling source out of
    # the reduce-over-iteration decode, so the placement round-trips.
    it = iterate("https://d/rows", "x=$item", intent="p")
    e = expr(it, "https://y", intent="r")
    assert e.sources[0] is it
    assert build(render(e)) == e


def test_expr_rewrites_reducer_iteration_sources():
    it = iterate("https://d/rows", "x=$item", intent="p", reduce="agg")
    e = expr(it, intent="r")
    inner = e.sources[0]
    assert isinstance(inner, Expression)
    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert inner.intent == NamedJob(value="agg")
    assert isinstance(inner.sources[0], Iteration)
    assert inner.sources[0].reducer is None
    assert build(render(e)) == e


def test_late_descriptored_iteration_round_trips_at_any_position():
    it = iterate("https://d/rows", "x=$item", intent="p")
    wrapped = src(it, name="scores", weight=0.0)
    # first position is fine at top level (the corpus shape)…
    ok = expr(wrapped, "https://y", intent="Aggregate $scores")
    assert build(render(ok)) == ok
    # …a later position round-trips too: the envelope reads a sibling source as a
    # source list, not as reduce-over-iteration…
    late = expr("https://y", wrapped, intent="Aggregate $scores")
    assert build(render(late)) == late
    # …and nested inside another group it parses via the grammar.
    outer = expr(late, intent="report")
    assert build(render(outer)) == outer


# --- expand() ------------------------------------------------------------------------------


def test_expand_forms():
    assert expand("https://feed.com/items") == Source(
        value=Url("https://feed.com/items"), expand=True
    )
    named = expand(src("https://feed.com/items", name="articles", weight=0.5))
    assert named.expand is True and named.name == "articles"
    assert render(expr(named, "https://o.com", intent=text("Summarize"))) == (
        "(*articles:0.5:https://feed.com/items, https://o.com)!'Summarize'"
    )
    # a Binding expands to a named Source (mirrors the grammar's _mark_expand)
    bound = expand(src("https://feed.com/items", name="articles"))
    assert bound == Source(value=Url("https://feed.com/items"), name="articles", expand=True)


# --- everything a builder returns is certified-renderable ----------------------------------


def test_builder_outputs_always_render():
    nodes = [
        expr(
            src(
                "https://n.com/s",
                name="article",
                weight=0.9,
                budgets={"tokens": 4000},
                required=True,
            ),
            src(text("formal"), name="tone"),
            intent="Summarize $article in a $tone tone",
        ),
        broadcast(self_(), identity("emily", "notes"), intent="Compare"),
        expr(expand("https://feed.com/items"), intent="Digest"),
        iterate(["a", "b"], [src("$item", name="x")], intent="Echo $x", reduce="Join"),
        expr(struct({"k": "v"}), ref("data", "tags", 0), intent="Inspect"),
    ]
    for node in nodes:
        rendered = render(node)  # check=True certifies build(rendered) == node
        assert build(rendered) is not None


def test_literal_text_resolves_to_its_content_in_an_rds_scope() -> None:
    # STORY: a Benchmark carries a Recipe holding `$input` as data beside code steps; in the
    # RDS scope quoted text is interpolated strictly, so it must travel as a literal.
    import asyncio

    from url4 import RelUrl, literal, literal_value
    from url4.peer.server import Url4Node

    node = Url4Node("literal")
    node.code("/echo")(lambda call: str(call.input("recipe").value))
    recipe = "/m?q=($input)!'cost $$5 and $item'"
    expression = expr(src(literal(recipe), name="recipe", weight=0.0), intent=RelUrl("/echo"))

    assert asyncio.run(node.evaluate(render(expression))).text == recipe
    assert literal_value(literal(recipe)) == recipe
