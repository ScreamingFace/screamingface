"""The depth-tracking scanner primitives and the sub-request wire codec."""

from __future__ import annotations

import pytest

from url4.core._scan import (
    balanced_body,
    balanced_braces,
    find_top_level,
    iter_non_string_chars,
    iter_top_level,
    skip_quoted,
    split_query_segments,
    split_top_level,
)
from url4.core.errors import ParseError
from url4.wire.subrequest import (
    decode_subrequest,
    encode_subrequest,
    extract_expression_params,
)


def _visible(expr: str) -> str:
    return "".join(ch for _, ch in iter_top_level(expr))


# -- skip_quoted ----------------------------------------------------------------


def test_skip_quoted_simple_run() -> None:
    assert skip_quoted("'ab'c", 0) == 4


def test_skip_quoted_empty_run() -> None:
    assert skip_quoted("''x", 0) == 2


def test_skip_quoted_escaped_quote() -> None:
    assert skip_quoted(r"'a\'b'x", 0) == 6


def test_skip_quoted_escaped_backslash() -> None:
    # The escaped backslash must not hide the real closing quote after it.
    assert skip_quoted(r"'a\\'x", 0) == 5


def test_skip_quoted_unterminated_returns_next_index() -> None:
    assert skip_quoted("'abc", 0) == 1


def test_skip_quoted_trailing_backslash_is_unterminated() -> None:
    assert skip_quoted("'ab\\", 0) == 1


# -- iter_top_level --------------------------------------------------------------


def test_parens_hide_contents() -> None:
    assert _visible("a(b,c)d") == "ad"


def test_braces_hide_contents() -> None:
    assert _visible("x{a: 1, b: 2}y") == "xy"


def test_quotes_hide_contents_and_delimiters() -> None:
    assert _visible("a'b,c'd") == "ad"


def test_quoted_structural_characters_are_hidden() -> None:
    assert _visible("'(!;,{'x") == "x"


def test_escaped_quote_does_not_end_the_run() -> None:
    assert _visible(r"'a\'b'z") == "z"


def test_unterminated_quote_is_a_literal() -> None:
    assert _visible("a'bc") == "a'bc"


def test_stray_closer_clamps_depth_at_zero() -> None:
    # Malformed input: the stray ')' is swallowed as structural, but scanning
    # continues at depth 0 instead of hiding the rest of the string.
    assert _visible("a)b") == "ab"


def test_indices_point_into_the_original_string() -> None:
    assert list(iter_top_level("x(y)z")) == [(0, "x"), (4, "z")]


# -- balanced_body ---------------------------------------------------------------


def test_balanced_body_nested() -> None:
    assert balanced_body("(a(b)c)!x", 1) == "a(b)c"


def test_balanced_body_quoted_paren_does_not_desync() -> None:
    assert balanced_body("(a')'b)!x", 1) == "a')'b"


def test_balanced_body_unterminated_quote_is_literal() -> None:
    assert balanced_body("(a'b)", 1) == "a'b"


def test_balanced_body_unbalanced_returns_none() -> None:
    assert balanced_body("(abc", 1) is None


# -- find_top_level / split_top_level ---------------------------------------------


def test_find_top_level_hit() -> None:
    assert find_top_level("a!b", "!") == 1


def test_find_top_level_skips_nested() -> None:
    assert find_top_level("(a!b)", "!") is None


def test_find_top_level_skips_quoted() -> None:
    assert find_top_level("'a!'!x", "!") == 4


def test_split_top_level_respects_all_nesting() -> None:
    assert split_top_level("a, (b,c), 'd,e', {f: 1, g: 2}", ",") == [
        "a",
        "(b,c)",
        "'d,e'",
        "{f: 1, g: 2}",
    ]


def test_split_top_level_empty_input() -> None:
    assert split_top_level("", ",") == []
    assert split_top_level("   ", ",") == []


# -- iter_non_string_chars -------------------------------------------------------


def _visible_non_string(text: str) -> str:
    return "".join(ch for _, ch in iter_non_string_chars(text))


def test_non_string_chars_skip_terminated_string() -> None:
    assert _visible_non_string('a"x{y}z"b') == "ab"


