"""Wire-codec laws (spec §3.4 / package spec §8.3) checked against the REAL codec.

L1  raw round trip      decode_subrequest(encode(ctx, intent).q) == (ctx, intent)
L2  ingress round trip  extract_expression_params + decode_subrequest_http on the
                        encoded query returns exactly (params, ctx, intent)
L3  no smuggling        whatever ctx/intent/param values hold, the split yields
                        exactly the encoder's param keys and ONE q, last
L4  over HTTP           the same through httpx -> ASGI -> Url4Node -> endpoint
L5  convention choice   _fully_encoded never changes the meaning of an input that
                        BOTH conventions can carry (the docstring's "inert" claim)

Each law runs as a hypothesis property; the deterministic witnesses found are
pinned as explicit examples below so the report can cite them.
"""

from __future__ import annotations

import json
from urllib.parse import quote, urlencode

import httpx
import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from url4.core.errors import ParseError
from url4.peer.server import Url4Node
from url4.wire.subrequest import (
    _fully_encoded,
    decode_subrequest,
    decode_subrequest_http,
    encode_subrequest,
    extract_expression_params,
)

SETTINGS = settings(max_examples=600, deadline=None, suppress_health_check=list(HealthCheck))

text = st.text(max_size=12)
# param-key grammar: [A-Za-z0-9._]+, never q/processor (expression-bearing)
keys = st.from_regex(r"[a-z][a-z0-9._]{0,5}", fullmatch=True).filter(
    lambda k: k not in ("q", "processor")
)
plain_values = st.from_regex(r"[A-Za-z0-9.\-_,:/]{1,8}", fullmatch=True)
# the quoted extension: one complete '…' run; inner text with no ' or \ so it is
# a single run by construction
quoted_values = st.text(
    alphabet=st.characters(blacklist_characters="'\\", blacklist_categories=("Cs",)), max_size=6
).map(lambda s: f"'{s}'")
values = st.one_of(plain_values, quoted_values)
params_st = st.dictionaries(keys, values, max_size=3).map(lambda d: list(d.items()))


def _q(url: str) -> str:
    return url.partition("?")[2]


# ---------------------------------------------------------------- L1
@SETTINGS
@given(ctx=text, intent=text)
@example(ctx="", intent="go ")  # trailing NBSP: strip() eats it
@example(ctx="", intent="go\x85")  # trailing NEL (C1, not in _WIRE_UNSAFE)
def test_L1_raw_roundtrip(ctx, intent):
    q = _q(encode_subrequest("/p", ctx, intent)).removeprefix("q=")
    assert decode_subrequest(q) == (ctx, intent)


# ---------------------------------------------------------------- L2 / L3
@SETTINGS
@given(ctx=text, intent=text, params=params_st)
@example(ctx="a", intent="b", params=[("note", "'a+b'")])  # '+' -> ' '
@example(ctx="a", intent="b", params=[("note", "'{'")])  # '{' swallows q=
def test_L2_L3_ingress_roundtrip_and_no_smuggling(ctx, intent, params):
    query = _q(encode_subrequest("/p", ctx, intent, params))
    got_params, raw_q = extract_expression_params(query)
    assert raw_q is not None, f"q= lost: {query!r}"
    assert list(got_params) == [k for k, _ in params], f"param keys changed: {query!r}"
    assert got_params == dict(params), f"param values changed: {query!r}"
    assert decode_subrequest_http(raw_q) == (ctx, intent)


# ---------------------------------------------------------------- L4 (HTTP)
def _echo_app():
    node = Url4Node("echo")

    @node.endpoint("/echo")
    def echo(req):
        return json.dumps([req.context, req.intent, dict(req.params)])

    return node.asgi()


@pytest.fixture(scope="module")
def http():
    return httpx.Client(transport=httpx.ASGITransport(app=_echo_app()), base_url="http://n")


async def _get(url: str):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_echo_app()), base_url="http://n"
    ) as c:
        return await c.get(url)


@SETTINGS
@given(ctx=text, intent=text, params=params_st.map(lambda ps: [(k, v) for k, v in ps if "'" not in v]))
@example(ctx="", intent="go ", params=[])
async def test_L4_raw_convention_over_http(ctx, intent, params):
    url = encode_subrequest("/echo", ctx, intent, params)
    r = await _get(url)
    assert r.status_code == 200, (url, r.text)
    assert json.loads(r.text) == [ctx, intent, dict(params)]


@SETTINGS
@given(
    ctx=st.text(alphabet=st.characters(blacklist_characters="()'", blacklist_categories=("Cs",)), max_size=10),
    intent=st.text(alphabet=st.characters(blacklist_characters="'", blacklist_categories=("Cs",)), max_size=10),
)
async def test_L4_fully_encoded_convention_over_http(ctx, intent):
    # a standard client: httpx encodes the whole value (URLSearchParams-like)
    r = await _get("/echo?" + urlencode({"q": f"({ctx})!{intent}"}))
    assert r.status_code == 200, r.text
    assert json.loads(r.text)[:2] == [ctx, intent]


# ---------------------------------------------------------------- L5 witnesses
def _js_encode_uri_component(s: str) -> str:
    # JavaScript encodeURIComponent leaves A-Z a-z 0-9 - _ . ! ~ * ' ( ) raw
    return quote(s, safe="-_.!~*'()")


@pytest.mark.parametrize(
    ("label", "wire", "author_meant"),
    [
        # form-encoding (URLSearchParams / urlencode) of an intent-only payload with
        # a space and no other escape: '+' is the space, but no '%' -> raw decoder
        ("form-encoded, no %", "summarize+this", ("", "summarize this")),
        # raw convention, author wrote a literal '+', and a %20: classified FULL
        ("raw, literal + and %20", "a+b%20c", ("", "a+b c")),
        # JS encodeURIComponent keeps ( ) ' ! raw -> classified RAW; the raw "'"
        # opens a quote run inside balanced_body and swallows the structural ')'
        ("encodeURIComponent", _js_encode_uri_component("(it's 50% off)!sum up"),
         ("it's 50% off", "sum up")),
        # encodeURIComponent of a context with an UNbalanced content paren
        ("encodeURIComponent unbalanced", _js_encode_uri_component("(a ) b)!go"),
         ("a ) b", "go")),
    ],
)
def test_L5_fully_encoded_misclassification(label, wire, author_meant):
    got = decode_subrequest_http(wire)
    print(f"\n{label}: wire={wire!r} fully_encoded={_fully_encoded(wire)} decoded={got!r}")
    assert got == author_meant


def test_L3_second_q_from_param_value_is_impossible():
    # '&' and '#' in any value are escaped, so no value can open a new segment
    url = encode_subrequest("/p", "x&q=evil", "y&q=(z)!w", [("note", "'&q=(p)!o'")])
    params, q = extract_expression_params(_q(url))
    assert set(params) == {"note"} and decode_subrequest_http(q) == ("x&q=evil", "y&q=(z)!w")


def test_params_after_q_are_refused():
    with pytest.raises(ParseError):
        extract_expression_params("q=(a)!b&tone=formal")
