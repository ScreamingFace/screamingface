import asyncio
from url4.dag import run, ExecutionContext
from url4.io.static import StaticIOLayer
from url4.core.context import Context
io = StaticIOLayer(routes={"/echo": lambda context, intent: f"ctx={context}|intent={intent}"})
async def main():
    for expr in ["/echo(x)!'literal $$a'", "/echo(x)!'literal $$$$a'", "/echo(literal $$a)!'go'", "(a: 'BOUND', /echo(x)!'literal $$a')!'go'"]:
        for scope in [None, Context(bindings={"a": "BOUND"}, parent=None)]:
            try:
                r = await run(expr, ctx=ExecutionContext(io, scope=scope)) if scope else await run(expr, io)
            except Exception as e:
                r = f"ERR {type(e).__name__}: {e}"
            print(f"{expr:42} scope={'a=BOUND' if scope else 'none':8} -> {r}")
asyncio.run(main())
