import url4, math
from url4 import build, render, src, text, ref, identity, iterate, expr, struct
from url4.core.nodes import *
from url4.core.errors import RenderError, ParseError
def t(label, f):
    try: print(label, "->", repr(f()))
    except Exception as e: print(label, "!!", type(e).__name__, str(e)[:150])
t("text newline", lambda: render(text("a\nb")))
t("text tab", lambda: render(Expression(sources=(Text("a\tb"),), intent=Text("go"))))
t("intent newline", lambda: render(expr("https://x", intent="sum\nit")))
t("weight nan", lambda: render(src("https://x", name="a", weight=float('nan'))))
t("weight inf builder", lambda: src("https://x", name="a", weight=float('inf')))
t("ref neg", lambda: render(ref("a", -1)))
t("identity space", lambda: render(identity("a b")))
t("identity coll #", lambda: render(IdentityRef("a","x#y"), check=False))
t("identity coll # check", lambda: render(IdentityRef("a","x#y")))
t("varref unicode digit", lambda: render(VarRef("١"), check=False))
t("build of it", lambda: build(render(VarRef("١"), check=False)))
t("concurrency True", lambda: render(iterate("https://x","b",intent="go",concurrency=True)))
t("mode space", lambda: render(src("https://x", mode="a b")))
t("struct nan", lambda: struct({"a": float('nan')}))
t("combined depth split", lambda: build("(a{b), c)!x"))
t("combined depth split2", lambda: build("({a), c)!x"))
t("brace close paren", lambda: build("(x, {a)!y"))
t("build '\\\\' end", lambda: build("('a\\')!x"))
t("param key unicode", lambda: render(Expression(sources=(Text("a"),), intent=Text("go"), params=(("é","1"),)), check=False))
