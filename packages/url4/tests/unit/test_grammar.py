"""Grammar-level parsing: each detection rule maps to the right AST node."""

from __future__ import annotations

import pytest

from url4.core.errors import ParseError
from url4.core.grammar import parse, parse_value
from url4.core.nodes import (
    Binding,
    Expression,
    NamedJob,
    RelExpr,
    RelUrl,
    Source,
    Text,
    Url,
)


def test_absolute_url() -> None:
    assert parse("https://example.com/a") == Url("https://example.com/a")


def test_relative_url() -> None:
    assert parse("/api/data") == RelUrl("/api/data")


def test_bare_text() -> None:
    assert parse("hello world") == Text("hello world")


def test_quoted_text_strips_quotes() -> None:
    # Quotes are delimiters (spec §5.1); content is what is inside.
    assert parse("'formal'") == Text("formal")


def test_group_of_sources() -> None:
    # `OME-508`: local-expr's intent is mandatory — the bare form raises.
    node = parse("(a, https://x)!go")
    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert node == Expression(sources=(Text("a"), Url("https://x")), intent=NamedJob(value="go"))
    with pytest.raises(ParseError, match="intent"):
        parse("(a, https://x)")


def test_named_binding() -> None:
    assert parse("article=https://x") == Binding("article", Url("https://x"), "=")


def test_relative_expression_with_context_and_intent() -> None:
    node = parse("/claude(ctx)!answer this")
    assert node == RelExpr(path="/claude", context="ctx", intent=Text("answer this"))


def test_weighted_relative_expression() -> None:
    # The name:weight: label is the two-axis descriptor (§4.3) — it wraps ANY
    # value in a Source, not just relative expressions.
    node = parse("claude:0.6:/claude(x)!go")
    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert node == Source(
        value=RelExpr(path="/claude", context="x", intent=NamedJob(value="go")),
        name="claude",
        weight=0.6,
    )


def test_expansion_prefix_source() -> None:
    # §5.2 rule 9: a source-initial '*' marks the source for expansion.
    node = parse("*https://data.com/rows")
    assert node == Source(value=Url("https://data.com/rows"), expand=True)


def test_star_not_before_paren_is_literal_mid_value() -> None:
    # §5.3.3: mid-value '*' is structural ONLY when immediately followed by '('.
    assert parse("s3://bucket/prefix/*") == Url("s3://bucket/prefix/*")


def test_grouped_reduce_binding() -> None:
    node = parse("consensus=(a, b)!merge")
    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert node == Binding(
        "consensus",
        Expression(sources=(Text("a"), Text("b")), intent=NamedJob(value="merge")),
        "=",
    )


def test_malformed_raises_parse_error() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse("(unclosed")
    assert exc_info.value.code == "malformed_source"


def test_empty_source_raises() -> None:
    for text in ("", "   "):
        with pytest.raises(ParseError) as exc_info:
            parse(text)
        assert exc_info.value.code == "malformed_source"
        assert "empty url4 expression" in str(exc_info.value)


def test_empty_value_raises() -> None:
    for text in ("", "   "):
        with pytest.raises(ParseError) as exc_info:
            parse_value(text)
        assert exc_info.value.code == "malformed_source"
        assert "empty url4 value" in str(exc_info.value)


def test_source_empty_before_separator_raises() -> None:
    # A source token starting with ';' has no value before the depth-0 split.
    with pytest.raises(ParseError) as exc_info:
        parse(";foo")
    assert "source has no value before ';'" in str(exc_info.value)


def test_head_explicit_src_prefix() -> None:
    # §4.3 — a head that itself starts with 'src=' (no name, no weight).
    assert parse("src=https://data") == Url("https://data")


def test_bare_token_in_attrib_chain_requires_src() -> None:
    # §4.3 — a bare token in the data-binding position has no 'src=' marker.
    with pytest.raises(ParseError) as exc_info:
        parse("weight:0.5:mytoken")
    assert exc_info.value.code == "malformed_source"
    assert "bare-token data binding requires 'src='" in str(exc_info.value)
    # Contrast: the same token behind 'src=' parses as a bare Text value.
    assert parse("weight:0.5:src=mytoken") == Source(
        value=Text("mytoken"), name="weight", weight=0.5
    )


