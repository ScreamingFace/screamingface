"""The IOLayer port, its adapters (StaticIOLayer, HttpIOLayer), and collection parsing."""

from __future__ import annotations

import httpx
import pytest

from url4.core.collection import parse_collection
from url4.core.errors import (
    CollectionError,
    ParseError,
    ResolutionError,
    Url4Error,
)
from url4.core.subrequest import encode_subrequest
from url4.io.http import HttpIOLayer
from url4.io.layer import FetchRequest, FetchResult, fetch_result, resolve_shelf
from url4.io.static import StaticIOLayer


@pytest.mark.asyncio
async def test_fetch_hit() -> None:
    io = StaticIOLayer(fetch_map={"https://x": "content"})
    assert await io.fetch("https://x", relative=False) == "content"


@pytest.mark.asyncio
async def test_fetch_miss_raises() -> None:
    with pytest.raises(ResolutionError):
        await StaticIOLayer().fetch("https://missing", relative=False)


@pytest.mark.asyncio
async def test_route_serves_relative_expression() -> None:
    # A relative expression is fetched as "/claude?q=(context)!intent"; the route
    # handler receives the decoded (context, intent).
    io = StaticIOLayer(routes={"/claude": lambda context, intent: f"{intent}:{context}"})
    assert await io.fetch("/claude?q=(the data)!summarize", relative=True) == "summarize:the data"


@pytest.mark.asyncio
async def test_route_empty_context_and_no_intent() -> None:
    io = StaticIOLayer(routes={"/reduce": lambda context, intent: f"[{context}|{intent}]"})
    assert await io.fetch("/reduce?q=()", relative=True) == "[|]"


@pytest.mark.asyncio
async def test_route_round_trips_wire_unsafe_characters() -> None:
    # A context/intent carrying newlines, unbalanced parens, quotes, and '&' —
    # which would crash an httpx GET or desync the paren scan raw — must survive
    # the ?q= wire and reach the handler decoded byte-for-byte.
    seen: dict[str, str] = {}

    def handler(context: str, intent: str) -> str:
        seen.update(context=context, intent=intent)
        return "ok"

    io = StaticIOLayer(routes={"/claude": handler})
    target = encode_subrequest("/claude", "a (stray & 'quoted' multi\nline", "do it! now")
    await io.fetch(target, relative=True)
    assert seen == {"context": "a (stray & 'quoted' multi\nline", "intent": "do it! now"}


@pytest.mark.asyncio
async def test_route_async_handler() -> None:
    async def handler(context: str, intent: str) -> str:
        return f"async:{intent}"

    io = StaticIOLayer(routes={"/claude": handler})
    assert await io.fetch("/claude?q=(x)!hi", relative=True) == "async:hi"


@pytest.mark.asyncio
async def test_unregistered_route_falls_through_to_fetch_miss() -> None:
    with pytest.raises(ResolutionError):
        await StaticIOLayer().fetch("/nope?q=()!x", relative=True)


# -- error taxonomy: spec codes + permanence ------------------------------------


def test_error_code_and_permanence_defaults() -> None:
    assert Url4Error("x").code == "internal_error"
    assert Url4Error("x").permanent is True
    assert ParseError("x").code == "malformed_source"
    assert CollectionError("x").code == "malformed_source"
    assert ResolutionError("x").permanent is False


def test_error_code_and_permanence_overrides() -> None:
    exc = ResolutionError("gone", code="unknown_identity", permanent=True)
    assert exc.code == "unknown_identity"
    assert exc.permanent is True


def test_parse_error_keeps_position() -> None:
    assert ParseError("bad", position=7).position == 7


# -- holdings: @ / @identity resolution (spec §5.6) ------------------------------


