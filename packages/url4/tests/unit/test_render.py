"""Renderer tests — ``render()`` is the exact inverse of ``build()``/``parse()``.

INVARIANT: for every parser-producible AST ``x``, ``build(render(x)) == x`` when
``x`` is an Expression/Iteration root, and ``build(render(x)) ==
Expression(sources=(x,))`` for any other node (mirroring build()'s envelope).
``render(check=True)`` enforces this per call, so a passing render is a certified
round-trip — the property tests below are the proof the certification relies on.
"""

from __future__ import annotations

import random

import pytest

from url4 import build
from url4.core.errors import RenderError
from url4.core.grammar import parse, parse_value
from url4.core.nodes import (
    Binding,
    Expression,
    IdentityRef,
    Iteration,
    RelExpr,
    RelUrl,
    RemoteExpr,
    SelfRef,
    Source,
    StructObject,
    Text,
    Url,
    VarRef,
)
from url4.core.render import render

# --- helpers -------------------------------------------------------------------


def roundtrip(text: str) -> None:
    """Assert build(render(build(text))) == build(text)."""
    ast = build(text)
    rendered = render(ast)
    assert build(rendered) == ast, f"{text!r} -> {rendered!r} reparses differently"


# --- leaf nodes: golden strings ---------------------------------------------------


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        (Url("https://news.com/story"), "https://news.com/story"),
        (
            Url("https://en.wikipedia.org/wiki/Fish_(animal)"),
            "https://en.wikipedia.org/wiki/Fish_(animal)",
        ),
        (Url("s3://bucket/train.parquet"), "s3://bucket/train.parquet"),
        (RelUrl("/api/patient/42"), "/api/patient/42"),
        (RelUrl("/api/search?q=hello&limit=10"), "/api/search?q=hello&limit=10"),
        (Text("formal"), "'formal'"),
        (Text("Summarize $a in $tone"), "'Summarize $a in $tone'"),
        (Text("with, comma (and parens)"), "'with, comma (and parens)'"),
        (Text("it's escaped \\ well"), r"'it\'s escaped \\ well'"),
        (Text(""), "''"),
        (SelfRef(), "@"),
        (IdentityRef("emily"), "@emily"),
        (IdentityRef("andrew", "published"), "@andrew/published"),
        (IdentityRef("alice", "drafts/2026"), "@alice/drafts/2026"),
        (VarRef("article"), "$article"),
        (VarRef("1"), "$1"),
        (VarRef("item", ("tags", 0)), "$item.tags[0]"),
        (VarRef("data", ("runs", 0, "results", "score")), "$data.runs[0].results.score"),
        (
            StructObject("{name: 'Emily', style: 'optimistic'}"),
            "{name: 'Emily', style: 'optimistic'}",
        ),
    ],
)
def test_leaf_golden(node, expected):
    assert render(node) == expected
    # a leaf value reparses to itself
    assert parse_value(expected) == node


def test_leaf_renders_bare_at_top_level():
    assert render(Url("https://x")) == "https://x"


# --- composite source nodes render as bare fragment roots (`OME-508`) ---------------


def test_binding_renders_bare_at_top_level():
    # WHY: the old paren wrap was an intent-less group, which the grammar
    # rejects (`OME-508`) — a lone composite source is a fragment root.
    node = Binding("a", Url("https://x"), "=")
    assert render(node) == "a=https://x"
    assert build(render(node)) == Expression(sources=(node,))


def test_relexpr_with_intent_renders_bare_at_top_level():
    # `OME-508` cycle 2: the envelope no longer hoists a lone call's intent —
    # that "!" belongs to the CALL — so the fragment root round-trips.
    node = RelExpr(path="/claude", context="https://x", intent=Text("summarize"))
    assert render(node) == "/claude(https://x)!'summarize'"
    assert build(render(node)) == Expression(sources=(node,))


def test_source_parenthesized_at_top_level():
    node = Source(value=Url("https://x"), name="a", weight=0.9)
    assert build(render(node)) == Expression(sources=(node,))


