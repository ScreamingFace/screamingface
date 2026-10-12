"""Probe F: a data route registered UNDER the eval path is shadowed by eval when ?q= is present."""
import asyncio
from url4.io.layer import FetchRequest
from url4.peer.server import Url4Node
from url4.peer.direct import dispatch_direct
n = Url4Node("n")
n.data("/v1/models", '["m1","m2"]', media_type="application/json")
@n.holdings
def own(c): return f"SELF[{c}]"
async def main():
    print("HTTP  no q :", await n.fetch("/v1/models", relative=True))
    print("HTTP  q    :", await n.fetch("/v1/models?q=(@)!'x'", relative=True))
    r = await n.fetch_ex(FetchRequest("/v1/models?q=(@)!'x'", relative=True))
    print("fetch_ex q :", repr(r.body[:30]), "media_type =", r.media_type)
    print("direct q   :", await dispatch_direct(n, "/v1/models?q=(@)!'x'"))
asyncio.run(main())
