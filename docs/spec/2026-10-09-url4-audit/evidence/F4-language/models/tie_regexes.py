"""Tie the z3 encodings to the real compiled regexes: exhaustive over a small alphabet.
Also checks the call-target classifier (parser._is_call_target) against the grammar's
own reading of `head(x)!'i'` (RelExpr/RemoteExpr or not)."""
import itertools, warnings, re; warnings.simplefilter("ignore")
from url4.core import parser as P, grammar as G, render as R
from url4.core.nodes import RelExpr, RemoteExpr
assert P._CALL_PATH_RE.pattern == G._PATH_RE.pattern, "pattern text differs"
assert P._CALL_PATH_RE.flags == G._PATH_RE.flags
assert R._PATH_RE is G._PATH_RE, "render does not share grammar's object"
print("pattern text identical:", P._CALL_PATH_RE.pattern, "flags equal; render._PATH_RE is grammar._PATH_RE")
ALPHA = "/a~$:é."
n = diff = 0
for L in range(0, 6):
    for t in itertools.product(ALPHA, repeat=L):
        s = "".join(t); n += 1
        if bool(P._CALL_PATH_RE.fullmatch(s)) != bool(G._PATH_RE.fullmatch(s)): diff += 1
print(f"exhaustive |alphabet|={len(ALPHA)} len<=5: {n} strings, CALL vs EXPR differences = {diff}")
# call-target classifier vs grammar
HEADS = ["/p", "/", "//", "/a.b~", "/p?t=1&q=", "url4://h/p", "url4://h:80/p", "url4://h:x/p", "url4:///p", "url4://h", "/a$b", "p", "https://h/p"]
for h in HEADS:
    txt = f"{h}(x)!'i'"
    try:
        node = G.parse(txt); kind = type(node).__name__
    except Exception as e:
        kind = f"ParseError({str(e)[:40]})"
    ct = P._is_call_target(h)
    gram_call = kind in ("RelExpr", "RemoteExpr")
    flag = "" if ct == gram_call else "   <-- DISAGREE"
    print(f"  head={h!r:18} _is_call_target={ct!s:5} grammar={kind}{flag}")
