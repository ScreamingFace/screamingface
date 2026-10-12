"""Probe: status mapping of caller errors and odd inputs over the real ASGI app."""
import asyncio, json
import httpx
from url4.cli._serve import ServeConfig, build_asgi_app
from url4.peer.server import Url4Node

def build():
    n = Url4Node("s", default_processor="/echo")
    @n.endpoint("/echo")
    def echo(req): return json.dumps([req.context, req.intent])
    @n.endpoint("/pyto")
    async def pyto(req): raise TimeoutError("handler's own timeout")
    @n.endpoint("/boom")
    def boom(req): raise RuntimeError("bug")
    return n

async def main():
    n = build()
    app = build_asgi_app(n, ServeConfig(timeout=5))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://n") as c:
        for url in ["/v1?processor=/nope&q=(a)!'x'", "/v1?q=(a)!'x';processor=/nope",
                    "/echo", "/pyto?q=(a)!x", "/boom?q=(a)!x"]:
            r = await c.get(url)
            print(f"{url:40} -> {r.status_code} {r.headers.get('content-type')} {r.text[:80]!r}")
    # raw UTF-8 bytes in the query (what a lenient HTTP parser may hand over)
    sent = []
    async def send(m): sent.append(m)
    async def receive(): return {"type": "http.request"}
    scope = {"type": "http", "method": "GET", "path": "/echo",
             "query_string": "q=(café)!x".encode("utf-8"), "headers": []}
    await n.asgi()(scope, receive, send)
    print("raw utf-8 query ->", sent[0]["status"], sent[1]["body"].decode())
asyncio.run(main())