# --- descriptors ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("article=https://news.com/story", "article=https://news.com/story"),
        ("article:0.9:https://news.com/story", "article:0.9:https://news.com/story"),
        ("0.8:s3://bucket/train.parquet", "0.8:s3://bucket/train.parquet"),
        (
            "article:0.9:tokens=4000:https://news.com/story;required",
            "article:0.9:tokens=4000:https://news.com/story;required",
        ),
        (
            "medical:0.5:tokens=8000:influence=0.6:https://h.org/api;mode=agent;t=120;retry=2;required",
            "medical:0.5:tokens=8000:influence=0.6:https://h.org/api;mode=agent;t=120;retry=2;required",
        ),
        # structured weight, struct budget, nested struct budget
        (
            "claude:(science:0.85,math:0.64,_default:0.4):https://x",
            "claude:(science:0.85,math:0.64,_default:0.4):https://x",
        ),
        (
            "claude:0.6:tokens=(science:6000,_default:4000):https://x",
            "claude:0.6:tokens=(science:6000,_default:4000):https://x",
        ),
        (
            "claude:0.6:tokens=(_each:(science:6000,_default:4000),_total:5000000):https://x",
            "claude:0.6:tokens=(_each:(science:6000,_default:4000),_total:5000000):https://x",
        ),
        # expansion prefix (canonical sugar for ;expand)
        ("*https://feed.com/items", "*https://feed.com/items"),
        ("*articles:0.5:https://feed.com/items", "*articles:0.5:https://feed.com/items"),
    ],
)
def test_descriptor_golden(text, expected):
    node = parse(text)
    assert render(node) == expected


def test_weight_keyword_normalizes_to_bare_scalar():
    # weight=0.5 and 0.5 produce the same AST; render emits the bare form.
    node = parse("claude:weight=0.5:https://x")
    assert render(node) == "claude:0.5:https://x"
    assert parse("claude:0.5:https://x") == node


def test_expand_annotation_normalizes_to_prefix():
    prefix = parse("*https://feed.com/items")
    annotated = parse("https://feed.com/items;expand")
    assert prefix == annotated
    assert render(annotated) == "*https://feed.com/items"


def test_src_binding_of_bare_token_renders_quoted():
    # 0.2:src=mytoken → Source(weight=0.2, value=Text("mytoken")); the quoted
    # form parses back to the same Text without needing src=.
    node = parse("0.2:src=mytoken;optional")
    assert render(node) == "0.2:'mytoken';optional"
    assert parse("0.2:'mytoken';optional") == node


def test_descriptor_empty_source_raises():
    # The grammar never produces a Source with a name and nothing else — that
    # shape parses as Binding, so rendering it would lie about the tree.
    with pytest.raises(RenderError, match="Binding"):
        render(Source(value=Url("https://x"), name="a"))


def test_unnamed_weightless_budgeted_source_raises():
    # 'tokens=…' at the token head is captured by the name=value sugar test
    # before descriptor parsing runs — the shape is parser-unreachable.
    with pytest.raises(RenderError, match="sugar"):
        render(Source(value=Url("https://x"), budgets=(("tokens", "4000"),)))


def test_unnamed_structured_weight_raises():
    # A token-initial '(' is value-shaped (§4.3): the weight-position
    # classifier never runs for an unnamed source.
    with pytest.raises(RenderError, match="name"):
        render(Source(value=Url("https://x"), weight={"science": 0.85, "_default": 0.4}))


def test_flag_annotation_without_value():
    node = parse("https://x;required;x_custom")
    assert render(node) == "https://x;required;x_custom"


