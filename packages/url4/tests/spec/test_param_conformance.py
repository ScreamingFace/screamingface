"""`OME-507` cycle 3 — `param-key` / `param-value` character classes.

# FEATURE: protocol parameters take the charsets the grammar defines, at every
# site that decodes one.
#
#   param-key          = 1*( ALPHA / DIGIT / "." / "_" )          <- no "-"
#   param-value        = 1*( ALPHA / DIGIT / "." / "-" / "_" / "," / ":" / "/" )
#   nested-param-value = param-value / processor-value
#   expr-param         = param-key "=" param-value / "broadcast"
#
# WHY this waited for `OME-506`: `nested-param-value` admits a
# `processor-value`, which may be a full expression body starting with "(" and
# can NEVER satisfy `param-value`. Validating a nested value therefore needs
# the §27.3 three-way split first. `url4.processor` now owns it, so the rule
# here is simply: expression-bearing keys (`q`, `processor`) are not
# charset-checked — their own owner validates them.
#
# One validator serves all three decode sites (the wire splitter, the nested
# query params inside a rel/remote expression, and the `;` expression chain),
# so the sides cannot disagree the way `OME-501` found them disagreeing.
#
# OWNER DECISION: valueless flag params (`?stream`, `;stream`) are an accepted
# extension and keep parsing — only the charsets are enforced.
"""

from __future__ import annotations

import pytest

from url4.core.errors import ParseError
from url4.core.grammar import parse
from url4.core.nodes import RelExpr
from url4.core.parser import build
from url4.wire.subrequest import extract_expression_params

# --- param-key: no "-" -----------------------------------------------------------


@pytest.mark.parametrize("key", ["we-ird", "a-b", "-lead"])
def test_dashed_param_key_is_rejected_on_the_wire(key: str) -> None:
    with pytest.raises(ParseError, match="param"):
        extract_expression_params(f"{key}=1&q=(a)!'go'")


@pytest.mark.parametrize("key", ["tone", "coord.rounds", "ct_mismatch", "mode2", "a1_b.c"])
def test_legal_param_key_is_accepted_on_the_wire(key: str) -> None:
    params, _q = extract_expression_params(f"{key}=1&q=(a)!'go'")
    assert params[key] == "1"


def test_dashed_param_key_is_rejected_in_a_nested_query() -> None:
    with pytest.raises(ParseError, match="param"):
        parse("/p?we-ird=1&q=(x)!'y'")


def test_dashed_param_key_is_rejected_in_the_expression_chain() -> None:
    with pytest.raises(ParseError, match="param"):
        build("(a)!'go';we-ird=1")


# --- param-value charset ----------------------------------------------------------


@pytest.mark.parametrize("value", ["fo rmal", "a@b", "a(b", "a'b", "a;b", ""])
def test_illegal_param_value_is_rejected_on_the_wire(value: str) -> None:
    with pytest.raises(ParseError, match="param"):
        extract_expression_params(f"tone={value}&q=(a)!'go'")


@pytest.mark.parametrize(
    "value",
    ["formal", "90", "1,2,3", "application/json", "1:3", "https://host/p", "a-b_c.d"],
)
def test_legal_param_value_is_accepted_on_the_wire(value: str) -> None:
    params, _q = extract_expression_params(f"tone={value}&q=(a)!'go'")
    assert params["tone"] == value


def test_illegal_param_value_is_rejected_in_a_nested_query() -> None:
    with pytest.raises(ParseError, match="param"):
        parse("/p?tone=a@b&q=(x)!'y'")


def test_illegal_param_value_is_rejected_in_the_expression_chain() -> None:
    with pytest.raises(ParseError, match="param"):
        build("(a)!'go';tone=a@b")


@pytest.mark.parametrize(
    "text",
    [
        "(a)!'go';quorum=2;triggers=1,2,3;meta=full",
        "(a)!'go';t=60",
        "(/p?t=90&q=(x)!'y')!'go'",
    ],
)
def test_legal_expression_params_still_parse(text: str) -> None:
    assert build(text) is not None


# --- the wire validates the DECODED value (owner decision) ------------------------


def test_percent_encoded_value_is_validated_after_decoding() -> None:
    # `%20` decodes to a space, which `param-value` has no form for — there is
    # no quoting in a param value. A node refuses over HTTP exactly what it
    # refuses in text.
    with pytest.raises(ParseError, match="param"):
        extract_expression_params("tone=very%20formal&q=(a)!'go'")


def test_percent_encoded_legal_value_still_decodes() -> None:
    params, _q = extract_expression_params("cb=https%3A%2F%2Fhost%2Fp&q=(a)!'go'")
    assert params["cb"] == "https://host/p"


# --- expression-bearing keys are NOT charset-checked (§27.3 owns them) ------------


def test_processor_expression_value_is_not_charset_checked() -> None:
    params, _q = extract_expression_params("processor=(p='/gpt4')!'$p'&q=(a)!'go'")
    assert params["processor"] == "(p='/gpt4')!'$p'"


def test_processor_id_and_uri_still_pass() -> None:
    for value in ("gpt4", "url4://node.example/p"):
        params, _q = extract_expression_params(f"processor={value}&q=(a)!'go'")
        assert params["processor"] == value


def test_nested_processor_expression_still_parses() -> None:
    assert parse("/p?processor=(a='/x')!'$a'&q=(y)!'z'") is not None


def test_q_value_is_not_charset_checked() -> None:
    _params, q = extract_expression_params("q=(a, b)!'a prose intent with spaces'")
    assert q == "(a, b)!'a prose intent with spaces'"


# --- valueless flags remain (owner decision) --------------------------------------


def test_flag_param_still_parses_on_the_wire() -> None:
    params, q = extract_expression_params("stream&a=1&q=(x)!'go'")
    assert params == {"stream": "", "a": "1"}
    assert q == "(x)!'go'"


def test_flag_param_still_parses_in_a_nested_query() -> None:
    node = parse("/claude?stream&q=(x)!'go'")
    assert isinstance(node, RelExpr)
    assert ("stream", None) in node.params


def test_flag_param_still_parses_in_the_expression_chain() -> None:
    assert build("(a)!'go';meta=full;stream") is not None


def test_flag_key_is_still_charset_checked() -> None:
    # The key is a `param-key` whether or not a value follows it.
    with pytest.raises(ParseError, match="param"):
        extract_expression_params("we-ird&q=(a)!'go'")
