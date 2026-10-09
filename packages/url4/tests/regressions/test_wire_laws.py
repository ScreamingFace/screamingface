"""Regression tests for the wire codec, checked against the real codec (spec §3.4, §7.3).

Laws (hypothesis properties):

L1  raw round trip      decode_subrequest(encode(ctx, intent).q) == (ctx, intent)
L2  ingress round trip  extract_expression_params + decode_subrequest_http on the
                        encoded query returns exactly (params, ctx, intent)
L3  no smuggling        whatever ctx/intent/param values hold, the split yields
                        exactly the encoder's param keys and ONE q, last
L4  over HTTP           the same through httpx -> ASGI -> Url4Node -> endpoint
L5  convention choice   a payload with no raw "(" is decoded the same by both
                        conventions (the "inert" claim of _fully_encoded)

Each law runs as a hypothesis property. Deterministic cases that the laws found
are pinned as explicit tests below.
"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote, urlencode

import httpx
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from url4.core.errors import ParseError
from url4.peer.server import Url4Node
from url4.wire.subrequest import (
    decode_subrequest,
    decode_subrequest_http,
    encode_subrequest,
    extract_expression_params,
)

text = st.text(max_size=12)
# param-key grammar: [A-Za-z0-9._]+, never q/processor (expression-bearing)
keys = st.from_regex(r"[a-z][a-z0-9._]{0,5}", fullmatch=True).filter(
    lambda k: k not in ("q", "processor")
)
plain_values = st.from_regex(r"[A-Za-z0-9.\-_,:/]{1,8}", fullmatch=True)
# a quoted value: one complete '…' run; inner text has no ' or \ so it is a single
# run by construction
quoted_values = st.text(
    alphabet=st.characters(blacklist_characters="'\\", blacklist_categories=("Cs",)), max_size=6
).map(lambda s: f"'{s}'")
values = st.one_of(plain_values, quoted_values)
params_st = st.dictionaries(keys, values, max_size=3).map(lambda d: list(d.items()))


def _q(url: str) -> str:
    return url.partition("?")[2]


def _echo_node() -> Url4Node:
    node = Url4Node("echo")

    @node.endpoint("/echo")
    def echo(req):
        return json.dumps([req.context, req.intent, dict(req.params)])

    return node


async def _get(url: str):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_echo_node().asgi()), base_url="http://n"
    ) as c:
        return await c.get(url)


# ---------------------------------------------------------------- L1
@settings(max_examples=200, deadline=None)
@given(ctx=text, intent=text)
@example(ctx="", intent="go ")  # trailing NBSP is intent text, not framing
@example(ctx="", intent="go\x85")  # trailing NEL (C1, not in _WIRE_UNSAFE)
def test_L1_raw_roundtrip(ctx, intent):
    q = _q(encode_subrequest("/p", ctx, intent)).removeprefix("q=")
    assert decode_subrequest(q) == (ctx, intent)


# ---------------------------------------------------------------- L2 / L3
@settings(max_examples=200, deadline=None)
@given(ctx=text, intent=text, params=params_st)
@example(ctx="a", intent="b", params=[("note", "'a+b'")])  # '+' is kept, not a space
@example(ctx="a", intent="b", params=[("note", "'{'")])  # '{' must not hide q=
def test_L2_L3_ingress_roundtrip_and_no_smuggling(ctx, intent, params):
    query = _q(encode_subrequest("/p", ctx, intent, params))
    got_params, raw_q = extract_expression_params(query)
    assert raw_q is not None, f"q= lost: {query!r}"
    assert list(got_params) == [k for k, _ in params], f"param keys changed: {query!r}"
    assert got_params == dict(params), f"param values changed: {query!r}"
    assert decode_subrequest_http(raw_q) == (ctx, intent)


# ---------------------------------------------------------------- L4 (HTTP)
# WHY sync + asyncio.run: hypothesis does not drive `async def` properties; the
# httpx ASGI client is async, so each example runs its own loop.
@settings(max_examples=200, deadline=None)
@given(ctx=text, intent=text, params=params_st)
@example(ctx="", intent="go ", params=[])
def test_L4_raw_convention_over_http(ctx, intent, params):
    url = encode_subrequest("/echo", ctx, intent, params)
    r = asyncio.run(_get(url))
    assert r.status_code == 200, (url, r.text)
    assert json.loads(r.text) == [ctx, intent, dict(params)]


@settings(max_examples=200, deadline=None)
@given(
    ctx=st.text(
        alphabet=st.characters(blacklist_characters="()'", blacklist_categories=("Cs",)),
        max_size=10,
    ),
    intent=st.text(
        alphabet=st.characters(blacklist_characters="'", blacklist_categories=("Cs",)), max_size=10
    ),
)
def test_L4_fully_encoded_convention_over_http(ctx, intent):
    # a standard client: httpx encodes the whole value (URLSearchParams-like)
    r = asyncio.run(_get("/echo?" + urlencode({"q": f"({ctx})!{intent}"})))
    assert r.status_code == 200, r.text
    assert json.loads(r.text)[:2] == [ctx, intent]


# ---------------------------------------------------------------- L5 classification
def _js_encode_uri_component(s: str) -> str:
    # JavaScript encodeURIComponent leaves A-Z a-z 0-9 - _ . ! ~ * ' ( ) raw
    return quote(s, safe="-_.!~*'()")


@pytest.mark.parametrize(
    ("wire", "expected"),
    [
        # form-encoded intent with a space and no other escape: '+' is the space
        ("summarize+this", ("", "summarize this")),
        # '+' is a space in every HTTP q= payload, even beside a %20
        ("a+b%20c", ("", "a b c")),
        # encodeURIComponent keeps ( ) ' ! raw -> no raw "(" before the envelope, so
        # the payload is fully-encoded; the raw "'" is an unterminated quote run
        (
            _js_encode_uri_component("(it's 50% off)!sum up"),
            ("it's 50% off", "sum up"),
        ),
    ],
)
def test_L5_fully_encoded_classification(wire, expected):
    assert decode_subrequest_http(wire) == expected


def test_L5_unbalanced_content_paren_is_refused():
    # encodeURIComponent of a context with an UNbalanced content paren. Spec B §7.2:
    # content parens must be balanced or quoted, so this is out-of-spec input and
    # MUST fail loudly instead of decoding to a silent partial context.
    with pytest.raises(ParseError):
        decode_subrequest_http(_js_encode_uri_component("(a ) b)!go"))


def test_L3_second_q_from_param_value_is_impossible():
    # '&' and '#' in any value are escaped, so no value can open a new segment
    url = encode_subrequest("/p", "x&q=evil", "y&q=(z)!w", [("note", "'&q=(p)!o'")])
    params, q = extract_expression_params(_q(url))
    assert q is not None
    assert set(params) == {"note"} and decode_subrequest_http(q) == ("x&q=evil", "y&q=(z)!w")


def test_params_after_q_are_refused():
    with pytest.raises(ParseError):
        extract_expression_params("q=(a)!b&tone=formal")


# ---------------------------------------------------------------- pinned cases


def test_brace_in_quoted_param_does_not_hide_q():
    # spec §3.4: a '{' in a quoted param value must not hide q= from the depth scan
    result = asyncio.run(_echo_node().evaluate("(r:0:/echo?note='{'&q=(x)!'go')!'$r'"))
    assert json.loads(result.text)[:2] == ["x", "go"]


def test_plus_in_quoted_param_arrives_as_plus():
    # spec §7.3: '+' is a space on the wire, so a literal '+' travels as %2B
    r = asyncio.run(_get(encode_subrequest("/echo", "", "go", [("note", "'a+b'")])))
    assert r.status_code == 200, r.text
    assert json.loads(r.text)[2] == {"note": "'a+b'"}


def test_trailing_unicode_space_in_intent_is_kept():
    # only ASCII whitespace is framing; U+3000 at the end of an intent is intent text
    assert decode_subrequest("(c)!go　") == ("c", "go　")
    wire = _q(encode_subrequest("/p", "c", "go　")).removeprefix("q=")
    assert decode_subrequest(wire) == ("c", "go　")


def test_plus_in_paren_free_payload_is_a_space():
    # spec §3.2 / §7.3: '+' decodes to a space on the HTTP wire
    assert decode_subrequest_http("summarize+this") == ("", "summarize this")


def test_raw_convention_plus_is_a_space():
    # wire behaviour change: a raw '+' from a url4 <= 1.5.1 encoder decodes as a
    # space (spec §3.2). Current encoders send %2B for a literal '+'.
    assert decode_subrequest_http("(a+b)!c") == ("a b", "c")


def test_unclosed_context_is_refused():
    # a context whose parens never close is malformed, not a partial context
    with pytest.raises(ParseError):
        decode_subrequest_http("(a%20b")
    with pytest.raises(ParseError):
        decode_subrequest("(a%20b")
    with pytest.raises(ParseError):
        decode_subrequest_http("%28a%20b")


def test_unicode_space_after_param_value_is_refused():
    # a param value keeps trailing U+3000 as value text, and that is not a valid
    # param-value, so the request is refused instead of silently trimmed
    with pytest.raises(ParseError):
        extract_expression_params("note=x　&q=(c)!go")
    r = asyncio.run(_get("/echo?note=x　&q=(c)!go"))
    assert r.status_code == 400, r.text
    with pytest.raises(ParseError):
        asyncio.run(_echo_node().evaluate("/echo?note=x　&q=(c)!go"))