# --- expressions -------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "(https://news.com/story)!'Summarize this'",
        "()!'Generate a haiku'",
        "(a=https://x, tone='formal')!'Summarize $a in a $tone tone'",
        "(https://a.com, https://b.com, https://c.com)!*'Extract key claims'",
        "((src_a, src_b)!*'Extract')!'Synthesize a report'",
        "(article:0.9:https://news.com/story, style:0.1:'formal')!'Summarize $article in $style'",
        "(https://news.com/story, 'formal')!'Summarize $1 in $2'",
        "(data:https://api.com/record)!'The first tag is $data.tags[0]'",
        "(@)!'science articles'",
        "(@johndoe/climate)!'science articles'",
        "(@, @emily)!'Compare holdings'",
        "(emily_data:0.3:influence=0.5:@emily/notes;required)!'Summarize $emily_data'",
        "(summary=(https://src.com)!'clean', data=https://d.com)!'Compare $summary vs $data'",
        "(scores:0.0:https://data.com/records)!'Aggregate $scores'",
        "(x)!'go';quorum=2;t=60",
        "(claude:0.6:/claude(https://u.com)!'Go', llama:0.4:/llama(https://u.com)!'Go')"
        "!'Merge $claude and $llama'",
        "(https://api.com/search?q=hello&limit=100)!'Summarize'",
        "({k: 'v', n: {deep: 'x'}})!'Describe $1'",
        "(0.2:'Supplementary guidelines';optional;retry=3)!'Apply'",
    ],
)
def test_expression_roundtrip(text):
    roundtrip(text)


def test_broadcast_param_folds_into_operator():
    # ;broadcast and !* produce the same AST; render emits the operator form
    # (bare tokens canonically render quoted — same Text AST).
    assert build("(a,b)!'x';broadcast") == build("(a,b)!*'x'")
    assert render(build("(a,b)!'x';broadcast")) == "('a', 'b')!*'x'"


def test_intent_forms():
    assert (
        render(build("(https://x)!https://code.com/score.py"))
        == "(https://x)!https://code.com/score.py"
    )
    assert render(build("(https://x)!/score.py")) == "(https://x)!/score.py"
    # a bare-token intent normalizes to the quoted form (same Text AST)
    assert render(build("(https://x)!Summarize")) == "(https://x)!'Summarize'"


# --- relative / remote expressions ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "(/claude(https://x)!'Answer')!'Use $1'",
        "(/claude?t=90&q=(https://x)!'Answer')!'Use $1'",
        "(model:0.5:/claude?t=60&quorum=2&q=(https://x)!'Answer';mode=agent;t=180;required)!'Go'",
        "(url4://analyst.example.com/v1(https://data.com)!'Analyze')!'Report'",
        "(url4://node.ai/v1?quorum=1&q=(https://d.com)!'Go')!'Use $1'",
        "(url4://registry.ai/nodes)!'Pick one'",  # bare remote reference (Url)
        "(/chef?q=(https://allrecipes.com)!'Find recipes')!'Cook'",
        "(/claude()!'go')!'Empty context call'",
        "(/claude?stream&q=(x)!'go')!'flags carry no value'",
    ],
)
def test_rel_remote_roundtrip(text):
    roundtrip(text)


def test_relexpr_sugar_when_no_params_canonical_when_params():
    # A lone RelExpr-with-intent has no top-level form (`OME-508`), so the
    # sugar/canonical emission is asserted through an intent-bearing group.
    sugar = build("(/claude(https://x)!'Answer')!'Use $1'")
    assert render(sugar) == "(/claude(https://x)!'Answer')!'Use $1'"
    canonical = build("(/claude?t=90&q=(https://x)!'Answer')!'Use $1'")
    assert render(canonical) == "(/claude?t=90&q=(https://x)!'Answer')!'Use $1'"


