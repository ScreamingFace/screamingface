"""Census of text-path vs AST-path disagreements (buckets by shape of the disagreement)."""
import sys, re, warnings
from gen import grammar_text
from hypothesis import HealthCheck, given, settings
from test_lowering_equiv import observe_pair
warnings.simplefilter("ignore")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
buckets = {}
def shape(s):
    s = re.sub(r"'(?:\\.|[^'\\])*'", "Q", s)
    return re.sub(r"[a-z0-9_.$@/:]+", "w", s)[:40]
@settings(max_examples=N, deadline=None, suppress_health_check=list(HealthCheck), database=None)
@given(grammar_text)
def go(s):
    pair = observe_pair(s)
    if pair is None: return
    (rt, ft), (ra, fa) = pair
    if rt == ra and ft == fa: return
    kind = ("result" if rt != ra else "") + ("+fetch" if ft != fa else "")
    key = (kind, rt[0], ra[0], shape(s))
    if key not in buckets or len(s) < len(buckets[key][0]):
        buckets[key] = (s, rt, ra, ft, fa)
go()
print(f"{len(buckets)} disagreement classes")
for key, (s, rt, ra, ft, fa) in sorted(buckets.items(), key=lambda kv: len(kv[1][0])):
    print(f"- {key}\n    s={s!r}\n    text={rt!r}\n    ast ={ra!r}\n    fetch text-only={dict(ft-fa)} ast-only={dict(fa-ft)}"[:900])
