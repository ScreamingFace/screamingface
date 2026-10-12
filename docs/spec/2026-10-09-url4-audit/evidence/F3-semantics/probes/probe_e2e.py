import asyncio, json
from url4.core.nodes import Expression, Iteration, Text, Url
from url4.dag import ExecutionContext, run
from url4.io.static import StaticIOLayer
from url4.dag.nodes.group import GatherNode, FanoutReduceNode
from url4.dag.nodes._shared import _gather
from url4.dag.node import SourceFailure

async def main():
    rows = json.dumps([{"q": "costs $$5"}, {"q": "see $index here"}, {"q": "literal $item"}])
    io = StaticIOLayer(fetch_map={"https://data": rows},
                       routes={"/echo": lambda context, intent: f"ctx={context}|intent={intent}"})
    node = Iteration(collection=Url("https://data"), body="/echo($item.q)!'go'")
    print("map rows:", json.loads(await run(node, io)))
    # row data in intent position
    node = Iteration(collection=Url("https://data"), body="/echo(x)!'Q: $item.q'")
    try:
        print("map intents:", json.loads(await run(node, io)))
    except Exception as e: print("ERR", type(e).__name__, e)
    # text-form expression
    from url4.core.parser import build
    try:
        print("text form:", await run("https://data*(/echo($item.q)!'go')!'r'", io))
    except Exception as e: print("text form ERR", type(e).__name__, e)

    # GatherNode: contributing empty source + instrumental leaks
    g = GatherNode(slots=((None, False), ("secret", True)))
    out = await g.resolve({"src:0": "", "src:1": "INSTRUMENTAL"}, None)
    print("gather empty contributing + instrumental ->", repr(out))
    out = await g.resolve({"src:0": SourceFailure("x","boom"), "src:1": "INSTRUMENTAL"}, None)
    print("gather failed contributing + instrumental ->", repr(out))

asyncio.run(main())