@pytest.mark.asyncio
async def test_holdings_self_named_and_scoped() -> None:
    io = StaticIOLayer(
        holdings={
            "": "NODE DATA",
            "science": "NODE SCIENCE",
            "emily": "EMILY DATA",
            "emily/notes": "EMILY NOTES",
        }
    )
    assert await io.fetch_holdings(None, None) == "NODE DATA"
    assert await io.fetch_holdings(None, "science") == "NODE SCIENCE"
    assert await io.fetch_holdings("emily", None) == "EMILY DATA"
    assert await io.fetch_holdings("emily", "notes") == "EMILY NOTES"


@pytest.mark.asyncio
async def test_holdings_unknown_identity_is_permanent() -> None:
    io = StaticIOLayer(holdings={"": "DATA"})
    with pytest.raises(ResolutionError) as excinfo:
        await io.fetch_holdings("nobody", None)
    assert excinfo.value.code == "unknown_identity"
    assert excinfo.value.permanent is True


@pytest.mark.asyncio
async def test_holdings_unconfigured_adapter_is_non_url4() -> None:
    with pytest.raises(ResolutionError) as self_ref:
        await StaticIOLayer().fetch_holdings(None, None)
    assert self_ref.value.code == "self_ref_on_non_url4"
    with pytest.raises(ResolutionError) as identity_ref:
        await StaticIOLayer().fetch_holdings("emily", None)
    assert identity_ref.value.code == "identity_ref_on_non_url4"


def test_resolve_shelf_exact_collection_wins() -> None:
    assert resolve_shelf({None: "DEFAULT", "science": "SCI"}, "science") == "SCI"


def test_resolve_shelf_falls_back_to_default_shelf() -> None:
    assert resolve_shelf({None: "DEFAULT"}, "missing") == "DEFAULT"


def test_resolve_shelf_none_collection_uses_default_shelf() -> None:
    assert resolve_shelf({None: "DEFAULT", "science": "SCI"}, None) == "DEFAULT"


def test_resolve_shelf_returns_none_when_absent() -> None:
    assert resolve_shelf({}, "missing") is None
    assert resolve_shelf({"science": "SCI"}, "missing") is None
    assert resolve_shelf({}, None) is None


# -- fetch_ex / fetch_result: media-type-aware port -------------------------------


@pytest.mark.asyncio
async def test_static_fetch_ex_reports_mapped_media_type() -> None:
    io = StaticIOLayer(
        fetch_map={"https://x": "[1]"}, media_types={"https://x": "application/json"}
    )
    result = await io.fetch_ex(FetchRequest("https://x"))
    assert result == FetchResult("[1]", media_type="application/json")


@pytest.mark.asyncio
async def test_static_fetch_ex_unmapped_media_type_is_none() -> None:
    io = StaticIOLayer(fetch_map={"https://x": "body"})
    assert (await io.fetch_ex(FetchRequest("https://x"))).media_type is None


@pytest.mark.asyncio
async def test_fetch_result_wraps_old_style_adapter() -> None:
    class OldStyle:
        async def fetch(self, target: str, *, relative: bool) -> str:
            return f"old:{target}"

    result = await fetch_result(OldStyle(), FetchRequest("https://x"))
    assert result == FetchResult("old:https://x", media_type=None)


@pytest.mark.asyncio
async def test_fetch_result_prefers_fetch_ex() -> None:
    io = StaticIOLayer(fetch_map={"/d": "rows"}, media_types={"/d": "text/csv"})
    result = await fetch_result(io, FetchRequest("/d", relative=True, kind="relative"))
    assert result.media_type == "text/csv"


# -- parse_collection: sniffed (no declared media type) ----------------------------


def test_sniff_empty_body_is_empty_collection() -> None:
    assert parse_collection("") == []
    assert parse_collection("   \n  ") == []


def test_sniff_json_array() -> None:
    assert parse_collection('[1, "a", {"k": 2}]') == ["1", "a", '{"k": 2}']


def test_sniff_json_object_is_malformed() -> None:
    with pytest.raises(CollectionError) as excinfo:
        parse_collection('{"a": 1}')
    assert excinfo.value.code == "malformed_source"


