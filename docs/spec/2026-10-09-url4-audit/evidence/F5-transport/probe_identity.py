"""Probe: paths by which identity holdings could be served without the identity gate."""
import asyncio
import httpx
from url4 import StaticIOLayer
from url4.core.errors import ResolutionError, Url4Error
from url4.dag import run
from url4.peer.server import Url4Node
from url4.peer.direct import dispatch_direct

CALLS = []

def build():
    n = Url4Node("gate", default_processor="/echo")
    @n.endpoint("/echo")
    def echo(req): return f"ECHO[{req.context}|{req.intent}]"
    @n.identity("emily")
    def emily(collection):
        CALLS.append(collection)
        if collection == "secret":
            raise ResolutionError("denied", code="identity_access_denied", permanent=True)
        return f"EMILY[{collection}]"
    @n.holdings
    def own(collection): return f"SELF[{collection}]"
    return n

async def http_probe():
    n = build()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=n.asgi()), base_url="http://n") as c:
        for path, q in [
            ("/v1", "(@emily/secret)!'x'"),
            ("/v1", "@emily/secret"),
            ("/v1", "(@emily/secret, @emily/pub)!'x'"),
            ("/v1", "(a:@emily/secret, b:@emily/pub)!'x'"),
            ("/v1", "(@emily/secret)!'x';broadcast"),
            ("/v1/emily/secret", "(@)!'x'"),
            ("/v1/emily", "(@/secret)!'x'"),
            ("/v1", "(@/emily/secret)!'x'"),
        ]:
            CALLS.clear()
            r = await c.get(path, params={"q": q})
            print(f"HTTP {path}?q={q!r:42} -> {r.status_code} {r.text[:70]!r} handler_calls={CALLS}")
    for t in ["/v1?q=(@emily/secret)!x", "/emily/secret", "/@emily"]:
        try:
            print("direct", t, "->", await dispatch_direct(build(), t))
        except Url4Error as e:
            print("direct", t, "->", e.code)

async def static_probe():
    io = StaticIOLayer(routes={"/echo": lambda c, i: f"ECHO[{c}]"},
                       holdings={"emily/secret": "EMILY-SECRET", "": "SELF"})
    for expr in ["(@emily/secret)!'x'", "(@/emily/secret)!'x'", "(@emily)!'x'"]:
        try:
            print("static", repr(expr), "->", (await run(expr, io=io)))
        except Url4Error as e:
            print("static", repr(expr), "->", type(e).__name__, e.code, str(e)[:80])
    from url4.io.static import _holdings_key
    print("key(None,'emily/secret') =", _holdings_key(None, "emily/secret"),
          "| key('emily','secret') =", _holdings_key("emily", "secret"))
    print("fetch_holdings(None,'emily/secret') ->", await io.fetch_holdings(None, "emily/secret"))

asyncio.run(http_probe()); asyncio.run(static_probe())
