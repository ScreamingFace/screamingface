"""Node SDK tests — Url4Node registries, dispatch, holdings, and the ASGI shim.

STORY: as a data owner I stand up a url4 node with decorator-registered intent
processors and holdings, evaluate expressions in-process, and serve the same
dispatch over HTTP GET (url4-engine doctrine N1: the expression is the address,
GET is the transactional verb).

INVARIANT: a Url4Node IS an IOLayer — in-process evaluation, engine-internal
sub-request dispatch, and the ASGI shim all flow through the same fetch().
"""

from __future__ import annotations

import json

import httpx
import pytest

from url4 import StaticIOLayer
from url4.core.builders import src
from url4.core.errors import ResolutionError, Url4Error
from url4.io.http import HttpIOLayer
from url4.io.layer import FetchRequest
from url4.peer.client import Client
from url4.peer.server import Request, Url4Node

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def wire() -> list[Request]:
    return []


@pytest.fixture()
def node(wire) -> Url4Node:
    n = Url4Node(
        name="testnode",
        outbound=StaticIOLayer(fetch_map={"https://x": "ARTICLE"}),
    )

    @n.endpoint("/claude")
    async def claude(request: Request) -> str:
        wire.append(request)
        return f"CLAUDE({request.intent})"

    @n.holdings()
    def own(collection: str | None) -> str:
        return f"SELF[{collection}]"

    @n.identity("emily")
    def emily(collection: str | None) -> str:
        if collection == "secret":
            raise ResolutionError(
                "emily denies access", code="identity_access_denied", permanent=True
            )
        return f"EMILY[{collection}]"

    n.data("/api/rows", '["alpha", "beta"]')
    return n


async def test_registration_sugar_forms():
    n = Url4Node("sugar")

    @n.holdings  # bare decorator, zero-arg handler
    def own() -> str:
        return "GENERAL"

    @n.holdings("science")  # per-shelf, still zero-arg
    def science() -> str:
        return "SCIENCE"

    @n.identity("zoe")  # zero-arg identity handler
    def zoe() -> str:
        return "ZOE"

    @n.data("/api/now")  # decorator data route
    def now() -> str:
        return "NOW"

    assert await n.fetch_holdings(None, None) == "GENERAL"
    assert await n.fetch_holdings(None, "science") == "SCIENCE"
    assert await n.fetch_holdings("zoe", "anything") == "ZOE"
    assert await n.fetch("/api/now", relative=True) == "NOW"
    assert "sugar" in repr(n)


# --- in-process evaluation (the node as its own execution engine) ----------------------


async def test_evaluate_resolves_outbound_sources(node):
    res = await node.evaluate("(a=https://x)!'Summarize $a'")
    assert "ARTICLE" in res.text
    assert res.request == "(a=https://x)!'Summarize $a'"


async def test_data_route_media_type_drives_collection_iteration():
    # server.py Url4Node.fetch_ex(): a data route may declare its Content-Type,
    # which the node reports so a node-hosted single-row NDJSON collection parses
    # by its declared type (spec §5.3.7) and iterates, instead of being sniffed
    # and rejected as a JSON object.
    n = Url4Node("nd")
    n.data("/api/nd", '{"q": "2+2"}', media_type="application/x-ndjson")
    assert (await n.fetch_ex(FetchRequest("/api/nd", relative=True))).media_type == (
        "application/x-ndjson"
    )
    # The single NDJSON row iterates; CollectNode embeds the JSON object row
    # structurally (spec §5.3.8).
    result = (await n.evaluate("/api/nd*(r:0:$item)!'$r'")).text
    assert json.loads(result) == [{"q": "2+2"}]


async def test_empty_string_data_provider_is_served():
    # url4.peer/_dispatch.py dispatch(): a legitimately falsy provider ("") is
    # skipped as if the route were missing.
    n = Url4Node("empty")
    n.data("/api/empty", "")
    assert await n.fetch("/api/empty", relative=True) == ""


async def test_data_decorator_route_reports_its_declared_media_type():
    # F10: the merged _data map carries the media type with the provider, so the
    # decorator form reports it exactly like the direct form.
    n = Url4Node("deco")

    @n.data("/api/deco", media_type="application/json")
    def deco() -> str:
        return '["x"]'

    result = await n.fetch_ex(FetchRequest("/api/deco", relative=True))
    assert result.media_type == "application/json"
    assert await n.fetch("/api/deco", relative=True) == '["x"]'


async def test_unapplied_data_decorator_leaves_no_route_or_media_type():
    # F10: a declared-but-unapplied decorator must not half-register a route
    # (the old parallel map could keep a stale media type for it).
    n = Url4Node("stale")
    register = n.data("/api/none", media_type="application/json")
    assert callable(register)
    assert n._data == {}
    with pytest.raises(Url4Error) as err:
        await n.fetch("/api/none", relative=True)
    assert err.value.code == "endpoint_not_found"


