import warnings; warnings.simplefilter("ignore")
from url4 import build, render, src, expr, iterate
from url4.core.grammar import parse
from url4.core.nodes import *
def t(label, f):
    try: print(f"{label:38s} -> {f()!r}"[:400])
    except Exception as e: print(f"{label:38s} !! {type(e).__name__}: {str(e)[:200]}")
t("build('')", lambda: build(""))
t("build('*(https://a, https://b)!go')", lambda: build("*(https://a, https://b)!go"))
t("parse same (grammar)", lambda: parse("*(https://a, https://b)!go"))
t("in group", lambda: build("(x, *(https://a, https://b)!go)!r"))
t("build('(x)!*(y)!z')", lambda: build("(x)!*(y)!z"))
t("build('https://x*(b)!*go')", lambda: build("https://x*(b)!*go"))
t("build('https://x*(b)!go;broadcast')", lambda: build("https://x*(b)!go;broadcast"))
t("canonical top RelExpr", lambda: build("/p?t=90&q=(x)!go"))
t("canonical top RelExpr render", lambda: render(RelExpr("/p", "x", Text("go"), (("t","90"),))))
t("canonical in group", lambda: build("(/p?t=90&q=(x)!go)!r"))
t("relurl query parens", lambda: build("/p?a=(1)"))
t("relurl query parens render", lambda: render(build("/p?a=(1)")))
t("url quote", lambda: build("https://w.org/it's"))
t("bare text tab", lambda: build("(a\tb)!go"))
t("bare text nonascii", lambda: build("(café)!go"))
t("quoted nonascii", lambda: build("('café')!go"))
# builder-reachable silent misreadings under check=False
for lab, n in [
  ("src mode with !", src("https://x.io", mode="a!b")),
  ("src annotations expand", src("https://x.io", annotations=[("expand", None)])),
  ("expr params value with !", expr("https://x.io", intent="go", params={"k": "x!y"})),
  ("expr intent=nested expr w/ params", expr("https://x.io", intent=expr("https://y.io", intent="in", params={"quorum": "1"}))),
  ("src accept=a!b", src("/p(x)!go", name="a", accept="a!b")),
]:
    try:
        s = render(n, check=False)
        b = build(s)
        wrap = n if isinstance(n,(Expression,Iteration)) else Expression(sources=(n,))
        print(f"{lab:38s} :: {s!r} -> same={b==wrap}  reparsed={b!r}"[:420])
    except Exception as e:
        print(f"{lab:38s} !! {type(e).__name__}: {str(e)[:200]}")
