"""Intent classification (contracts C1) and the code-pointer reader (C7).

STORY: as an expression author, the form of my intent alone decides whether it is a
prompt, a code pointer or a computed value (Spec B §5.2, §6; overview rule R1).
Lean: ``IntentForm.specMode``, ``v1_act_eq_invokeLocal_iff`` (formal/Url4Rds/Intent.lean).
"""

from __future__ import annotations

from typing import cast

import pytest

from url4.core.errors import ErrorCode, ParseError
from url4.core.intent import (
    CodePointer,
    IntentForm,
    IntentMode,
    classify_intent,
    intent_mode,
    parse_code_pointer,
)
from url4.core.parser import build, intent_atom
from url4.core.render import render

# One case per C1 detection row, plus the C1 traps (TDD row 1).
_FORMS = [
    ("'Pick the best'", IntentForm.QUOTED),
    ("(c, d)!'agg'", IntentForm.EXPRESSION),
    ("/p(c)!x", IntentForm.EXPRESSION),
    ("/p?q=(c)!x", IntentForm.EXPRESSION),
    ("/p?t=1&q=(c)!x", IntentForm.EXPRESSION),
    ("/claude?t=90&q=(y)!'go'", IntentForm.EXPRESSION),
    ("url4://n/p(c)!x", IntentForm.EXPRESSION),
    ("url4://n/p?t=1&q=(c)!x", IntentForm.EXPRESSION),
    ("/api?q=hi", IntentForm.RELATIVE_URI),
    ("/p?x=1&y=2", IntentForm.RELATIVE_URI),
    ("/ensemble/combine/v1?reducer=vote&extract=last_number@1", IntentForm.RELATIVE_URI),
    ("/score/v$v", IntentForm.RELATIVE_URI),
    ("/reduce()", IntentForm.RELATIVE_URI),  # no `!` tail: not an expression (C1 note)
    ("url4://n/instr", IntentForm.URL4_REFERENCE),
    ("url4://n", IntentForm.URL4_REFERENCE),
    ("https://a/score.py", IntentForm.ABSOLUTE_URI),
    ("s3://bucket/key", IntentForm.ABSOLUTE_URI),
    ("{k: 'v'}", IntentForm.STRUCT_OBJECT),
    ("@", IntentForm.SELF_REF),
    ("@alice", IntentForm.IDENTITY_REF),
    ("$name", IntentForm.VARIABLE_REF),
    ("$2", IntentForm.VARIABLE_REF),
    ("$cfg.k", IntentForm.VARIABLE_REF),
    ("$rows*(x)!'R'", IntentForm.EXPRESSION),
    ("rows*()!x", IntentForm.EXPRESSION),
    ("score_v1", IntentForm.BARE_TOKEN),
    ("summarize this", IntentForm.BARE_TOKEN),
]


@pytest.mark.parametrize(("text", "form"), _FORMS)
def test_classify_intent_names_the_c1_form(text: str, form: IntentForm) -> None:
    assert classify_intent(text) == form


def test_classify_intent_ignores_surrounding_whitespace() -> None:
    assert classify_intent("  /code  ") == IntentForm.RELATIVE_URI


def test_classify_intent_raises_the_parsers_refusal() -> None:
    # A chained intent is refused by the grammar; the classifier never invents a form.
    with pytest.raises(ParseError):
        classify_intent("a!b")


_SPEC_MODE = {
    IntentForm.QUOTED: IntentMode.LLM,
    IntentForm.RELATIVE_URI: IntentMode.RDS,
    IntentForm.URL4_REFERENCE: IntentMode.RDS,
    IntentForm.ABSOLUTE_URI: IntentMode.RDS,
    IntentForm.BARE_TOKEN: IntentMode.RDS,
    IntentForm.EXPRESSION: IntentMode.COMPUTED,
    IntentForm.VARIABLE_REF: IntentMode.COMPUTED,
    IntentForm.SELF_REF: IntentMode.COMPUTED,
    IntentForm.IDENTITY_REF: IntentMode.COMPUTED,
    IntentForm.STRUCT_OBJECT: IntentMode.COMPUTED,
}


def test_intent_mode_is_the_spec_b_table_for_every_form() -> None:
    # INVARIANT (TDD row 2): the mirror of the Lean `IntentForm.specMode`, total.
    assert {form: intent_mode(form) for form in IntentForm} == _SPEC_MODE


@pytest.mark.parametrize(
    "text",
    ["/p(c)!x", "/p?q=(c)!x", "/p?t=1&q=(c)!x", "/w?q=($1)!'Write'", "/p(c)!(d)!'e'"],
)
def test_relative_expression_intent_parses_as_a_relexpr(text: str) -> None:
    # B §5.2 rules 2.1/2.2: the grammar's own source reading (C1, TDD row 3).
    assert type(intent_atom(text)).__name__ == "RelExpr"


@pytest.mark.parametrize(
    "text",
    [
        "(a)!/p(c)!x",
        "(a)!/p?q=(c)!x",
        "(a)!/p?t=1&q=(c)!x",
        "(a)!/api?q=hi",
        "(a)!/p?x=1&y=2",
        "(a)!/reduce()",
        "(a)!rows*()!x",
        "((x='hi')!'S')!/w?q=($1)!'Write'",
    ],
)
def test_every_trap_round_trips(text: str) -> None:
    # render stays in lockstep with intent_atom (TDD row 3).
    tree = build(text)
    assert build(render(tree)) == tree


# --- the code-pointer reader (C1 "the code-pointer text", C7) -------------------------


def test_parse_code_pointer_splits_path_and_query_tail() -> None:
    pointer = parse_code_pointer("/combine?reducer=vote&extract=last_number@1&sep=a+b&dry")
    assert pointer == CodePointer(
        "/combine", {"reducer": "vote", "extract": "last_number@1", "sep": "a+b", "dry": ""}
    )
    assert pointer.is_static


def test_parse_code_pointer_keeps_dollar_references_in_the_path() -> None:
    pointer = parse_code_pointer("/score/v$v")
    assert pointer.path == "/score/v$v"
    assert pointer.params == {}
    assert not pointer.is_static


def test_parse_code_pointer_params_are_read_only() -> None:
    pointer = parse_code_pointer("/c?a=1")
    with pytest.raises(TypeError):
        cast("dict[str, str]", pointer.params)["a"] = "2"


@pytest.mark.parametrize(
    "text",
    [
        "/p?x=1,2",  # `,` is not in query-tail (E8)
        "/p?x=%40",  # no second percent-decode (E8)
        "/p?a=1&a=2",  # duplicate key (Q8)
        "/reduce()",  # `(` is not a path-segment character
        "/",  # an empty segment
    ],
)
def test_parse_code_pointer_refuses_with_malformed_source(text: str) -> None:
    with pytest.raises(ParseError) as info:
        parse_code_pointer(text)
    assert info.value.code == ErrorCode.MALFORMED_SOURCE