async def test_node_injected_outbound_is_never_closed(node):
    # The `node` fixture injects a StaticIOLayer; the node owns nothing to close.
    await node.aclose()  # no-op; must not raise
    assert await node.fetch("/api/rows", relative=True) == '["alpha", "beta"]'


async def test_node_closes_its_owned_outbound_on_exit(monkeypatch):
    closed: list[bool] = []

    class Tracked(StaticIOLayer):
        async def aclose(self) -> None:
            closed.append(True)

    monkeypatch.setattr("url4.peer._owned._http_io", Tracked)
    async with Url4Node("own") as node:
        node._outbound_io()  # force the owned adapter into existence
        assert closed == []
    assert closed == [True]


async def test_evaluate_env_seeds_scope(node):
    res = await node.evaluate("()!'Hello $who'", env={"who": "world"})
    assert "world" in res.text


async def test_self_holdings_and_identity_resolution(node):
    assert "SELF[None]" in (await node.evaluate("(@)!'science'")).text
    assert "EMILY[notes]" in (await node.evaluate("(@emily/notes)!'thoughts'")).text


async def test_unknown_identity_fails_permanently(node):
    with pytest.raises(Url4Error) as err:
        await node.evaluate("(@bob)!'x'")
    assert err.value.code == "unknown_identity"
    assert err.value.permanent is True


async def test_identity_handler_can_deny_access(node):
    with pytest.raises(Url4Error) as err:
        await node.evaluate("(@emily/secret)!'x'")
    assert err.value.code == "identity_access_denied"


async def test_endpoint_dispatch_from_engine_internals(node, wire):
    # A relative expression source dispatches to the registered endpoint with
    # the wire-decoded (context, intent) pair — context is opaque data.
    res = await node.evaluate("(r:0:/claude(https://x)!'Go')!'$r'")
    assert res.text.startswith("CLAUDE(")
    assert wire[0].path == "/claude"
    # `OME-535`: the caller resolves the context source-list — the endpoint
    # receives the FETCHED content as opaque data, never the URL text.
    assert wire[0].context == "ARTICLE"
    assert wire[0].intent == "Go"


async def test_default_processor_receives_local_intents(node, wire):
    # A flat fan-out+reduce dispatches its reducer to the default processor.
    await node.evaluate("(/claude(https://x)!'A', /claude(https://x)!'B')!'Merge'")
    assert any("Merge" in request.intent for request in wire)


async def test_node_as_client_io(node):
    async with Client(node) as client:
        res = await client.query(src("https://x", name="a"), intent="Summarize $a")
    assert "ARTICLE" in res.text


# --- the eval path (protocol surface) -----------------------------------------------------


async def test_eval_path_evaluates_full_expressions(node):
    body = await node.fetch("/v1?q=(a=https://x)!'Summarize $a'", relative=True)
    assert "ARTICLE" in body


async def test_eval_path_reattaches_protocol_params(node):
    # ;broadcast has spec-equivalent standing as a protocol param (§6.1.1)
    body = await node.fetch("/v1?broadcast&q=('a', 'b')!'x'", relative=True)
    assert isinstance(json.loads(body), list)


async def test_eval_path_accepts_standard_encoded_call_expression(node, wire):
    # WHY (OME-530): curl --data-urlencode / browsers percent-encode EVERY
    # head. A fully-encoded bare relative call (%2F head) must evaluate
    # exactly as its in-process `evaluate()` twin — not mis-decode into a
    # bogus endpoint_not_found.
    from urllib.parse import quote

    q = quote("/claude(https://x)!'Go'", safe="")
    body = await node.fetch(f"/v1?q={q}", relative=True)
    assert body.startswith("CLAUDE(")
    assert wire[0].context == "ARTICLE"  # `OME-535`: resolved caller-side
    assert wire[0].intent == "Go"


async def test_eval_path_accepts_standard_encoded_group(node):
    # Control: the group head (%28) stays on the fully-encoded path, spaces
    # and $refs intact end-to-end.
    from urllib.parse import quote

    q = quote("(a=https://x)!'Summarize $a'", safe="")
    body = await node.fetch(f"/v1?q={q}", relative=True)
    assert "ARTICLE" in body


async def test_unknown_path_fails(node):
    with pytest.raises(Url4Error) as err:
        await node.fetch("/nope?q=()!'x'", relative=True)
    assert err.value.code == "endpoint_not_found"


async def test_data_routes_serve_reads(node):
    assert await node.fetch("/api/rows", relative=True) == '["alpha", "beta"]'
    # …which makes them iterable collections
    res = await node.evaluate("/api/rows*()!'Echo $item'")
    assert json.loads(res.text) == ["Echo alpha", "Echo beta"]