# --- iteration -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "https://data.com/paragraphs*()!'Translate: $item.text'",
        "https://data.com/records*(model:/claude($item.input)!'Analyze';mode=agent, truth=$item.answer)!https://code.com/score.py",
        # AIDEV-NOTE: spec §5.3.1 writes this as (expr)!'Clean'*(...) directly, but the
        # engine's envelope decode needs the expression collection double-parenthesized.
        "((https://raw.com/messy)!'Clean')*(analysis:/claude($item)!'Analyze')"
        "!'Summarize $analysis'",
        "records*(a=$item.answers[0].text)!score.py;iteration.concurrency=10;iteration.on_error=collect",
        "records*(x=$item)!go.py;iteration.slice=2:5;iteration.fmt_result=csv",
        "(src*(model:/claude($item.q)!'Answer')!score_one.py)!'Aggregate into a report'",
        "('a', 'b', 'c')*()!'Classify $item'",
        "({name: 'Emily', style: 'upbeat'}, {name: 'Max', style: 'dry'})*()!'Mimic $item.style'",
        "(scores:0.0:https://data.com/records*(m:0.5:/claude($item.q)!'A';mode=agent;required,"
        " truth=$item.answer)!score.py)!'Aggregate $scores'",
    ],
)
def test_iteration_roundtrip(text):
    roundtrip(text)


def test_iteration_directives_golden():
    ast = build("records*(x=$item)!go.py;iteration.concurrency=3")
    assert isinstance(ast, Iteration)
    # the bare-token collection canonically renders quoted (same Text AST)
    assert render(ast) == "'records'*(x=$item)!go.py;iteration.concurrency=3"


def test_reduce_over_iteration_golden():
    ast = build("(records*(x=$item)!'per row';iteration.on_error=skip)!'across rows'")
    assert isinstance(ast, Iteration)
    assert ast.reducer == "'across rows'"
    rendered = render(ast)
    assert build(rendered) == ast


# --- error cases: unrepresentable values ----------------------------------------------


@pytest.mark.parametrize(
    "node",
    [
        Url("https://x/a(b"),  # unbalanced paren cannot survive bare-value parsing
        Url("https://x/a,b"),  # depth-0 comma would split the source list
        Url("https://x/a'b"),  # a quote desyncs bare-value consumption
        RelUrl("/api/a(b)"),  # any '(' reparses as a sugar-form RelExpr
        RelUrl("/api/a!b"),  # depth-0 '!' would split as intent
        Url("https://x;jsessionid=1"),  # depth-0 ';' would split as annotations
    ],
)
def test_unrepresentable_uris_raise(node):
    with pytest.raises(RenderError):
        render(node)


def test_negative_weight_raises():
    with pytest.raises(RenderError):
        render(Source(value=Url("https://x"), weight=-0.5))


def test_vanishing_weight_raises():
    with pytest.raises(RenderError):
        render(Source(value=Url("https://x"), weight=1e-15))


def test_overdeep_struct_budget_raises():
    node = Source(value=Url("https://x"), budgets=(("tokens", {"a": {"b": {"c": 1}}}),))
    with pytest.raises(RenderError):
        render(node)


def test_iteration_source_with_intent_round_trips():
    # "(A*(b)!'p', B)!'r'" once reparsed as reduce-over-iteration, swallowing B;
    # the envelope's source-list check now keeps it a group. Bare, wrapped, first
    # or later — every placement round-trips.
    it = Iteration(collection=Url("https://x"), body="a=$item", intent="'p'")
    for e in (
        Expression(sources=(it, Url("https://y")), intent=Text("r")),
        Expression(sources=(Url("https://y"), Source(value=it, weight=0.5)), intent=Text("r")),
        Expression(sources=(Source(value=it, weight=0.5), Url("https://y")), intent=Text("r")),
    ):
        assert build(render(e)) == e
        assert build(render(e, check=False)) == e


def test_iteration_reducer_in_value_position_raises():
    # Only the top-level envelope decodes reduce-over-iteration; nested it would
    # reparse as Expression(sources=(Iteration,), intent) — a different AST.
    inner = Iteration(collection=Url("https://x"), body="a=$item", intent="'p'", reducer="'r'")
    with pytest.raises(RenderError):
        render(Expression(sources=(inner,), intent=Text("go")))


