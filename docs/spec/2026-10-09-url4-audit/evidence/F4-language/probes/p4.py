import sys, warnings; warnings.simplefilter("ignore")
sys.path.insert(0, sys.argv[1])
from test_lowering_equiv import observe, EchoIO
from url4 import build
from url4.core.grammar import parse
for s in ["/p(x)!a!b", "(/p(x)!a!b)!r", "(()!'h';broadcast)!'t'", "(x, (*(https://a.io)!'i')!'j')!'k'",
          "*(https://a.io, https://b.io)!'m'", "(x, *(https://a.io, https://b.io)!'m')!'k'"]:
    try: b = build(s)
    except Exception as e: b = f"!! {type(e).__name__} {e}"
    print(s); print("   build:", repr(b)[:300])
    print("   text :", observe(s)); 
    try: print("   ast  :", observe(build(s)))
    except Exception as e: print("   ast !!", e)