# --- ASGI shim ------------------------------------------------------------------------------


def _http(node: Url4Node) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=node.asgi())
    return httpx.AsyncClient(transport=transport, base_url="http://testnode")


async def test_asgi_get_evaluates(node):
    async with _http(node) as http:
        response = await http.get("/v1", params={"q": "(a=https://x)!'Summarize $a'"})
    assert response.status_code == 200
    assert "ARTICLE" in response.text


async def test_asgi_full_client_loop(node, wire):
    # Client → url4://testnode/v1 → HTTP GET (ASGI) → node evaluates → the
    # intent dispatches to the /claude processor endpoint → result flows back.
    async with _http(node) as http:
        client = Client(HttpIOLayer(client=http), node="url4://testnode/v1")
        res = await client.query(src("https://x", name="a"), intent="Summarize $a")
    assert "ARTICLE" in res.text or res.text.startswith("CLAUDE(")
    assert res.request.startswith("(r:0.0:url4://testnode/v1")


@pytest.mark.parametrize(
    ("path", "params", "status", "code"),
    [
        ("/v1", {"q": "(a::)!'x'"}, 400, "malformed_source"),
        ("/nope", {"q": "()!'x'"}, 404, "endpoint_not_found"),
        ("/v1", {"q": "(@bob)!'x'"}, 404, "unknown_identity"),
        ("/v1", {"q": "(@emily/secret)!'x'"}, 403, "identity_access_denied"),
    ],
)
async def test_asgi_error_mapping(node, path, params, status, code):
    async with _http(node) as http:
        response = await http.get(path, params=params)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def test_asgi_get_only(node):
    async with _http(node) as http:
        response = await http.post("/v1", content=b"q=()!'x'")
    assert response.status_code == 405


async def test_asgi_serves_data_routes(node):
    async with _http(node) as http:
        response = await http.get("/api/rows")
    assert response.status_code == 200
    assert response.json() == ["alpha", "beta"]


# --- registration validation -----------------------------------------------------------------


async def test_registration_validation(node):
    with pytest.raises(ValueError):
        node.endpoint("no-slash")
    with pytest.raises(ValueError):
        node.endpoint("/v1")  # the eval path is reserved
    with pytest.raises(ValueError):
        node.endpoint("/claude")  # duplicate


async def test_serve_requires_uvicorn(node, hide_uvicorn):
    # `hide_uvicorn` creates the missing-extra condition; without it this test
    # depended on the ambient venv and, with uvicorn installed, called the real
    # uvicorn.run().
    with pytest.raises(RuntimeError, match=r"url4\[server\]"):
        node.serve()


async def test_constructor_data_param():
    n = Url4Node("d", data={"/api/x": "payload"})
    assert await n.fetch("/api/x", relative=True) == "payload"


async def test_dual_wire_conventions_are_codec_owned():
    # WHY: spec §3.4 — a node MUST accept url4's raw-structural escaping AND a
    # standard client's full percent-encoding; the codec module owns both.
    from url4.wire.subrequest import decode_expression_http, decode_subrequest_http

    raw = "(a=https://x)!'go'"
    encoded = "%28a%3Dhttps%3A%2F%2Fx%29%21%27go%27"
    assert decode_subrequest_http(raw) == ("a=https://x", "'go'")
    assert decode_subrequest_http(encoded) == ("a=https://x", "'go'")
    assert decode_expression_http(raw) == raw
    assert decode_expression_http(encoded) == raw


# --- default route: first registered endpoint replaces the hardcoded default ----


async def test_node_default_route_is_first_registered_endpoint() -> None:
    n = Url4Node("t")
    assert n.default_route() is None

    @n.endpoint("/alpha")
    async def alpha(request: Request) -> str:  # noqa: ARG001 - handler contract
        return "alpha"

    @n.endpoint("/beta")
    async def beta(request: Request) -> str:  # noqa: ARG001 - handler contract
        return "beta"

    assert n.default_route() == "/alpha"
    assert Url4Node("t", default_processor="/x").default_route() == "/x"


async def test_node_reduce_dispatches_to_first_registered_endpoint() -> None:
    n = Url4Node("t")
    calls: list[str] = []

    @n.endpoint("/reducer")
    async def reducer(request: Request) -> str:  # noqa: ARG001 - handler contract
        calls.append("/reducer")
        return "REDUCED"

    @n.endpoint("/leaf")
    async def leaf(request: Request) -> str:  # noqa: ARG001 - handler contract
        calls.append("/leaf")
        return "LEAF"

    result = await n.evaluate("(/leaf(x)!'go')!'pick'")
    assert result.text == "REDUCED"
    assert calls == ["/leaf", "/reducer"]
