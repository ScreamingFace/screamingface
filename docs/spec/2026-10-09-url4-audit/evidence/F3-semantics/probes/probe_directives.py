import asyncio, json
from url4.core.parser import build, _merge_directives
from url4.core.nodes import IterationDirectives as D
from url4.dag import run
from url4.io.static import StaticIOLayer
from url4.core.errors import ResolutionError
for text in ["(https://d*(/s($item)!'g')!'p';iteration.on_error=collect)!'r';iteration.on_error=fail",
             "(https://d*(/s($item)!'g')!'p';iteration.on_error=skip)!'r';iteration.on_error=fail",
             "(https://d*(/s($item)!'g')!'p';iteration.concurrency=2)!'r';iteration.concurrency=5"]:
    try:
        n = build(text); print(text, "->", getattr(n, "directives", n))
    except Exception as e: print(text, "ERR", e)
print(_merge_directives(D(on_error="collect"), D(on_error="fail")))
def solve(c, i):
    if c == "r1": raise ResolutionError("bad row")
    return "ok-" + c
io = StaticIOLayer(fetch_map={"https://d": '["r0","r1"]'}, routes={"/s": solve, "/r": lambda c,i: i})
async def main():
    for e in ["((a, b)!'j';expand, c)!'m'", "(https://d*(/s($item)!'g')!'p';expand, c)!'m'"]:
        try: print(e, "->", repr(await run(e, io, processor="/r")))
        except Exception as ex: print(e, "RAISED", type(ex).__name__, ex)
asyncio.run(main())
