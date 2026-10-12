import asyncio, json
from url4.dag import compile_expression, run
from url4.dag.nodes.iteration import ExpandNode, MapNode
from url4.io.static import StaticIOLayer
g = compile_expression("(https://d*(/s($item)!'g')!'p';expand, c)!'m'")
def walk(n, seen=set(), depth=0):
    if id(n) in seen: return
    seen.add(id(n))
    if isinstance(n, ExpandNode):
        print("ExpandNode inner:", type(n.deps["inner"]).__name__)
    for d in getattr(n, "deps", {}).values(): walk(d, seen, depth+1)
root = getattr(g, "root", g)
walk(root)
async def main():
    # Direct: ExpandNode given a list payload (what a MapNode returns)
    e = ExpandNode()
    for inner in [["one row"], ["a,b", "c,d"], ["multi\nline row", "x"], ['{"k":1}']]:
        try: print(inner, "->", await e.resolve({"inner": inner}, None))
        except Exception as ex: print(inner, "-> RAISED", type(ex).__name__, getattr(ex, "code", ""), str(ex)[:70])
    io = StaticIOLayer(fetch_map={"https://d": '["a,b", "c,d"]'}, routes={"/s": lambda c,i: c, "/r": lambda c,i: c})
    print("e2e expand(map rows a,b / c,d):", repr(await run("(https://d*(/s($item)!'g')!'p';expand, z)!'m'", io, processor="/r")))
    io = StaticIOLayer(fetch_map={"https://d": '["only"]'}, routes={"/s": lambda c,i: c, "/r": lambda c,i: c})
    try: print("e2e expand(map 1 row):", repr(await run("(https://d*(/s($item)!'g')!'p';expand, z)!'m'", io, processor="/r")))
    except Exception as ex: print("e2e expand(map 1 row): RAISED", type(ex).__name__, getattr(ex,"code",""), ex)
asyncio.run(main())
