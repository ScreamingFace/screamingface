import asyncio, json
from url4.core.nodes import Iteration, Url, IterationDirectives
from url4.dag import run, ExecutionContext
from url4.io.static import StaticIOLayer
from url4.core.errors import ResolutionError

def s(c, i):
    if c == "bad": raise ResolutionError("inner bad")
    return "s-" + c
def red(c, i): raise ResolutionError("row reducer down")
io = StaticIOLayer(
    fetch_map={"https://outer": '["A","B"]', "/coll/A": '["x","bad"]'},
    routes={"/s": s, "/red": red, "/ok": lambda c, i: "ok"})

async def case(label, body, on_error):
    ctx = ExecutionContext(io)
    node = Iteration(collection=Url("https://outer"), body=body,
                     directives=IterationDirectives(on_error=on_error, concurrency=1))
    try:
        out = await run(node, ctx=ctx); res = out
    except Exception as e:
        res = f"RAISED {type(e).__name__}: {e}"
    print(f"{label}: tally={ctx.collected_errors}\n   out={res}")

async def main():
    # Row A: nested collect map captures 1 error and succeeds. Row B: '/coll/B' ok, so fail via missing path
    await case("fail-mode: A nested-collects 1 error, B fails",
               "/coll/$item*(/s($item)!'g')!'p'", "fail")
    # collect-mode: nested map records then the ROW fails afterwards (reducer over nested rows fails)
    await case("collect-mode: nested records, then row reducer fails",
               "(/coll/$item*(/s($item)!'g')!'p')!/red(all)!'r'", "collect")
asyncio.run(main())