def test_sniff_html_is_malformed() -> None:
    with pytest.raises(CollectionError, match="HTML page"):
        parse_collection("<!doctype html><html><body>404</body></html>")


def test_sniff_jsonl() -> None:
    assert parse_collection('{"a": 1}\n{"a": 2}') == ['{"a": 1}', '{"a": 2}']


def test_sniff_csv_table() -> None:
    rows = parse_collection("name,age\nalice,30\nbob,25")
    assert rows == ['{"name": "alice", "age": "30"}', '{"name": "bob", "age": "25"}']


def test_sniff_multiline_plain_text_degrades_to_lines() -> None:
    assert parse_collection("alpha\nbeta\n\ngamma") == ["alpha", "beta", "gamma"]


def test_sniff_single_line_scalar_is_not_iterable() -> None:
    with pytest.raises(CollectionError, match="not an iterable") as excinfo:
        parse_collection("hello world")
    assert excinfo.value.code == "malformed_source"


def test_sniff_single_json_scalar_line_is_not_iterable() -> None:
    # A lone valid-JSON line is indistinguishable from a scalar; sniffing must
    # not iterate it (declare application/x-ndjson to iterate a single row).
    with pytest.raises(CollectionError):
        parse_collection("42")


# -- parse_collection: declared media types (spec §5.3.7) ---------------------------


def test_declared_json_array() -> None:
    assert parse_collection("[1, 2]", "application/json") == ["1", "2"]


def test_declared_json_object_and_scalar_are_malformed() -> None:
    with pytest.raises(CollectionError):
        parse_collection('{"a": 1}', "application/json")
    with pytest.raises(CollectionError):
        parse_collection('"hi"', "application/json")


def test_declared_json_invalid_is_malformed() -> None:
    with pytest.raises(CollectionError, match="not valid JSON"):
        parse_collection("not json", "application/json")


def test_declared_ndjson_accepts_a_single_row() -> None:
    assert parse_collection('{"a": 1}', "application/x-ndjson") == ['{"a": 1}']


def test_declared_ndjson_invalid_line_is_malformed() -> None:
    with pytest.raises(CollectionError, match="NDJSON"):
        parse_collection('{"a": 1}\nnot json', "application/x-ndjson")


def test_declared_csv_trusts_the_declaration() -> None:
    # Multi-word headers fail the sniffing heuristic but a declared table is
    # parsed as-is.
    rows = parse_collection("first name,last name\nada l,lovelace x", "text/csv")
    assert rows == ['{"first name": "ada l", "last name": "lovelace x"}']


def test_declared_tsv() -> None:
    assert parse_collection("a\tb\n1\t2", "text/tab-separated-values") == ['{"a": "1", "b": "2"}']


def test_declared_plain_text_single_line() -> None:
    assert parse_collection("only line", "text/plain") == ["only line"]


def test_declared_media_type_parameters_are_ignored() -> None:
    assert parse_collection("[1]", "application/json; charset=utf-8") == ["1"]


def test_declared_unsupported_type_is_malformed() -> None:
    with pytest.raises(CollectionError, match="unsupported content type"):
        parse_collection("%PDF-1.7", "application/pdf")


# -- HttpIOLayer: driven through an injected httpx MockTransport (no network) --


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_http_fetch_issues_get() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="BODY")

    io = HttpIOLayer(client=_mock_client(handler))
    assert await io.fetch("https://x/doc", relative=False) == "BODY"
    assert seen[0].method == "GET"
    assert str(seen[0].url) == "https://x/doc"