def test_dual_key_boundary_guard_raises():
    # A leading dual-scope key on an expression-valued source would be
    # reclassified to expression level on reparse (spec §8.1.2).
    bad = Source(
        value=RelExpr(path="/claude", context="x", intent=Text("go")),
        annotations=(("t", "90"),),
    )
    with pytest.raises(RenderError):
        render(bad)
    ok = Source(
        value=RelExpr(path="/claude", context="x", intent=Text("go")),
        annotations=(("mode", "agent"), ("t", "90")),
    )
    # A lone annotated rel-expr source hoists its tail at top level (`OME-508`
    # removed the paren wrap), so representability is asserted inside a group.
    ok_expr = Expression(sources=(ok,), intent=Text("r"))
    assert build(render(ok_expr)) == ok_expr


def test_binding_inside_source_raises():
    node = Source(value=Binding("a", Url("https://x"), "="), weight=0.5)
    with pytest.raises(RenderError):
        render(node)


def test_unknown_node_type_raises():
    with pytest.raises(TypeError):
        render(object())  # type: ignore[arg-type]


# --- additional error/validation branches (OME-397 coverage follow-up) -----------------


def test_broadcast_without_intent_raises():
    node = Expression(sources=(Url("https://x"),), intent=None, broadcast=True)
    with pytest.raises(RenderError, match="broadcast"):
        render(node)


@pytest.mark.parametrize("key", ["broadcast", "iteration.concurrency", "foreach.slice"])
def test_non_canonical_param_key_raises(key):
    # broadcast/iteration.*/foreach.* keys fold into dedicated node fields — they
    # are never legal as literal Expression.params entries.
    node = Expression(sources=(Url("https://x"),), intent=Text("go"), params=((key, None),))
    with pytest.raises(RenderError, match="non-canonical"):
        render(node)


def test_source_level_param_on_nested_expression_raises():
    # "mode" is exclusively source-level (§8.1.3); on a NESTED (non-top)
    # Expression it has nowhere faithful to reparse to.
    inner = Expression(sources=(Url("https://x"),), intent=Text("go"), params=(("mode", "agent"),))
    outer = Expression(sources=(inner,), intent=Text("outer"))
    with pytest.raises(RenderError, match="source-level"):
        render(outer)


def test_non_leaf_intent_raises():
    # intent_atom() only produces Text / Url / RelUrl; anything else has no
    # intent-position surface form.
    with pytest.raises(RenderError, match="cannot be an intent"):
        render(Expression(sources=(Url("https://x"),), intent=VarRef("a")))


def test_relurl_intent_depth0_semicolon_raises():
    with pytest.raises(RenderError, match="depth-0 ';'"):
        render(Expression(sources=(Url("https://x"),), intent=RelUrl("/a;b")))


def test_reserved_source_name_raises():
    with pytest.raises(RenderError, match="invalid source name"):
        render(Source(value=Url("https://x"), name="src", weight=0.5))


def test_invalid_budget_key_raises():
    with pytest.raises(RenderError, match="invalid budget key"):
        render(Source(value=Url("https://x"), name="a", budgets=(("src", "4000"),)))


def test_url_missing_scheme_raises():
    with pytest.raises(RenderError, match="scheme"):
        render(Url("not-a-url"))


def test_relurl_missing_leading_slash_raises():
    with pytest.raises(RenderError, match="must start with"):
        render(RelUrl("no-slash"))


def test_uri_unbalanced_closing_paren_raises():
    # a stray ')' (no matching '(') drives the depth counter negative mid-scan.
    with pytest.raises(RenderError, match="unbalanced parentheses"):
        render(Url("https://x)"))


def test_invalid_varref_name_raises():
    with pytest.raises(RenderError, match="invalid variable name"):
        render(VarRef("bad-name"))


def test_invalid_varref_path_segment_raises():
    with pytest.raises(RenderError, match="invalid field-path segment"):
        render(VarRef("item", ("bad seg",)))


@pytest.mark.parametrize(
    ("node", "match"),
    [
        (IdentityRef("bad name"), "invalid identity name"),
        (IdentityRef("emily", "my notes"), "invalid identity collection"),
    ],
)
def test_identity_ref_validation_raises(node, match):
    with pytest.raises(RenderError, match=match):
        render(node)


