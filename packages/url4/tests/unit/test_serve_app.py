"""Node wiring + the ASGI wrapper for `url4 serve` (url4._serve).

STORY: `url4 serve` exposes `GET /v1?q=<expr>` (the node eval path), dispatches
every route to a user-owned command (subprocess), serves /healthz, and — beyond
what Url4Node gives — sheds load over max-inflight (503), bounds each request
(504), and closes the node on shutdown.

INVARIANT: the wrapper never double-sends — a timeout after the node has begun
responding is swallowed, not turned into a second (504) response.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from url4.cli._serve import ServeConfig, build_asgi_app, build_node
from url4.peer.server import Url4Node

pytestmark = pytest.mark.asyncio

_PASSTHROUGH = ("python3", "-c", "import sys; sys.stdout.write(sys.stdin.read())")
# WHY: the reducer receives the formatted reducer input as INTENT (context is
# empty), so an observable reducer must echo argv-substituted {intent}, not stdin.
_INTENT_ECHO = (
    "python3",
    "-c",
    "import sys; sys.stdout.write('REDUCED:' + sys.argv[1])",
    "{intent}",
)


def _config(**kwargs) -> ServeConfig:
    kwargs.setdefault("commands", {"/echo": _PASSTHROUGH})
    return ServeConfig(**kwargs)


def _driver(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://node")


async def test_eval_path_resolves_pure_expression() -> None:
    config = _config()
    app = build_asgi_app(build_node(config), config)
    async with _driver(app) as http:
        response = await http.get("/v1", params={"q": "('a', 'b')!'join'"})
    assert response.status_code == 200
    assert "join" in response.text


async def test_command_route_dispatches_subprocess() -> None:
    config = _config()
    app = build_asgi_app(build_node(config), config)
    async with _driver(app) as http:
        response = await http.get("/v1", params={"q": "(r:0:/echo(ping)!'noop')!'$r'"})
    assert response.status_code == 200
    assert "ping" in response.text


async def test_reduce_dispatches_to_resolved_default_route() -> None:
    # Two commands; default_route unset — the reduce must hit the FIRST declared
    # command (/reduce), whose output tags the reducer input it received.
    config = _config(commands={"/reduce": _INTENT_ECHO, "/echo": _PASSTHROUGH})
    node = build_node(config)
    result = await node.evaluate("(/echo(a)!'go', /echo(b)!'go')!'pick best'")
    assert result.text.startswith("REDUCED:")
    assert "pick best" in result.text


async def test_healthz_needs_no_evaluation() -> None:
    config = _config()
    app = build_asgi_app(build_node(config), config)
    async with _driver(app) as http:
        response = await http.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


async def test_unknown_route_maps_to_404() -> None:
    config = _config()
    app = build_asgi_app(build_node(config), config)
    async with _driver(app) as http:
        response = await http.get("/v1", params={"q": "/nope(x)!go"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "endpoint_not_found"


async def test_parse_error_maps_to_400() -> None:
    config = _config()
    app = build_asgi_app(build_node(config), config)
    async with _driver(app) as http:
        response = await http.get("/v1", params={"q": "(a::)!'x'"})
    assert response.status_code == 400


async def test_over_max_inflight_returns_503() -> None:
    node = Url4Node("t", eval_path="/v1")
    entered = asyncio.Event()
    gate = asyncio.Event()

    @node.endpoint("/slow")
    async def slow(request) -> str:
        entered.set()  # the first request now holds the only slot
        await gate.wait()
        return "done"

    config = _config(commands={"/slow": ("true",)}, max_inflight=1, timeout=5.0)
    app = build_asgi_app(node, config)
    async with _driver(app) as http:
        first = asyncio.create_task(http.get("/v1", params={"q": "(r=/slow(x)!'go')!'$r'"}))
        await asyncio.wait_for(entered.wait(), 5)
        second = await http.get("/v1", params={"q": "(r=/slow(x)!'go')!'$r'"})
        assert second.status_code == 503
        assert second.headers["retry-after"] == "1"
        gate.set()
        assert (await first).status_code == 200


async def test_request_timeout_returns_504() -> None:
    node = Url4Node("t", eval_path="/v1")

    @node.endpoint("/slow")
    async def slow(request) -> str:
        await asyncio.sleep(5)
        return "done"

    config = _config(commands={"/slow": ("true",)}, timeout=0.05)
    app = build_asgi_app(node, config)
    async with _driver(app) as http:
        response = await http.get("/v1", params={"q": "(r=/slow(x)!'go')!'$r'"})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "timeout"


async def test_lifespan_closes_node() -> None:
    closed: list[bool] = []

    class _SpyNode(Url4Node):
        async def aclose(self) -> None:
            closed.append(True)
            await super().aclose()

    app = build_asgi_app(_SpyNode("t"), _config())
    sent: list[str] = []
    messages = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

    async def receive() -> dict:
        return next(messages)

    async def send(message: dict) -> None:
        sent.append(message["type"])

    await app({"type": "lifespan"}, receive, send)
    assert sent == ["lifespan.startup.complete", "lifespan.shutdown.complete"]
    assert closed == [True]
