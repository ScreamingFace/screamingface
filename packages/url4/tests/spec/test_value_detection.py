"""Spec §5.2 — structural value-detection rules, one test per rule branch."""

from __future__ import annotations

import pytest

from url4.core.grammar import parse
from url4.core.nodes import Binding, Expression, NamedJob, RelUrl, Text, Url

# --- rule 1: '(' → local expression -------------------------------------------


def test_group_of_sources() -> None:
    # §5.2 rule 1; the intent is mandatory (`OME-508`)
    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert parse("(a, https://x)!go") == Expression(
        sources=(Text("a"), Url("https://x")), intent=NamedJob(value="go")
    )


def test_group_with_intent() -> None:
    # §5.2 rule 1.1.1 — ')' followed by '!' → expression intent
    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert parse("(a, b)!merge") == Expression(
        sources=(Text("a"), Text("b")), intent=NamedJob(value="merge")
    )


def test_grouped_reduce_binding() -> None:
    # §5.2 rule 1 nested under a binding
    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert parse("consensus=(a, b)!merge") == Binding(
        "consensus", Expression(sources=(Text("a"), Text("b")), intent=NamedJob(value="merge")), "="
    )


# --- rule 2: '/' → relative expression (canonical / sugar) or relative URI ----


def test_relative_expression_canonical_form() -> None:
    # §5.2 rule 2.1 — '?q=(' before any stop char → canonical relative expression
    from url4.core.nodes import RelExpr

    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert parse("/claude?q=(ctx)!go") == RelExpr(
        path="/claude", context="ctx", intent=NamedJob(value="go")
    )


def test_relative_expression_canonical_with_params() -> None:
    # §5.2 rule 2.1 — chars between '?' and 'q=' are protocol params
    from url4.core.nodes import RelExpr

    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert parse("/claude?t=90&q=(ctx)!go") == RelExpr(
        path="/claude", context="ctx", intent=NamedJob(value="go"), params=(("t", "90"),)
    )


def test_relative_expression_sugar_form() -> None:
    # §5.2 rule 2.2 — '(' before any '?' → sugar form
    from url4.core.nodes import RelExpr

    assert parse("/claude(ctx)!answer this") == RelExpr(
        path="/claude", context="ctx", intent=Text("answer this")
    )


def test_relative_expression_without_intent_is_rejected() -> None:
    # `OME-508`: `relative-expr-sugar` carries `intent-op intent` — the tail is
    # NOT optional. A path with no context is a `relative-uri` data fetch.
    from url4.core.errors import ParseError

    with pytest.raises(ParseError, match="intent"):
        parse("/claude(ctx)")


def test_relative_uri_with_query_is_data_reference() -> None:
    # §5.2 rule 2.3 — '?' present but no 'q=(' → relative data URI
    assert parse("/api/search?q=hello") == RelUrl("/api/search?q=hello")


def test_relative_uri_plain() -> None:
    # §5.2 rule 2.3
    assert parse("/api/data") == RelUrl("/api/data")


# --- rule 3: url4:// → remote expression or remote reference ------------------


def test_remote_expression_canonical_form() -> None:
    # §5.2 rule 3.1
    from url4.core.nodes import RemoteExpr

    node = parse("url4://node.ai/v1?quorum=2&q=($d)!'A'")
    assert node == RemoteExpr(
        authority="node.ai",
        path="/v1",
        context="$d",
        intent=Text("A"),
        params=(("quorum", "2"),),
    )


def test_remote_expression_sugar_form() -> None:
    # §5.2 rule 3.2
    from url4.core.nodes import RemoteExpr

    node = parse("url4://node.ai/v1($d)!'A'")
    assert node == RemoteExpr(authority="node.ai", path="/v1", context="$d", intent=Text("A"))


def test_remote_bare_reference() -> None:
    # §5.2 rule 3.3 — no expression body → remote URL4 reference
    assert parse("url4://node.ai/v1") == Url("url4://node.ai/v1")


def test_remote_reference_with_non_expression_query() -> None:
    # §5.2 rule 3.3 — '?' without 'q=(' stays a bare reference
    assert parse("url4://node.ai/v1?limit=10") == Url("url4://node.ai/v1?limit=10")


# --- rule 4: quoted text -------------------------------------------------------


def test_quoted_text_strips_quotes() -> None:
    # §5.1 free text — quotes are delimiters, content is inside (contract #1)
    assert parse("'formal'") == Text("formal")


def test_quoted_text_escaped_quote() -> None:
    # §8 quoted-char — \' escape
    assert parse(r"'it\'s'") == Text("it's")


def test_quoted_text_escaped_backslash() -> None:
    # §8 quoted-char — \\ escape
    assert parse(r"'a\\b'") == Text("a\\b")


def test_quoted_text_protects_structural_characters() -> None:
    # §7.2 — ',', '!', ';' inside quotes are content, not separators
    node = parse("('a, b!c;d', other)!go")
    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert node == Expression(
        sources=(Text("a, b!c;d"), Text("other")), intent=NamedJob(value="go")
    )


# --- rule 5: any scheme '://' → absolute URI -----------------------------------


def test_absolute_uri_https() -> None:
    # §5.2 rule 5
    assert parse("https://example.com/a") == Url("https://example.com/a")