@pytest.mark.parametrize("raw", ["not-braces", "{a: 1", "{a:1}{b:2}"])
def test_struct_object_unbalanced_raises(raw):
    with pytest.raises(RenderError, match="not one balanced"):
        render(StructObject(raw))


@pytest.mark.parametrize("authority", ["", "bad/host", "bad?host", "bad'host"])
def test_remoteexpr_invalid_authority_raises(authority):
    with pytest.raises(RenderError, match="invalid remote authority"):
        render(RemoteExpr(authority=authority, path="/v1"))


def test_expression_path_invalid_raises():
    with pytest.raises(RenderError, match="invalid expression path"):
        render(RelExpr(path="noslash", intent=Text("go")))


def test_expression_context_unbalanced_raises():
    with pytest.raises(RenderError, match="unbalanced or unstripped"):
        render(RelExpr(path="/claude", context="a(b", intent=Text("go")))


def test_top_iteration_descriptored_collection_reducer_raises():
    # §5.3.10 — the reduce-over-iteration decode rejects a descriptored
    # collection (the descriptor would attribute the iteration in the
    # enclosing expression instead), so this shape has no text form.
    it = Iteration(
        collection=Source(value=Url("https://x"), weight=0.5),
        body="x=$item",
        intent="'p'",
        reducer="'r'",
    )
    with pytest.raises(RenderError, match="descriptored collection"):
        render(it)


def test_top_iteration_reducer_depth0_semicolon_raises():
    it = Iteration(collection=Url("https://x"), body="x=$item", intent="'p'", reducer="a;b")
    with pytest.raises(RenderError, match="depth-0 ';'"):
        render(it)


def test_iteration_collection_cannot_be_iteration_raises():
    inner = Iteration(collection=Url("https://x"), body="a=1", intent="'p'")
    outer = Iteration(collection=inner, body="b=2", intent="'q'")
    with pytest.raises(RenderError, match="cannot be another iteration's collection"):
        render(outer)


def test_iteration_body_unbalanced_raises():
    with pytest.raises(RenderError, match="unbalanced"):
        render(Iteration(collection=Url("https://x"), body="(a=1"))


def test_iteration_intent_depth0_semicolon_raises():
    with pytest.raises(RenderError, match="depth-0 ';'"):
        render(Iteration(collection=Url("https://x"), body="x=$item", intent="a;b"))


def test_nested_reduce_over_iteration_in_value_position_raises():
    # Companion to test_iteration_reducer_in_value_position_raises above, one
    # level deeper: the reducer'd iteration is a bare source of a NESTED
    # (non-top) Expression, and _check_value_iteration's own reducer guard
    # refuses it there too.
    inner_it = Iteration(collection=Url("https://x"), body="a=$item", intent="'p'", reducer="'r'")
    nested = Expression(sources=(inner_it,), intent=Text("go"))
    outer = Expression(sources=(nested,), intent=Text("outer"))
    with pytest.raises(RenderError, match="top-level envelope"):
        render(outer)


# AIDEV-NOTE: _render_value_iteration's non-default-directives guard
# (render.py lines 518-524) is unreachable through render() as currently
# structured — every source-position Iteration (bare, Binding-wrapped,
# Source-wrapped, or a bare Expression-source element) is intercepted by
# _source_value_and_tail's own `isinstance(value, Iteration)` branch, which
# calls _render_iteration_core directly and serializes directives onto the
# source's ';' tail instead of ever calling _render_value(iteration). Verified
# empirically (coverage never marks lines 518-524 hit regardless of nesting
# position); skipped per the spec's fallback for parser-only-reachable shapes.


def test_empty_struct_annotation_raises():
    with pytest.raises(RenderError, match="cannot be empty"):
        render(Source(value=Url("https://x"), name="a", weight={}))


def test_struct_value_nested_three_levels_raises():
    # Distinct from test_overdeep_struct_budget_raises above: that case is
    # unnamed+weightless+budgeted and actually raises via the sugar-ambiguity
    # guard before struct nesting is ever checked. Naming the source here lets
    # the render reach the §24.4.6 two-level nesting check itself.
    node = Source(
        value=Url("https://x"), name="a", budgets=(("tokens", {"top": {"mid": {"leaf": 1}}}),)
    )
    with pytest.raises(RenderError, match="nested deeper than two levels"):
        render(node)