def test_unclosed_paren_in_weight_position_raises() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse("name:(a:1:https://x")
    assert exc_info.value.code == "malformed_source"
    assert "unclosed '('" in str(exc_info.value)


def test_structured_weight_without_data_binding_raises() -> None:
    # §4.1.1.4 — a committed structured weight not followed by ':<data-binding>'.
    with pytest.raises(ParseError) as exc_info:
        parse("name:(a:1)")
    assert exc_info.value.code == "malformed_source"
    assert "structured weight must be followed by ':<data-binding>'" in str(exc_info.value)


def test_non_struct_pair_entry_falls_back_to_expression_list() -> None:
    # §4.1.1.4 — a later entry using '=' instead of ':' fails the struct-pair
    # test, so the whole '(' group is reclassified as an expression source
    # list rather than a structured weight.
    node = parse("name:(a:'x',b=2)!go")
    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert node == Binding(
        "name",
        Expression(
            sources=(Binding("a", Text("x"), ":"), Binding("b", Text("2"), "=")),
            intent=NamedJob(value="go"),
        ),
        ":",
    )


def test_malformed_struct_entry_after_commitment_raises() -> None:
    # §4.1.1.4 — once committed to the struct form (first entry classifies),
    # a later entry violating the struct-pair production is a hard error, not
    # a reclassification.
    with pytest.raises(ParseError) as exc_info:
        parse("name:(a:1,b=2):https://x")
    assert exc_info.value.code == "malformed_source"
    assert "malformed structured annotation entry" in str(exc_info.value)


def test_empty_structured_annotation_raises() -> None:
    # A structured budget value whose parens contain no entries at all.
    with pytest.raises(ParseError) as exc_info:
        parse("name:cost=():src=data")
    assert exc_info.value.code == "malformed_source"
    assert "empty structured annotation value" in str(exc_info.value)


def test_nested_struct_too_deep_raises() -> None:
    # §24.4.6 — at most scope -> domain -> scalar; a third level of nesting
    # inside a structured weight value is rejected.
    with pytest.raises(ParseError) as exc_info:
        parse("name:(a:(b:(c:1))):src=data")
    assert exc_info.value.code == "malformed_source"
    assert "nested too deep" in str(exc_info.value)


def test_malformed_nested_struct_value_raises() -> None:
    # A nested '(' group whose parens don't balance against the surrounding
    # value (trailing garbage after the matched close).
    with pytest.raises(ParseError) as exc_info:
        parse("name:weight=(a:(b:1)x):src=data")
    assert exc_info.value.code == "malformed_source"
    assert "malformed structured annotation value" in str(exc_info.value)


def test_invalid_weight_value_raises() -> None:
    # §4.1.1.3 — the reserved 'weight=' key requires a numeric or structured
    # value; a bare word is neither.
    with pytest.raises(ParseError) as exc_info:
        parse("name:weight=abc:src=data")
    assert exc_info.value.code == "malformed_source"
    assert "malformed weight value" in str(exc_info.value)


def test_malformed_structured_budget_value_raises() -> None:
    # A budget value's parens don't balance (extra trailing ')').
    with pytest.raises(ParseError) as exc_info:
        parse("name:cost=(a:1)):src=data")
    assert exc_info.value.code == "malformed_source"
    assert "malformed structured budget value" in str(exc_info.value)


def test_unclosed_iteration_body_raises() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse("https://x*(unclosed")
    assert exc_info.value.code == "malformed_source"
    assert "unclosed iteration body" in str(exc_info.value)


def test_unexpected_text_after_iteration_body_raises() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse("https://x*(body)trailing")
    assert exc_info.value.code == "malformed_source"
    assert "unexpected text after iteration body" in str(exc_info.value)


def test_unclosed_paren_in_sugar_expression_raises() -> None:
    # §3.1.1.1 — sugar-form '/path(context)!intent'.
    with pytest.raises(ParseError) as exc_info:
        parse("/claude(unclosed")
    assert exc_info.value.code == "malformed_source"
    assert "unclosed '('" in str(exc_info.value)