def test_non_string_chars_honor_escaped_quote() -> None:
    assert _visible_non_string(r'a"x\"{y"b') == "ab"


def test_non_string_chars_unterminated_quote_is_literal() -> None:
    # No real string exists, so the quote is yielded and scanning continues.
    assert _visible_non_string('a"x{y') == 'a"x{y'


# -- balanced_braces -------------------------------------------------------------


def test_balanced_braces_nested() -> None:
    assert balanced_braces("{a: {b: 1}}tail", 0) == 11


def test_balanced_braces_quoted_brace_does_not_desync() -> None:
    assert balanced_braces("{a: '}'}x", 0) == 8


def test_balanced_braces_unbalanced_returns_none() -> None:
    assert balanced_braces("{a: 1", 0) is None


# -- split_query_segments --------------------------------------------------------


def test_split_query_segments_respects_depth_and_quotes() -> None:
    assert split_query_segments("a=1&q=(x&y)&b=2") == ["a=1", "q=(x&y)", "b=2"]
    assert split_query_segments("q=(x)!'a & b'") == ["q=(x)!'a & b'"]


def test_split_query_segments_empty_input() -> None:
    assert split_query_segments("") == []


# -- encode_subrequest / decode_subrequest -----------------------------------------


def test_encode_escapes_spaces() -> None:
    assert encode_subrequest("/p", "a b", "c d") == "/p?q=(a%20b)!c%20d"


def test_encode_escapes_quotes_and_round_trips() -> None:
    # A raw quote in the payload would let the decoder's quote-aware balanced
    # scan skip the structural ')'; it must ride the wire as %27.
    target = encode_subrequest("/p", "it's", "don't")
    assert "'" not in target
    assert decode_subrequest(target.partition("?q=")[2]) == ("it's", "don't")


def test_encode_params_precede_q() -> None:
    target = encode_subrequest("/claude", "x", "go", params=[("t", "90"), ("quorum", "2")])
    assert target == "/claude?t=90&quorum=2&q=(x)!go"


def test_encode_decode_round_trips_wire_unsafe_payload() -> None:
    target = encode_subrequest("/r", "a (stray & multi\nline", "do it! now")
    assert decode_subrequest(target.partition("?q=")[2]) == (
        "a (stray & multi\nline",
        "do it! now",
    )


# -- extract_expression_params ------------------------------------------------------


def test_extract_splits_on_depth_zero_ampersand_only() -> None:
    params, q = extract_expression_params("delivery=sync&q=(https://api.com/s?p=1&limit=2)!'Sum'")
    assert params == {"delivery": "sync"}
    assert q == "(https://api.com/s?p=1&limit=2)!'Sum'"


def test_extract_q_value_ends_at_depth_zero_ampersand() -> None:
    # The depth-0 boundary is still detected — but `q=` is last (`OME-507`),
    # so the segment beyond it is an error rather than another param.
    with pytest.raises(ParseError, match="last"):
        extract_expression_params("q=(a)!b&meta=full")


def test_extract_processor_value_stays_raw() -> None:
    params, q = extract_expression_params(
        "processor=(url4://reg.ai(@)!'List')!'Select'&q=(@)!'Sum'"
    )
    assert params["processor"] == "(url4://reg.ai(@)!'List')!'Select'"
    assert q == "(@)!'Sum'"


def test_extract_percent_decodes_plain_params_but_not_q() -> None:
    params, q = extract_expression_params("cb=https%3A%2F%2Fx&q=(a%20b)!go")
    assert params == {"cb": "https://x"}
    assert q == "(a%20b)!go"  # decoding the q payload is decode_subrequest's job


def test_extract_flag_param_and_missing_q() -> None:
    params, q = extract_expression_params("stream&a=1")
    assert params == {"stream": "", "a": "1"}
    assert q is None


def test_extract_quoted_ampersand_inside_q() -> None:
    # A QUOTED "&" is content, never a parameter boundary — so this q value
    # runs to the end and is accepted (contrast the depth-0 case above).
    params, q = extract_expression_params("q=(x)!'a & b'")
    assert q == "(x)!'a & b'"
    assert params == {}