def test_invalid_struct_value_type_raises():
    node = Source(value=Url("https://x"), name="a", budgets=(("tokens", {"key": [1, 2]}),))
    with pytest.raises(RenderError, match="invalid structured annotation value"):
        render(node)


# --- the corpus: every spec construct round-trips --------------------------------------

CORPUS = [
    # §4.5 complete descriptor examples
    "(https://news.com/story)!'go'",
    "(article=https://news.com/story)!'go'",
    "(article:https://news.com/story)!'go'",
    "(article:0.9:https://news.com/story)!'go'",
    "(0.8:s3://bucket/train.parquet)!'go'",
    "(article:0.9:tokens=4000:https://news.com/story;required)!'go'",
    "(article:0.9:tokens=4000:src=https://news.com/story;required)!'go'",
    "(0.2:'Supplementary AMA guidelines';optional;retry=3)!'go'",
    "(0.2:src=mytoken;optional;retry=3)!'go'",
    "(chef:0.4:/chef?q=(https://allrecipes.com)!'Find recipes';mode=agent;t=120)!'go'",
    "(chef:0.4:/chef(https://allrecipes.com)!'Find recipes';mode=agent;t=120)!'go'",
    "(data:https://api.example.com/records;accept=csv;t=30)!'go'",
    # §4.1.1 structured values
    "(claude:(science:0.85,math:0.64,classics:0.10,_default:0.4):https://x)!'go'",
    "(claude:weight=(_default:0.5):https://x)!'go'",
    "(claude:0.6:tokens=(_each:4000,_total:5000000):https://x)!'go'",
    "(claude:(formal:'academic',_default:'neutral'):https://x)!'go'",
    # §5.6 self / identity references with descriptors
    "(mine:0.7:@;required, other:@bob/notes)!'compare'",
    # §5.3.12 expansion
    "(*https://thepost.com/feed, other=https://o.com)!'Summarize'",
    "(articles:0.5:https://thepost.com/feed;expand, https://o.com)!'Summarize'",
    # §6.1 broadcast + nesting
    "((a1=https://a.com, a2=https://b.com)!*'Extract claims')!'Synthesize'",
    # variables and paths (§6.2, §5.3.4)
    "(d=https://api.com/r)!'Author: $d.author.name, tag: $d.tags[0], lit: $$item'",
    "(x=$item.answers[0].text, truth=$item.expected)!https://code.com/score.py",
    # iteration in all shapes (§5.3)
    "https://data.com/rows*(m:0.9:/claude($item.q)!'A';mode=agent;t=180;required,"
    " truth=$item.answer)!score.py",
    "rows*(ctx=/api/guidelines/$item.guide)!'Given $ctx, evaluate $item.text'",
    "(matrix*(cell=$item.data[0][2])!analyze.py)!'Summarize $1'",
    "('sci', 'tech', 'econ')*()!'List $item stories'",
    # quoting / escaping (§7)
    "('What is 2 + 2, really?')!'Answer (with care); use $1!'",
    "(u='https://api.com/point?lat=1.0,lon=2.0')!'go'",
    "(w='https://en.wikipedia.org/wiki/Fish_(animal)')!'go'",
    # params & flags (§9.2 surface)
    "(a=https://x)!'go';quorum=2;triggers=1,2,3;meta=full",
]


@pytest.mark.parametrize("text", CORPUS)
def test_corpus_roundtrip(text):
    roundtrip(text)


# --- randomized ASTs: the generator only emits parser-canonical shapes ------------------