def test_unclosed_paren_in_canonical_expression_raises() -> None:
    # §5.2 rule 7a — canonical-form '/path?q=(context)!intent'.
    with pytest.raises(ParseError) as exc_info:
        parse("/path?q=(unclosed")
    assert exc_info.value.code == "malformed_source"
    assert "unclosed '('" in str(exc_info.value)


def test_unexpected_text_after_expression_body_raises() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse("/path?q=(ctx)trailing")
    assert exc_info.value.code == "malformed_source"
    assert "unexpected text after expression body" in str(exc_info.value)


def test_remote_expression_requires_path_raises() -> None:
    # A '(' before any path slash in a url4:// remote reference is invalid —
    # a remote expression always needs a path.
    with pytest.raises(ParseError) as exc_info:
        parse("url4://host(a)/")
    assert exc_info.value.code == "malformed_source"
    assert "remote expression requires a path" in str(exc_info.value)


def test_bare_remote_url_without_path() -> None:
    # §5.2 rule 3.3 — a bare 'url4://hostname' with no path is a plain Url.
    assert parse("url4://host") == Url("url4://host")


def test_unterminated_quote_raises() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse("'unclosed")
    assert exc_info.value.code == "malformed_source"
    assert "unterminated quote" in str(exc_info.value)


def test_trailing_text_after_quoted_value_raises() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse("'quoted' extra")
    assert exc_info.value.code == "malformed_source"
    assert "unexpected text after quoted value" in str(exc_info.value)


def test_unclosed_struct_object_raises() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse("{unclosed")
    assert exc_info.value.code == "malformed_source"
    assert "unclosed '{'" in str(exc_info.value)


def test_trailing_text_after_struct_object_raises() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse("{a:1} extra")
    assert exc_info.value.code == "malformed_source"
    assert "unexpected text after structured object" in str(exc_info.value)


def test_invalid_identity_reference_format_raises() -> None:
    # §5.6.2 — '@' must be followed by \\w+ (a leading '-' doesn't match).
    with pytest.raises(ParseError) as exc_info:
        parse("@-invalid")
    assert exc_info.value.code == "malformed_source"
    assert "invalid reference" in str(exc_info.value)


def test_invalid_collection_path_in_reference_raises() -> None:
    # §5.6.2 — an empty collection segment, or one containing a space.
    for text in ("@name/", "@name/a b"):
        with pytest.raises(ParseError) as exc_info:
            parse(text)
        assert exc_info.value.code == "malformed_source"
        assert "invalid identity reference" in str(exc_info.value)


def test_invalid_varref_segment_falls_back_to_bare_text() -> None:
    # §8 rule 17b — a '.' path segment that doesn't match an identifier ends
    # the varref scan without fully consuming the token, so the whole thing
    # is reparsed as bare text rather than a VarRef.
    assert parse("$var.123") == Text("$var.123")


def test_bare_value_with_quoted_substring() -> None:
    # §7.2 — a quoted run inside bare text is skipped over as a unit.
    assert parse("text'quoted'more") == Text("text'quoted'more")


def test_uri_shaped_bare_value_unclosed_paren_raises() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse("s3://bucket/(unclosed")
    assert exc_info.value.code == "malformed_source"
    assert "unclosed '('" in str(exc_info.value)


def test_non_uri_bare_value_unmatched_paren_raises() -> None:
    # In plain text a paren is structural and must be quoted (spec §7.2).
    with pytest.raises(ParseError) as exc_info:
        parse("hello(unmatched")
    assert exc_info.value.code == "malformed_source"
    assert "unexpected '(' in bare value" in str(exc_info.value)


def test_varref_head_mismatch_falls_back_to_bare_text() -> None:
    # A lone '$' (or '$' followed by a non-identifier, non-digit character)
    # doesn't match the varref head pattern at all, so it stays bare text.
    assert parse("$") == Text("$")
    assert parse("$!bad") == Text("$!bad")


def test_quoted_segment_skipped_when_scanning_relative_expression() -> None:
    # A quoted query-param value containing '(' must not be mistaken for the
    # 'q=(' expression opener while scanning for it.
    node = parse("/x?a='(y)'&q=(ctx)!go")
    # url4 2.0 (P3): a bare one-word intent is a named job.
    assert node == RelExpr(
        path="/x",
        context="ctx",
        intent=NamedJob(value="go"),
        params=(("a", "'(y)'"),),
    )