@pytest.mark.asyncio
async def test_http_relative_expression_is_a_get_to_localhost_route() -> None:
    # A relative expression reaches HttpIOLayer already encoded as /claude?q=…,
    # so a model backend is just a GET against the localhost node.
    seen: list[str] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        return httpx.Response(200, text=str(request.url))

    io = HttpIOLayer(base_url="https://host", client=_mock_client(recording))
    got = await io.fetch("/claude?q=(x)!go", relative=True)
    assert got.startswith("https://host/claude?q=")
    assert seen == ["GET"]


@pytest.mark.asyncio
async def test_http_url4_scheme_travels_as_https() -> None:
    # Spec §3.5: a url4:// target rides HTTPS on the wire.
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="OK")

    io = HttpIOLayer(client=_mock_client(handler))
    await io.fetch("url4://node.ai/v1?q=(a)!b", relative=False)
    assert str(seen[0].url) == "https://node.ai/v1?q=(a)!b"


@pytest.mark.asyncio
async def test_http_fetch_ex_reports_media_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="[1]", headers={"Content-Type": "application/json; charset=utf-8"}
        )

    io = HttpIOLayer(client=_mock_client(handler))
    result = await io.fetch_ex(FetchRequest("https://x/data"))
    assert result == FetchResult("[1]", media_type="application/json")


@pytest.mark.asyncio
async def test_http_fetch_ex_missing_content_type_is_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(200, text="raw")
        del response.headers["content-type"]  # httpx defaults it; the wire may not
        return response

    io = HttpIOLayer(client=_mock_client(handler))
    assert (await io.fetch_ex(FetchRequest("https://x"))).media_type is None


@pytest.mark.asyncio
async def test_owned_client_follows_redirects() -> None:
    # A 301/302 source must resolve to the real body, not the empty redirect
    # response — raise_for_status never fires on a 3xx. The client the adapter
    # creates for itself must therefore follow redirects.
    io = HttpIOLayer()
    try:
        assert io._get_client().follow_redirects is True
    finally:
        await io.aclose()


@pytest.mark.asyncio
async def test_http_error_becomes_resolution_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    io = HttpIOLayer(client=_mock_client(handler))
    with pytest.raises(ResolutionError):
        await io.fetch("https://x", relative=False)
    with pytest.raises(ResolutionError):
        await io.fetch_ex(FetchRequest("https://x"))


@pytest.mark.asyncio
async def test_invalid_url_becomes_resolution_error() -> None:
    # httpx.InvalidURL is not an HTTPError subclass; it must still be wrapped
    # (a reducer query with control chars can trigger it at request time).
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.InvalidURL("malformed URL")

    io = HttpIOLayer(client=_mock_client(handler))
    with pytest.raises(ResolutionError):
        await io.fetch("https://x", relative=False)


@pytest.mark.asyncio
async def test_owned_client_is_created_once_and_closed_by_aclose() -> None:
    # With no client injected, one AsyncClient is created lazily and reused
    # across fetches (so a fan-out shares its connection pool), then released.
    io = HttpIOLayer()
    client = io._get_client()
    assert io._get_client() is client  # reused, not recreated
    assert not client.is_closed
    await io.aclose()
    assert client.is_closed


@pytest.mark.asyncio
async def test_injected_client_is_not_closed() -> None:
    # A caller-supplied client is used as-is and never closed by the adapter.
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    async with HttpIOLayer(client=client) as io:
        assert io._get_client() is client
    assert not client.is_closed
    await client.aclose()


# --- SupportsDefaultRoute: the io world's declared default reduce route ---------


@pytest.mark.asyncio
async def test_static_io_default_route_is_first_declared() -> None:
    # WHY: no hardcoded processor route in the core — an adapter that declares
    # routes reports the FIRST one as the reduce default (SupportsDefaultRoute).
    io = StaticIOLayer(routes={"/first": lambda c, i: "1", "/second": lambda c, i: "2"})
    assert io.default_route() == "/first"


@pytest.mark.asyncio
async def test_static_io_default_route_is_none_without_routes() -> None:
    assert StaticIOLayer(fetch_map={"https://x": "y"}).default_route() is None
