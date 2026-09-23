"""Client facade tests — Client + Url4Result over a deterministic StaticIOLayer.

STORY: as an SDK user I build queries in Python (or raw url4 text), point them
at a node (or run them locally), and get back a result that carries the exact
canonical expression that ran (`.request`) — the protocol's audit artifact.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from url4 import StaticIOLayer, build
from url4.core.builders import iterate, src
from url4.peer.client import Client, Url4Result, evaluate_sync

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def wire() -> list[tuple[str, str, str]]:
    """Captured (route, context, intent) triples for every routed call."""
    return []


@pytest.fixture()
def io(wire) -> StaticIOLayer:
    def route(name: str):
        def handler(context: str, intent: str) -> str:
            wire.append((name, context, intent))
            return f"{name.upper()}-RESULT"

        return handler

    return StaticIOLayer(
        fetch_map={
            "https://x": "ARTICLE",
            "https://data/rows": '["alpha", "beta"]',
        },
        routes={
            "/claude": route("/claude"),
            "/llama": route("/llama"),
            "url4://node.ai/v1": route("remote"),
        },
    )


# --- Url4Result --------------------------------------------------------------------


async def test_result_envelope_accessors():
    res = Url4Result(text='["a", "b"]', request="(x)!'go'")
    assert str(res) == '["a", "b"]'
    assert res.json() == ["a", "b"]
    assert res.elements == ["a", "b"]
    scalar = Url4Result(text='{"k": 1}', request="(x)!'go'")
    assert scalar.json() == {"k": 1}
    with pytest.raises(ValueError, match="list"):
        _ = scalar.elements
    prose = Url4Result(text="not json", request="(x)!'go'")
    with pytest.raises(ValueError, match="JSON"):
        _ = prose.json()


async def test_result_reprs_stay_readable():
    res = Url4Result(text="A" * 300, request="(x)!'go'")
    assert repr(res).startswith("Url4Result(request=")
    assert len(repr(res)) < 250  # long bodies are truncated, not dumped
    assert "(x)!" in res._repr_html_()  # request shown (quotes are HTML-escaped)


# --- local execution ------------------------------------------------------------------


async def test_local_query_resolves_and_carries_request(io):
    async with Client(io) as client:
        res = await client.query(src("https://x", name="a"), intent="Summarize $a")
    assert "ARTICLE" in res.text
    assert res.request == "(a=https://x)!'Summarize $a'"
    assert build(res.request) is not None  # the request is valid canonical url4


async def test_local_query_accepts_raw_strings(io):
    async with Client(io) as client:
        res = await client.query("a=https://x", intent="Summarize $a")
    assert "ARTICLE" in res.text


async def test_evaluate_raw_expression_and_env(io):
    async with Client(io) as client:
        res = await client.evaluate("(a=https://x)!'[$who] Summarize $a'", env={"who": "junior"})
    assert "junior" in res.text
    assert "ARTICLE" in res.text


async def test_local_iterate_returns_elements(io):
    async with Client(io) as client:
        res = await client.iterate("https://data/rows", intent="Echo $item")
    assert res.elements == ["Echo alpha", "Echo beta"]
    assert res.request == "https://data/rows*()!'Echo $item'"


async def test_local_broadcast_produces_per_source_results(io):
    async with Client(io) as client:
        res = await client.broadcast("https://x", "https://x", intent="Extract")
    assert len(res.elements) == 2


async def test_local_reduce_dispatches_calls_and_reducer(io, wire):
    async with Client(io) as client:
        res = await client.reduce(
            "/claude(https://x)!'Go'", "/llama(https://x)!'Go'", intent="Merge $1 and $2"
        )
    routes = [name for name, _, _ in wire]
    assert "/claude" in routes and "/llama" in routes
    # the reducer instruction itself is dispatched to the default processor
    assert routes.count("/claude") == 2
    assert res.text == "/CLAUDE-RESULT"


async def test_local_query_params_ride_the_expression(io):
    # AIDEV-NOTE: quorum is ENFORCED by the executor (not just carried) — the
    # value must be satisfiable by the source list.
    async with Client(io) as client:
        res = await client.query("https://x", intent="go", quorum=1, triggers=(1, 2), t=60)
    assert res.request == "(https://x)!'go';quorum=1;triggers=1,2;t=60"


# --- remote execution --------------------------------------------------------------------


async def test_remote_query_sends_context_and_intent(io, wire):
    async with Client(io, node="url4://node.ai") as client:
        res = await client.query(src("https://x", name="a"), intent="Summarize $a")
    assert res.text == "REMOTE-RESULT"
    assert wire == [("remote", "a=https://x", "Summarize $a")]
    # the request is the passthrough-wrapped remote expression (intent stays
    # remote; `OME-508` — the group's own intent is the pure `$r` interpolation)
    assert res.request == "(r:0.0:url4://node.ai/v1(a=https://x)!'Summarize $a')!'$r'"


async def test_remote_target_forms(io, wire):
    async with Client(io) as client:
        await client.query("https://x", intent="go", node="node.ai", path="/v1")
        await client.query("https://x", intent="go", node="url4://node.ai/v1")
    assert [name for name, _, _ in wire] == ["remote", "remote"]


async def test_remote_broadcast_rides_as_param(io, wire):
    async with Client(io, node="url4://node.ai/v1") as client:
        res = await client.broadcast("https://a.com", "https://b.com", intent="Extract")
    assert "?broadcast&q=" in res.request
    # the remote node's envelope decode folds the param back into !*
    _, context, _ = wire[0]
    assert context == "https://a.com, https://b.com"


async def test_remote_iterate_reduce_is_canonical_reduce_over_iteration(io, wire):
    async with Client(io, node="url4://node.ai/v1") as client:
        it = iterate("https://data/rows", "x=$item", intent="per row", reduce="agg")
        res = await client.evaluate(it)
    _, context, intent = wire[0]
    assert context == "https://data/rows*(x=$item)!'per row'"
    assert intent == "agg"
    assert res.text == "REMOTE-RESULT"


async def test_remote_protocol_params_precede_q(io):
    async with Client(io, node="url4://node.ai/v1") as client:
        res = await client.query("https://x", intent="go", quorum=2)
    assert "?quorum=2&q=" in res.request


# --- lifecycle -----------------------------------------------------------------------------


async def test_injected_io_is_never_closed(io):
    client = Client(io)
    await client.query("https://x", intent="go")
    await client.aclose()  # no-op for injected io; must not raise
    # io still usable
    res = await Client(io).query("https://x", intent="go")
    assert "ARTICLE" in res.text


async def test_owned_io_lifecycle_without_use():
    # No network: the owned HttpIOLayer is created lazily, so an unused client
    # closes cleanly.
    async with Client() as client:
        assert client is not None


async def test_client_effective_io_returns_the_injected_layer(io):
    assert Client(io)._effective_io() is io


async def test_client_closes_its_owned_io_on_exit(monkeypatch):
    # A used owned adapter is closed by __aexit__, through the shared _OwnedIO.
    closed: list[bool] = []

    class Tracked(StaticIOLayer):
        async def aclose(self) -> None:
            closed.append(True)

    monkeypatch.setattr("url4.peer._owned._http_io", Tracked)
    async with Client() as client:
        client._effective_io()  # force the owned adapter into existence
        assert closed == []
    assert closed == [True]


async def test_result_is_json_roundtrippable():
    res = Url4Result(text=json.dumps({"ok": True}), request="()!'x'")
    assert res.json() == {"ok": True}


# --- the unified front door -----------------------------------------------------------------


async def test_evaluate_routes_raw_text_to_the_node_target(io, wire):
    async with Client(io, node="url4://node.ai/v1") as client:
        res = await client.evaluate("(a=https://x)!'Summarize $a'")
    assert res.text == "REMOTE-RESULT"
    assert res.request == "(r:0.0:url4://node.ai/v1(a=https://x)!'Summarize $a')!'$r'"
    assert wire == [("remote", "a=https://x", "Summarize $a")]


async def test_evaluate_merges_params_locally(io):
    async with Client(io) as client:
        res = await client.evaluate("(https://x)!'go'", params={"quorum": 1})
    assert res.request == "(https://x)!'go';quorum=1"


async def test_query_seeds_env(io):
    async with Client(io) as client:
        res = await client.query("https://x", intent="[$who] go", env={"who": "junior"})
    assert "junior" in res.text


# --- string-first construction and the sync convenience --------------------------------------


async def test_client_accepts_a_node_target_string():
    async with Client("url4://node.ai/v1") as client:
        assert client._node == "url4://node.ai/v1"  # noqa: SLF001 — facade contract
    with pytest.raises(ValueError, match="once"):
        Client("url4://node.ai", node="url4://other.ai")


async def test_evaluate_sync_refuses_a_running_loop(io):
    with pytest.raises(RuntimeError, match="event loop"):
        evaluate_sync("(https://x)!'go'", io)


async def test_evaluate_sync_runs_from_plain_sync_code(io):
    # a worker thread has no running loop — exactly the script/REPL situation
    res = await asyncio.to_thread(evaluate_sync, "(a=https://x)!'Summarize $a'", io)
    assert "ARTICLE" in res.text
    assert res.request == "(a=https://x)!'Summarize $a'"
