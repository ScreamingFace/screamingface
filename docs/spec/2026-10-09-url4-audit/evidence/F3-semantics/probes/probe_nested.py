import asyncio
from url4.core.nodes import Iteration, Url
from url4.dag import run
from url4.io.static import StaticIOLayer
io = StaticIOLayer(fetch_map={"https://outer": '["A","B"]', "https://flat": '["x","y"]', "/coll/A": '["x","y"]', "/coll/B": '["z"]'},
                   routes={"/s": lambda c, i: f"s-{c}|{i}"})
async def main():
    print("flat  :", await run(Iteration(collection=Url("https://flat"), body="/s($item)!'g'"), io))
    print("nested:", await run(Iteration(collection=Url("https://outer"), body="/coll/$item*(/s($item)!'g')!'p'"), io))
    print("nested-idx:", await run(Iteration(collection=Url("https://outer"), body="/coll/$item*(/s($item $index)!'g')!'p'"), io))
asyncio.run(main())
