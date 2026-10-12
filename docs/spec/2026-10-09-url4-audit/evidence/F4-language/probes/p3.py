import warnings; warnings.simplefilter("ignore")
from url4 import build, render, src, expr, iterate
from url4.core.nodes import *
for lab, mk in [
  ("src mode with !", lambda: src("https://x.io", mode="a!b")),
  ("src annotations expand", lambda: src("https://x.io", annotations=[("expand", None)])),
  ("expr params value with !", lambda: expr("https://x.io", intent="go", params={"k": "x!y"})),
  ("expr(src(mode=a!b)) in group", lambda: expr(src("https://x.io", mode="a!b"), "https://z.io", intent="go")),
  ("src accept=a!b on call", lambda: src("/p(x)!go", name="a", accept="a!b")),
  ("expr params quorum in nested src", lambda: expr(expr("https://y.io", intent="in", params={"quorum": "1"}), intent="go")),
  ("iterate intent='*x'", lambda: iterate("https://x.io", "$item", intent="/*x")),
  ("build('(x)!')", lambda: build("(x)!")),
]:
    try:
        n = mk()
        s = render(n, check=False)
        try:
            b = build(s); wrap = n if isinstance(n,(Expression,Iteration)) else Expression(sources=(n,))
            print(f"{lab:34s} :: {s!r} -> same={b==wrap}  reparsed={b!r}"[:500])
        except Exception as e:
            print(f"{lab:34s} :: {s!r} -> build !! {type(e).__name__}: {e}"[:300])
    except Exception as e:
        print(f"{lab:34s} !! {type(e).__name__}: {str(e)[:200]}")
