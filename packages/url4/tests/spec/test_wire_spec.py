"""Spec §3.3 / §7 — HTTP wire concerns: depth-aware expression-bearing
parameter extraction and sub-request encoding."""

from __future__ import annotations

from url4.wire.subrequest import decode_subrequest, encode_subrequest

# --- §3.3.1 expression-bearing parameter extraction --------------------------------


def test_ampersand_inside_parens_stays_in_q() -> None:
    # §3.3.1 — & at depth > 0 is part of the expression, not a param separator
    from url4.wire.subrequest import extract_expression_params

    params, q = extract_expression_params(
        "delivery=sync&q=(https://api.com/s?q=hello&limit=100)!'Summarize'"
    )
    assert params == {"delivery": "sync"}
    assert q == "(https://api.com/s?q=hello&limit=100)!'Summarize'"


def test_nested_canonical_expression_keeps_inner_ampersand() -> None:
    # §3.3.1 second example — nested /claude?t=90&q=... inside q=
    from url4.wire.subrequest import extract_expression_params

    params, q = extract_expression_params("q=(/claude?t=90&q=($data)!'Answer')!'Use $1'")
    assert params == {}
    assert q == "(/claude?t=90&q=($data)!'Answer')!'Use $1'"


def test_depth_zero_ampersand_after_q_is_rejected() -> None:
    # §3.3.1 parsing rule 3 — & at depth 0 outside quotes terminates the value.
    # `OME-507`: what follows is NOT a further param — `q=` closes the query
    # string, so a depth-0 param after it is malformed.
    import pytest

    from url4.core.errors import ParseError
    from url4.wire.subrequest import extract_expression_params

    with pytest.raises(ParseError, match="last"):
        extract_expression_params("q=(x)!go&meta=full")


def test_multiple_protocol_params_before_q() -> None:
    # §3.1 canonical form — protocol params precede q=
    from url4.wire.subrequest import extract_expression_params

    params, q = extract_expression_params("delivery=stream&quorum=2&meta=full&q=(a)!'go'")
    assert params == {"delivery": "stream", "quorum": "2", "meta": "full"}
    assert q == "(a)!'go'"


def test_query_without_q_returns_none() -> None:
    # §3.3.1 — a query string with no expression-bearing parameter
    from url4.wire.subrequest import extract_expression_params

    params, q = extract_expression_params("limit=10&offset=3")
    assert params == {"limit": "10", "offset": "3"}
    assert q is None


# --- §5.4 / §7.3 sub-request encoding -------------------------------------------------


def test_encode_with_protocol_params() -> None:
    # §5.4 canonical form — params appear as ?&-separated parameters before q=
    from url4.wire.subrequest import encode_subrequest as enc

    assert enc("/claude", "ctx", "go", params=(("t", "90"),)) == "/claude?t=90&q=(ctx)!go"


def test_encode_escapes_spaces() -> None:
    # §7.3 — space MUST be encoded on the HTTP wire (contract #16)
    assert encode_subrequest("/p", "a b", "c d") == "/p?q=(a%20b)!c%20d"


def test_decode_round_trips_spaces() -> None:
    # §7.4 — percent-decoding restores the expression text
    assert decode_subrequest("(a%20b)!c%20d") == ("a b", "c d")


def test_encode_decode_round_trip_structural_chars() -> None:
    # §7.4 pipeline — parens/& in content survive the wire
    encoded = encode_subrequest("/reduce", "", 'rows: ["a (1)", "b & c"]')
    _, _, query = encoded.partition("?q=")
    context, intent = decode_subrequest(query)
    assert context == ""
    assert intent == 'rows: ["a (1)", "b & c"]'


def test_extract_then_decode_pipeline() -> None:
    # §7.4 — server pipeline: extract q=, then decode the payload
    from url4.wire.subrequest import extract_expression_params

    params, q = extract_expression_params("t=90&q=(a%20b)!go")
    assert params == {"t": "90"}
    assert q is not None
    assert decode_subrequest(q) == ("a b", "go")


# --- §3.4 dual wire conventions — every grammar head, both conventions (OME-530) ---
#
# INVARIANT: a node accepts over HTTP exactly the expression set it accepts
# in-process — the convention discriminator must classify EVERY grammar-legal
# head, and the raw-convention reassembly must never truncate a legal payload.


def test_fully_encoded_relative_call_head_round_trips() -> None:
    # §3.4 — a standard client (curl --data-urlencode) encodes EVERY head; a
    # fully-encoded relative-call sugar payload (%2F head) must decode to the
    # author's expression, not fall into the raw decoder and come out mangled.
    from urllib.parse import quote

    from url4.wire.subrequest import decode_expression_http

    text = "/opus(hi there)!'answer'"
    assert decode_expression_http(quote(text, safe="")) == text


def test_fully_encoded_canonical_call_head_round_trips() -> None:
    # §3.4 — same for the canonical /path?params&q=… form.
    from urllib.parse import quote

    from url4.wire.subrequest import decode_expression_http

    text = "/judge?t=0.2&q=(a b)!'grade'"
    assert decode_expression_http(quote(text, safe="")) == text


def test_fully_encoded_remote_call_head_round_trips() -> None:
    # §3.4 — and for the url4:// remote form (url4%3A head).
    from urllib.parse import quote

    from url4.wire.subrequest import decode_expression_http

    text = "url4://peer:4404/gpt(x)!'go'"
    assert decode_expression_http(quote(text, safe="")) == text


def test_raw_relative_call_head_is_not_mangled() -> None:
    # §3.4 raw convention — a /path(...)!intent eval payload is a full
    # expression, not a (context)!intent envelope; it must not become ()!text.
    from url4.wire.subrequest import decode_expression_http

    assert decode_expression_http("/opus(hi%20there)!'go'") == "/opus(hi there)!'go'"


def test_raw_paren_collection_iteration_keeps_its_tail() -> None:
    # §5.3 — a raw iteration with a paren-collection head is NOT the envelope
    # shape; the decoder must not truncate `('a','b')*(body)!''` to "('a','b')".
    from url4.wire.subrequest import decode_expression_http

    text = "('a','b')*(/p($item)!'x')!''"
    assert decode_expression_http(text) == text


def test_raw_envelope_still_part_unquotes() -> None:
    # INVARIANT guard: the raw-convention (context)!intent envelope keeps the
    # §7.4 locate-structure-then-unquote-parts pipeline unchanged — with and
    # without an intent tail.
    from url4.wire.subrequest import decode_expression_http

    assert decode_expression_http("(a%26b)!go") == "(a&b)!go"
    assert decode_expression_http("(a%26b)") == "(a&b)"


def test_raw_unbalanced_payload_decodes_whole_for_the_parser() -> None:
    # An unbalanced raw payload is not an envelope; it decodes as one text so
    # the PARSER reports the malformed expression (never silently rewrapped).
    from url4.wire.subrequest import decode_expression_http

    assert decode_expression_http("(a%20b") == "(a b"