def test_absolute_uri_s3_scheme() -> None:
    # §5.2 rule 5 — any scheme; previously misparsed as Text
    assert parse("s3://bucket/x") == Url("s3://bucket/x")


def test_trailing_star_is_literal_in_uri() -> None:
    # §5.3.3 — '*' not followed by '(' is a literal bare-value character
    assert parse("s3://bucket/prefix/*") == Url("s3://bucket/prefix/*")


# --- rule 6: '{' → structured object -------------------------------------------


def test_struct_object_detected() -> None:
    # §5.2 rule 6 / §5.3.11.3
    from url4.core.nodes import StructObject

    node = parse("{name: 'Emily', style: 'optimistic'}")
    assert node == StructObject(raw="{name: 'Emily', style: 'optimistic'}")


def test_struct_object_commas_not_split_in_group() -> None:
    # §5.3.11.5 depth tracking through {} — braces protect inner commas
    from url4.core.nodes import StructObject

    node = parse("({a: 'x', b: 'y'}, other)!go")
    assert isinstance(node, Expression)
    assert len(node.sources) == 2
    assert isinstance(node.sources[0], StructObject)
    assert node.sources[1] == Text("other")


# --- rule 7: '@' → self-reference / identity-reference --------------------------


def test_self_reference() -> None:
    # §5.2 rule 7.1 / §5.6.2
    from url4.core.nodes import SelfRef

    assert parse("@") == SelfRef()


def test_identity_reference() -> None:
    # §5.2 rule 7.2
    from url4.core.nodes import IdentityRef

    assert parse("@emily") == IdentityRef("emily")


def test_identity_reference_with_collection() -> None:
    # §5.6.2 identity-collection — stored without the leading slash
    from url4.core.nodes import IdentityRef

    assert parse("@emily/notes") == IdentityRef("emily", "notes")


def test_identity_reference_with_deep_collection() -> None:
    # §5.6.2 — identity-collection = 1*( "/" path-segment )
    from url4.core.nodes import IdentityRef

    assert parse("@andrew/drafts/2026") == IdentityRef("andrew", "drafts/2026")


def test_numeric_identity_reference() -> None:
    # §5.6.2 identity-name = name-part / 1*DIGIT
    from url4.core.nodes import IdentityRef

    assert parse("@123") == IdentityRef("123")


def test_self_and_identity_in_group() -> None:
    # §5.6.5.1 "Self- + identity-reference"
    from url4.core.nodes import IdentityRef, SelfRef

    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert parse("(@, @emily)!go") == Expression(
        sources=(SelfRef(), IdentityRef("emily")), intent=NamedJob(value="go")
    )


# --- rule 8: '$' → variable reference with field path ---------------------------


def test_standalone_variable_reference() -> None:
    # §5.2 rule 8.1
    from url4.core.nodes import VarRef

    assert parse("$data") == VarRef("data")


def test_variable_reference_with_dot_path() -> None:
    # §5.3.4 field segments
    from url4.core.nodes import VarRef

    assert parse("$data.a.b") == VarRef("data", ("a", "b"))


def test_variable_reference_with_index_path() -> None:
    # §5.3.4 index segments
    from url4.core.nodes import VarRef

    assert parse("$item.tags[0]") == VarRef("item", ("tags", 0))


def test_variable_reference_mixed_path() -> None:
    # §5.3.4 mixed traversal
    from url4.core.nodes import VarRef

    assert parse("$item.answers[0].text") == VarRef("item", ("answers", 0, "text"))


def test_binding_to_variable_reference() -> None:
    # §5.3.4 "Array index in source value"
    from url4.core.nodes import VarRef

    node = parse("answer=$item.answers[0].text")
    assert node == Binding("answer", VarRef("item", ("answers", 0, "text")), "=")


def test_positional_variable_reference() -> None:
    # §6.2 positional references
    from url4.core.nodes import VarRef

    assert parse("$1") == VarRef("1")


# --- rule 9: source-initial '*' → expansion prefix -------------------------------


def test_expansion_prefix_detected() -> None:
    # §5.2 rule 9 / §5.3.12.3 — source-initial '*' marks expansion
    from url4.core.nodes import Source

    node = parse("*https://thepost.com/feed")
    assert isinstance(node, Source)
    assert node.expand is True
    assert node.value == Url("https://thepost.com/feed")


# --- rules 10–11: bare token, iteration stop -------------------------------------


def test_bare_token() -> None:
    # §5.2 rule 10
    assert parse("hello world") == Text("hello world")


def test_iteration_operator_stops_bare_value() -> None:
    # §5.2 rule 11.1 — '*(' after a consumed bare value triggers iteration
    from url4.core.nodes import Iteration

    node = parse("https://d.com/rows*(m=/api/$item)!'per'")
    assert isinstance(node, Iteration)
    assert node.collection == Url("https://d.com/rows")
    assert node.body == "m=/api/$item"
    assert node.intent is not None and "per" in node.intent


def test_star_mid_value_not_before_paren_is_literal() -> None:
    # §5.2 rule 11.2 — '*' not followed by '(' is consumed as a literal
    assert parse("https://api.com/a*b") == Url("https://api.com/a*b")