EXEC_KEYS = [("mode", "agent"), ("retry", "3"), ("accept", "csv"), ("required", None)]
BUDGET_VALUES = [
    "4000",
    {"science": 6000, "_default": 4000},
    {"_each": {"a": 1, "_default": 2}, "_total": 9},
]
WEIGHTS = [0.0, 0.5, 1.0, 0.25, 2.0, {"science": 0.85, "_default": 0.4}]
TEXT_POOL = ["formal", "with, commas", "parens (ok)", "quote ' and \\ slash", "$ref $$lit", ""]
URL_POOL = [
    "https://news.com/story",
    "https://api.com/search?q=hello&limit=100",
    "s3://bucket/data.parquet",
    "https://en.wikipedia.org/wiki/Fish_(animal)",
]
STRUCT_POOL = ["{k: 'v'}", "{a: 1, b: {c: 'deep'}}"]


def _leaf(rng: random.Random):
    factories = [
        lambda: Url(rng.choice(URL_POOL)),
        lambda: RelUrl("/api/data"),
        lambda: Text(rng.choice(TEXT_POOL)),
        lambda: VarRef(rng.choice(["a", "item", "1"]), rng.choice([(), ("f",), ("f", 0)])),
        lambda: SelfRef(),
        lambda: IdentityRef("emily", rng.choice([None, "notes", "drafts/2026"])),
        lambda: StructObject(rng.choice(STRUCT_POOL)),
    ]
    return rng.choice(factories)()


def _source(rng: random.Random, depth: int):
    value = _value(rng, depth)
    if isinstance(value, (Expression, RelExpr, RemoteExpr)):
        # keep the §8.1.2 boundary unambiguous: exclusive source key first
        annotations = (("mode", "agent"), ("t", "90")) if rng.random() < 0.5 else ()
    else:
        annotations = tuple(rng.sample(EXEC_KEYS, k=rng.randrange(3)))
    weight = rng.choice(WEIGHTS) if rng.random() < 0.6 else None
    budgets = (("tokens", rng.choice(BUDGET_VALUES)),) if rng.random() < 0.4 else ()
    name = rng.choice(["a", "src2", None])
    if budgets and name is None and weight is None:
        weight = 0.5  # unnamed+weightless+budgeted is parser-unreachable (sugar capture)
    if isinstance(weight, dict) and name is None:
        name = "a"  # unnamed structured weight is token-initial '(' → parser-unreachable
    expand = rng.random() < 0.15
    if weight is None and not budgets and not annotations and not expand:
        if name is not None:
            return Binding(name, value, "=")
        return value
    return Source(
        value=value,
        name=name,
        weight=weight,
        budgets=budgets,
        annotations=annotations,
        expand=expand,
    )


def _shielded_iteration() -> Expression:
    # WHY: iteration values are shielded in their own intent-bearing group — an
    # unshielded iteration source is position-dependent (see the hazard tests
    # above), and an intent-less wrap has no surface form (`OME-508`).
    it = Iteration(collection=Url("https://data.com/rows"), body="x=$item", intent="'p'")
    return Expression(sources=(Source(value=it, weight=0.5),), intent=Text("go"))


def _value(rng: random.Random, depth: int):
    if depth <= 0 or rng.random() < 0.6:
        return _leaf(rng)
    factories = [
        lambda: Expression(
            sources=tuple(_source(rng, depth - 1) for _ in range(rng.randrange(3))),
            intent=Text("do it"),
            broadcast=rng.random() < 0.2,
        ),
        lambda: RelExpr(
            path="/claude",
            context="https://x",
            intent=Text("go"),
            params=rng.choice([(), (("t", "90"),)]),
        ),
        lambda: RemoteExpr(
            authority="node.ai",
            path="/v1",
            context="https://x",
            intent=Text("go"),
            params=rng.choice([(), (("quorum", "2"),)]),
        ),
        _shielded_iteration,
    ]
    return rng.choice(factories)()


def test_random_ast_roundtrip():
    rng = random.Random(20260713)
    for i in range(200):
        root = Expression(
            sources=tuple(_source(rng, 2) for _ in range(rng.randrange(4))),
            intent=rng.choice([Text("merge it"), Url("https://code.com/s.py")]),
        )
        rendered = render(root)  # check=True certifies the round-trip
        assert build(rendered) == root, f"case {i}: {rendered!r}"
