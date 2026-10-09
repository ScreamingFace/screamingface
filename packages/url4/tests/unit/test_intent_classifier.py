"""The intent classifier and the code-pointer query-tail reader (PRD §2.5, C6; rows 1, 2, 4).

# FEATURE: RDS code pointer (url4 2.0)
#
# STORY: as a url4 author, the form of my intent decides how it runs. A quoted
# intent is a prompt, a `/path` or `url4://` intent is a code pointer, a
# nested expression stays computed, and any other scheme is refused.
#
# INVARIANT: the classifier reads the ABNF production the atom's text matches.
# The node type alone does not decide it, because `intent_atom` also puts
# relative and remote EXPRESSIONS in `RelUrl` and `Url`.
"""

from __future__ import annotations

import pytest

from url4.core._annotations import read_query_tail
from url4.core.errors import ErrorCode, ParseError
from url4.core.grammar import intent_atom
from url4.core.intent import CodePointer, IntentClass, IntentMode, classify_intent


def _classify(text: str) -> IntentClass:
    return classify_intent(intent_atom(text))


# --- row 1: the §2.5 classification table ------------------------------------------


@pytest.mark.parametrize(
    ("text", "mode"),
    [
        ("'go'", IntentMode.LLM),
        ("summarize", IntentMode.LLM),
        ("(a)!'go'", IntentMode.COMPUTED),
        ("/p(c)!x", IntentMode.LEGACY),
        ("/p?q=(c)!x", IntentMode.LEGACY),
        ("url4://n/p(c)!x", IntentMode.LEGACY),
        ("/reduce()", IntentMode.LEGACY),
        ("https://x/y", IntentMode.UNSUPPORTED),
        ("http://x", IntentMode.UNSUPPORTED),
        ("s3://b/k", IntentMode.UNSUPPORTED),
    ],
)
def test_intent_mode_follows_the_abnf_production(text: str, mode: IntentMode) -> None:
    assert _classify(text).mode is mode


def test_relative_uri_is_a_code_pointer_on_the_current_node() -> None:
    assert _classify("/instr") == IntentClass(
        IntentMode.RDS, CodePointer(path="/instr", query="", params={}, authority=None)
    )


def test_relative_uri_with_query_tail_is_a_code_pointer() -> None:
    result = _classify("/ensemble/combine/v1?reducer=vote&extract=last_number@1")
    assert result == IntentClass(
        IntentMode.RDS,
        CodePointer(
            path="/ensemble/combine/v1",
            query="reducer=vote&extract=last_number@1",
            params={"reducer": "vote", "extract": "last_number@1"},
            authority=None,
        ),
    )


def test_url4_uri_is_a_code_pointer_on_the_remote_node() -> None:
    result = _classify("url4://scorer.example/score/v1?k=2")
    assert result == IntentClass(
        IntentMode.RDS,
        CodePointer(
            path="/score/v1",
            query="k=2",
            params={"k": "2"},
            authority="scorer.example",
        ),
    )


# --- row 2: a query outside query-tail is refused at compile time (E8) -------------


@pytest.mark.parametrize("text", ["/p?x=1,2", "/p?q=hello", "/p?a=1&a=2"])
def test_query_outside_query_tail_is_malformed(text: str) -> None:
    with pytest.raises(ParseError) as err:
        _classify(text)
    assert err.value.code == ErrorCode.MALFORMED_SOURCE


# --- row 4: the query-tail reader (C6) ---------------------------------------------


def test_reader_keeps_at_and_plus_literal() -> None:
    assert read_query_tail("extract=last_number@1&a=x+y") == {
        "extract": "last_number@1",
        "a": "x+y",
    }


def test_reader_keeps_a_plus_in_a_key() -> None:
    assert read_query_tail("a+b=1") == {"a+b": "1"}


def test_reader_decodes_percent_escapes_once() -> None:
    assert read_query_tail("who=%40home&n=1%2B2") == {"who": "@home", "n": "1+2"}


def test_reader_gives_a_flag_the_empty_value() -> None:
    assert read_query_tail("stream&a=1") == {"stream": "", "a": "1"}


def test_reader_keeps_the_order_of_the_query() -> None:
    assert list(read_query_tail("b=1&a=2")) == ["b", "a"]


def test_reader_skips_empty_segments() -> None:
    assert read_query_tail("a=1&&b=2") == {"a": "1", "b": "2"}


def test_reader_of_empty_input_is_empty() -> None:
    assert read_query_tail("") == {}


@pytest.mark.parametrize(
    ("query", "name"),
    [
        ("q=(x)", "q"),
        ("q", "q"),
        ("a=1&a=2", "a"),
        ("x=1,2", "x"),
        ("x=%2C", "x"),
        ("a%3Db=1", "a=b"),
        ("=1", ""),
        ("n=caf%C3%A9", "n"),
    ],
)
def test_reader_refuses_and_names_the_key(query: str, name: str) -> None:
    with pytest.raises(ParseError) as err:
        read_query_tail(query)
    assert err.value.code == ErrorCode.MALFORMED_SOURCE
    assert repr(name) in str(err.value)


@pytest.mark.parametrize("text", ["url4://n(c)/p", "url4:///p", "url4://n?x=1/p"])
def test_url4_uri_without_a_plain_authority_is_legacy(text: str) -> None:
    # INVARIANT: a `(`, `?`, `#` or `'` in the authority, or no authority, is not a
    # remote reference, so 2.0 leaves the intent as it was (LEGACY), never RDS.
    assert classify_intent(intent_atom(text)).mode is IntentMode.LEGACY
