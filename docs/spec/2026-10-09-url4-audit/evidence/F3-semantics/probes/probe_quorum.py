import asyncio
from url4.dag import run
from url4.io.static import StaticIOLayer
from url4.core.errors import ResolutionError
def boom(context, intent): raise ResolutionError("down")
io = StaticIOLayer(
    fetch_map={"https://ok": "OK", "https://rows": '["r1","r2","r3"]'},
    routes={"/a": lambda c, i: "A-said", "/b": boom, "/c": boom,
            "/reduce": lambda c, i: f"REDUCER<<{i}>>"})
async def main():
    exprs = [
      ("fan-out, 1/3 ok, quorum=3", "(/a(x)!'y', /b(x)!'y';optional, /c(x)!'y';optional)!'merge';quorum=3"),
      ("local group, 1/3 ok, quorum=3", "(https://ok, /b(x)!'y';optional, /c(x)!'y';optional)!'merge';quorum=3"),
      ("broadcast, 1/3 ok, quorum=3", "(https://ok, /b(x)!'y';optional, /c(x)!'y';optional)!*'merge';quorum=3"),
      ("expand counts elements: 1 source + expand(3), quorum=4", "(/b(x)!'y';optional, https://rows;expand)!'merge';quorum=3"),
      ("fan-out $$a escape", "(a:/a(x)!'y', /a(x)!'y')!'literal $$a and ref $a'"),
    ]
    for name, e in exprs:
        try:
            r = await run(e, io, processor="/reduce")
        except Exception as ex:
            r = f"RAISED {type(ex).__name__}: {getattr(ex,'code','')} {ex}"
        print(f"{name}:\n   {r!r}")
asyncio.run(main())
